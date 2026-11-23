import ftplib
import io
import sys
import unittest
from contextlib import contextmanager, redirect_stdout
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
probe = import_module("staging-ftps-probe")

TEST_ID = "a" * 32
TARGET_PATH = f"{probe.PRIVATE}/stage-007-probe-{TEST_ID}.txt"
MISSING = "550 hidden-server-response /hidden-path"


class FakeFTP:
    lastresp = "226"

    def __init__(self, server):
        self.server = server
        self.last_command = None

    def pwd(self):
        return "/"

    def mlsd(self, path):
        self.last_command = "MLSD"
        if path == "/":
            return [("htdocs", {"type": "dir"}), ("top-pariks-backups", {"type": "dir"})]
        if path == "/htdocs":
            return [("wp-load.php", {"type": "file"}), ("wp-content", {"type": "dir"})]
        if self.server.denied:
            raise ftplib.error_perm(MISSING)
        if self.server.data is None or self.server.hide:
            return []
        return [(TARGET_PATH.rsplit("/", 1)[1], {"type": "file"})]

    def retrbinary(self, command, collect):
        self.last_command = "RETR"
        assert command == f"RETR {TARGET_PATH}"
        if self.server.data is None or (self.server.writes and self.server.retr_denied):
            raise ftplib.error_perm(MISSING)
        collect(self.server.data)
        return "226 hidden-server-response"

    def storbinary(self, command, data):
        self.last_command = "STOR"
        assert command == f"STOR {TARGET_PATH}"
        self.server.writes += 1
        if self.server.stor_denied:
            raise ftplib.error_perm(MISSING)
        self.server.data = data.read()
        return "226 hidden-server-response"


class FakeServer:
    def __init__(self):
        self.data = None
        self.writes = 0
        self.sessions = 0
        self.active = False
        self.denied = False
        self.stor_denied = False
        self.retr_denied = False
        self.hide = False
        self.disappear = False
        self.corrupt = False

    @contextmanager
    def connect(self, *credentials):
        assert not self.active
        self.active = True
        self.sessions += 1
        if self.sessions == 2 and self.writes:
            if self.disappear:
                self.data = None
            if self.corrupt:
                self.data = b"x" * len(self.data)
        try:
            yield FakeFTP(self)
        finally:
            self.active = False


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.env = {
            "FTPS_MODE": "probe",
            "FTPS_TARGET": probe.TARGET,
            "FTPS_RUN_ATTEMPT": "1",
            "FTPS_CONFIRMATION": probe.CONFIRMATION,
            "FTPS_HOST": "ftps.example",
            "FTPS_PORT": "21",
            "FTPS_USER": "hidden-user",
            "FTPS_PASSWORD": "hidden-password",
            "FTPS_WP_ROOT": "/htdocs",
            "FTPS_PRIVATE_DIR": "/top-pariks-backups",
        }

    def execute(self, status):
        output = io.StringIO()
        with patch.dict(probe.os.environ, self.env, clear=True), patch.object(
            probe.deployment, "session", self.server.connect
        ), patch.object(probe, "uuid4", return_value=SimpleNamespace(hex=TEST_ID)), (
            redirect_stdout(output)
        ):
            self.assertEqual(probe.main(), status)
        log = output.getvalue()
        for line in log.splitlines():
            self.assertRegex(
                line,
                rf"^stage=[a-z-]+ command=(?:[A-Z]+|none) reply=(?:[1-5][0-9]{{2}}|none)"
                rf" result=[a-z0-9-]+ test={TEST_ID}$",
            )
        for private in ("hidden-", TARGET_PATH, "TOP-PARIKS STAGE-007"):
            self.assertNotIn(private, log)
        return log

    def test_success_and_collision_on_repeat(self):
        self.assertIn("result=verified", self.execute(0))
        self.assertEqual(self.server.sessions, 2)
        self.assertIn("result=name-occupied", self.execute(1))
        self.assertEqual(self.server.writes, 1)

    def test_github_rerun_is_blocked_before_connect(self):
        self.env["FTPS_RUN_ATTEMPT"] = "2"
        self.assertIn("result=invalid-confirmation-or-attempt", self.execute(1))
        self.assertEqual(self.server.sessions, 0)

    def test_stor_refused(self):
        self.server.stor_denied = True
        self.assertIn("stage=write command=STOR reply=550 result=failed", self.execute(1))
        self.assertEqual(self.server.sessions, 1)
        self.assertEqual(self.server.writes, 1)

    def test_retr_550_despite_listing(self):
        self.server.retr_denied = True
        log = self.execute(1)
        self.assertIn("result=listed", log)
        self.assertIn("stage=after-write-read command=RETR reply=550", log)
        self.assertEqual(self.server.writes, 1)

    def test_disappears_after_successful_stor(self):
        self.server.disappear = True
        log = self.execute(1)
        self.assertIn("command=STOR reply=226 result=accepted", log)
        self.assertIn("stage=after-write-list command=MLSD reply=226 result=not-listed", log)
        self.assertIn("stage=after-write-read command=RETR reply=550", log)
        self.assertEqual(self.server.writes, 1)

    def test_listing_omits_readable_file(self):
        self.server.hide = True
        log = self.execute(1)
        self.assertIn("result=read", log)
        self.assertIn("result=listing-disagrees", log)

    def test_direct_read_detects_hidden_existing_file(self):
        self.server.hide = True
        self.server.data = b"existing"
        self.execute(1)
        self.assertEqual(self.server.writes, 0)
        self.assertEqual(self.server.data, b"existing")

    def test_sha256_mismatch(self):
        self.server.corrupt = True
        self.assertIn("result=sha256-mismatch", self.execute(1))
        self.assertEqual(self.server.writes, 1)

    def test_missing_list_permission(self):
        self.server.denied = True
        self.assertIn("stage=before-write command=MLSD reply=550 result=failed", self.execute(1))
        self.assertEqual(self.server.writes, 0)

    def test_invalid_directory(self):
        self.env["FTPS_PRIVATE_DIR"] = "/top-pariks-backups/../htdocs"
        self.assertIn("result=invalid-path", self.execute(1))
        self.assertEqual(self.server.sessions, 0)

    def test_dry_run_needs_no_credentials(self):
        self.env = {"FTPS_MODE": "dry-run", "FTPS_TARGET": probe.TARGET}
        self.assertIn("result=dry-run", self.execute(0))
        self.assertEqual(self.server.sessions, 0)

    def test_write_requires_exact_target_and_confirmation(self):
        with patch.object(probe.deployment, "session", self.server.connect):
            for field in ("FTPS_TARGET", "FTPS_CONFIRMATION"):
                with self.subTest(field=field), self.assertRaises(probe.ProbeFailed):
                    probe.run({**self.env, field: "wrong"}, TEST_ID)
        self.assertEqual(self.server.sessions, 0)
