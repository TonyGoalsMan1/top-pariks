#!/usr/bin/env python3
"""Operate the dedicated WordPress Factory staging host."""

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import syslog
import tempfile
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zipfile import ZipFile

FACTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FACTORY))
from factory import (  # noqa: E402
    BACKUP_ID, ERRORS, SLUG, FactoryError, Site, SiteBusy, deploy, file_record, health,
    provision, read_json, restore, rollback, snapshot, start_database,
    verified_backup, verify_release, write_json,
)

STATE = Path("/var/lib/wordpress-factory")
PROXY = Path("/etc/caddy/WordPressFactory.caddy")
SITE_ID = re.compile(SLUG)
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
DOMAIN = re.compile(rf"(?=.{{1,253}}\Z)(?:{LABEL}\.)+[a-z](?:[a-z0-9-]{{0,61}}[a-z0-9])?")
COMMIT = re.compile(rb"[0-9a-f]{40}\n")
MAX_UPLOAD = 32 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
FAILURES = (*ERRORS, URLError)
QUEUE_OPERATIONS = ("backup", "check")


class Busy(FactoryError):
    pass


def event(message):
    print(message, flush=True)


@contextlib.contextmanager
def lock(path, *, shared=False, wait=False):
    flags = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, flags if wait else flags | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Busy("Another operation holds the server lock") from error
        yield


@contextlib.contextmanager
def quiet():
    """Keep dependency output (including PHP messages and dump errors) private."""
    sys.stdout.flush()
    sys.stderr.flush()
    with open(os.devnull, "wb") as sink:
        stdout, stderr = os.dup(1), os.dup(2)
        try:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(stdout, 1)
            os.dup2(stderr, 2)
            os.close(stdout)
            os.close(stderr)


class ServerSite(Site):
    def __init__(self, profile, state):
        super().__init__(profile, state)
        domain = self.config["domain"]
        if not isinstance(domain, str) or not DOMAIN.fullmatch(domain):
            raise FactoryError("Expected a fully qualified staging domain")
        self.url = f"https://{domain}"
        # Compose global options precede the project name.
        self.compose_command[-2:-2] = ["-f", str(FACTORY / "server/compose.yaml")]
        self.env["FACTORY_ENVIRONMENT"] = "staging"
        self.backup_profile["origin"] = self.url
        self.maintenance = self.root / "maintenance"
        self.last_release = self.root / "last-release.json"
        self.provisioned = self.root / "provisioned"

def site_for(site_id):
    if not SITE_ID.fullmatch(site_id):
        raise FactoryError("Invalid site ID")
    site = ServerSite(STATE / "sites" / f"{site_id}.json", STATE)
    if site.id != site_id:
        raise FactoryError("Site ID does not match the registry")
    return site


def sites():
    return [site_for(path.stem) for path in sorted((STATE / "sites").glob("*.json"))]


def proxy_config(entries):
    return "".join(
        f"{site.config['domain']} {{\n"
        "    header X-Robots-Tag \"noindex, nofollow\"\n"
        f"    reverse_proxy 127.0.0.1:{site.port}\n"
        "}\n\n"
        for site in entries
    )


