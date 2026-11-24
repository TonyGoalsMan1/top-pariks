#!/usr/bin/env python3
"""Exercise the console through HTTP, a live dispatcher and optional browser/WordPress."""

import argparse
from contextlib import contextmanager
from hashlib import scrypt
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from orchestrator_lifecycle import REPO, Scenario, allocate_ports, require, run



PASSWORD = "synthetic-integration-test"
SECRET = "synthetic-worker-secret-no-network"
OBJECTIVE = "Уточнить подписи в тестовом каталоге <img src=x onerror=alert(1)>"


class Client:
    def __init__(self, origin, actor=None):
        self.origin = origin
        self.cookie = ""
        if actor:
            self.call("session", {"username": actor, "password": PASSWORD})

    def call(self, path, data=None, status=200, *, origin=None):
        payload = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(self.origin + "/api/v1/" + path, data=payload, headers={
            "Content-Type": "application/json", "Origin": self.origin if origin is None else origin,
            "Cookie": self.cookie,
        })
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            content = response.read().decode()
            require(response.code == status, f"{path}: expected HTTP {status}, got {response.code}: {content}")
            require(response.headers["Cache-Control"] == "no-store", "API can be cached")
            require(SECRET not in content and PASSWORD not in content, "API exposed a secret")
            header = response.headers.get("Set-Cookie")
            if header:
                require("HttpOnly" in header and "SameSite=Strict" in header, "Weak session cookie")
                self.cookie = header.split(";", 1)[0]
            return json.loads(content)


