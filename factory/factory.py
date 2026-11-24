#!/usr/bin/env python3
"""Build, exercise and recover isolated WordPress + WooCommerce stores."""

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from zipfile import BadZipFile, ZipFile

from artifacts import (
    BACKUP_FILES, FactoryError, archive_path, build_release, file_record, read_json,
    verify_backup, verify_release, write_json,
)
from health import health


REPO = Path(__file__).resolve().parent.parent
SLUG = r"[a-z0-9][a-z0-9-]{0,39}"
SHA256 = r"[0-9a-f]{64}"
BACKUP_ID = r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}"
ERRORS = (FactoryError, OSError, ValueError, TypeError, KeyError, AttributeError,
          subprocess.SubprocessError, tarfile.TarError, BadZipFile)


class SiteBusy(FactoryError):
    pass


class Site:
    repo = REPO

    def __init__(self, config_path, state, *, repo=None):
        if repo is not None:
            self.repo = repo
        self.config = read_json(config_path)
        self.id = self.config["site_id"]
        self.slug = self.config["theme"]["slug"]
        self.woocommerce = "woocommerce" in self.config
        self.packages = ("wp_cli", "woocommerce") if self.woocommerce else ("wp_cli",)
        self.port = self.config["port"]
        self.validate()
        self.url = f"http://127.0.0.1:{self.port}"
        self.root = state / self.id
        self.runtime = self.root / "runtime"
        self.backups = self.root / "backups"
        self.pending = self.root / "pending.json"
        scope = hashlib.sha256(os.fsencode(state)).hexdigest()[:12]
        self.compose_command = [
            "docker", "compose", "--env-file", "/dev/null", "--project-directory", str(REPO / "factory"),
            "-f", str(REPO / "factory/compose.yaml"), "-p", f"factory-{self.id}-{scope}",
        ]
        self.env = dict(
            os.environ, FACTORY_ENVIRONMENT="local", FACTORY_PORT=str(self.port), FACTORY_RUNTIME=str(self.runtime),
            FACTORY_WP_IMAGE=self.config["wordpress_image"], FACTORY_DB_IMAGE=self.config["database_image"],
        )
        self.backup_profile = {key: self.config[key] for key in (
            "site_id", "port", "wordpress_image", "database_image"
        )}
        self.backup_profile["theme"] = self.slug
        for key in self.packages:
            self.backup_profile[f"{key}_sha256"] = self.config[key]["sha256"]

    def validate(self):
        if not all(re.fullmatch(SLUG, value) for value in (self.id, self.slug)):
            raise FactoryError("Invalid site ID or theme slug")
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise FactoryError("The site must use a loopback port between 1024 and 65535")
        if not 1 <= len(self.config["title"].strip()) <= 120:
            raise FactoryError("A site title is required")
        source = archive_path(self.config["theme"]["source"])
        if source.name != self.slug:
            raise FactoryError("The theme source directory must end with its slug")
        if not self.local_file(self.config["seed"]).is_file():
            raise FactoryError("Seed must reference a file in the repository")
        for key in ("wordpress_image", "database_image"):
            if not re.fullmatch(rf"[a-z0-9][a-zA-Z0-9/.:_-]+@sha256:{SHA256}", self.config[key]):
                raise FactoryError(f"{key} requires a pinned image digest")
        for key in self.packages:
            package = self.config[key]
            if not package["url"].startswith("https://") or not re.fullmatch(SHA256, package["sha256"]):
                raise FactoryError(f"{key} requires an HTTPS URL and SHA-256")
        smoke = self.config["smoke"]
        markers = ("home_text", "product_name", "cart_price") if self.woocommerce else ("home_text",)
        for key in markers:
            if not smoke[key].strip():
                raise FactoryError(f"Empty storefront marker: {key}")
        if self.woocommerce:
            for key in ("catalog_path", "product_path", "cart_path"):
                if not re.fullmatch(r"/[a-zA-Z0-9_/-]+", smoke[key]) or "//" in smoke[key]:
                    raise FactoryError(f"Invalid storefront path: {key}")

    def local_file(self, path):
        resolved = (self.repo / archive_path(path)).resolve()
        if not resolved.is_relative_to(self.repo):
            raise FactoryError("File must stay inside the repository")
        return resolved

    @contextlib.contextmanager
    def lock(self, *, timeout=0):
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.stat().st_mode & 0o077:
            raise FactoryError("Site state must be a private directory (0700)")
        with (self.root / "operation.lock").open("a") as lock:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as error:
                    if time.monotonic() >= deadline:
                        raise SiteBusy(f"Another Factory operation owns {self.id}") from error
                    time.sleep(1)
            profile = self.root / "profile.json"
            if profile.exists() and read_json(profile) != self.backup_profile:
                raise FactoryError("Existing state belongs to a different site profile")
            if not profile.exists():
                write_json(profile, self.backup_profile)
            yield

    def compose(self, *args, capture=False, **kwargs):
        result = subprocess.run(
            [*self.compose_command, *args], env=self.env, check=True,
            stdout=subprocess.PIPE if capture else kwargs.pop("stdout", None), **kwargs
        )
        return result.stdout.decode().strip() if capture else None

    def wp(self, *args, **kwargs):
        return self.compose(
            "exec", "-T", "--user", "www-data", "wordpress", "php", "/opt/factory/wp-cli.phar",
            "--path=/var/www/html", f"--url={self.url}", *args, **kwargs
        )

    def files(self, script, *args, **kwargs):
        self.compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "/bin/sh",
                     "wordpress", "-eu", "-c", script, "factory", *args, **kwargs)

    def database(self, script, *args, **kwargs):
        return self.compose(
            "exec", "-T", "db", "sh", "-eu", "-c",
            'export MYSQL_PWD="$(cat /run/secrets/database_password)"; ' + script,
            "factory", *args, **kwargs
        )

    def prepare_runtime(self, install_woocommerce=False):
        self.runtime.mkdir(exist_ok=True)
        for name in ("database-password", "database-root-password"):
            password = self.runtime / name
            if not password.exists():
                temporary = password.with_suffix(".tmp")
                temporary.write_text(secrets.token_hex(32), encoding="ascii")
                # The Compose file secret is a bind mount. The web worker must
                # read it. Its containing directories are private on the host.
                temporary.chmod(0o444)
                temporary.replace(password)
        self.download("wp_cli", self.runtime / "wp-cli.phar")
        if install_woocommerce:
            self.download("woocommerce", self.runtime / "woocommerce.zip")

    def download(self, key, target):
        package = self.config[key]
        if target.exists() and file_record(target)["sha256"] == package["sha256"]:
            return
        temporary = target.with_suffix(".download")
        try:
            subprocess.run(
                ["curl", "-fSsL", "--proto", "=https", "--proto-redir", "=https", "--max-time", "90",
                 "--retry", "2", "-o", temporary, package["url"]], check=True
            )
            if file_record(temporary)["sha256"] != package["sha256"]:
                raise FactoryError(f"Dependency checksum mismatch: {key}")
            temporary.chmod(0o444)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def start_web(self):
        self.compose("up", "-d", "--wait", "--wait-timeout", "90")

    def stop_web(self):
        self.compose("stop", "wordpress")


