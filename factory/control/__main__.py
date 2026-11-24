"""Run the WordPress Factory control center on a loopback listener."""

import argparse
from collections import deque
from contextlib import closing
from getpass import getpass
from hashlib import scrypt
from hmac import compare_digest
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from factory.orchestrator.__main__ import private_state
from factory.orchestrator.projects import IDENTIFIER, integer, load
from factory.orchestrator.queue import Queue, QueueError, encode

from .views import OPERATIONS, dashboard, events, page, task_view


STATIC = Path(__file__).with_name("static")
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/icon-180.png": ("icon-180.png", "image/png"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS console_projects (
    id TEXT PRIMARY KEY, registered REAL NOT NULL, identity TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS console_audit (
    seq INTEGER PRIMARY KEY, at REAL NOT NULL, actor TEXT NOT NULL,
    project TEXT, action TEXT NOT NULL, target TEXT, detail TEXT NOT NULL
);
"""
SESSION_SECONDS = 8 * 60 * 60


class HTTPError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def password_hash(password, salt):
    return scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024**2).hex()


def users(path, projects):
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise QueueError("Account file must be operator-owned and private (0600)")
    accounts = json.loads(path.read_text())
    if not isinstance(accounts, dict) or not accounts:
        raise QueueError("An account registry is required")
    for name, account in accounts.items():
        if (not re.fullmatch(IDENTIFIER, name)
                or not re.fullmatch(r"[a-f0-9]{32}", account["salt"])
                or not re.fullmatch(r"[a-f0-9]{128}", account["hash"])
                or type(account.get("owner", False)) is not bool
                or not all(project in projects and role in {"operator", "viewer"}
                           for project, role in account.get("projects", {}).items())):
            raise QueueError("Invalid account registry")
    if not any(account.get("owner") for account in accounts.values()):
        raise QueueError("An owner account is required")
    return accounts


def audit(queue, actor, project, action, target=None, **detail):
    queue.db.execute(
        "INSERT INTO console_audit(at,actor,project,action,target,detail) VALUES(?,?,?,?,?,?)",
        (time.time(), actor, project, action, target, encode(detail)),
    )


def project_identity(project):
    return encode([project.repo, project.site_type, getattr(project, "site_id", None)])


class Console(ThreadingHTTPServer):
    request_queue_size = 32
    allow_reuse_address = True

    def __init__(self, port, origin, state, projects, accounts):
        parsed = urlsplit(origin)
        if (not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query
                or parsed.fragment or origin != f"{parsed.scheme}://{parsed.netloc.lower()}"
                or (parsed.scheme != "https" and origin != f"http://127.0.0.1:{port}")):
            raise QueueError("Use a canonical HTTPS origin or the explicit loopback HTTP origin")
        self.origin = origin
        self.host = parsed.netloc
        self.secure = parsed.scheme == "https"
        self.cookie_name = "__Host-factory-session" if self.secure else "factory-session"
        self.state = state
        self.db_path = state / "queue.sqlite3"
        self.projects = projects
        self.accounts = accounts
        self.sessions = {}
        self.failed = deque()
        self.lock = threading.Lock()
        self.requests = threading.BoundedSemaphore(32)
        with closing(Queue(self.db_path).db) as db:
            db.executescript(SCHEMA)
            for project_id, identity in db.execute("SELECT id,identity FROM console_projects"):
                if project_id in projects and identity != project_identity(projects[project_id]):
                    raise QueueError("Registered project identity changed; use a new project ID")
        super().__init__(("127.0.0.1", port), Handler)

    def process_request(self, request, client_address):
        if not self.requests.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.requests.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            request.settimeout(10)
            super().process_request_thread(request, client_address)
        finally:
            self.requests.release()

    def sign_in(self, actor, password):
        now = time.monotonic()
        with self.lock:
            while self.failed and now - self.failed[0] >= 60:
                self.failed.popleft()
            if len(self.failed) >= 12:
                raise HTTPError(429, "Повторите вход через минуту")
            account = self.accounts.get(actor)
            candidate = password_hash(password, bytes.fromhex(account["salt"]) if account else bytes(16))
            if not compare_digest(candidate, account["hash"] if account else "0" * 128) or not account:
                self.failed.append(now)
                raise HTTPError(401, "Неверный логин или пароль")
            self.sessions = {key: value for key, value in self.sessions.items()
                             if value[1] > now}
            if len(self.sessions) >= 256:
                self.sessions.pop(next(iter(self.sessions)))
            token = secrets.token_urlsafe(32)
            self.sessions[token] = (actor, now + SESSION_SECONDS)
            return token


class Handler(BaseHTTPRequestHandler):
    server: Console

    def log_message(self, *_args):
        pass

    def send_content(self, status, data, mime, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
                         "connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if cookie is not None:
            age = SESSION_SECONDS if cookie else 0
            secure = "; Secure" if self.server.secure else ""
            self.send_header("Set-Cookie", f"{self.server.cookie_name}={cookie}; Path=/; "
                             f"Max-Age={age}; HttpOnly; SameSite=Strict{secure}")
        self.end_headers()
        self.wfile.write(data)

    def json(self, status, data, cookie=None):
        self.send_content(status, encode(data).encode(), "application/json; charset=utf-8", cookie)

    def body(self):
        if self.headers.get("Origin") != self.server.origin:
            raise HTTPError(403, "Запрос должен исходить из панели")
        if self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
            raise HTTPError(415, "Ожидается JSON")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,6}", lengths[0]):
            raise HTTPError(400, "Недопустимая длина запроса")
        length = int(lengths[0])
        if not 0 < length <= 65536:
            raise HTTPError(413, "Слишком большой запрос")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise HTTPError(400, "Ожидается объект JSON")
        return data

    def session(self):
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", "")).get(self.server.cookie_name)
        except CookieError:
            cookie = None
        token = cookie.value if cookie else ""
        with self.server.lock:
            session = self.server.sessions.get(token)
        if not session or session[1] <= time.monotonic():
            raise HTTPError(401, "Войдите в панель")
        return token, session[0]

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def dispatch(self):
        try:
            if self.headers.get_all("Host") != [self.server.host]:
                raise HTTPError(403, "Неизвестный адрес панели")
            target = urlsplit(self.path)
            if self.command == "GET" and target.path in ASSETS:
                filename, mime = ASSETS[target.path]
                self.send_content(200, (STATIC / filename).read_bytes(), mime)
                return
            if not target.path.startswith("/api/v1/"):
                raise HTTPError(404, "Маршрут отсутствует")
            body = self.body() if self.command == "POST" else None
            queue = Queue(self.server.db_path)
            with closing(queue.db):
                self.api(queue, target.path.removeprefix("/api/v1/"), body)
        except HTTPError as error:
            self.json(error.status, {"error": str(error)})
        except QueueError as error:
            self.json(409, {"error": str(error)})
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
            self.json(400, {"error": "Недопустимые параметры запроса"})
        except sqlite3.Error:
            self.json(503, {"error": "Очередь временно недоступна"})
        except (ConnectionError, TimeoutError):
            return
        except OSError:
            self.json(503, {"error": "Состояние панели временно недоступно"})

    def api(self, queue, path, body):
        if path == "session" and body is not None:
            actor, password = body["username"], body["password"]
            if (not isinstance(actor, str) or not isinstance(password, str)
                    or not re.fullmatch(IDENTIFIER, actor) or not 1 <= len(password) <= 256):
                raise HTTPError(401, "Неверный логин или пароль")
            try:
                token = self.server.sign_in(actor, password)
            except HTTPError as error:
                if error.status == 401:
                    with queue.transaction():
                        audit(queue, "anonymous", None, "login_rejected")
                raise
            with queue.transaction():
                audit(queue, actor, None, "login")
            self.json(200, {"user": actor}, token)
            return

        token, actor = self.session()
        account = self.server.accounts[actor]
        owner = account.get("owner", False)
        grants = account.get("projects", {})
        if path == "logout" and body is not None:
            with self.server.lock:
                self.server.sessions.pop(token, None)
            with queue.transaction():
                audit(queue, actor, None, "logout")
            self.json(200, {"logged_out": True}, "")
            return
        if path == "projects" and body is None:
            registered = {row[0] for row in queue.db.execute("SELECT id FROM console_projects")}
            self.json(200, {
                "user": actor, "owner": owner,
                "projects": [{"id": project.id, "role": "owner" if owner else grants[project.id],
                              "executor": project.executor, "type": project.site_type}
                             for project in self.server.projects.values()
                             if project.id in registered and (owner or project.id in grants)],
                "available": sorted(set(self.server.projects) - registered) if owner else [],
            })
            return

        match = re.fullmatch(rf"projects/({IDENTIFIER})(?:/(.+))?", path)
        if not match:
            raise HTTPError(404, "Маршрут отсутствует")
        project_id, action = match.groups()
        project = self.server.projects.get(project_id)
        if not project or not (owner or project_id in grants):
            raise HTTPError(404, "Проект отсутствует")
        if action == "register" and owner and body is not None:
            with queue.transaction():
                if queue.db.execute("INSERT OR IGNORE INTO console_projects VALUES (?,?,?)",
                                    (project_id, time.time(), project_identity(project))).rowcount:
                    audit(queue, actor, project_id, "register", version=project.fingerprint)
            self.json(200, {"project": project_id})
            return
        if not queue.db.execute("SELECT 1 FROM console_projects WHERE id=?", (project_id,)).fetchone():
            raise HTTPError(404, "Проект отсутствует")
        if body is None and action is None:
            self.json(200, dashboard(queue, self.server.state, project))
            return
        older = re.fullmatch(r"tasks/before/([a-f0-9]{32})", action or "")
        if body is None and older:
            self.project_task(queue, project, older[1])
            self.json(200, page(queue, project, older[1]))
            return
        if body is None and action == "audit" and owner:
            records = [dict(row, detail=json.loads(row["detail"])) for row in queue.db.execute(
                "SELECT * FROM console_audit WHERE project=? ORDER BY seq DESC LIMIT 100", (project_id,)
            )]
            self.json(200, {"records": records})
            return
        task_route = re.fullmatch(r"tasks/([a-f0-9]{32})(?:/(hold|release|cancel|retry|approve))?", action or "")
        if body is None and task_route and not task_route[2]:
            task = self.project_task(queue, project, task_route[1])
            self.json(200, dict(task_view(queue, project, task), events=events(queue, task["id"])))
            return
        if body is None:
            raise HTTPError(404, "Маршрут отсутствует")
        if not owner and grants[project_id] != "operator":
            raise HTTPError(403, "Недостаточно прав")
        with queue.transaction():
            result, status = self.mutate(queue, actor, project, action, body, owner, task_route)
        self.json(status, result)

    def project_task(self, queue, project, task):
        if not queue.db.execute("SELECT 1 FROM jobs WHERE id=? AND project=?", (task, project.id)).fetchone():
            raise HTTPError(404, "Задача отсутствует")
        return queue.job(task)

    def mutate(self, queue, actor, project, action, body, owner, task_route):
        if action == "budget":
            if not owner:
                raise HTTPError(403, "Требуется разрешение владельца")
            if project.executor != "responses":
                raise HTTPError(409, "Демонстрационный исполнитель не использует бюджет")
            amount = integer(body["limit_microdollars"], 0, project.budget["total_microdollars"])
            queue.set_budget_cap(project.id, amount)
            audit(queue, actor, project.id, action, limit_microdollars=amount)
            return {"limit_microdollars": amount}, 200
        if action in {"pause", "resume"}:
            paused = action == "pause"
            queue.set_project_pause(project.id, paused)
            audit(queue, actor, project.id, action)
            return {"paused": paused}, 200
        if action in {"business", "operations"}:
            objective = body["objective"]
            if action == "business":
                specs = project.business(objective, body["role"])
            else:
                operation = body["operation"]
                if operation not in OPERATIONS:
                    raise HTTPError(403, "Операция недоступна в панели")
                specs = [project.task(operation, objective, ref=body.get("ref"), backup=body.get("backup"))]
            after = body.get("after", [])
            if not isinstance(after, list) or len(after) > 20 or len(set(after)) != len(after):
                raise HTTPError(400, "Недопустимые зависимости")
            for task in after:
                self.project_task(queue, project, task)
            tasks = queue.add(project, specs, integer(body.get("priority", 0), -100, 100), after)
            audit(queue, actor, project.id, action, tasks[-1], tasks=tasks)
            return {"tasks": tasks}, 201
        if not task_route or not task_route[2]:
            raise HTTPError(404, "Маршрут отсутствует")
        task, command = task_route.groups()
        row = self.project_task(queue, project, task)
        if command == "approve":
            if not owner:
                raise HTTPError(403, "Требуется разрешение владельца")
            if (row["fingerprint"] != project.fingerprint or not row["spec"]["critical"]
                    or row["spec"]["operation"] not in OPERATIONS):
                raise HTTPError(409, "Версия или операция больше недоступна")
            version = body["version"]
            if not isinstance(version, str) or not re.fullmatch(r"[a-f0-9]{64}", version):
                raise HTTPError(400, "Укажите версию разрешения")
            queue.approve(task, body["operation"], version=version)
            audit(queue, actor, project.id, command, task, version=version, operation=body["operation"])
        elif command == "cancel":
            queue.cancel(task)
            audit(queue, actor, project.id, command, task)
        elif command in {"hold", "release"}:
            queue.set_hold(task, command == "hold")
            audit(queue, actor, project.id, command, task)
        elif command == "retry":
            new_task = queue.retry_job(project, task)
            audit(queue, actor, project.id, command, task, new_task=new_task)
            return {"task": new_task}, 201
        return {"task": task}, 200


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hash-password", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--accounts", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--origin")
    args = parser.parse_args()
    if args.hash_password:
        password = getpass("Password: ")
        if not 16 <= len(password) <= 256 or password != getpass("Repeat password: "):
            parser.error("Use a matching password of 16–256 characters")
        salt = secrets.token_bytes(16)
        print(encode({"salt": salt.hex(), "hash": password_hash(password, salt)}))
        return
    if not all((args.config, args.accounts, args.state, args.origin)):
        parser.error("--config, --accounts, --state and --origin are required")
    os.umask(0o077)
    try:
        state = private_state(args.state)
        projects = load(args.config.resolve())
        if any(project.github.get("auto_merge") for project in projects.values()):
            raise QueueError("The control center requires a registry with automatic merge disabled")
        accounts = users(args.accounts.resolve(), projects)
        with Console(args.port, args.origin, state, projects, accounts) as server:
            print(f"WordPress Factory Control Center listening on 127.0.0.1:{args.port}", flush=True)
            server.serve_forever()
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f"Control center: {error if isinstance(error, QueueError) else type(error).__name__}\n")
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
