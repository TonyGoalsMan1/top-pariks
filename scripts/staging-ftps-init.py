"""Check the staging FTPS layout and optionally initialize its marker."""
import ftplib
import os
import re
import sys
from importlib import import_module
from io import BytesIO

deployment = import_module("staging-ftps")
SITE = deployment.SITE
WP_ROOT = "/htdocs"
PRIVATE = "/top-pariks-backups"
MARKER = "staging-site.txt"
CONFIRMATION = "initialize top-pariks-test.freehosting.dev on an isolated account"


class CheckFailed(Exception):
    """A fixed diagnostic that is safe to show in Actions logs."""


def entries(ftp, directory):
    result = {}
    for name, facts in ftp.mlsd(directory):
        kind = facts.get("type")
        if kind in ("cdir", "pdir"):
            continue
        if name.casefold() in result:
            raise CheckFailed("The directory listing contains ambiguous names.")
        result[name.casefold()] = (name, kind)
    return result


def verify_marker(ftp, path):
    data = bytearray()

    def collect(chunk):
        if len(data) + len(chunk) > len(SITE):
            raise CheckFailed("The existing marker differs from the required bytes.")
        data.extend(chunk)

    ftp.retrbinary(f"RETR {path}", collect)
    if data != SITE:
        raise CheckFailed("The existing marker differs from the required bytes.")


def check(ftp, mode):
    if ftp.pwd() != "/":
        raise CheckFailed("The FTPS login directory must be /.")
    root = entries(ftp, "/")
    for directory in (WP_ROOT, PRIVATE):
        name = directory[1:]
        if root.get(name) != (name, "dir"):
            raise CheckFailed("The expected staging directories were not confirmed.")

    wordpress = entries(ftp, WP_ROOT)
    for name, kind in (("wp-load.php", "file"), ("wp-content", "dir")):
        if wordpress.get(name) != (name, kind):
            raise CheckFailed("The expected WordPress layout was not confirmed.")

    backup = entries(ftp, PRIVATE)
    path = f"{PRIVATE}/{MARKER}"
    if MARKER in backup:
        if backup[MARKER] != (MARKER, "file"):
            raise CheckFailed("The marker name is occupied by an unexpected entry.")
        verify_marker(ftp, path)
        print("Staging marker verified.")
        return
    if mode == "check":
        print("Staging FTPS layout verified. Marker absent from the directory listing.")
        return

    ftp.storbinary(f"STOR {path}", BytesIO(SITE))
    verify_marker(ftp, path)
    print("Staging marker created and verified.")


def main():
    get = os.environ.__getitem__
    mode = get("FTPS_MODE")
    if (get("FTPS_TARGET") != SITE.decode("ascii") or mode not in ("check", "initialize")
            or (mode == "initialize" and get("FTPS_CONFIRMATION") != CONFIRMATION)):
        raise CheckFailed("The staging target or initialization confirmation is invalid.")
    if get("FTPS_WP_ROOT") != WP_ROOT or get("FTPS_PRIVATE_DIR") != PRIVATE:
        raise CheckFailed("The configured paths must be /htdocs and /top-pariks-backups.")

    host, port = get("FTPS_HOST"), int(get("FTPS_PORT"))
    user, password = get("FTPS_USER"), get("FTPS_PASSWORD")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host) or not 1 <= port <= 65535:
        raise CheckFailed("The FTPS endpoint configuration is invalid.")
    if not user or not password or any(c in user + password for c in "\r\n"):
        raise CheckFailed("The FTPS credentials configuration is invalid.")

    with deployment.session(host, port, user, password) as ftp:
        check(ftp, mode)


if __name__ == "__main__":
    try:
        main()
    except CheckFailed as error:
        sys.exit(f"{error} See docs/STAGE-003.md.")
    except (OSError, KeyError, ValueError, EOFError, ftplib.Error):
        # Server replies and configuration values may contain sensitive details.
        sys.exit("FTPS check or initialization failed. See docs/STAGE-003.md.")
