"""Check and launch the existing Factory control center and dispatcher together."""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from .control.__main__ import ASSETS, STATIC, Console, users
from .orchestrator.__main__ import private_state
from .orchestrator.executors import Critical, Retryable, api_key, model_access
from .orchestrator.integrations import Integrations, timeout_command
from .orchestrator.projects import integer, load
from .orchestrator.queue import Queue, QueueError


def check(args):
    integer(args.port, 1024, 65535)
    state = private_state(args.state)
    projects = load(args.config.resolve())
    if not projects:
        raise QueueError("At least one test project is required")
    if any(p.github.get("auto_merge") for p in projects.values()):
        raise QueueError("The pilot requires automatic merge disabled")
    accounts = users(args.accounts.resolve(), projects)
    commands = {"git"}
    for project in projects.values():
        if project.profile:
            commands.add("docker")
        if project.github:
            commands.add("gh")
        if project.executor == "responses":
            commands.add("curl")
        for path in project.editable:
            tool = {".js": "node", ".php": "php"}.get(Path(path).suffix)
            if tool:
                commands.add(tool)
    missing = sorted(name for name in commands if not shutil.which(name))
    if missing:
        raise QueueError("Missing commands: " + ", ".join(missing))
    timeout_command()
    if any(not (STATIC / name).is_file() for name, _ in ASSETS.values()):
        raise QueueError("PWA assets are incomplete")
    factory = Path(__file__).with_name("factory.py")
    if "docker" in commands:
        # Check the effective context before contacting the daemon.
        endpoint = os.environ.get("DOCKER_HOST")
        if os.environ.get("DOCKER_CONTEXT") or not endpoint:
            endpoint = probe(["docker", "context", "inspect", "--format",
                              "{{.Endpoints.docker.Host}}"], "Docker context").strip()
        if not endpoint.startswith("unix:///"):
            raise QueueError("Select a local Docker Unix socket for the pilot")
        probe(["docker", "info", "--format", "{{.ServerVersion}}"], "Docker daemon")
        probe(["docker", "compose", "version"], "Docker Compose")
    for project in projects.values():
        tool = Integrations(project, state, {"id": "0" * 32}, None)
        if project.executor == "responses":
            key = api_key()
        if project.github:
            tool.gh("api", f"repos/{project.slug}", label="Test repository access", cwd=state)
        branch = f"refs/heads/{project.base}"
        tool.git("ls-remote", "--exit-code", "--", project.repo, branch, cwd=state,
                 auth=bool(project.github), label=f"Read test Git branch for {project.id}")
        if project.profile:
            check_site(project, factory, state, args.port)
        if project.executor == "responses":
            model_access(key, project.budget["model"], min(project.timeout, 20))
        print(f"{project.id}: {project.executor}, Git and configured dependencies ready", flush=True)
    with Console(args.port, args.origin, state, projects, accounts):
        pass
    print("Preflight passed: PWA assets, loopback API and SQLite ready", flush=True)
    return state


def probe(command, label):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        raise QueueError(f"{label} timed out") from None
    if result.returncode:
        raise QueueError(f"{label} failed (exit {result.returncode})")
    return result.stdout


def check_site(project, factory, state, panel_port):
    if project.port == panel_port:
        raise QueueError(f"{project.id}: WordPress and the panel need different ports")
    command = [sys.executable, "-B", factory, "--site", project.profile,
               "--state", state / "wordpress", "--repository", project.factory_source]
    result = json.loads(probe([*command, "check", "--branch", project.base],
                              f"Factory profile or recovery state for {project.id}"))
    if result["running"]:
        probe([*command, "health"], f"WordPress health for {project.id}")
        print(f"{project.id}: WordPress healthy at {result['url']}", flush=True)
        return
    with socket.socket() as port:
        try:
            port.bind(("127.0.0.1", project.port))
        except OSError:
            raise QueueError(f"{project.id}: WordPress port {project.port} is in use") from None
    print(f"{project.id}: WordPress stopped, start it with an approved Factory task", flush=True)


def wait_ready(process, ready, label):
    deadline = time.monotonic() + 12
    while process.poll() is None and time.monotonic() < deadline:
        if ready():
            return
        time.sleep(.2)
    raise QueueError(f"{label} did not become ready")


def serve(args, state):
    base = [sys.executable, "-B", "-m"]
    common = ["--config", str(args.config.resolve()), "--state", str(state)]
    web_env = dict(os.environ)
    for name in ("OPENAI_API_KEY", "FACTORY_AUTHORIZE_PAID_AI", "FACTORY_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        web_env.pop(name, None)
    processes = []
    stopping = False

    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        web = subprocess.Popen([*base, "factory.control", *common, "--accounts", str(args.accounts.resolve()),
                                "--port", str(args.port), "--origin", args.origin],
                               env=web_env, start_new_session=True)
        processes.append(web)
        opener = build_opener(ProxyHandler({}))
        host = args.origin.split("://", 1)[1]

        def panel_ready():
            try:
                with opener.open(Request(f"http://127.0.0.1:{args.port}/",
                                         headers={"Host": host}), timeout=2) as response:
                    return response.status == 200
            except URLError:
                return False

        wait_ready(web, panel_ready, "Control center")
        started = time.time()
        worker = subprocess.Popen([*base, "factory.orchestrator", *common, "run",
                                   "--workers", str(args.workers)], start_new_session=True)
        processes.append(worker)

        def worker_ready():
            with closing(Queue(state / "queue.sqlite3").db) as db:
                heartbeat = db.execute("SELECT heartbeat FROM runtime WHERE id=1").fetchone()
                return heartbeat and heartbeat[0] >= started

        wait_ready(worker, worker_ready, "Dispatcher")
        print(f"Pilot ready at {args.origin}", flush=True)
        while not stopping:
            if any(process.poll() is not None for process in processes):
                raise QueueError("Control center or dispatcher exited")
            time.sleep(.25)
    finally:
        # Stop accepting HTTP requests and let claimed work finish before releasing SQLite.
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--accounts", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--port", default=8787, type=int)
    parser.add_argument("--origin", help="Exact private HTTPS URL, defaults to loopback HTTP")
    parser.add_argument("--workers", default=2, type=int, choices=range(1, 17))
    parser.add_argument("--check", action="store_true", help="Check prerequisites without running services")
    args = parser.parse_args()
    args.origin = args.origin or f"http://127.0.0.1:{args.port}"
    os.umask(0o077)
    try:
        state = check(args)
        if not args.check:
            serve(args, state)
    except (QueueError, Critical, Retryable) as error:
        parser.exit(2, f"Pilot: {error}\n")
    except (OSError, ValueError, TypeError, AttributeError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f"Pilot: {type(error).__name__}\n")
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
