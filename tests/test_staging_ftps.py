import ftplib
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from importlib import import_module
from io import StringIO
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
deploy = import_module("staging-ftps")
init = import_module("staging-ftps-init")

LIVE = "/htdocs/wp-content/themes/top-pariks"
PRIVATE = "/top-pariks-backups"
WORK = f"{PRIVATE}/1-1"


class LocalFTP:
    def __init__(self, root):
        self.root = root
        self.fail_move = None
        self.fail_restore = False
        self.writes = 0

    def path(self, name):
        return self.root / name.lstrip("/")

    def pwd(self):
        return "/"

    def mlsd(self, name):
        for entry in self.path(name).iterdir():
            yield entry.name, {"type": "dir" if entry.is_dir() else "file"}

    def mkd(self, name):
        try:
            self.path(name).mkdir()
        except FileExistsError:
            raise ftplib.error_perm(f"550 private path {name} exists") from None

    def retrbinary(self, command, callback):
        callback(self.path(command.split(" ", 1)[1]).read_bytes())

    def storbinary(self, command, stream):
        self.writes += 1
        self.path(command.split(" ", 1)[1]).write_bytes(stream.read())

    def rename(self, source, target):
        if self.fail_restore and source.endswith("/previous"):
            raise ftplib.error_perm("550 recovery-sensitive-detail")
        self.path(source).rename(self.path(target))
        if self.fail_move == source:
            self.fail_move = None
            raise ftplib.error_temp("450 move-sensitive-detail")


class FTPSDiagnostics(unittest.TestCase):
    def test_command_and_reply_are_safe(self):
        ftp = deploy.DiagnosticFTP()
        ftp.putline = Mock()
        ftp.getline = Mock(side_effect=["350 ready", "550 /sensitive/path"])
        with self.assertRaisesRegex(
            deploy.OperationFailed, r"stage=backup-move category=rename command=RNTO reply=550"
        ) as failure:
            with deploy.operation(ftp, "backup-move", "rename"):
                ftp.rename("/old", "/sensitive/path")
        self.assertNotIn("sensitive", str(failure.exception))

        ftp.getline = Mock(side_effect=["331 password required", "530 private-user private-password"])
        with self.assertRaisesRegex(deploy.OperationFailed, r"command=PASS reply=530") as failure:
            with deploy.operation(ftp, "login", "authentication"):
                ftp.login("private-user", "private-password", secure=False)
        self.assertNotIn("private", str(failure.exception))

    def test_lazy_listing_failure_is_tagged(self):
        ftp = Mock(spec=ftplib.FTP_TLS)

        def listing(_path):
            yield "partial", {}
            raise ftplib.error_perm("502-disabled with sensitive details")

        ftp.mlsd = listing
        with self.assertRaisesRegex(deploy.OperationFailed, r"category=list command=none reply=502"):
            deploy.listing(ftp, "/private", "backup-layout")

    def test_unstructured_errors_do_not_expose_text_or_guess_code(self):
        for error in (OSError("550 private"), ftplib.error_perm("invalid 550 /private")):
            with self.subTest(error=type(error).__name__):
                with self.assertRaisesRegex(deploy.OperationFailed, r"command=none reply=none") as failure:
                    with deploy.operation(None, "connect", "connection"):
                        raise error
                self.assertNotIn("private", str(failure.exception))


class FTPSRetry(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ftp = LocalFTP(self.root)
        self.ftp.path(LIVE).mkdir(parents=True)
        self.ftp.path(PRIVATE).mkdir()
        self.ftp.path("/htdocs/wp-load.php").touch()
        self.marker = self.ftp.path(f"{PRIVATE}/staging-site.txt")
        self.marker.write_bytes(deploy.SITE)
        for name in ("style.css", "index.php"):
            self.ftp.path(f"{LIVE}/{name}").write_bytes(b"old")
        self.archive = self.root / "theme.zip"
        with ZipFile(self.archive, "w") as archive:
            archive.writestr("top-pariks/style.css", b"new")
            archive.writestr("top-pariks/index.php", b"new")

    @contextmanager
    def connect(self):
        yield self.ftp

    def run_deploy(self, attempt):
        with redirect_stdout(StringIO()):
            deploy.deploy(self.connect, "/htdocs", PRIVATE, attempt, self.archive)

    def test_marker_check_and_existing_initialize_are_read_only(self):
        with redirect_stdout(StringIO()):
            init.check(self.ftp, "check")
            init.check(self.ftp, "initialize")
        self.assertEqual(self.ftp.writes, 0)

    def test_marker_retry_after_lost_write_reply_does_not_overwrite(self):
        self.marker.unlink()
        store = self.ftp.storbinary

        def write_then_fail(command, stream):
            store(command, stream)
            raise ftplib.error_temp("426 lost reply")

        self.ftp.storbinary = write_then_fail
        with self.assertRaisesRegex(deploy.OperationFailed, r"stage=marker-initialize.*reply=426"):
            init.check(self.ftp, "initialize")
        with redirect_stdout(StringIO()):
            init.check(self.ftp, "check")
            init.check(self.ftp, "initialize")
        self.assertEqual(self.ftp.writes, 1)

    def test_collision_keeps_failed_attempt_and_new_attempt_backs_up_old_theme(self):
        self.ftp.path(WORK).mkdir()
        sentinel = self.ftp.path(f"{WORK}/keep.txt")
        sentinel.write_bytes(b"keep")
        with self.assertRaisesRegex(deploy.OperationFailed, r"stage=attempt-directory.*reply=550"):
            self.run_deploy("1-1")
        self.assertEqual(self.ftp.path(f"{LIVE}/index.php").read_bytes(), b"old")
        self.run_deploy("1-2")
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertEqual(self.ftp.path(f"{PRIVATE}/1-2/previous/index.php").read_bytes(), b"old")
        self.assertEqual(self.ftp.path(f"{LIVE}/index.php").read_bytes(), b"new")

    def test_lost_activation_reply_restores_and_preserves_both_versions(self):
        self.ftp.fail_move = f"{WORK}/candidate"
        with self.assertRaisesRegex(deploy.OperationFailed, r"stage=candidate-activate.*reply=450"):
            self.run_deploy("1-1")
        self.assertEqual(self.ftp.path(f"{LIVE}/index.php").read_bytes(), b"old")
        self.assertEqual(self.ftp.path(f"{WORK}/rejected/index.php").read_bytes(), b"new")
        self.run_deploy("1-2")

    def test_recovery_failure_keeps_original_diagnosis(self):
        self.ftp.fail_move = LIVE
        self.ftp.fail_restore = True
        output = StringIO()
        with redirect_stderr(output):
            with self.assertRaisesRegex(deploy.OperationFailed, r"stage=backup-move.*reply=450"):
                self.run_deploy("1-1")
        self.assertIn("stage=recovery-restore category=rename command=none reply=550", output.getvalue())
        self.assertNotIn("sensitive", output.getvalue())
        self.assertEqual(self.ftp.path(f"{WORK}/previous/index.php").read_bytes(), b"old")


if __name__ == "__main__":
    unittest.main()
