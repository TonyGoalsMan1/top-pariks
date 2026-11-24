"""Prepare two local, synthetic projects with a randomly generated demo login."""

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

from factory.orchestrator.__main__ import private_state
from factory.orchestrator.queue import QueueError

from .__main__ import password_hash


def prepare(root):
    config = root / "projects.json"
    accounts = root / "accounts.json"
    if any(root.iterdir()):
        raise QueueError("Use a fresh, empty directory for the demonstration")
    projects = []
    for name in ("demo-store", "demo-site"):
        source = root / name
        source.mkdir()
        (source / "fixture.js").write_text(f'module.exports = () => "{name}";\n')
        subprocess.run(["git", "-c", "init.templateDir=", "init", "-q", "-b", "main", source],
                       check=True)
        subprocess.run(["git", "add", "fixture.js"], cwd=source, check=True)
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false",
                        "-c", "user.name=Factory Demo", "-c", "user.email=demo@example.invalid",
                        "commit", "-qm", "Create synthetic demo fixture"], cwd=source, check=True)
        projects.append({
            "id": name, "base": "main", "repository": name,
            "site_type": "woocommerce" if name == "demo-store" else "wordpress",
            "domain": f"{name}.test", "environments": ["test"],
            "permissions": ["report", "code"],
            "agents": ["project-manager", "architect", "wordpress", "qa"],
            "executor": "mock", "budget": {}, "editable": ["fixture.js"],
            "mock": {"files": {"fixture.js": f'module.exports = () => "Updated {name}";\n'}},
        })
    config.write_text(json.dumps({"version": 1, "projects": projects}, indent=2))
    password = secrets.token_urlsafe(24)
    salt = secrets.token_bytes(16)
    accounts.write_text(json.dumps({
        "owner": {"owner": True, "salt": salt.hex(), "hash": password_hash(password, salt)},
    }, indent=2))
    print(f"Demo login: owner\nDemo password: {password}\nFiles: {root}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        prepare(private_state(args.directory))
    except (QueueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"Demo: {error}\n")


if __name__ == "__main__":
    main()
