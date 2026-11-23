"""Replace the existing staging theme over explicit FTPS."""
import ftplib
import hashlib
import os
import re
import ssl
import sys
from contextlib import closing, contextmanager
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

SITE = b"https://top-pariks-test.freehosting.dev"
THEME = "top-pariks"


FTP_COMMANDS = frozenset(
    "AUTH USER PASS ACCT PBSZ PROT PWD TYPE PASV EPSV MLSD RETR MKD STOR RNFR RNTO".split()
)
OPERATION_ERRORS = (OSError, ValueError, EOFError, ftplib.Error)


class DiagnosticFTP(ftplib.FTP_TLS):
    last_command = None

    def putcmd(self, line):
        command = line.split(" ", 1)[0]
        self.last_command = command if command in FTP_COMMANDS else None
        super().putcmd(line)


class OperationFailed(Exception):
    """A diagnostic built only from fixed labels and a validated reply code."""

    def __init__(self, stage, category, error, command=None):
        code = None
        if isinstance(error, ftplib.Error) and error.args and isinstance(error.args[0], str):
            match = re.match(r"([1-5][0-9]{2})(?=[ -]|$)", error.args[0])
            if match:
                code = match[1]
        self.command = command
        self.reply_code = code
        super().__init__(
            f"stage={stage} category={category} command={command or 'none'} "
            f"reply={code or 'none'} error={type(error).__name__}"
        )


@contextmanager
def operation(ftp, stage, category):
    if isinstance(ftp, DiagnosticFTP):
        ftp.last_command = None
    try:
        yield
    except OPERATION_ERRORS as error:
        command = getattr(ftp, "last_command", None)
        if command not in FTP_COMMANDS:
            command = None
        raise OperationFailed(stage, category, error, command) from None


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
    with closing(DiagnosticFTP(context=context, timeout=30, encoding="utf-8")) as ftp:
        with operation(ftp, "connect", "connection"):
            ftp.connect(host, port)
        with operation(ftp, "control-tls", "security"):
            ftp.auth()
        with operation(ftp, "login", "authentication"):
            ftp.login(user, password)
        with operation(ftp, "data-protection", "security"):
            ftp.prot_p()
        yield ftp


def download_hash(ftp, path):
    digest = hashlib.sha256()
    ftp.retrbinary(f"RETR {path}", digest.update)
    return digest.hexdigest()


def listing(ftp, path, stage):
    # MLSD is lazy, so consume it inside the diagnostic scope.
    with operation(ftp, stage, "list"):
        return list(ftp.mlsd(path))


def snapshot(ftp, root, stage):
    files = {}
    for name, facts in listing(ftp, root, stage):
        kind = facts.get("type")
        if kind in ("cdir", "pdir"):
            continue
        component(name)
        if kind == "dir":
            files[name] = None
            files.update({f"{name}/{key}": value
                          for key, value in snapshot(ftp, f"{root}/{name}", stage).items()})
        elif kind == "file":
            with operation(ftp, stage, "read"):
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
                with operation(ftp, "candidate-upload", "mkdir"):
                    ftp.mkd(destination)
                expected[relative] = None
            else:
                data = archive.read(entry)
                with operation(ftp, "candidate-upload", "write"):
                    ftp.storbinary(f"STOR {destination}", BytesIO(data))
                expected[relative] = hashlib.sha256(data).hexdigest()
    require_snapshot(ftp, candidate, expected, "candidate-verify")
    return expected


def require_snapshot(ftp, path, expected, stage):
    actual = snapshot(ftp, path, stage)
    with operation(ftp, stage, "verify"):
        if actual != expected:
            raise ValueError("Remote theme files differ from the expected files")


def deploy(connect, wp_root, private, run_id, archive_path):
    themes = f"{wp_root}/wp-content/themes"
    live = f"{themes}/{THEME}"
    work = f"{private}/{run_id}"
    old = f"{work}/previous"
    candidate = f"{work}/candidate"

    with connect() as ftp:
        marker = BytesIO()
        with operation(ftp, "staging-marker", "read"):
            ftp.retrbinary(f"RETR {private}/staging-site.txt", marker.write)
        with operation(ftp, "staging-marker", "verify"):
            if marker.getvalue().strip() != SITE:
                raise ValueError("Staging marker does not match")
        before = snapshot(ftp, live, "existing-theme")
        with operation(ftp, "existing-theme", "verify"):
            if not {"style.css", "index.php"} <= before.keys():
                raise ValueError("An existing theme installation is required")
        with operation(ftp, "attempt-directory", "mkdir"):
            ftp.mkd(work)
        with operation(ftp, "candidate-directory", "mkdir"):
            ftp.mkd(candidate)
        expected = upload(ftp, candidate, archive_path)
        require_snapshot(ftp, live, before, "existing-theme-recheck")
        print(f"FTPS backup ID: {run_id}", flush=True)

        try:
            with operation(ftp, "backup-move", "rename"):
                ftp.rename(live, old)
            require_snapshot(ftp, old, before, "backup-verify")
            with operation(ftp, "candidate-activate", "rename"):
                ftp.rename(candidate, live)
            require_snapshot(ftp, live, expected, "active-theme-verify")
        except (*OPERATION_ERRORS, OperationFailed):
            # A lost reply can mean a rename succeeded. Inspect a fresh session.
            try:
                with connect() as recovery:
                    names = dict(listing(recovery, work, "recovery-inspect"))
                    if "previous" in names:
                        if "candidate" not in names:
                            with operation(recovery, "recovery-quarantine", "rename"):
                                recovery.rename(live, f"{work}/rejected")
                        with operation(recovery, "recovery-restore", "rename"):
                            recovery.rename(old, live)
                    require_snapshot(recovery, live, before, "recovery-verify")
            except OperationFailed as error:
                print(f"FTPS recovery failed ({error}). Stop before retrying.", file=sys.stderr)
            except OPERATION_ERRORS:
                print("FTPS recovery failed. Stop before retrying.", file=sys.stderr)
            else:
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
    except OperationFailed as error:
        sys.exit(f"FTPS failed ({error}). See docs/STAGE-004.md.")
    except (*OPERATION_ERRORS, KeyError) as error:
        # FTP replies can include server-side details. Keep them out of CI logs.
        sys.exit(f"FTPS failed ({type(error).__name__}). See docs/STAGE-004.md.")
