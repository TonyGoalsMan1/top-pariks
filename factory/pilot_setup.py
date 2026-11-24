"""Prepare and optionally publish the isolated STAGE-017 storefront seed."""

import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile

from .control.__main__ import password_hash
from .orchestrator.__main__ import private_state
from .orchestrator.projects import GITHUB, load
from .orchestrator.queue import QueueError


ROOT = Path(__file__).resolve().parent.parent
CSS = "theme/top-pariks/style.css"
CHECK = "Pilot stylesheet"


def command(*args, cwd, **kwargs):
    return subprocess.check_output(args, cwd=cwd, timeout=120, **kwargs)


def write_json(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def fixture(directory):
    if directory.exists():
        return
    with tempfile.TemporaryDirectory(dir=directory.parent) as staging:
        target = Path(staging) / "seed"
        target.mkdir()
        archive = command("git", "archive", "HEAD", "theme/top-pariks", "sandbox/seed.php", cwd=ROOT)
        subprocess.run(["tar", "-xf", "-"], cwd=target, input=archive, check=True)
        workflow = target / ".github/workflows/pilot.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("""name: Factory pilot
on:
  push:
    branches: ['factory/test-*']
permissions:
  contents: read
jobs:
  stylesheet:
    name: Pilot stylesheet
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with:
          persist-credentials: false
          fetch-depth: 0
      - name: Check the isolated CSS patch
        run: |
          set -eu
          css=theme/top-pariks/style.css
          git diff --check origin/main HEAD
          test "$(git diff --no-renames --name-only origin/main HEAD)" = "$css"
          test "$(git ls-tree HEAD -- "$css" | cut -d ' ' -f 1)" = "100644"
          test "$(wc -c < "$css")" -le 65536
""", encoding="utf-8")
        command("git", "init", "-b", "main", cwd=target)
        command("git", "add", "--all", cwd=target)
        command("git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                "-c", "user.name=Factory Pilot", "-c", "user.email=factory@example.invalid",
                "commit", "-m", "Seed the isolated WooCommerce pilot", cwd=target)
        target.rename(directory)


def setup(args, home):
    source = home / "seed"
    fixture(source)
    base = command("git", "rev-parse", "refs/heads/main", cwd=source, text=True).strip()
    profile_path = home / "site.json"
    if not profile_path.exists():
        profile = json.loads((ROOT / "factory/sites/example-store.json").read_text())
        profile.update(site_id="stage-017-store", port=args.wordpress_port)
        write_json(profile_path, profile)
    registry = home / "projects.json"
    if not registry.exists():
        write_json(registry, {"version": 1, "projects": [{
            "id": "stage-017-store", "repository": args.repository, "base": "main",
            "site_type": "woocommerce", "domain": "localhost", "environments": ["test"],
            "wordpress_profile": "site.json", "factory_source": "seed",
            "permissions": ["report", "code", "start", "health", "backup", "restore", "rollback"],
            "agents": ["project-manager", "architect", "frontend", "qa"], "review_role": "qa",
            "executor": "codex", "budget": {"max_calls": 6}, "preview_base": base,
            "context": ["theme/top-pariks/woocommerce.php", "theme/top-pariks/functions.php"],
            "editable": [CSS], "timeout_seconds": 600, "max_attempts": 2,
            "github": {"trusted_test_ci": True, "auto_merge": False, "required_checks": [CHECK]},
        }]})
    project = load(registry)["stage-017-store"]
    if project.slug.lower() != args.repository.lower() or project.preview_base != base:
        raise QueueError("Existing directory is bound to a different test repository or seed")
    accounts = home / "accounts.json"
    if not accounts.exists() and not args.seed_only:
        password = getpass("New PWA owner password (at least 12 characters): ")
        if not 12 <= len(password) <= 256 or password != getpass("Repeat password: "):
            raise QueueError("Use a matching password of 12–256 characters")
        salt = secrets.token_bytes(16)
        write_json(accounts, {"owner": {"owner": True, "salt": salt.hex(),
                                        "hash": password_hash(password, salt)}})
    return source, base


def publish(slug, source, base):
    # This is the owner's interactive GitHub session, separate from the runtime PAT.
    env = dict(os.environ)
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "FACTORY_GITHUB_TOKEN", "GH_HOST"):
        env.pop(name, None)
    identity = command("gh", "api", "user", "--jq", ".login", cwd=source, env=env, text=True).strip()
    if slug.split("/")[0].lower() != identity.lower():
        raise QueueError("Create the private pilot repository in the signed-in owner's account")
    receipt = source.parent / "created-repository.json"
    if not receipt.exists():
        command("gh", "repo", "create", slug, "--private", cwd=source, env=env)
        info = json.loads(command("gh", "api", f"repos/{slug}", cwd=source, env=env))
        write_json(receipt, {"repository_id": info["id"], "base": base})
    else:
        info = json.loads(command("gh", "api", f"repos/{slug}", cwd=source, env=env))
    if (not info["private"] or info["fork"]
            or json.loads(receipt.read_text()) != {"repository_id": info["id"], "base": base}):
        raise QueueError("Push requires the original private test repository created by setup")
    git = ("git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential")
    remote = f"https://github.com/{slug}.git"
    refs = command(*git, "ls-remote", "--refs", remote, cwd=source, env=env, text=True).strip()
    if refs == f"{base}\trefs/heads/main":
        return
    if refs:
        raise QueueError("Test repository already contains unexpected refs")
    command(*git, "push", remote, f"{base}:refs/heads/main", cwd=source, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="New private GitHub OWNER/REPO for synthetic data")
    parser.add_argument("--home", type=Path, default=Path.home() / ".factory-pilot-017")
    parser.add_argument("--wordpress-port", type=int, default=8181)
    parser.add_argument("--seed-only", action="store_true", help="Generate fixture and profile without password prompt")
    parser.add_argument("--publish", action="store_true", help="Create the new private repo and push the trusted seed")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if not re.fullmatch(GITHUB, args.repository) or args.repository.lower() == "tonygoalsman1/top-pariks":
            raise QueueError("Use a distinct test GitHub owner/repository")
        home = private_state(args.home)
        source, base = setup(args, home)
        if args.publish:
            publish(args.repository, source, base)
        print(f"Pilot profile: {home}\nTrusted start commit: {base}")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Pilot setup: {error}\n")


if __name__ == "__main__":
    main()
