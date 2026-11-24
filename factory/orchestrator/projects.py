"""Load the operator-controlled registry and validate submitted operations."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re

from .queue import CRITICAL, QueueError, encode


ROLES = json.loads(Path(__file__).with_name("roles.json").read_text())
FACTORY = {"build", "health", *CRITICAL}
OPERATIONS = {"code", "report", *FACTORY}
IDENTIFIER = r"[a-z0-9][a-z0-9-]{0,39}"
SHA = r"[0-9a-f]{40}"
BACKUP_ID = r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}"
BRANCH = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
GITHUB = r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+"
PATH = r"[A-Za-z0-9_/-][A-Za-z0-9_./-]{0,199}"
FILE_TYPES = {".php", ".css", ".js", ".html", ".md", ".txt", ".svg"}


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise QueueError(f"Expected integer in range {low}–{high}")
    return value


def source_path(value):
    path = PurePosixPath(value)
    if (not re.fullmatch(PATH, value) or str(path) != value or path.is_absolute()
            or any(part.startswith(".") for part in path.parts)
            or path.suffix not in FILE_TYPES):
        raise QueueError("Source files must be explicit relative paths of supported file types")
    return value


class Project:
    def __init__(self, config, directory):
        self.id = config["id"]
        self.base = config["base"]
        self.site_type = config["site_type"]
        self.domain = config["domain"]
        self.environments = config["environments"]
        self.permissions = set(config["permissions"])
        self.roles = set(config["agents"])
        self.queue = config.get("queue", [])
        self.executor = config["executor"]
        self.github = config.get("github", {})
        self.preview_base = config.get("preview_base")
        self.budget = config["budget"]
        self.timeout = integer(config.get("timeout_seconds", 120), 1, 900)
        self.max_attempts = integer(config.get("max_attempts", 3), 1, 5)
        self.backoff = integer(config.get("retry_seconds", 10), 0, 300)
        self.editable = {source_path(path) for path in config.get("editable", [])}
        self.context = {source_path(path) for path in config.get("context", [])}
        if len(self.editable | self.context) > 32:
            raise QueueError("Select at most 32 source files")
        self.mock = config.get("mock", {})
        if (not re.fullmatch(IDENTIFIER, self.id) or not re.fullmatch(BRANCH, self.base)
                or self.base.lower() == "production" or self.environments != ["test"]
                or not re.fullmatch(r"[a-z0-9.-]+\.test|localhost", self.domain)
                or self.site_type not in {"wordpress", "woocommerce"}
                or self.executor not in {"mock", "responses", "codex"}
                or not self.permissions <= OPERATIONS or not self.roles <= ROLES.keys()):
            raise QueueError("Invalid project identity, test environment, permissions or executor")
        if self.executor == "mock" and self.github:
            raise QueueError("Mock execution can only use local Git repositories")
        repo = config["repository"]
        if self.github:
            if not re.fullmatch(GITHUB, repo):
                raise QueueError("GitHub repository must use owner/name syntax")
            self.repo = f"https://github.com/{repo}.git"
            self.slug = repo
            required = self.github.get("required_checks", [])
            if (not required or len(required) != len(set(required))
                    or not all(re.fullmatch(r"[A-Za-z0-9_ ./()&,:-]{1,100}", name) for name in required)
                    or self.github.get("trusted_test_ci") is not True
                    or type(self.github.get("auto_merge", False)) is not bool):
                raise QueueError("GitHub requires named checks and explicit isolated test CI authorization")
            if self.github.get("auto_merge"):
                reviewer = self.github.get("reviewer", "")
                if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", reviewer):
                    raise QueueError("Automatic merge requires an independent GitHub reviewer")
            self.ci_timeout = integer(self.github.get("timeout_seconds", 1800), 30, 86400)
        else:
            self.repo = str((directory / repo).resolve(strict=True))
            self.slug = None
        self.reviewer = config.get("review_role", "qa")
        if ("code" in self.permissions and
                (self.reviewer not in {"qa", "security"} or self.reviewer not in self.roles)):
            raise QueueError("Code changes require a separate QA or security role")
        self.profile = None
        self.profile_digest = None
        self.factory_source = None
        if self.permissions & FACTORY:
            self.profile = (directory / config["wordpress_profile"]).resolve(strict=True)
            self.factory_source = (directory / config["factory_source"]).resolve(strict=True)
            raw_profile = self.profile.read_bytes()
            profile = json.loads(raw_profile)
            self.profile_digest = hashlib.sha256(raw_profile).hexdigest()
            if ("woocommerce" in profile) != (self.site_type == "woocommerce"):
                raise QueueError("Project site type must match the Factory profile")
            self.site_id = profile["site_id"]
            self.port = integer(profile["port"], 1024, 65535)
            if not re.fullmatch(IDENTIFIER, self.site_id):
                raise QueueError("Invalid Factory site ID")
            config = dict(config, profile_sha256=self.profile_digest,
                          resolved_factory_source=str(self.factory_source))
        if self.preview_base is not None:
            css = profile["theme"]["source"] + "/style.css" if self.profile else None
            if (not re.fullmatch(SHA, self.preview_base) or not self.github
                    or self.github.get("auto_merge") or self.slug.lower() == "tonygoalsman1/top-pariks"
                    or not self.profile or not {"code", "start", "health"} <= self.permissions
                    or self.editable != {css}):
                raise QueueError("Local preview requires a pinned test repository and CSS-only edits")
        if self.executor == "codex":
            integer(self.budget["max_calls"], 1, 20)
        if self.executor == "responses":
            integer(self.budget["total_microdollars"], 1, 1_000_000_000)
            integer(self.budget["max_input_tokens"], 1, 100_000)
            integer(self.budget["max_output_tokens"], 16, 32_000)
            for key in ("input_microdollars_per_million", "output_microdollars_per_million"):
                integer(self.budget[key], 1, 1_000_000_000)
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,79}", self.budget["model"]):
                raise QueueError("Set the pricing and supported model explicitly")
        self.fingerprint = hashlib.sha256(encode([config, self.repo, ROLES]).encode()).hexdigest()

    def resource(self, spec):
        if self.preview_base or spec["operation"] in FACTORY - {"build"}:
            return f"site:{self.site_id}"
        return f"repository:{self.repo.lower() if self.github else self.repo}"

    def task(self, operation, objective, role=None, ref=None, backup=None):
        if operation not in self.permissions:
            raise QueueError("Operation is not permitted for this project")
        if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 8000:
            raise QueueError("Objective must contain 1–8000 characters")
        if operation in {"code", "report"}:
            mode = "edit" if operation == "code" else "read"
            if role not in self.roles or ROLES[role]["permission"] != mode:
                raise QueueError("Role is not permitted for this operation")
        elif role is not None:
            raise QueueError("Factory actions do not use AI roles")
        if operation in {"build", "start", "deploy"}:
            if not re.fullmatch(SHA, ref or ""):
                raise QueueError("Factory builds require an explicit trusted Git commit SHA")
        elif ref is not None:
            raise QueueError("This operation takes no source commit")
        if operation == "restore":
            if not re.fullmatch(BACKUP_ID, backup or ""):
                raise QueueError("Restore requires a Factory backup ID")
        elif backup is not None:
            raise QueueError("This operation takes no backup ID")
        return {"operation": operation, "objective": objective, "critical": operation in CRITICAL,
                "role": role, "ref": ref, "backup": backup}

    def business(self, objective, role):
        specs = [self.task("report", objective, agent) for agent in ("project-manager", "architect")
                 if agent in self.roles and "report" in self.permissions]
        return [*specs, self.task("code", objective, role)]


def load(path):
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o022:
        raise QueueError("Registry must be operator-owned and protected from other writers")
    config = json.loads(path.read_text())
    if config["version"] != 1:
        raise QueueError("Unsupported registry version")
    projects = {}
    site_ids, ports = set(), set()
    for item in config["projects"]:
        project = Project(item, path.parent)
        if project.id in projects:
            raise QueueError("Duplicate project ID")
        if project.profile:
            if project.site_id in site_ids or project.port in ports:
                raise QueueError("Factory site IDs and loopback ports must be unique")
            site_ids.add(project.site_id)
            ports.add(project.port)
        projects[project.id] = project
    return projects
