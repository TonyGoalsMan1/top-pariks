import io
import json
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from artifacts import FactoryError, file_record, inspect_theme, verify_backup, verify_release
from factory import REPO, Site


class ArtifactsTest(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.site = Site(REPO / "factory/sites/top-pariks.json", self.root / "state")
        self.slug = self.site.slug

    def make_zip(self, name=None):
        path = self.root / "theme.zip"
        with ZipFile(path, "w") as archive:
            archive.writestr(f"{self.slug}/style.css", "/*\nTheme Name: Test\nVersion: 1.2\n*/")
            archive.writestr(f"{self.slug}/index.php", "<?php echo 'factory';")
            if name:
                archive.writestr(name, "../../wp-config.php")
        return path

    def test_release_checks_actual_zip_bytes(self):
        path = self.make_zip()
        manifest = {
            "version": 1, "kind": "theme", "site_id": self.site.id, "slug": self.slug,
            "commit": "a" * 40, "theme.zip": file_record(path),
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        verify_release(self.site, self.root)
        with path.open("ab") as append:
            append.write(b"changed")
        with self.assertRaisesRegex(FactoryError, "checksum"):
            verify_release(self.site, self.root)

    def test_zip_rejects_traversal_and_symlink(self):
        with self.assertRaisesRegex(FactoryError, "Unsafe archive path"):
            inspect_theme(self.make_zip(f"{self.slug}/../../outside.php"), self.slug)
        link = ZipInfo(f"{self.slug}/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaisesRegex(FactoryError, "Unexpected theme entry"):
            inspect_theme(self.make_zip(link), self.slug)

    def make_backup(self, *, add_link=False):
        sql = self.root / "database.sql"
        sql.write_text("-- test database\n", encoding="utf-8")
        files = self.root / "wordpress.tar.gz"
        with tarfile.open(files, "w:gz") as archive:
            directory = tarfile.TarInfo("./wp-content/cache")
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o1777
            archive.addfile(directory)
            for name in ("wp-config.php", "wp-includes/version.php", f"wp-content/themes/{self.slug}/style.css"):
                member = tarfile.TarInfo(f"./{name}")
                member.size = 4
                archive.addfile(member, io.BytesIO(b"test"))
            if add_link:
                link = tarfile.TarInfo("./wp-content/uploads/link")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../../outside"
                archive.addfile(link)
        manifest = {
            "version": 1, "kind": "backup", "profile": self.site.backup_profile,
            "files": {path.name: file_record(path) for path in (sql, files)},
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_backup_accepts_default_cache_permissions_and_rejects_links(self):
        self.make_backup()
        verify_backup(self.site, self.root)
        self.make_backup(add_link=True)
        with self.assertRaisesRegex(FactoryError, "Unexpected WordPress archive entry"):
            verify_backup(self.site, self.root)


class QueueTest(unittest.TestCase):
    def test_dependencies_and_retry_limits(self):
        queue = json.loads((REPO / "factory/queue.json").read_text(encoding="utf-8"))
        registered = set()
        for task in queue["tasks"]:
            self.assertNotIn(task["id"], registered)
            self.assertIn(task["status"], queue["statuses"])
            self.assertTrue(task["criteria"] and task["verify"])
            self.assertLessEqual(set(task["depends_on"]), registered)
            policy = queue["retry_policies"][task["retry_policy"]]
            self.assertEqual(len(policy["backoff_seconds"]), policy["max_attempts"] - 1)
            registered.add(task["id"])
