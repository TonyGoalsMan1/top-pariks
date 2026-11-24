#!/usr/bin/env python3
"""Run the disposable Factory lifecycle used by GitHub Actions."""

import contextlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from artifacts import read_json
from factory import REPO, Site


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, **kwargs).strip()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def candidate(workspace, slug, changes):
    """Make a test commit with a private Git index and no changes to the branch."""
    env = dict(os.environ, GIT_INDEX_FILE=str(workspace / "test-index"),
               GIT_AUTHOR_NAME="Factory Test", GIT_AUTHOR_EMAIL="factory@example.test",
               GIT_COMMITTER_NAME="Factory Test", GIT_COMMITTER_EMAIL="factory@example.test")
    run("git", "read-tree", "HEAD", env=env)
    for name, content in changes.items():
        blob = run("git", "hash-object", "-w", "--stdin", env=env, input=content)
        run("git", "update-index", "--add", "--cacheinfo", f"100644,{blob},theme/{slug}/{name}", env=env)
    tree = run("git", "write-tree", env=env)
    return run("git", "commit-tree", tree, "-p", "HEAD", "-m", "Factory lifecycle fixture", env=env)


class Lifecycle:
    def __init__(self, workspace):
        self.workspace = workspace
        self.state = workspace / "state"
        self.sites = {}

    def profile(self, filename, port):
        config = read_json(REPO / "factory/sites" / filename)
        config["port"] = port
        path = self.workspace / filename
        path.write_text(json.dumps(config), encoding="utf-8")
        self.sites[config["site_id"]] = (path, Site(path, self.state))
        return self.sites[config["site_id"]][1]

    def factory(self, site, *args, reject=None):
        path = self.sites[site.id][0]
        command = [sys.executable, REPO / "factory/factory.py",
                   "--site", path, "--state", self.state, *args]
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(result.stdout, end="", flush=True)
        if reject is None:
            result.check_returncode()
        else:
            require(result.returncode != 0 and reject in result.stdout, f"Expected rejection: {reject}")
        return result.stdout

    def build(self, site, name, *args):
        release = self.workspace / name
        self.factory(site, "build", release, *args)
        self.factory(site, "verify-release", release)
        return release

    def cleanup(self, failed):
        for _, site in self.sites.values():
            if failed:
                with contextlib.suppress(subprocess.SubprocessError):
                    site.compose("logs", "--no-color", "--tail", "60")
            site.compose("down", "--volumes")


def allocate_ports():
    # Hold both reservations until the profiles have distinct loopback ports.
    with socket.socket() as first, socket.socket() as second:
        for sock in (first, second):
            sock.bind(("127.0.0.1", 0))
        return first.getsockname()[1], second.getsockname()[1]


