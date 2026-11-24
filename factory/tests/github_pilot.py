"""Exercise the real GitHub adapter against a dedicated, owner-authorized fixture repo."""

import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from factory.orchestrator.executors import Critical, Retryable
from factory.orchestrator.integrations import Integrations
from factory.orchestrator.projects import load
from factory.orchestrator.queue import QueueError


def run(project, state):
    job = {"id": uuid.uuid4().hex}
    tool = Integrations(project, state, job, None)
    base = tool.ensure_checkout({})
    _, head = tool.apply([{"path": "README.md",
                           "content": tool.file("README.md").rstrip() + f"\n\nPilot {job['id']}\n"}], base)
    result = {"base": base, "head": head}
    print(json.dumps({"repository": project.slug, "branch": tool.branch, "head": head}), flush=True)
    result["pr"] = tool.publish(result)
    if tool.publish(result) != result["pr"]:
        raise QueueError("Repeated publication did not reuse the pull request")
    print(json.dumps({"pr": result["pr"]}), flush=True)

    deadline = tool.deadline()
    while time.time() < deadline:
        if tool.pull_status(result)["state"] != "OPEN":
            raise QueueError("The fixture pull request must remain open")
        checks = tool.check_states(head)
        failures = {name: status for name, status in checks.items() if status not in {None, "success"}}
        if failures:
            raise QueueError(f"Fixture CI failed: {json.dumps(failures)}")
        if None not in checks.values():
            print(json.dumps({"checks": checks, "head": head}), flush=True)
            return
        time.sleep(5)
    raise QueueError("GitHub CI did not report all checks against the published SHA")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--confirm-repository", required=True, help="Exact owner/name of the disposable fixture")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        projects = load(args.config.resolve())
        project = projects.get(args.project)
        if (project is None or not project.github or project.slug != args.confirm_repository
                or project.slug.lower() == "tonygoalsman1/top-pariks"
                or project.github.get("auto_merge") or "README.md" not in project.editable):
            raise QueueError("Use a confirmed, separate test repository with editable README.md and no auto-merge")
        with tempfile.TemporaryDirectory(prefix="factory-github-pilot-") as directory:
            run(project, Path(directory))
    except (QueueError, Retryable, Critical) as error:
        parser.exit(2, f"GitHub pilot: {error}\n")
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"GitHub pilot: {type(error).__name__}\n")


if __name__ == "__main__":
    main()
