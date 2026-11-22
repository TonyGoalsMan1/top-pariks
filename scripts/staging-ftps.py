"""Replace the existing staging theme over explicit FTPS."""
import ftplib
import hashlib
import os
import re
import ssl
import sys
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

SITE = b"https://top-pariks-test.freehosting.dev"
THEME = "top-pariks"


def component(name):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in (".", ".."):
        raise ValueError("Unsupported path component")
    return name


def absolute_path(value):
    if not value.startswith("/"):
        raise ValueError("An absolute FTP path is required")
    for part in value[1:].split("/"):
        component(part)
    return value


@contextmanager
def session(host, port, user, password):
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with ftplib.FTP_TLS(context=context, timeout=30, encoding="utf-8") as ftp:
        ftp.connect(host, port)
        ftp.auth()
        ftp.login(user, password)
        ftp.prot_p()
        yield ftp


def download_hash(ftp, path):
    digest = hashlib.sha256()
    ftp.retrbinary(f"RETR {path}", digest.update)
    return digest.hexdigest()


def snapshot(ftp, root):
    files = {}
    for name, facts in ftp.mlsd(root):
        kind = facts.get("type")
        if kind in ("cdir", "pdir"):
            continue
        component(name)
        if kind == "dir":
            files[name] = None
            files.update({f"{name}/{key}": value
                          for key, value in snapshot(ftp, f"{root}/{name}").items()})
        elif kind == "file":
            files[name] = download_hash(ftp, f"{root}/{name}")
        else:
            raise ValueError("Unsupported FTP entry type")
    return files


def upload(ftp, candidate, archive_path):
    expected = {}
    with ZipFile(archive_path) as archive:
        # The workflow verifies the ZIP against the checked-out theme first.
        for entry in sorted(archive.infolist(), key=lambda item: item.filename):
            name = entry.filename.removesuffix("/")
            parts = name.split("/")
            if parts[0] != THEME:
                raise ValueError("Unexpected theme ZIP root")
            for part in parts:
                component(part)
            if len(parts) == 1 and entry.is_dir():
                continue
            relative = "/".join(parts[1:])
            destination = f"{candidate}/{relative}"
            if entry.is_dir():
                ftp.mkd(destination)
                expected[relative] = None
            else:
                data = archive.read(entry)
                ftp.storbinary(f"STOR {destination}", BytesIO(data))
                expected[relative] = hashlib.sha256(data).hexdigest()
    require_snapshot(ftp, candidate, expected)
    return expected


def require_snapshot(ftp, path, expected):
    if snapshot(ftp, path) != expected:
        raise ValueError("Remote theme files differ from the expected files")


def deploy(connect, wp_root, private, run_id, archive_path):
    themes = f"{wp_root}/wp-content/themes"
    live = f"{themes}/{THEME}"
    work = f"{private}/{run_id}"
    old = f"{work}/previous"
    candidate = f"{work}/candidate"

    with connect() as ftp:
        marker = BytesIO()
        ftp.retrbinary(f"RETR {private}/staging-site.txt", marker.write)
        if marker.getvalue().strip() != SITE:
            raise ValueError("Staging marker does not match")
        before = snapshot(ftp, live)
        if not {"style.css", "index.php"} <= before.keys():
            raise ValueError("An existing theme installation is required")
        ftp.mkd(work)
        ftp.mkd(candidate)
        expected = upload(ftp, candidate, archive_path)
        require_snapshot(ftp, live, before)
        print(f"FTPS backup ID: {run_id}", flush=True)

        try:
            ftp.rename(live, old)
            require_snapshot(ftp, old, before)
            ftp.rename(candidate, live)
            require_snapshot(ftp, live, expected)
        except (OSError, ValueError, EOFError, ftplib.Error):
            # A lost reply can mean a rename succeeded. Inspect a fresh session.
            with connect() as recovery:
                names = dict(recovery.mlsd(work))
                if "previous" in names:
                    if "candidate" not in names:
                        recovery.rename(live, f"{work}/rejected")
                    recovery.rename(old, live)
                require_snapshot(recovery, live, before)
            print("Previous theme verified after recovery.", flush=True)
            raise


def main():
    get = os.environ.__getitem__
    host = get("FTPS_HOST")
    port = int(get("FTPS_PORT"))
    user, password = get("FTPS_USER"), get("FTPS_PASSWORD")
    wp_root = absolute_path(get("FTPS_WP_ROOT"))
    private = absolute_path(get("FTPS_PRIVATE_DIR"))
    run_id = get("FTPS_RUN_ID")
    if not re.fullmatch(r"[0-9]+-[0-9]+", run_id):
        raise ValueError("Invalid run ID")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host) or not 1 <= port <= 65535:
        raise ValueError("Invalid FTPS endpoint")
    if not user or not password or any(c in user + password for c in "\r\n"):
        raise ValueError("Invalid FTPS credentials")
    themes = f"{wp_root}/wp-content/themes"
    if (private == themes or private.startswith(f"{themes}/")
            or themes.startswith(f"{private}/")):
        raise ValueError("Private directory must be separate from the theme tree")

    def connect():
        return session(host, port, user, password)

    deploy(connect, wp_root, private, run_id, Path(sys.argv[1]))
    print("Staging theme files verified after replacement.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError, EOFError, ftplib.Error) as error:
        # FTP replies can include server-side details. Keep them out of CI logs.
        sys.exit(f"FTPS failed ({type(error).__name__}). See docs/STAGE-002B.md.")
