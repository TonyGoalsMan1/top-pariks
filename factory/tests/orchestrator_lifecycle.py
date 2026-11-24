#!/usr/bin/env python3
"""Exercise the orchestrator with real Git and optionally two Docker WordPress sites."""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from lifecycle import Lifecycle, REPO, Site, allocate_ports, require, run


class Scenario:
    def __init__(self, temp, wordpress):
        self.temp = temp
        self.wordpress = wordpress
        self.lifecycle = Lifecycle(temp)
        self.state = temp / "orchestrator"
        self.lifecycle.state = self.state / "wordpress"
        self.config = temp / "projects.json"
        self.projects = []
        self.refs = {}
        self.sites = {}
        self.cli = [sys.executable, "-B", "-m", "factory.orchestrator", "--config", self.config,
                    "--state", self.state]

    def register(self):
        for project, port in zip(("alpha", "beta"), allocate_ports()):
            repo = self.temp / project
            repo.mkdir()
            run("git", "init", "-q", "-b", "main", cwd=repo)
            run("git", "config", "user.name", "Fixture", cwd=repo)
            run("git", "config", "user.email", "fixture@example.invalid", cwd=repo)
            (repo / "note.txt").write_text(f"Initial {project}\n")
            if self.wordpress:
                profile = json.loads((REPO / "factory/sites/example-store.json").read_text())
                profile.update(site_id=f"{project}-{uuid.uuid4().hex[:8]}", port=port,
                               title=f"Fixture {project}")
                path = self.temp / f"{project}.json"
                path.write_text(json.dumps(profile))
                site = Site(path, self.lifecycle.state)
                self.sites[project] = site
                self.lifecycle.sites[site.id] = (path, site)
                seed = repo / profile["seed"]
                seed.parent.mkdir(parents=True)
                shutil.copyfile(REPO / profile["seed"], seed)
                theme = repo / profile["theme"]["source"]
                theme.parent.mkdir(parents=True)
                shutil.copytree(REPO / profile["theme"]["source"], theme)
            run("git", "add", ".", cwd=repo)
            run("git", "commit", "-qm", "Initial synthetic fixture", cwd=repo)
            self.refs[project] = run("git", "rev-parse", "HEAD", cwd=repo)
            operations = ["code", "report"]
            if self.wordpress:
                operations += ["build", "start", "health", "backup", "restore", "rollback"]
                if project == "alpha":
                    operations += ["deploy"]
            self.projects.append({
                "id": project, "repository": project, "base": "main", "site_type": "woocommerce",
                "domain": f"{project}.test", "environments": ["test"], "permissions": operations,
                "agents": ["project-manager", "architect", "wordpress", "qa", "security"],
                "executor": "mock", "budget": {}, "editable": ["note.txt"],
                "mock": {"files": {"note.txt": f"Updated {project}\n"}, "fail_first": True},
                "wordpress_profile": f"{project}.json", "factory_source": project,
                "timeout_seconds": 300, "retry_seconds": 0,
            })
        self.config.write_text(json.dumps({"version": 1, "projects": self.projects}))

    def call(self, *args, reject=None, **kwargs):
        result = subprocess.run([*self.cli, *args], cwd=REPO, capture_output=True, text=True, **kwargs)
        if reject:
            require(result.returncode == 2 and reject in result.stderr, f"Expected rejection: {reject}")
        else:
            require(result.returncode == 0, result.stderr)
            return json.loads(result.stdout) if result.stdout else None

    def submit(self, project, operation, *args):
        return self.call("submit", project, operation, "Synthetic integration fixture", *args)["tasks"][0]

    def check(self, task, status):
        row = self.call("get", task)
        require(row["status"] == status, f"Expected {status}: {row}")
        return row

    def run(self):
        self.call("run", "--once", "--workers", "2")

    def crash_dispatcher(self, task):
        # Delay the first real subprocess to make an actual SIGKILL after claim reproducible.
        wrapper = self.temp / "controlled-bin"
        wrapper.mkdir()
        marker = self.temp / "subprocess-started"
        timeout = wrapper / "timeout"
        timeout.write_text(f'#!/bin/sh\ntouch "{marker}"\nexec sleep 30\n')
        timeout.chmod(0o700)
        env = dict(os.environ, PATH=f"{wrapper}:{os.environ['PATH']}")
        with subprocess.Popen([*self.cli, "run", "--once"], cwd=REPO, env=env,
                              start_new_session=True) as process:
            try:
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline and process.poll() is None:
                    time.sleep(0.02)
                require(marker.exists(), "Dispatcher did not start the claimed command")
                self.check(task, "running")
                self.call("run", "--once", reject="Another dispatcher")
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
        self.check(task, "running")

    def git_jobs(self):
        self.call("pause")
        objectives = {}
        for project in ("alpha", "beta"):
            objectives[project] = self.call("business", project, "Update fixture", "--role", "wordpress",
                                            "--priority", "20" if project == "alpha" else "10")["tasks"]
        self.run()
        self.check(objectives["alpha"][0], "queued")
        self.call("resume")
        self.crash_dispatcher(objectives["alpha"][0])
        self.run()
        for project, tasks in objectives.items():
            plan, architecture, code = tasks
            self.check(plan, "done")
            self.check(architecture, "done")
            result = self.check(code, "done")["result"]
            checkout = Path(result["checkout"])
            require((checkout / "note.txt").read_text() == f"Updated {project}\n", "Wrong project content")
            require(run("git", "rev-parse", "HEAD", cwd=checkout) == result["head"], "Missing real commit")
            require(run("git", "rev-parse", "HEAD", cwd=self.temp / project) == self.refs[project],
                    "Orchestrator modified the source repository")
            require(run("git", "branch", "--show-current", cwd=checkout) == result["branch"],
                    "Expected a task-specific branch")
            events = self.call("events", code)
            require(any("Whitespace check failed" in e["detail"].get("failure", "") for e in events),
                    "Real git diff check did not reject the first proposal")
            require(self.check(code, "done")["attempt"] == 2, "Expected a bounded real retry")
        require(any(e["event"] == "interrupted" for e in self.call("events", objectives["alpha"][0])),
                "Dispatcher restart did not recover the interrupted task")
        self.call("submit", "beta", "deploy", "Unauthorized operation", "--ref", self.refs["beta"],
                  reject="Operation is not permitted")
        self.call("submit", "alpha", "code", "Unauthorized role", "--role", "qa",
                  reject="Role is not permitted")
        return {project: tasks[-1] for project, tasks in objectives.items()}

    def wordpress_jobs(self, code_tasks):
        jobs = {}
        for project in code_tasks:
            build = self.submit(project, "build", "--ref", self.refs[project], "--after", code_tasks[project])
            start = self.submit(project, "start", "--ref", self.refs[project], "--after", build)
            health = self.submit(project, "health", "--after", start)
            backup = self.submit(project, "backup", "--after", health)
            jobs[project] = (build, start, health, backup)
            self.call("approve", start, "deploy", reject="Approval does not match")
        self.run()
        for build, start, _, _ in jobs.values():
            self.check(build, "done")
            self.check(start, "queued")
            self.call("approve", start, "start")
        self.run()
        for project, (_, start, health, backup) in jobs.items():
            self.check(start, "done")
            self.check(health, "done")
            self.check(backup, "queued")
            self.call("approve", backup, "backup")
            require(self.sites[project].wp("option", "get", "blogname", capture=True) == f"Fixture {project}",
                    "Sites do not have isolated WordPress settings")
        self.run()
        site = self.sites["alpha"]
        backup_id = self.check(jobs["alpha"][-1], "done")["result"]["backup"]
        self.check(jobs["beta"][-1], "done")
        site.wp("option", "update", "blogname", "Changed after snapshot")
        restore = self.submit("alpha", "restore", "--backup", backup_id)
        self.call("approve", restore, "restore")
        self.run()
        self.check(restore, "done")
        require(site.wp("option", "get", "blogname", capture=True) == "Fixture alpha", "Restore failed")

        repo = self.temp / "alpha"
        theme = repo / site.config["theme"]["source"]
        (theme / "orchestrator-release.txt").write_text("known good release\n")
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "Safe deployment fixture", cwd=repo)
        good = self.submit("alpha", "deploy", "--ref", run("git", "rev-parse", "HEAD", cwd=repo))
        self.call("approve", good, "deploy")
        self.run()
        self.check(good, "done")

        (theme / "front-page.php").write_text("<?php get_header(); ?>Intentional health failure<?php get_footer(); ?>")
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "Broken deployment fixture", cwd=repo)
        bad = self.submit("alpha", "deploy", "--ref", run("git", "rev-parse", "HEAD", cwd=repo))
        self.call("approve", bad, "deploy")
        after = self.submit("alpha", "health", "--after", bad)
        self.run()
        self.check(bad, "blocked")
        require(self.call("status")["paused"], "Critical failure did not stop the dispatcher")
        require(not site.pending.exists(), "Factory failed to recover the broken deployment")
        self.call("resume")
        self.run()
        self.check(after, "blocked")
        for project in self.sites:
            smoke = self.submit(project, "health")
            self.run()
            self.check(smoke, "done")
        print("Real Docker WordPress/WooCommerce operations passed on two isolated sites.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wordpress", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="factory-orchestrator-") as folder:
        scenario = Scenario(Path(folder), args.wordpress)
        failed = True
        try:
            scenario.register()
            code = scenario.git_jobs()
            print("Local Git, durable queue and restart integration passed. AI executor: mock.", flush=True)
            if args.wordpress:
                scenario.wordpress_jobs(code)
            failed = False
        finally:
            scenario.lifecycle.cleanup(failed)
