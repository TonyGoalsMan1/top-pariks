"""Release and backup formats shared by the Factory commands."""

import hashlib
import json
import re
import shutil
import stat
import subprocess
import tarfile
from pathlib import PurePosixPath
from zipfile import ZipFile


class FactoryError(Exception):
    pass


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def file_record(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise FactoryError(f"Expected a nonempty regular file: {path.name}")
    with path.open("rb") as source:
        return {"bytes": path.stat().st_size, "sha256": hashlib.file_digest(source, "sha256").hexdigest()}


def archive_path(name):
    parts = name.removeprefix("./").rstrip("/").split("/")
    if any(part in ("", ".", "..") for part in parts) or "\\" in name:
        raise FactoryError(f"Unsafe archive path: {name}")
    return PurePosixPath(*parts)


def inspect_theme(path, slug, destination=None):
    """Read every file, verifying CRCs, archive types and the WordPress header."""
    seen = set()
    with ZipFile(path) as archive:
        for entry in archive.infolist():
            name = archive_path(entry.filename)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            expected_mode = stat.S_IFDIR if entry.is_dir() else stat.S_IFREG
            if name.parts[0] != slug or name in seen or mode not in (0, expected_mode):
                raise FactoryError(f"Unexpected theme entry: {entry.filename}")
            seen.add(name)
            if entry.is_dir():
                if destination is not None:
                    (destination / name).mkdir(parents=True, exist_ok=True)
                continue
            if len(name.parts) < 2:
                raise FactoryError("Theme ZIP must contain a theme directory")
            if entry.filename == f"{slug}/style.css":
                with archive.open(entry) as source:
                    header = source.read(8192).decode("utf-8", errors="replace")
                for field in ("Theme Name", "Version"):
                    if not re.search(rf"(?mi)^[\s/*#@]*{field}:\s*\S", header):
                        raise FactoryError(f"Missing theme header: {field}")
            with archive.open(entry) as source:
                if destination is None:
                    while source.read(1024 * 1024):
                        pass
                else:
                    target = destination / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as output:
                        shutil.copyfileobj(source, output)
        required = {PurePosixPath(slug, "style.css"), PurePosixPath(slug, "index.php")}
        if not required <= seen or any(archive.getinfo(str(name)).file_size == 0 for name in required):
            raise FactoryError("Expected nonempty style.css and index.php")


def build_release(site, ref, output):
    source = PurePosixPath(site.config["theme"]["source"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    try:
        git = ["git", "-C", site.repo]
        commit = subprocess.check_output(
            [*git, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"], text=True
        ).strip()
        package = output / "theme.zip"
        tree = commit if source.parent == PurePosixPath(".") else f"{commit}:{source.parent}"
        subprocess.run(
            [*git, "archive", "--format=zip", f"--output={package}",
             tree, source.name], check=True
        )
        inspect_theme(package, site.slug)
        write_json(output / "manifest.json", {
            "version": 1, "kind": "theme", "site_id": site.id, "slug": site.slug,
            "commit": commit, "theme.zip": file_record(package),
        })
    except BaseException:
        shutil.rmtree(output)
        raise
    print(f"Release: {output} ({commit})")


def verify_release(site, directory, destination=None):
    manifest = read_json(directory / "manifest.json")
    package = directory / "theme.zip"
    if (manifest.get("version"), manifest.get("kind"), manifest.get("site_id"), manifest.get("slug")) != (
        1, "theme", site.id, site.slug
    ) or not re.fullmatch(r"[0-9a-f]{40}", manifest.get("commit", "")):
        raise FactoryError("Release manifest does not match this site")
    if file_record(package) != manifest.get("theme.zip"):
        raise FactoryError("Release checksum or size mismatch")
    inspect_theme(package, site.slug, destination)


BACKUP_FILES = ("database.sql", "wordpress.tar.gz")


def verify_backup(site, directory):
    manifest = read_json(directory / "manifest.json")
    if (manifest.get("version"), manifest.get("kind"), manifest.get("profile")) != (
        1, "backup", site.backup_profile
    ):
        raise FactoryError("Backup profile does not match this site")
    if manifest.get("files") != {name: file_record(directory / name) for name in BACKUP_FILES}:
        raise FactoryError("Backup checksum, size or file list mismatch")
    seen = set()
    files = set()
    with tarfile.open(directory / "wordpress.tar.gz", "r:gz") as archive:
        for member in archive:
            if member.name == "." and member.isdir():
                continue
            name = archive_path(member.name)
            allowed_special_bits = stat.S_ISVTX if member.isdir() else 0
            if (name in seen or not (member.isfile() or member.isdir())
                    or member.mode & (0o7000 & ~allowed_special_bits)):
                raise FactoryError(f"Unexpected WordPress archive entry: {member.name}")
            seen.add(name)
            if member.isfile():
                files.add(name)
    required = ("wp-config.php", "wp-includes/version.php", f"wp-content/themes/{site.slug}/style.css")
    if not all(PurePosixPath(name) in files for name in required):
        raise FactoryError("Backup is missing required WordPress files")
