"""Operator CLI for WordPress Factory's autonomous test-project queue."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import signal
from threading import Event

from .projects import integer, load
from .queue import Queue, QueueError
from .worker import Worker


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("submit", "business"):
        command = commands.add_parser(name)
        command.add_argument("project")
        if name == "submit":
            command.add_argument("operation")
            command.add_argument("--ref")
            command.add_argument("--backup")
        command.add_argument("objective")
        command.add_argument("--role", required=name == "business")
        command.add_argument("--priority", type=int, default=0)
        command.add_argument("--after", action="append", default=[])
    seed = commands.add_parser("seed")
    seed.add_argument("project")
    for name in ("get", "events", "cancel", "approve"):
        command = commands.add_parser(name)
        command.add_argument("id")
        if name == "approve":
            command.add_argument("expected")
    for name in ("list", "status", "pause", "resume"):
        commands.add_parser(name)
    run = commands.add_parser("run")
    run.add_argument("--workers", type=int, default=2)
    run.add_argument("--once", action="store_true", help="Drain ready tasks and exit when idle")
    return parser, parser.parse_args()


def private_state(path):
    path = path.absolute()
    if path.is_symlink():
        raise QueueError("Runtime state cannot be a symbolic link")
    path = path.resolve()
    current = path
    while current != current.parent:
        if (current / ".git").exists():
            raise QueueError("Runtime state must be outside Git checkouts")
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise QueueError("Runtime state must be owned by the operator and private (0700)")
    return path


def main(args):
    os.umask(0o077)
    projects = load(args.config.resolve())
    state = private_state(args.state)
    db = state / "queue.sqlite3"
    queue = Queue(db)
    command = args.command
    try:
        if command == "run":
            workers = integer(args.workers, 1, 16)
            with (state / "dispatcher.lock").open("a") as lease:
                try:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise QueueError("Another dispatcher owns this state") from None
                stop = Event()
                previous = signal.signal(signal.SIGTERM, lambda *_: stop.set())
                try:
                    Worker(db, state, projects, lease.fileno()).run(queue, workers, args.once, stop)
                finally:
                    signal.signal(signal.SIGTERM, previous)
            return None
        if command in ("business", "submit", "seed"):
            if args.project not in projects:
                raise QueueError("Unknown project")
            project = projects[args.project]
            if command == "seed":
                specs = [project.task(**spec) for spec in project.queue]
                return {"tasks": queue.add(project, specs, 0, [])}
            if command == "business":
                specs = project.business(args.objective, args.role)
            else:
                specs = [project.task(args.operation, args.objective, args.role, args.ref, args.backup)]
            return {"tasks": queue.add(project, specs, integer(args.priority, -100, 100), args.after)}
        if command in {"pause", "resume"}:
            queue.pause(command == "pause")
        elif command == "cancel":
            queue.cancel(args.id)
        elif command == "approve":
            queue.approve(args.id, args.expected)
        elif command == "get":
            return queue.job(args.id)
        elif command == "events":
            return queue.history(args.id)
        elif command == "list":
            return queue.list()
        return {"paused": queue.paused()}
    finally:
        queue.db.close()


if __name__ == "__main__":
    parser, args = arguments()
    try:
        result = main(args)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError, TypeError, sqlite3.Error) as error:
        parser.exit(2, f"Orchestrator: {error if isinstance(error, QueueError) else type(error).__name__}\n")