def install_theme(site, source, backup=False):
    # Both archive layouts land in a temporary directory on the WordPress volume
    # before replacement. A partial candidate never becomes the active directory.
    parent = "wp-content/themes"
    member = f"./{parent}/{site.slug}" if backup else site.slug
    script = """
        cd /var/www/html
        mkdir -p wp-content/themes
        stage=$(mktemp -d wp-content/themes/.factory.XXXXXXXX)
        trap 'rm -rf -- "$stage"' EXIT
        tar "$1" -f - -C "$stage" "$2"
        test -s "$stage/$2/style.css"
        test -s "$stage/$2/index.php"
        if [ "$1" = "-x" ]; then chown -R www-data:www-data "$stage/$2"; fi
        rm -rf -- "wp-content/themes/$3"
        mv -- "$stage/$2" "wp-content/themes/$3"
    """
    with source.open("rb") as stream:
        site.files(script, "-xz" if backup else "-x", member, site.slug, stdin=stream)


@contextlib.contextmanager
def release_tar(site, directory):
    with tempfile.TemporaryDirectory(dir=site.root) as work:
        workspace = Path(work)
        content = workspace / "content"
        content.mkdir()
        verify_release(site, directory, content)
        destination = workspace / "theme.tar"
        with tarfile.open(destination, "w") as archive:
            archive.add(content / site.slug, arcname=site.slug)
        yield destination