def exercise(test):
    port, example_port = allocate_ports()
    site = test.profile("top-pariks.json", port)
    example = test.profile("example-store.json", example_port)

    initial = test.build(site, "initial")
    test.factory(site, "start", initial)
    test.factory(site, "start", initial)
    test.factory(example, "start", test.build(example, "example"))
    require(example.wp("option", "get", "blogname", capture=True) == example.config["title"],
            "Second store must have its own settings")
    test.factory(example, "verify-release", initial, reject="Release manifest does not match this site")

    site.wp("option", "update", "factory_saved", "snapshot")
    site.compose("exec", "-T", "wordpress", "sh", "-ec",
                 'mkdir -p wp-content/uploads; printf "snapshot" > wp-content/uploads/factory.txt')
    backups_before = set(site.backups.glob("*"))
    test.factory(site, "backup")
    [backup] = set(site.backups.glob("*")) - backups_before
    test.factory(site, "verify-backup", backup.name)
    foreign = example.backups / backup.name
    shutil.copytree(backup, foreign)
    test.factory(example, "restore", backup.name, reject="Backup profile does not match this site")
    require(example.wp("option", "get", "blogname", capture=True) == example.config["title"],
            "Cross-site rejection must leave the other store running")
    shutil.rmtree(foreign)

    with (backup / "database.sql").open("ab") as altered:
        altered.write(b"\n-- corrupted for the integrity drill\n")
    test.factory(site, "restore", backup.name, reject="Backup checksum")
    with (backup / "database.sql").open("r+b") as original:
        original.truncate(read_json(backup / "manifest.json")["files"]["database.sql"]["bytes"])

    site.wp("option", "update", "factory_saved", "changed")
    site.database('exec mariadb -u wordpress wordpress -e "CREATE TABLE factory_after_snapshot (id int)"')
    site.compose("exec", "-T", "wordpress", "sh", "-ec",
                 'printf "changed" > wp-content/uploads/factory.txt; touch wp-content/uploads/extra.txt')
    test.factory(site, "restore", backup.name)
    require(site.wp("option", "get", "factory_saved", capture=True) == "snapshot",
            "Restore did not replace the database")
    require(site.database('exec mariadb -u wordpress wordpress -Nse "SHOW TABLES LIKE \'factory_after_snapshot\'"',
                          capture=True) == "", "Restore left a table created after the backup")
    site.compose("exec", "-T", "wordpress", "sh", "-ec",
                 'test "$(cat wp-content/uploads/factory.txt)" = snapshot; test ! -e wp-content/uploads/extra.txt')

    site.compose("down", "--volumes")
    test.factory(site, "restore", backup.name)
    require(site.wp("option", "get", "factory_saved", capture=True) == "snapshot",
            "Clean-volume restore did not recover WordPress data")
    site.compose("exec", "-T", "wordpress", "sh", "-ec",
                 'test "$(cat wp-content/uploads/factory.txt)" = snapshot')

    good_sha = candidate(test.workspace, site.slug, {"factory-release.txt": "known-good release\n"})
    good = test.build(site, "healthy-update", "--ref", good_sha)
    test.factory(site, "deploy", good)
    theme_path = f"wp-content/themes/{site.slug}"
    site.compose("exec", "-T", "wordpress", "test", "-s", f"{theme_path}/factory-release.txt")
    site.wp("option", "update", "factory_saved", "before-failed-release")

    # Valid ZIP, valid PHP and HTTP 200, but the mandatory homepage marker is gone.
    bad_sha = candidate(test.workspace, site.slug, {
        "front-page.php": "<?php get_header(); ?><main>Intentional smoke failure</main><?php get_footer(); ?>\n",
        "bad-only.txt": "must disappear after rollback\n",
        "functions.php": (REPO / "theme" / site.slug / "functions.php").read_text(encoding="utf-8")
        + "\nadd_action('template_redirect', static function () {\n"
          "    if (is_front_page()) { update_option('factory_candidate_ran', 'yes'); }\n"
          "});\n",
    })
    bad = test.build(site, "broken-update", "--ref", bad_sha)
    output = test.factory(site, "deploy", bad, reject="Operation failed and the site was recovered")
    require("Storefront content check failed for /" in output and "Rollback verified (deploy)" in output,
            "Expected a failed health check followed by successful rollback")
    require(not site.pending.exists(), "Successful rollback must clear the journal")
    require(site.wp("option", "get", "factory_saved", capture=True) == "before-failed-release",
            "Theme rollback modified pre-existing database state")
    require(site.wp("option", "get", "factory_candidate_ran", capture=True) == "yes",
            "Theme rollback must preserve database writes made after the snapshot")
    site.compose("exec", "-T", "wordpress", "sh", "-ec",
                 'test "$(cat "$1/factory-release.txt")" = "known-good release"; test ! -e "$1/bad-only.txt"',
                 "factory-test", theme_path)
    test.factory(site, "health")
    test.factory(example, "health")
    print("Factory lifecycle verified for two independent sites.", flush=True)


if __name__ == "__main__":
    os.chdir(REPO)
    with tempfile.TemporaryDirectory(prefix="factory-lifecycle-") as work:
        test = Lifecycle(Path(work))
        failed = True
        try:
            exercise(test)
            failed = False
        finally:
            test.cleanup(failed)
