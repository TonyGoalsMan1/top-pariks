import os
from pathlib import Path
import runpy
import sqlite3
import stat
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
prepare = runpy.run_path(str(ROOT / ".devcontainer/pilot-state.py"))["prepare"]


class CodespaceStateTests(unittest.TestCase):
    def setUp(self):
        workspaces = tempfile.TemporaryDirectory()
        self.addCleanup(workspaces.cleanup)
        self.workspaces = Path(workspaces.name)
        self.state = self.workspaces / ".factory-pilot-017"

    def prepare(self):
        prepare(self.workspaces, os.getuid(), os.getgid())

    def test_create_private_state_and_repair_mode_without_replacing_data(self):
        self.prepare()
        original = self.state.stat()
        self.assertEqual(original.st_uid, os.getuid())
        self.assertEqual(stat.S_IMODE(original.st_mode), 0o700)
        password = self.state / "owner-password"
        password.write_text("fixture\n")
        database = self.state / "queue.sqlite3"
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE fixture (value INTEGER)")
            db.execute("INSERT INTO fixture VALUES (17)")
        self.state.chmod(0o755)
        self.prepare()
        self.prepare()
        self.assertEqual(self.state.stat().st_ino, original.st_ino)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        self.assertEqual(password.read_text(), "fixture\n")
        with sqlite3.connect(database) as db:
            self.assertEqual(db.execute("SELECT value FROM fixture").fetchone(), (17,))

    def test_repair_empty_shared_writable_state_but_reject_populated_state(self):
        self.state.mkdir()
        self.state.chmod(0o777)
        self.prepare()
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        (self.state / "fixture").touch()
        self.state.chmod(0o777)
        with self.assertRaisesRegex(ValueError, "Cannot safely repair populated"):
            self.prepare()
        self.assertTrue((self.state / "fixture").is_file())
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o777)

    def test_reject_symlink_and_regular_file(self):
        target = self.workspaces / "target"
        target.mkdir()
        target.chmod(0o755)
        self.state.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "must be a real directory"):
            self.prepare()
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)
        self.state.unlink()
        self.state.write_text("fixture")
        with self.assertRaisesRegex(ValueError, "must be a real directory"):
            self.prepare()
        self.assertEqual(self.state.read_text(), "fixture")

    def test_reject_git_checkout_before_creation(self):
        (self.workspaces / ".git").touch()
        with self.assertRaisesRegex(ValueError, "outside Git checkouts"):
            self.prepare()
        self.assertFalse(self.state.exists())