def write_proxy(content):
    with tempfile.NamedTemporaryFile(dir=PROXY.parent, mode="w", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        temporary.chmod(0o644)
        temporary.replace(PROXY)
    finally:
        temporary.unlink(missing_ok=True)


def reload_proxy(entries):
    previous = PROXY.read_text()
    write_proxy(proxy_config(entries))
    try:
        with quiet():
            subprocess.run(["systemctl", "reload", "caddy"], check=True, timeout=30)
    except FAILURES:
        write_proxy(previous)
        raise FactoryError("Caddy reload failed. Previous proxy configuration restored.") from None


def add_site(profile, domain, release):
    (STATE / "sites").mkdir(exist_ok=True)
    config = read_json(profile)
    config["domain"] = domain
    with tempfile.TemporaryDirectory(dir=STATE) as temporary:
        candidate = Path(temporary) / "site.json"
        write_json(candidate, config)
        site = ServerSite(candidate, STATE)
        verify_release(site, release)
    others = [entry for entry in sites() if entry.id != site.id]
    if any(entry.port == site.port or entry.url == site.url for entry in others):
        raise FactoryError("The loopback port and domain must be unique")
    registered = STATE / "sites" / f"{site.id}.json"
    if registered.exists() and read_json(registered) != config:
        raise FactoryError("Site already registered with a different profile")
    write_json(registered, config)
    reload_proxy([*others, site])
    with site.lock(), quiet():
        if site.pending.exists() or site.maintenance.exists():
            raise FactoryError("Run recover before provisioning")
        provision(site, release)
    event(f"{site.id}: provisioned at {site.url}")


def clean_snapshots(site):
    # A pending core transaction needs its verified snapshot for rollback.
    if site.pending.exists():
        return
    for directory in site.backups.iterdir() if site.backups.exists() else ():
        if directory.name.startswith(".snapshot-") or re.fullmatch(BACKUP_ID, directory.name):
            shutil.rmtree(directory)


def recover(site):
    if site.pending.exists():
        with quiet():
            start_database(site)
            rollback(site)
        event(f"{site.id}: interrupted operation rolled back")
    elif site.maintenance.exists() and site.provisioned.exists():
        with quiet():
            site.start_web()
            health(site)
        event(f"{site.id}: recovered after interrupted maintenance")
    clean_snapshots(site)
    site.maintenance.unlink(missing_ok=True)


@contextlib.contextmanager
def maintenance(site):
    if site.pending.exists() or site.maintenance.exists():
        raise FactoryError("Recovery required before maintenance")
    site.maintenance.touch()
    yield
    clean_snapshots(site)
    site.maintenance.unlink()


def read_upload(destination):
    def timed_out(_signum, _frame):
        raise FactoryError("Timed out receiving the release")

    previous = signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(45)
    try:
        commit = sys.stdin.buffer.readline(42)
        if not COMMIT.fullmatch(commit):
            raise FactoryError("Expected a commit SHA and theme ZIP")
        remaining = MAX_UPLOAD
        with destination.open("xb") as output:
            while chunk := sys.stdin.buffer.read(min(remaining + 1, 1024 * 1024)):
                remaining -= len(chunk)
                if remaining < 0:
                    raise FactoryError("Theme ZIP exceeds the upload limit")
                output.write(chunk)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    return commit.strip().decode("ascii")


def package_upload(site, release):
    package = release / "theme.zip"
    commit = read_upload(package)
    with ZipFile(package) as archive:
        entries = archive.infolist()
        if len(entries) > 4096 or sum(entry.file_size for entry in entries) > MAX_EXPANDED:
            raise FactoryError("Theme ZIP exceeds extraction limits")
    manifest = {
        "version": 1, "kind": "theme", "site_id": site.id, "slug": site.slug,
        "commit": commit, "theme.zip": file_record(package),
    }
    write_json(release / "manifest.json", manifest)
    verify_release(site, release)
    return manifest


def receive():
    site = site_for((STATE / "staging-site").read_text().strip())
    with site.lock(), tempfile.TemporaryDirectory(dir=site.root, prefix="upload-") as temporary:
        if not site.provisioned.exists():
            raise FactoryError("Provision the staging site first")
        release = Path(temporary)
        manifest = package_upload(site, release)
        if site.pending.exists() or site.maintenance.exists():
            raise FactoryError("Recovery required before deployment")
        if site.last_release.exists():
            previous = read_json(site.last_release)
            if previous["commit"] == manifest["commit"]:
                if previous != manifest:
                    raise FactoryError("Different package for a published commit")
                with quiet():
                    health(site)
                event(f"{site.id}: release already verified")
                return
        try:
            with maintenance(site), quiet():
                deploy(site, release)
                write_json(site.last_release, manifest)
        except FAILURES:
            if not site.pending.exists():
                event(f"{site.id}: deployment rejected, checking recovery")
                recover(site)
            else:
                event(f"{site.id}: deployment failed, rollback pending")
            raise
        event(f"{site.id}: deployment verified at {manifest['commit']}")


def site_operation(site, operation):
    with site.lock():
        if operation == "recover" or (operation in ("check", "monitor")
                                     and (site.pending.exists() or site.maintenance.exists())):
            recover(site)
        if not site.provisioned.exists():
            if operation == "recover":
                return
            raise FactoryError("Site is not provisioned")
        if operation in ("check", "monitor"):
            with quiet():
                health(site)
        elif operation == "backup":
            backup(site)


def for_sites(operation, site_id):
    failed = False
    entries = [site_for(site_id)] if site_id else sites()
    for site in entries:
        try:
            site_operation(site, operation)
            if operation in ("monitor", "recover", "backup"):
                alert(site, operation, False)
            event(f"{site.id}: {operation} passed")
        except (Busy, SiteBusy):
            event(f"{site.id}: {operation} skipped because the site is busy")
            if operation == "backup" and not site_id:
                enqueue(site, "backup")
            else:
                failed |= bool(site_id)
        except FAILURES as error:
            event(f"{site.id}: {operation} failed ({type(error).__name__})")
            alert(site, operation, True)
            failed = True
    return int(failed)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def alert(site, operation, failed):
    # Notifications carry only a site ID and a fixed event, never an error body.
    flag = site.root / f"alert-{operation}"
    webhook = site.root / "webhook-url"
    if not webhook.is_file() or flag.exists() == failed:
        return
    try:
        url = webhook.read_text().strip()
        if not url.startswith("https://"):
            raise FactoryError("HTTPS webhook required")
        payload = json.dumps({"site": site.id, "operation": operation, "failed": failed})
        with build_opener(ProxyHandler({}), NoRedirect()).open(
            Request(url, data=payload.encode(), headers={"Content-Type": "application/json"}),
            timeout=8,
        ):
            pass
        if failed:
            flag.touch()
        else:
            flag.unlink(missing_ok=True)
    except FAILURES:
        event(f"{site.id}: notification delivery failed")


def restic(site, operation, *args, remote=False, **kwargs):
    password_file = site.root / "restic-password"
    env = {
        "PATH": os.defpath, "HOME": str(site.root), "LANG": "C.UTF-8",
        "RESTIC_PASSWORD_FILE": str(password_file),
    }
    repo = str(site.root / "encrypted-backups")
    if remote:
        config = read_json(site.root / "s3.json")
        repo = config["repository"]
        if not isinstance(repo, str) or not re.fullmatch(r"s3:https://[^\s/?#@]+/[^\s?#]+", repo):
            raise FactoryError("Remote backups require a private HTTPS S3 repository")
        env.update({key: config[key] for key in (
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"
        )})
        if config.get("AWS_SESSION_TOKEN"):
            env["AWS_SESSION_TOKEN"] = config["AWS_SESSION_TOKEN"]
    return subprocess.run(
        ["restic", "-r", repo, "--cache-dir", str(site.root / "restic-cache"), operation, *args],
        env=env, check=True, stderr=subprocess.DEVNULL, **kwargs,
    )


def backup(site):
    if site.pending.exists() or site.maintenance.exists():
        raise FactoryError("Recovery required before backup")
    password = site.root / "restic-password"
    if not password.exists():
        if (site.root / "encrypted-backups").exists() or (site.root / "s3.json").exists():
            raise FactoryError("Recover or provision the restic password file first")
        temporary = password.with_suffix(".tmp")
        temporary.write_text(secrets.token_urlsafe(48) + "\n")
        temporary.replace(password)
    if not (site.root / "encrypted-backups" / "config").is_file():
        with quiet():
            restic(site, "init")
    with maintenance(site):
        with quiet():
            health(site)
            site.stop_web()
            try:
                backup_id = snapshot(site)
            finally:
                site.start_web()
            health(site)
        directory = verified_backup(site, backup_id)
        try:
            with quiet():
                for remote in (False, True) if (site.root / "s3.json").exists() else (False,):
                    restic(site, "backup", "--host", site.id, "--tag", backup_id,
                           "manifest.json", "database.sql", "wordpress.tar.gz",
                           cwd=directory, remote=remote)
                    restic(site, "forget", "--host", site.id, "--group-by", "host",
                           "--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "6",
                           "--keep-last", "3", "--prune", remote=remote)
        finally:
            # No pending transaction references this completed scheduled snapshot.
            clean_snapshots(site)
    event(f"{site.id}: encrypted backup {backup_id}")


def restore_copy(site, backup_id, remote):
    if not re.fullmatch(BACKUP_ID, backup_id):
        raise FactoryError("Invalid backup ID")
    with site.lock(), maintenance(site), quiet():
        result = restic(site, "snapshots", "--host", site.id, "--tag", backup_id, "--json",
                        remote=remote, capture_output=True)
        snapshots = json.loads(result.stdout)
        if len(snapshots) != 1 or not re.fullmatch(r"[0-9a-f]{64}", snapshots[0]["id"]):
            raise FactoryError("Expected one matching encrypted snapshot")
        site.backups.mkdir(exist_ok=True)
        target = site.backups / backup_id
        with tempfile.TemporaryDirectory(dir=site.backups, prefix=".snapshot-") as temporary:
            directory = Path(temporary)
            for name in ("manifest.json", "database.sql", "wordpress.tar.gz"):
                with (directory / name).open("wb") as output:
                    restic(site, "dump", snapshots[0]["id"], f"/{name}", remote=remote, stdout=output)
            directory.rename(target)
        restore(site, backup_id)
    event(f"{site.id}: encrypted backup restored {backup_id}")


def enqueue(site, operation):
    queue = STATE / "queue"
    queue.mkdir(exist_ok=True)
    job_id = secrets.token_hex(16)
    write_json(queue / f"{job_id}.job", {"site": site.id, "operation": operation})
    event(f"Queued {job_id}")


def dispatch():
    queue = STATE / "queue"
    if not queue.exists():
        return
    with lock(STATE / "queue.lock"):
        for job in queue.glob("*.running"):
            job.rename(job.with_suffix(".interrupted"))
            event(f"Queue {job.stem}: interrupted, inspect before resubmitting")
        job = min(queue.glob("*.job"), key=lambda entry: (entry.stat().st_mtime_ns, entry.name), default=None)
        if job is None:
            return
        running = job.with_suffix(".running")
        job.rename(running)
        site = None
        try:
            task = read_json(running)
            operation = task["operation"]
            if operation not in QUEUE_OPERATIONS:
                raise FactoryError("Queue operation is not allowed")
            site = site_for(task["site"])
            if not site.provisioned.exists():
                raise FactoryError("Site is not provisioned")
            site_operation(site, operation)
            if operation == "backup":
                alert(site, "backup", False)
        except (Busy, SiteBusy):
            running.rename(job)
            event(f"Queue {job.stem}: site busy, task deferred")
            return
        except FAILURES as error:
            running.rename(job.with_suffix(".failed"))
            event(f"Queue {job.stem}: failed ({type(error).__name__})")
            if site is not None and operation == "backup":
                alert(site, "backup", True)
            return 1
        running.rename(job.with_suffix(".done"))
        event(f"Queue {job.stem}: completed")


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add-site")
    add.add_argument("profile", type=Path)
    add.add_argument("domain")
    add.add_argument("release", type=Path)
    for name in ("monitor", "backup", "recover"):
        commands.add_parser(name).add_argument("site", nargs="?")
    for name in ("enable-staging", "init-remote", "restore-copy", "enqueue"):
        command = commands.add_parser(name)
        command.add_argument("site")
        if name == "restore-copy":
            command.add_argument("backup_id")
            command.add_argument("--remote", action="store_true")
        elif name == "enqueue":
            command.add_argument("operation", choices=QUEUE_OPERATIONS)
    for name in ("receive", "queue"):
        commands.add_parser(name)
    return parser.parse_args()


def main():
    os.umask(0o077)
    args = arguments()
    command = args.command
    with lock(STATE / "server.lock", shared=command not in ("add-site", "enable-staging")):
        if command == "add-site":
            add_site(args.profile, args.domain, args.release)
        elif command == "enable-staging":
            site = site_for(args.site)
            if not site.provisioned.exists():
                raise FactoryError("Provision the staging site first")
            target = STATE / "staging-site"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(site.id + "\n")
            temporary.replace(target)
            event(f"Staging deployments enabled for {site.id}")
        elif command == "receive":
            syslog.openlog("wordpress-factory-deploy", syslog.LOG_PID, syslog.LOG_AUTH)
            try:
                receive()
            except FAILURES as error:
                syslog.syslog(syslog.LOG_ERR, f"Staging deployment failed ({type(error).__name__})")
                if (STATE / "staging-site").is_file():
                    alert(site_for((STATE / "staging-site").read_text().strip()), "deploy", True)
                raise
            syslog.syslog(syslog.LOG_INFO, "Staging deployment verified")
            alert(site_for((STATE / "staging-site").read_text().strip()), "deploy", False)
        elif command in ("monitor", "backup", "recover"):
            return for_sites(command, args.site)
        elif command == "init-remote":
            site = site_for(args.site)
            with site.lock(), quiet():
                restic(site, "init", remote=True)
            event(f"{site.id}: remote repository initialized")
        elif command == "restore-copy":
            restore_copy(site_for(args.site), args.backup_id, args.remote)
        elif command == "enqueue":
            enqueue(site_for(args.site), args.operation)
        elif command == "queue":
            return dispatch()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FAILURES as error:
        # SSH, application and cloud-provider errors may contain untrusted or
        # sensitive data. Only fixed operational messages and types are logged.
        sys.exit(f"WordPress Factory operation failed ({type(error).__name__}).")
