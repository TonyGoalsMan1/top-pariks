"""Durable scheduler for a single Linux dispatcher and concurrent CLI clients."""

from contextlib import contextmanager
import hashlib
import json
import sqlite3
import time
import uuid


TERMINAL = ("done", "failed", "cancelled", "blocked")
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, project TEXT NOT NULL, fingerprint TEXT NOT NULL,
    spec TEXT NOT NULL, priority INTEGER NOT NULL, resource TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued', phase TEXT NOT NULL DEFAULT 'execute',
    attempt INTEGER NOT NULL DEFAULT 0, ready REAL NOT NULL DEFAULT 0,
    approved TEXT, cancel INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT '{}',
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS dependencies (
    job TEXT NOT NULL REFERENCES jobs(id), prerequisite TEXT NOT NULL REFERENCES jobs(id),
    PRIMARY KEY (job, prerequisite)
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY, job TEXT REFERENCES jobs(id), time REAL NOT NULL,
    event TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS control (
    id INTEGER PRIMARY KEY CHECK (id = 1), paused INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO control(id) VALUES (1);
CREATE TABLE IF NOT EXISTS budgets (
    project TEXT PRIMARY KEY, reserved INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS budget_caps (
    project TEXT PRIMARY KEY, microdollars INTEGER NOT NULL CHECK(microdollars >= 0)
);
CREATE TABLE IF NOT EXISTS holds (
    job TEXT PRIMARY KEY REFERENCES jobs(id)
);
CREATE TABLE IF NOT EXISTS project_pauses (
    project TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS runtime (
    id INTEGER PRIMARY KEY CHECK (id = 1), heartbeat REAL NOT NULL
);
"""
CRITICAL = {"start", "deploy", "backup", "rollback", "restore"}


class QueueError(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def approval_version(row):
    return hashlib.sha256(encode([
        row["project"], row["id"], row["fingerprint"], row["spec"], row["phase"], row["attempt"],
    ]).encode()).hexdigest()


class Queue:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        if self.db.in_transaction:
            yield
            return
        self.db.execute("BEGIN IMMEDIATE")
        with self.db:
            yield

    def event(self, job, event, **detail):
        self.db.execute("INSERT INTO events(job,time,event,detail) VALUES(?,?,?,?)",
                        (job, time.time(), event, encode(detail)))

    def job(self, job):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
        if row is None:
            raise QueueError("Unknown task")
        result = dict(row)
        for key in ("spec", "result"):
            result[key] = json.loads(result[key])
        return result

    def list(self):
        return [dict(row) for row in self.db.execute(
            "SELECT id, project, status, phase, attempt, priority FROM jobs ORDER BY created, id"
        )]

    def history(self, job):
        self.job(job)
        return [dict(row, detail=json.loads(row["detail"])) for row in self.db.execute(
            "SELECT * FROM events WHERE job=? ORDER BY seq", (job,)
        )]

    def add(self, project, specs, priority, dependencies):
        ids = []
        with self.transaction():
            for dependency in dependencies:
                if self.job(dependency)["project"] != project.id:
                    raise QueueError("Dependencies must belong to the same project")
            for spec in specs:
                job = uuid.uuid4().hex
                self.db.execute(
                    "INSERT INTO jobs(id,project,fingerprint,spec,priority,resource,created)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (job, project.id, project.fingerprint, encode(spec), priority,
                     project.resource(spec), time.time()),
                )
                for dependency in dependencies:
                    self.db.execute("INSERT INTO dependencies VALUES(?,?)", (job, dependency))
                self.event(job, "queued", operation=spec["operation"], role=spec.get("role"))
                ids.append(job)
                dependencies = [job]
        return ids

    def pause(self, value):
        with self.transaction():
            self.db.execute("UPDATE control SET paused=? WHERE id=1", (value,))
            self.event(None, "paused" if value else "resumed")

    def paused(self):
        return bool(self.db.execute("SELECT paused FROM control").fetchone()[0])

    def approve(self, job, expected, *, version=None):
        with self.transaction():
            row = self.job(job)
            if row["status"] != "queued":
                raise QueueError("Task must be queued to approve it")
            if row["spec"]["operation"] in CRITICAL:
                approval = row["spec"]["operation"]
            elif row["phase"] == "merge" and row["result"].get("head") == expected:
                approval = expected
            else:
                raise QueueError("Provide the exact reviewed head when approving a merge")
            if approval != expected:
                raise QueueError("Approval does not match the operation")
            if version is not None and (row["approved"] or approval_version(row) != version):
                raise QueueError("Approval was already used or the task version changed")
            self.db.execute("UPDATE jobs SET approved=?,ready=0 WHERE id=?", (approval, job))
            self.event(job, "approved", scope=approval, version=approval_version(row))

    def dependencies(self, job):
        return [row[0] for row in self.db.execute(
            "SELECT prerequisite FROM dependencies WHERE job=? ORDER BY prerequisite", (job,)
        )]

    def retry_job(self, project, job):
        with self.transaction():
            row = self.job(job)
            if row["project"] != project.id or row["fingerprint"] != project.fingerprint:
                raise QueueError("Project registration changed; submit a new task")
            if row["status"] not in TERMINAL:
                raise QueueError("Task must end before it can be retried")
            if row["spec"]["critical"] and (row["attempt"] or row["status"] != "cancelled"):
                raise QueueError("Inspect Factory recovery before submitting a new operation")
            dependencies = self.dependencies(job)
            if any(self.job(parent)["status"] != "done" for parent in dependencies):
                raise QueueError("Finish prerequisites before retrying or submit with new dependencies")
            new_job, = self.add(project, [row["spec"]], row["priority"], dependencies)
            self.event(new_job, "retried_from", task=job)
            return new_job

    def set_hold(self, job, hold):
        with self.transaction():
            row = self.job(job)
            if row["status"] in TERMINAL or row["cancel"]:
                raise QueueError("Task has ended or is being cancelled")
            if hold:
                self.db.execute("INSERT OR IGNORE INTO holds VALUES (?)", (job,))
            else:
                self.db.execute("DELETE FROM holds WHERE job=?", (job,))
            self.event(job, "held" if hold else "released")

    def is_held(self, job):
        return self.db.execute("SELECT 1 FROM holds WHERE job=?", (job,)).fetchone() is not None

    def set_project_pause(self, project, paused):
        with self.transaction():
            if paused:
                self.db.execute("INSERT OR IGNORE INTO project_pauses VALUES (?)", (project,))
            else:
                self.db.execute("DELETE FROM project_pauses WHERE project=?", (project,))

    def project_paused(self, project):
        return self.db.execute("SELECT 1 FROM project_pauses WHERE project=?", (project,)).fetchone() is not None

    def heartbeat(self, active=True):
        with self.transaction():
            if active:
                self.db.execute("INSERT OR REPLACE INTO runtime VALUES (1,?)", (time.time(),))
            else:
                self.db.execute("DELETE FROM runtime WHERE id=1")

    def cancel(self, job):
        with self.transaction():
            row = self.job(job)
            if row["status"] in TERMINAL:
                raise QueueError("Task already ended")
            status = "running" if row["status"] == "running" else "cancelled"
            self.db.execute("UPDATE jobs SET cancel=1,status=? WHERE id=?", (status, job))
            self.event(job, "cancel_requested" if status == "running" else status)

    def claim(self):
        with self.transaction():
            if self.paused():
                return None
            # Repeat until transitive dependency failures have propagated.
            while True:
                blocked = self.db.execute(
                    """SELECT DISTINCT j.id FROM jobs j JOIN dependencies d ON d.job=j.id
                    JOIN jobs parent ON parent.id=d.prerequisite
                    WHERE j.status='queued' AND parent.status IN ('failed','cancelled','blocked')"""
                ).fetchall()
                if not blocked:
                    break
                for (job,) in blocked:
                    self.db.execute("UPDATE jobs SET status='blocked' WHERE id=?", (job,))
                    self.event(job, "blocked", reason="dependency did not complete")
            row = self.db.execute(
                """SELECT j.id FROM jobs j WHERE j.status='queued' AND j.ready<=?
                AND NOT EXISTS (SELECT 1 FROM holds h WHERE h.job=j.id)
                AND NOT EXISTS (SELECT 1 FROM project_pauses p WHERE p.project=j.project)
                AND (json_extract(j.spec,'$.critical')=0 OR j.approved IS NOT NULL)
                AND NOT EXISTS (SELECT 1 FROM dependencies d JOIN jobs p ON p.id=d.prerequisite
                    WHERE d.job=j.id AND p.status!='done')
                AND NOT EXISTS (SELECT 1 FROM jobs owner WHERE owner.resource=j.resource
                    AND owner.id!=j.id AND (owner.status='running' OR
                    (owner.status='queued' AND (owner.phase IN ('publish','ci','merge')
                    OR json_extract(owner.result,'$.pr') IS NOT NULL))))
                ORDER BY j.priority DESC,j.created,j.id LIMIT 1""", (time.time(),)
            ).fetchone()
            if row is None:
                return None
            job = row["id"]
            self.db.execute("UPDATE jobs SET status='running',attempt=attempt+(phase='execute') WHERE id=?",
                            (job,))
            claimed = self.job(job)
            self.event(job, "started", phase=claimed["phase"], attempt=claimed["attempt"])
            return claimed

    def finish(self, job, status, phase, result, delay=0, critical=False):
        with self.transaction():
            current = self.job(job)
            if current["cancel"] and not critical and status != "done":
                status = "cancelled"
            self.db.execute("UPDATE jobs SET status=?,phase=?,result=?,ready=? WHERE id=?",
                            (status, phase, encode(result), time.time() + delay, job))
            self.event(job, status, phase=phase, **result)
            if critical:
                self.db.execute("UPDATE control SET paused=1 WHERE id=1")
                self.event(job, "automatic_pause")

    def previous_reports(self, job):
        rows = self.db.execute(
            """WITH RECURSIVE previous(id) AS (
                SELECT prerequisite FROM dependencies WHERE job=?
                UNION SELECT d.prerequisite FROM dependencies d JOIN previous p ON d.job=p.id
            )
            SELECT json_extract(spec,'$.role') AS role,
                   json_extract(result,'$.summary') AS summary
            FROM previous p JOIN jobs j ON p.id=j.id
            WHERE j.status='done' AND json_extract(spec,'$.operation')='report'
            ORDER BY j.created DESC LIMIT 10""", (job,)
        )
        return [dict(row) for row in rows]

    def recover(self):
        with self.transaction():
            for row in self.db.execute("SELECT id,spec,phase,cancel FROM jobs WHERE status='running'"):
                critical = json.loads(row["spec"])["critical"]
                status = "blocked" if critical else "cancelled" if row["cancel"] else "queued"
                self.db.execute("UPDATE jobs SET status=? WHERE id=?", (status, row["id"]))
                self.event(row["id"], "interrupted", phase=row["phase"], recovery=status)
                if critical:
                    self.db.execute("UPDATE control SET paused=1 WHERE id=1")
                    self.event(row["id"], "automatic_pause")

    def reserve(self, project, amount, job=None):
        with self.transaction():
            used = self.db.execute("SELECT reserved FROM budgets WHERE project=?", (project.id,)).fetchone()
            total = (used[0] if used else 0) + amount
            if total > self.budget_limit(project):
                raise QueueError("Project AI budget exhausted")
            self.db.execute("INSERT OR REPLACE INTO budgets VALUES (?,?)", (project.id, total))
            if job is not None:
                self.event(job, "budget_reserved", microdollars=amount, project_reserved=total)

    def budget_limit(self, project):
        cap = self.db.execute("SELECT microdollars FROM budget_caps WHERE project=?", (project.id,)).fetchone()
        limit = project.budget.get("total_microdollars", 0)
        return min(limit, cap[0]) if cap else limit

    def set_budget_cap(self, project, amount):
        with self.transaction():
            self.db.execute("INSERT OR REPLACE INTO budget_caps VALUES (?,?)", (project, amount))

    def record_usage(self, job, usage, estimated):
        with self.transaction():
            self.event(job, "ai_usage", input_tokens=usage["input_tokens"],
                       output_tokens=usage["output_tokens"], estimated_microdollars=estimated)
