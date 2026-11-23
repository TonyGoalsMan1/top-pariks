"""Write one staging probe and check its persistence in a fresh FTPS session."""
import hashlib
import os
import re
from importlib import import_module
from io import BytesIO
from uuid import uuid4

marker = import_module("staging-ftps-init")
deployment = marker.deployment
TARGET = marker.SITE.decode("ascii")
CONFIRMATION = "write one probe on top-pariks-test.freehosting.dev"
PRIVATE = marker.PRIVATE


class ProbeFailed(Exception):
    def __init__(self, stage, result):
        self.stage = stage
        self.result = result


def report(test_id, stage, result, command=None, reply=None):
    code = reply[:3] if reply and re.match(r"^[1-5][0-9]{2}(?=[ -]|$)", reply) else "none"
    print(f"stage={stage} command={command or 'none'} reply={code} result={result} test={test_id}",
          flush=True)


def inspect_layout(ftp):
    with deployment.operation(ftp, "login-directory", "inspect"):
        login_directory = ftp.pwd()
    if login_directory != "/":
        raise ProbeFailed("login-directory", "unexpected-directory")

    root = marker.entries(ftp, "/", "account-layout")
    for directory in (marker.WP_ROOT, PRIVATE):
        name = directory[1:]
        if root.get(name) != (name, "dir"):
            raise ProbeFailed("account-layout", "unexpected-directory")
    wordpress = marker.entries(ftp, marker.WP_ROOT, "wordpress-layout")
    if wordpress.get("wp-load.php") != ("wp-load.php", "file") or (
            wordpress.get("wp-content") != ("wp-content", "dir")):
        raise ProbeFailed("wordpress-layout", "unexpected-layout")


def read(ftp, path, limit, stage):
    data = bytearray()

    def collect(chunk):
        if len(data) + len(chunk) > limit:
            raise ProbeFailed(stage, "unexpected-size")
        data.extend(chunk)

    with deployment.operation(ftp, stage, "read"):
        reply = ftp.retrbinary(f"RETR {path}", collect)
    return bytes(data), reply


def probe(connect, test_id):
    if not re.fullmatch(r"[a-f0-9]{32}", test_id):
        raise ProbeFailed("configuration", "invalid-test-id")
    filename = f"stage-007-probe-{test_id}.txt"
    path = f"{PRIVATE}/{filename}"
    payload = f"TOP-PARIKS STAGE-007 {test_id}\n".encode("ascii")
    expected_hash = hashlib.sha256(payload).digest()

    with connect() as ftp:
        inspect_layout(ftp)
        entries = marker.entries(ftp, PRIVATE, "before-write")
        if filename in entries:
            raise ProbeFailed("before-write", "name-occupied")
        report(test_id, "before-write", "not-listed", "MLSD", ftp.lastresp)
        try:
            # Abort as soon as any byte is seen, including if MLSD hid the file.
            read(ftp, path, 0, "before-write-read")
        except deployment.OperationFailed as error:
            if (error.command, error.reply_code) != ("RETR", "550"):
                raise
            report(test_id, error.stage, "unavailable", error.command, error.reply_code)
        else:
            raise ProbeFailed("before-write-read", "name-occupied")

        with deployment.operation(ftp, "write", "write"):
            reply = ftp.storbinary(f"STOR {path}", BytesIO(payload))
        report(test_id, "write", "accepted", "STOR", reply)

    with connect() as ftp:
        inspect_layout(ftp)
        try:
            entries = marker.entries(ftp, PRIVATE, "after-write-list")
            entry = entries.get(filename)
            listed = entry == (filename, "file")
            result = "listed" if listed else ("unexpected-entry" if entry else "not-listed")
            report(test_id, "after-write-list", result, "MLSD", ftp.lastresp)
        except deployment.OperationFailed as error:
            report(test_id, error.stage, "failed", error.command, error.reply_code)
            listed = False
        except marker.CheckFailed:
            report(test_id, "after-write-list", "ambiguous", "MLSD", ftp.lastresp)
            listed = False

        data, reply = read(ftp, path, len(payload), "after-write-read")
        report(test_id, "after-write-read", "read", "RETR", reply)
        if hashlib.sha256(data).digest() != expected_hash or data != payload:
            raise ProbeFailed("verify", "sha256-mismatch")
        if not listed:
            raise ProbeFailed("verify", "listing-disagrees")
        report(test_id, "verify", "verified")


def run(env, test_id):
    mode = env.get("FTPS_MODE")
    if env.get("FTPS_TARGET") != TARGET:
        raise ProbeFailed("configuration", "invalid-target")
    if mode == "dry-run":
        report(test_id, "configuration", "dry-run")
        return
    if (mode != "probe" or env.get("FTPS_CONFIRMATION") != CONFIRMATION
            or env.get("FTPS_RUN_ATTEMPT") != "1"):
        raise ProbeFailed("configuration", "invalid-confirmation-or-attempt")
    if env.get("FTPS_PRIVATE_DIR") != PRIVATE or env.get("FTPS_WP_ROOT") != marker.WP_ROOT:
        raise ProbeFailed("configuration", "invalid-path")
    host, port = env["FTPS_HOST"], int(env["FTPS_PORT"])
    user, password = env["FTPS_USER"], env["FTPS_PASSWORD"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host) or not 1 <= port <= 65535:
        raise ProbeFailed("configuration", "invalid-endpoint")
    if not user or not password or any(c in user + password for c in "\r\n"):
        raise ProbeFailed("configuration", "invalid-credentials")

    def connect():
        return deployment.session(host, port, user, password)

    probe(connect, test_id)


def main():
    test_id = uuid4().hex
    try:
        run(os.environ, test_id)
    except deployment.OperationFailed as error:
        report(test_id, error.stage, "failed", error.command, error.reply_code)
    except ProbeFailed as error:
        report(test_id, error.stage, error.result)
    except marker.CheckFailed:
        report(test_id, "layout", "ambiguous")
    except (*deployment.OPERATION_ERRORS, KeyError):
        report(test_id, "probe", "failed")
    else:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
