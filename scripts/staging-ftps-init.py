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


def entries(ftp, directory, stage):
    result = {}
    for name, facts in deployment.listing(ftp, directory, stage):
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

    with deployment.operation(ftp, "marker-check", "read"):
        ftp.retrbinary(f"RETR {path}", collect)
    if data != SITE:
        raise CheckFailed("The existing marker differs from the required bytes.")


def check(ftp, mode):
    with deployment.operation(ftp, "login-directory", "inspect"):
        login_directory = ftp.pwd()
    if login_directory != "/":
        raise CheckFailed("The expected FTPS login directory was not confirmed.")
    root = entries(ftp, "/", "account-layout")
    for directory in (WP_ROOT, PRIVATE):
        name = directory[1:]
        if root.get(name) != (name, "dir"):
            raise CheckFailed("The expected staging directories were not confirmed.")

    wordpress = entries(ftp, WP_ROOT, "wordpress-layout")
    for name, kind in (("wp-load.php", "file"), ("wp-content", "dir")):
        if wordpress.get(name) != (name, kind):
            raise CheckFailed("The expected WordPress layout was not confirmed.")

    backup = entries(ftp, PRIVATE, "backup-layout")
    path = f"{PRIVATE}/{MARKER}"
    if MARKER in backup:
        name, kind = backup[MARKER]
        if name != MARKER:
            raise CheckFailed("The listed marker name has unexpected capitalization.")
        if kind != "file":
            raise CheckFailed("The marker name is occupied by an unexpected entry.")
        verify_marker(ftp, path)
        return False

    try:
        verify_marker(ftp, path)
    except deployment.OperationFailed as error:
        # Only RETR 550 permits the guarded write. It can also mean access denied,
        # so initialize still requires independent confirmation of absence.
        if mode != "initialize" or (error.command, error.reply_code) != ("RETR", "550"):
            raise CheckFailed(
                f"MLSD did not list the marker and RETR failed ({error}). "
                "The marker may be missing or inaccessible."
            ) from None
    except CheckFailed as error:
        raise CheckFailed(f"MLSD did not list the marker. {error}") from None
    else:
        raise CheckFailed(
            "MLSD did not list the marker, but RETR verified its bytes. "
            "The listing and direct read disagree."
        )

    with deployment.operation(ftp, "marker-initialize", "write"):
        ftp.storbinary(f"STOR {path}", BytesIO(SITE))
    return True


def main():
    get = os.environ.__getitem__
    mode = get("FTPS_MODE")
    if (get("FTPS_TARGET") != SITE.decode("ascii") or mode not in ("check", "initialize")
            or (mode == "initialize" and get("FTPS_CONFIRMATION") != CONFIRMATION)):
        raise CheckFailed("The staging target or initialization confirmation is invalid.")
    if get("FTPS_WP_ROOT") != WP_ROOT or get("FTPS_PRIVATE_DIR") != PRIVATE:
        raise CheckFailed("The configured staging directories do not match the expected layout.")

    host, port = get("FTPS_HOST"), int(get("FTPS_PORT"))
    user, password = get("FTPS_USER"), get("FTPS_PASSWORD")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host) or not 1 <= port <= 65535:
        raise CheckFailed("The FTPS endpoint configuration is invalid.")
    if not user or not password or any(c in user + password for c in "\r\n"):
        raise CheckFailed("The FTPS credentials configuration is invalid.")

    with deployment.session(host, port, user, password) as ftp:
        wrote_marker = check(ftp, mode)
    if not wrote_marker:
        print("Staging marker verified.")
        return

    try:
        with deployment.session(host, port, user, password) as ftp:
            check(ftp, "check")
    except (CheckFailed, deployment.OperationFailed) as error:
        raise CheckFailed(
            f"Marker write completed but verification in a fresh session failed ({error}). "
            "Run check before retrying."
        ) from None
    print("Staging marker created and verified.")


if __name__ == "__main__":
    readiness = "Staging is not ready for publication. " if os.getenv("FTPS_MODE") == "check" else ""
    try:
        main()
    except deployment.OperationFailed as error:
        sys.exit(f"{readiness}FTPS failed ({error}). See docs/STAGE-004.md.")
    except CheckFailed as error:
        sys.exit(f"{readiness}{error} See docs/STAGE-006.md.")
    except (OSError, KeyError, ValueError, EOFError, ftplib.Error):
        # Server replies and configuration values may contain sensitive details.
        sys.exit(f"{readiness}FTPS check or initialization failed. See docs/STAGE-006.md.")