def provision(site, release):
    marker = site.root / "provisioned"
    if marker.exists():
        verify_release(site, release)
        site.prepare_runtime()
        site.start_web()
        health(site)
        return
    with release_tar(site, release) as theme:
        site.prepare_runtime(install_woocommerce=site.woocommerce)
        site.start_web()
        for attempt in range(30):
            try:
                site.compose("exec", "-T", "wordpress", "test", "-s", "/var/www/html/wp-config.php")
                break
            except subprocess.CalledProcessError:
                if attempt == 29:
                    raise FactoryError("WordPress did not initialize its files")
                time.sleep(1)
        try:
            site.wp("core", "is-installed", "--skip-plugins", "--skip-themes")
        except subprocess.CalledProcessError as error:
            if error.returncode != 1:
                raise
            site.wp(
                "core", "install", f"--title={site.config['title']}", "--admin_user=factory",
                "--admin_email=admin@example.test", "--skip-email", stdout=subprocess.DEVNULL
            )

        install_theme(site, theme)
        if site.woocommerce:
            with ZipFile(site.runtime / "woocommerce.zip") as woo:
                # The pinned upstream package is installed from local bytes.
                first = {archive_path(name).parts[0] for name in woo.namelist()}
                if first != {"woocommerce"}:
                    raise FactoryError("Unexpected WooCommerce ZIP layout")
            with (site.runtime / "woocommerce.zip").open("rb") as stream:
                site.files("""cat > /tmp/woocommerce.zip
                php -r '$zip = new ZipArchive();
                    exit($zip->open("/tmp/woocommerce.zip") === true
                        && $zip->extractTo("/var/www/html/wp-content/plugins") ? 0 : 1);'
                chown -R www-data:www-data /var/www/html/wp-content/plugins/woocommerce""",
                    stdin=stream)
        with (REPO / "sandbox/test-only.php").open("rb") as stream:
            site.files("""mkdir -p /var/www/html/wp-content/mu-plugins
                cat > /var/www/html/wp-content/mu-plugins/factory-test-only.php
                chmod 644 /var/www/html/wp-content/mu-plugins/factory-test-only.php""", stdin=stream)
        if site.woocommerce:
            site.wp("plugin", "activate", "woocommerce")
        site.wp("theme", "activate", site.slug)
        site.wp("rewrite", "structure", "/%postname%/", "--hard")
        with site.local_file(site.config["seed"]).open("rb") as seed:
            site.wp("eval-file", "-", stdin=seed)

        health(site)
        marker.touch()


def snapshot(site):
    """Save both components while the only WordPress writer is stopped."""
    when = dt.datetime.now(dt.timezone.utc)
    backup_id = f"{when:%Y%m%dT%H%M%SZ}-{secrets.token_hex(6)}"
    site.backups.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=site.backups, prefix=".snapshot-") as staging:
        directory = Path(staging)
        with (directory / "database.sql").open("wb") as output:
            site.database(
                "exec mariadb-dump -u wordpress --single-transaction --skip-lock-tables "
                "--routines --events --triggers --add-drop-database --databases wordpress", stdout=output
            )
        with (directory / "wordpress.tar.gz").open("wb") as output:
            site.files("exec tar -czf - --hard-dereference -C /var/www/html .", stdout=output)
        write_json(directory / "manifest.json", {
            "version": 1, "kind": "backup", "profile": site.backup_profile, "created_at": when.isoformat(),
            "files": {name: file_record(directory / name) for name in BACKUP_FILES},
        })
        verify_backup(site, directory)
        directory.rename(site.backups / backup_id)
    print(f"Backup verified: {backup_id}", flush=True)
    return backup_id


def verified_backup(site, backup_id):
    if not isinstance(backup_id, str) or not re.fullmatch(BACKUP_ID, backup_id):
        raise FactoryError("Invalid backup ID")
    directory = site.backups / backup_id
    if directory.is_symlink() or directory.parent.is_symlink():
        raise FactoryError("Backup must be a local directory")
    verify_backup(site, directory)
    return directory


def apply_backup(site, directory):
    # Keep the web container stopped until both components have been replaced.
    with (directory / "wordpress.tar.gz").open("rb") as stream:
        site.files("""cd /var/www/html
            find . -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
            exec tar -xzf - --numeric-owner -C /var/www/html""", stdin=stream)
    with (directory / "database.sql").open("rb") as stream:
        site.database("exec mariadb -u wordpress", stdin=stream)


def start_database(site):
    site.prepare_runtime()
    site.compose("up", "-d", "--wait", "--wait-timeout", "90", "db")


