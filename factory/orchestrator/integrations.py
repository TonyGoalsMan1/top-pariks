"""Trusted Git, GitHub and Factory operations. Executors cannot invoke these tools."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from .executors import Critical, Retryable
from .queue import QueueError


FACTORY = Path(__file__).resolve().parents[1] / "factory.py"
MAX_FILE = 64 * 1024
MAX_CONTEXT = 192 * 1024
ASSIGNEE = re.compile(r"[a-f0-9]{32}")
BASE_ENV = ("PATH", "HOME", "LANG", "SSL_CERT_FILE", "SSL_CERT_DIR",
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")
GIT_AUTHOR = {
    "GIT_AUTHOR_NAME": "Factory Orchestrator", "GIT_AUTHOR_EMAIL": "factory@example.invalid",
    "GIT_COMMITTER_NAME": "Factory Orchestrator", "GIT_COMMITTER_EMAIL": "factory@example.invalid",
}


class Integrations:
    def __init__(self, project, state, job, lease):
        self.project = project
        self.state = state
        self.job = job
        self.lease = lease
        if not ASSIGNEE.fullmatch(job["id"]):
            raise Critical("Invalid internal task ID")
        self.branch = f"factory/test-{job['id']}"
        self.directory = state / self.job["id"]
        self.checkout = self.directory / "checkout"

    def command(self, args, *, cwd=None, environment=None, fail=None, label="Tool command"):
        env = {name: os.environ[name] for name in BASE_ENV if name in os.environ}
        env.update(environment or {})
        try:
            process = subprocess.run(
                ["timeout", "--signal=TERM", "--kill-after=3", str(self.project.timeout), *map(str, args)],
                cwd=cwd, env=env, pass_fds=(self.lease,), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
            )
        except OSError:
            raise Critical(f"{label} could not start") from None
        if process.returncode and fail is not None:
            raise fail(f"{label} failed (exit {process.returncode})")
        return process

    def github_env(self):
        token = os.environ.get("FACTORY_GITHUB_TOKEN")
        if not token:
            raise Critical("GitHub requires a dedicated test-repository credential")
        return {"GH_TOKEN": token, "GH_PROMPT_DISABLED": "1", "GH_HOST": "github.com",
                "GH_CONFIG_DIR": str(self.state / "gh-config")}

    def git(self, *args, cwd=None, fail=QueueError, label="Git command", auth=False):
        environment = {
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0", "GIT_ATTR_NOSYSTEM": "1", **GIT_AUTHOR,
        }
        options = ["-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never"]
        if auth:
            environment.update(self.github_env())
            options += ["-c", "credential.helper=!gh auth git-credential"]
        return self.command(["git", *options, *args], cwd=cwd or self.checkout, fail=fail,
                            environment=environment, label=label)

    def ensure_checkout(self, result):
        self.directory.mkdir(exist_ok=True)
        if not self.checkout.exists():
            staging = self.directory / "clone-in-progress"
            if staging.exists():
                shutil.rmtree(staging)
            self.git("clone", "--no-local", "--single-branch", "--branch", self.project.base,
                     "--", self.project.repo, staging, cwd=self.directory,
                     auth=bool(self.project.github), fail=Retryable, label="Repository clone")
            staging.rename(self.checkout)
        base = result.get("base") or self.git("rev-parse", f"refs/remotes/origin/{self.project.base}").stdout.strip()
        self.git("checkout", "-B", self.branch, result.get("head") or base)
        self.git("reset", "--hard", result.get("head") or base)
        return base

    def file(self, name):
        entry = self.git("ls-files", "--stage", "--", name).stdout
        path = self.checkout / name
        if (not entry.startswith("100644 ") or path.resolve() != path or not path.is_file()
                or path.stat().st_size > MAX_FILE):
            raise Critical("Input or output path must be a tracked, regular text file within the size limit")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeError:
            raise Critical("Selected files must contain UTF-8 text") from None

    def payload(self):
        return {
            "site_type": self.project.site_type, "objective": self.job["spec"]["objective"],
            "editable_paths": sorted(self.project.editable),
            "files": {name: self.file(name) for name in sorted(self.project.context | self.project.editable)},
        }

    def apply(self, proposal, base):
        updated = set()
        for item in proposal:
            name, content = item["path"], item["content"]
            if (name not in self.project.editable or name in updated or not isinstance(content, str)
                    or len(content.encode()) > MAX_FILE or "\0" in content):
                raise Critical("Executor proposed an unauthorized or invalid file change")
            self.file(name)
            (self.checkout / name).write_text(content, encoding="utf-8")
            updated.add(name)
        if not updated:
            raise QueueError("Executor proposed no file changes")
        if self.git("diff", "--check", "--no-ext-diff", "--no-textconv", base, fail=None).returncode:
            raise Retryable("Whitespace check failed (git diff --check)")
        self.git("add", "--", *sorted(updated))
        if self.git("diff", "--cached", "--quiet", "--", fail=None).returncode == 0:
            raise QueueError("Proposal did not change the working tree")
        patch = self.diff(base)
        self.git("commit", "-m", f"Factory task {self.job['id']}")
        return patch, self.git("rev-parse", "HEAD").stdout.strip()

    def diff(self, base, head=None):
        patch = self.git("diff", "--no-ext-diff", "--no-textconv", base, *([head] if head else []),
                         "--").stdout
        if len(patch.encode()) > MAX_CONTEXT:
            raise QueueError("Diff exceeds the review size limit")
        return patch

    def gh(self, *args, fail=Retryable, label="GitHub command"):
        return self.command(["gh", *args], cwd=self.checkout, environment=self.github_env(),
                            fail=fail, label=label).stdout

    def pr(self):
        output = self.gh("pr", "list", "--repo", self.project.slug, "--head", self.branch,
                         "--state", "all", "--limit", "2",
                         "--json", "number,state,headRefOid,baseRefName,mergeStateStatus,author")
        prs = json.loads(output)
        if len(prs) > 1:
            raise Critical("Multiple pull requests refer to the task branch")
        if prs and prs[0]["baseRefName"] != self.project.base:
            raise Critical("Pull request base unexpectedly changed")
        return prs[0] if prs else None

    def publish(self, result):
        self.git("push", "origin", f"{result['head']}:refs/heads/{self.branch}",
                 fail=Retryable, auth=True, label="Push task branch")
        pr = self.pr()
        if not pr:
            self.gh("pr", "create", "--repo", self.project.slug, "--head", self.branch,
                    "--base", self.project.base, "--title", f"Factory task {self.job['id']}",
                    "--body", "Generated in an isolated Factory test project. Review changes and CI before merging.")
            pr = self.pr()
        if not pr or pr["headRefOid"] != result["head"]:
            raise Retryable("GitHub has not reported the published head")
        return pr["number"]

    def checks(self, head):
        output = json.loads(self.gh("api", f"repos/{self.project.slug}/commits/{head}/check-runs?per_page=100"))
        if output["total_count"] > 100:
            raise Critical("Too many GitHub checks to validate unambiguously")
        checks = {}
        for item in output["check_runs"]:
            if item["name"] in self.project.github["required_checks"]:
                # GitHub may retain checks from multiple applications. Ambiguous names fail closed.
                if item["name"] in checks:
                    raise Critical("Ambiguous GitHub check name")
                checks[item["name"]] = item["conclusion"] if item["status"] == "completed" else None
        pending = any(checks.get(name) is None for name in self.project.github["required_checks"])
        failed = {name: status for name, status in checks.items() if status and status != "success"}
        return pending, failed

    def pull_status(self, result):
        pr = self.pr()
        if not pr or pr["number"] != result["pr"]:
            raise Critical("GitHub pull request disappeared")
        if pr["headRefOid"] != result["head"]:
            raise Critical("GitHub pull request head changed outside the orchestrator")
        if pr["state"] == "CLOSED":
            raise QueueError("GitHub pull request was closed")
        return pr

    def merge(self, pr, result):
        project = self.project
        branch = json.loads(self.gh("api", f"repos/{project.slug}/branches/{project.base}"))
        protection = json.loads(self.gh("api", f"repos/{project.slug}/branches/{project.base}/protection",
                                        fail=Critical, label="Read enforced branch protection"))
        status = protection.get("required_status_checks") or {}
        reviews = protection.get("required_pull_request_reviews") or {}
        configured_checks = set(status.get("contexts", [])) | {check["context"] for check in status.get("checks", [])}
        if (not branch["protected"] or not (protection.get("enforce_admins") or {}).get("enabled")
                or not status.get("strict") or not set(project.github["required_checks"]) <= configured_checks
                or not reviews.get("dismiss_stale_reviews") or not reviews.get("require_last_push_approval")
                or not reviews.get("required_approving_review_count")
                or any((reviews.get("bypass_pull_request_allowances") or {}).values())):
            raise Critical("Auto-merge requires enforced strict checks and protected stale-review rules")
        identity = json.loads(self.gh("api", "user"))["login"].lower()
        reviewer = project.github["reviewer"].lower()
        author = (pr.get("author") or {}).get("login", "").lower()
        if reviewer in {identity, author} or not author:
            raise Critical("GitHub reviewer must differ from the task author and merge identity")
        endpoint = f"repos/{project.slug}/pulls/{pr['number']}"
        records = json.loads(self.gh("api", f"{endpoint}/reviews?per_page=100"))
        if len(records) == 100:
            raise Critical("Too many GitHub reviews to validate unambiguously")
        decisions = [review for review in records
                     if (review.get("user") or {}).get("login", "").lower() == reviewer
                     and review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}]
        if not decisions or decisions[-1]["state"] != "APPROVED" or decisions[-1]["commit_id"] != result["head"]:
            return False
        pending, failed = self.checks(result["head"])
        if pending or failed or self.pull_status(result)["mergeStateStatus"] != "CLEAN":
            return False
        merged = json.loads(self.gh("api", "--method", "PUT", f"{endpoint}/merge",
                                    "-f", f"sha={result['head']}", "-f", "merge_method=squash"))
        if not merged.get("merged"):
            raise Retryable("GitHub declined the protected merge")
        return True

    def factory(self):
        spec = self.job["spec"]
        operation = spec["operation"]
        args = ["python3", "-B", FACTORY, "--site", self.project.profile,
                "--state", self.state / "wordpress", "--repository", self.project.factory_source]
        self.directory.mkdir(exist_ok=True)
        if spec["ref"]:
            release = self.directory / f"release-{self.job['attempt']}"
            self.git("merge-base", "--is-ancestor", spec["ref"], f"refs/heads/{self.project.base}",
                     cwd=self.project.factory_source, fail=Critical, label="Require trusted Factory source commit")
            self.command([*args, "build", release, "--ref", spec["ref"]], fail=QueueError,
                         label="Factory build")
            self.command([*args, "verify-release", release], fail=Critical, label="Verify Factory release")
            if operation == "build":
                return {"release": str(release), "commit": spec["ref"]}
            tail = [release]
        else:
            tail = [spec["backup"]] if spec["backup"] else []
        protected = Critical if spec["critical"] else QueueError
        output = self.command([*args, operation, *tail], fail=protected, label=f"Factory {operation}").stdout
        backup = re.search(r"(?m)^Backup verified: ([a-z0-9T-]+)$", output)
        if operation == "backup":
            if backup is None:
                raise Critical("Factory backup did not report a verified identifier")
            return {"backup": backup[1]}
        return {"operation": operation, "verified": True}

    def deadline(self):
        return time.time() + self.project.ci_timeout