@contextmanager
def background(command, environment):
    with subprocess.Popen(command, cwd=REPO, env=environment, start_new_session=True) as process:
        try:
            yield process
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def until(probe, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        time.sleep(.15)
    raise AssertionError("State did not converge before deadline")


def wait_for(client, project, task, status, timeout=25):
    def check():
        row = client.call(f"projects/{project}/tasks/{task}")
        if row["status"] in {"failed", "blocked", "cancelled", "done"}:
            require(row["status"] == status, f"Unexpected terminal state: {row}")
        return row if row["status"] == status else None
    return until(check, timeout)


def api_checks(scenario, origin, wordpress):
    anon = Client(origin)
    anon.call("projects", status=401)
    anon.call("session", {"username": "owner", "password": "wrong"}, 401)
    owner, operator, viewer = (Client(origin, role) for role in ("owner", "operator", "viewer"))
    owner.call("projects/alpha/register", {}, 403, origin="https://untrusted.test")
    require(owner.call("projects")["available"] == ["alpha", "beta"], "Missing trusted profiles")
    operator.call("projects/beta/register", {}, 404)
    for project in ("alpha", "beta"):
        owner.call(f"projects/{project}/register", {})
    until(lambda: owner.call("projects/alpha")["dispatcher_online"])
    require([p["id"] for p in operator.call("projects")["projects"]] == ["alpha"], "Project leak")
    viewer.call("projects/alpha", status=404)
    viewer.call("projects/beta/pause", {}, 403)
    operator.call("projects/alpha/audit", status=404)
    operator.call("projects/alpha/pause", {})
    alpha = operator.call("projects/alpha/business", {"objective": OBJECTIVE, "role": "wordpress"}, 201)["tasks"]
    beta = owner.call("projects/beta/business", {"objective": "Независимая задача beta", "role": "wordpress"},
                      201)["tasks"]
    operator.call(f"projects/alpha/tasks/{beta[0]}", status=404)
    operator.call(f"projects/alpha/tasks/{beta[0]}/cancel", {}, 404)
    operator.call("projects/alpha/business", {"objective": "Foreign dependency", "role": "wordpress",
                                               "after": [beta[0]]}, 404)
    wait_for(owner, "beta", beta[-1], "done")
    require(owner.call(f"projects/alpha/tasks/{alpha[0]}")["status"] == "queued", "Project pause not honoured")

    owner.call(f"projects/alpha/tasks/{alpha[0]}/hold", {})
    owner.call("projects/alpha/resume", {})
    require(owner.call(f"projects/alpha/tasks/{alpha[0]}")["held"], "Task hold not persisted")
    owner.call(f"projects/alpha/tasks/{alpha[0]}/release", {})
    last = wait_for(owner, "alpha", alpha[-1], "done")
    require(last["dependencies"] == [alpha[-2]], "Chain of dependencies missing")
    require(last["result"]["checks"] == {"git diff --check": "success"}, "Missing real local check")
    require("checkout" not in last["result"] and str(scenario.temp) not in json.dumps(last), "Private path leaked")
    require(last["attempt"] == 2, "Mock did not exercise real validation failure/retry")
    require(any("Whitespace check failed" in e["detail"].get("failure", "")
                for e in last["events"]), "Missing failure event")
    require(run("node", "-p", 'require("./fixture.js")()', cwd=scenario.state / alpha[-1] / "checkout")
            == "Updated alpha", "Job submitted over HTTP did not produce the expected Git change")
    owner.call("projects/alpha/pause", {})
    task = owner.call("projects/alpha/business", {"objective": "Отменяемая задача", "role": "wordpress"},
                      201)["tasks"][0]
    owner.call(f"projects/alpha/tasks/{task}/cancel", {})
    wait_for(owner, "alpha", task, "cancelled")
    retried = owner.call(f"projects/alpha/tasks/{task}/retry", {}, 201)["task"]
    require(task != retried, "Retry must preserve the original task")
    owner.call("projects/alpha/resume", {})
    wait_for(owner, "alpha", retried, "done")

    if wordpress:
        factory_checks(scenario, owner, operator)
    require(any(item["event"] == "done" for item in owner.call("projects/alpha")["notifications"]),
            "Missing completion notice")
    require(any(item["action"] == "register" for item in owner.call("projects/alpha/audit")["records"]),
            "Missing registration audit")
    owner.call("logout", {})
    owner.call("projects", status=401)


def factory_checks(scenario, owner, operator):
    def submit(project, operation, **args):
        return owner.call(f"projects/{project}/operations", {
            "operation": operation, "objective": f"Factory test {operation}", **args,
        }, 201)["tasks"][0]

    def approve(project, task, operation, *, reject=False):
        path = f"projects/{project}/tasks/{task}"
        entry = owner.call(path)
        require(entry["status"] == "queued" and entry["approval"], "Critical task ran without approval")
        require(any(n["job"] == task and n["event"] == "approval_required"
                    for n in owner.call(f"projects/{project}")["notifications"]), "Missing approval notice")
        payload = {"operation": operation, "version": entry["approval"]}
        if reject:
            owner.call(path + "/approve", dict(payload, version="0" * 64), 409)
            owner.call(path + "/approve", dict(payload, operation="deploy"), 409)
            operator.call(path + "/approve", payload, 403)
            owner.call(f"projects/beta/tasks/{task}/approve", payload, 404)
        owner.call(path + "/approve", payload)
        owner.call(path + "/approve", payload, 409)
        return wait_for(owner, project, task, "done", timeout=310)

    for project in ("alpha", "beta"):
        task = submit(project, "start", ref=scenario.refs[project])
        approve(project, task, "start", reject=project == "alpha")
    health = submit("alpha", "health")
    wait_for(owner, "alpha", health, "done", timeout=90)
    task = submit("alpha", "backup")
    backup = approve("alpha", task, "backup")["result"]["backup"]
    require(backup in {item["id"] for item in owner.call("projects/alpha")["site"]["backups"]},
            "Created backup is missing from the panel")
    require(not owner.call("projects/beta")["site"]["backups"], "Foreign backups leaked")
    site = scenario.sites["alpha"]
    site.wp("option", "update", "blogname", "Changed after control center backup")
    task = submit("alpha", "restore", backup=backup)
    approve("alpha", task, "restore")
    require(site.wp("option", "get", "blogname", capture=True) == "Fixture alpha", "Restore did not apply")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wordpress", action="store_true")
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        scenario = Scenario(root, args.wordpress)
        scenario.register()
        os.umask(0o077)
        accounts = root / "accounts.json"
        entries = {
            "owner": {"owner": True}, "operator": {"projects": {"alpha": "operator"}},
            "viewer": {"projects": {"beta": "viewer"}},
        }
        for account in entries.values():
            salt = os.urandom(16)
            account.update(salt=salt.hex(), hash=scrypt(PASSWORD.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024**2).hex())
        accounts.write_text(json.dumps(entries))
        port = allocate_ports()[0]
        origin = f"http://127.0.0.1:{port}"
        # Deliberately provide a dummy secret and strip paid authorization from the worker.
        environment = dict(os.environ, OPENAI_API_KEY=SECRET, FACTORY_AUTHORIZE_PAID_AI="0")
        command = [sys.executable, "-B", "-m", "factory.pilot", "--config", scenario.config,
                   "--state", scenario.state, "--accounts", accounts, "--origin", origin, "--port", str(port)]
        def ready():
            try:
                Client(origin).call("projects", status=401)
                return True
            except urllib.error.URLError:
                return False

        try:
            with background(command, environment):
                until(ready)
                api_checks(scenario, origin, args.wordpress)
                print("Control Center HTTP/queue integration passed. AI executor: mock.", flush=True)
                if args.browser:
                    subprocess.run(["node", "factory/tests/control_browser.cjs", origin, PASSWORD], check=True,
                                   cwd=REPO, env=dict(environment, FACTORY_WORDPRESS_TEST=str(int(args.wordpress))))
        finally:
            if args.wordpress:
                scenario.lifecycle.cleanup(sys.exc_info()[0] is not None)


if __name__ == "__main__":
    main()