def rollback(site):
    transaction = read_json(site.pending)
    kind = transaction["kind"]
    if kind not in ("deploy", "restore"):
        raise FactoryError("Unknown pending operation")
    directory = verified_backup(site, transaction["backup"])
    site.stop_web()
    if kind == "deploy":
        install_theme(site, directory / "wordpress.tar.gz", backup=True)
    else:
        apply_backup(site, directory)
    try:
        site.start_web()
        health(site)
    except ERRORS:
        site.stop_web()
        raise
    (site.root / "provisioned").touch()
    site.pending.unlink()
    print(f"Rollback verified ({kind}) from {directory.name}", flush=True)


def recover_failure(site, error):
    print(f"Operation failed: {error}", file=sys.stderr, flush=True)
    try:
        rollback(site)
    except ERRORS as rollback_error:
        raise FactoryError(f"Rollback failed or is incomplete: {rollback_error}. Pending journal: {site.pending}") from error
    raise FactoryError("Operation failed and the site was recovered") from error


def deploy(site, directory):
    with release_tar(site, directory) as theme:
        health(site)
        site.stop_web()
        try:
            backup_id = snapshot(site)
            write_json(site.pending, {"kind": "deploy", "backup": backup_id})
        except ERRORS:
            site.start_web()
            raise
        try:
            install_theme(site, theme)
            site.start_web()
            health(site)
        except ERRORS as error:
            recover_failure(site, error)
        site.pending.unlink()
        print("Deployment verified", flush=True)


def restore(site, backup_id):
    directory = verified_backup(site, backup_id)
    start_database(site)
    site.stop_web()
    try:
        previous = site.database(
            "exec mariadb -u wordpress -Nse \"SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'wordpress'\"", capture=True
        )
        rescue = snapshot(site) if int(previous) else backup_id
        write_json(site.pending, {"kind": "restore", "backup": rescue})
    except ERRORS:
        site.start_web()
        raise
    try:
        apply_backup(site, directory)
        site.start_web()
        health(site)
    except ERRORS as error:
        recover_failure(site, error)
    site.pending.unlink()
    (site.root / "provisioned").touch()
    print(f"Restore verified: {backup_id}", flush=True)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True, type=Path, help="JSON site profile")
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    parser.add_argument("--repository", type=Path, default=REPO, help="Trusted Git checkout for theme and seed")
    parser.add_argument("--state", type=Path, default=state_home / "wordpress-factory")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("output", type=Path)
    build.add_argument("--ref", default="HEAD")
    for command in ("start", "deploy", "verify-release"):
        commands.add_parser(command).add_argument("release", type=Path)
    for command in ("restore", "verify-backup"):
        commands.add_parser(command).add_argument("backup_id")
    for command in ("health", "backup", "rollback", "stop"):
        commands.add_parser(command)
    return parser.parse_args()


def main():
    os.umask(0o077)
    args = arguments()
    state = args.state.resolve()
    repository = args.repository.resolve(strict=True)
    if state.is_relative_to(REPO) or state.is_relative_to(repository):
        raise FactoryError("Runtime state and backups must be outside the Git checkout")
    site = Site(args.site, state, repo=repository)
    if args.command == "build":
        build_release(site, args.ref, args.output.resolve())
        return
    if args.command == "verify-release":
        verify_release(site, args.release)
        print("Release verified")
        return
    with site.lock():
        if site.pending.exists() and args.command not in ("rollback", "verify-backup"):
            raise FactoryError("Unfinished operation. Run rollback before continuing.")
        if args.command == "start":
            provision(site, args.release)
        elif args.command == "stop":
            site.compose("down")
        elif args.command == "health":
            health(site)
        elif args.command == "deploy":
            deploy(site, args.release)
        elif args.command == "backup":
            health(site)
            site.stop_web()
            try:
                snapshot(site)
            finally:
                site.start_web()
        elif args.command == "verify-backup":
            verified_backup(site, args.backup_id)
            print(f"Backup verified: {args.backup_id}")
        elif args.command == "restore":
            restore(site, args.backup_id)
        elif args.command == "rollback":
            if not site.pending.exists():
                raise FactoryError("No pending operation to recover")
            start_database(site)
            rollback(site)


if __name__ == "__main__":
    try:
        main()
    except ERRORS as error:
        sys.exit(f"Factory: {error}")
