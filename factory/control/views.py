"""Project-scoped views of the queue and local Factory state."""

import json
import re
import time

from factory.orchestrator.projects import BACKUP_ID, FACTORY, ROLES
from factory.orchestrator.queue import approval_version


OPERATIONS = FACTORY - {"rollback"}
RESULT_FIELDS = {
    "base", "head", "branch", "summary", "review", "pr", "checks", "pr_state", "merge_state",
    "merged", "merge_source", "failure", "commit", "operation", "verified", "backup", "stylesheet_sha256",
}
EVENT_FIELDS = RESULT_FIELDS | {
    "role", "phase", "attempt", "scope", "version", "recovery", "reason", "task", "microdollars",
    "project_reserved", "input_tokens", "output_tokens", "estimated_microdollars", "calls_reserved",
}
NOTICES = {
    "done": "Задача завершена", "failed": "Ошибка задачи", "blocked": "Задача заблокирована",
    "automatic_pause": "Диспетчер остановлен для проверки", "interrupted": "Выполнение прервано",
}


def pick(row, fields):
    return {key: value for key, value in row.items() if key in fields}


def task_view(queue, project, row):
    spec = row["spec"]
    result = pick(row["result"], RESULT_FIELDS)
    if project.slug and type(result.get("pr")) is int:
        result["pr_url"] = f"https://github.com/{project.slug}/pull/{result['pr']}"
    needs_approval = (spec["critical"] and row["status"] == "queued" and not row["approved"]
                      and row["fingerprint"] == project.fingerprint and spec["operation"] in OPERATIONS)
    return {
        **pick(row, {"id", "status", "phase", "attempt", "created", "priority"}),
        "spec": spec, "result": result, "dependencies": queue.dependencies(row["id"]),
        "held": queue.is_held(row["id"]), "cancelling": bool(row["cancel"]) and row["status"] == "running",
        "approval": approval_version(row) if needs_approval else None,
    }


def events(queue, task):
    return [dict(pick(row, {"seq", "time", "event"}), detail=pick(row["detail"], EVENT_FIELDS))
            for row in queue.history(task)]


def site_view(state, project, rows):
    if not project.profile:
        return None
    root = state / "wordpress" / project.site_id
    backups = root / "backups"
    entries = []
    if backups.is_dir() and not backups.is_symlink():
        for directory in sorted(backups.iterdir(), reverse=True):
            manifest = directory / "manifest.json"
            if (not re.fullmatch(BACKUP_ID, directory.name) or directory.is_symlink()
                    or manifest.is_symlink() or not manifest.is_file()):
                continue
            try:
                record = json.loads(manifest.read_text())
                if record["kind"] == "backup" and record["profile"]["site_id"] == project.site_id:
                    entries.append({"id": directory.name, "created_at": record["created_at"]})
            except (OSError, ValueError, TypeError, KeyError):
                continue
    health = next((task for task in rows if task["spec"]["operation"] == "health"), None)
    return {
        "environment": "test", "domain": project.domain, "provisioned": (root / "provisioned").is_file(),
        "recovery_required": (root / "pending.json").is_file(),
        "health": pick(health, {"id", "status", "result"}) if health else None,
        "backups": entries,
    }


def page(queue, project, before=None):
    rows = queue.db.execute(
        "SELECT id FROM jobs WHERE project=? AND (? IS NULL OR (created,id)<"
        "(SELECT created,id FROM jobs WHERE id=? AND project=?)) ORDER BY created DESC,id DESC LIMIT 21",
        (project.id, before, before, project.id),
    ).fetchall()
    return {"tasks": [task_view(queue, project, queue.job(row[0])) for row in rows[:20]],
            "next": rows[19][0] if len(rows) > 20 else None}


def dashboard(queue, state, project):
    listing = page(queue, project)
    health = queue.db.execute(
        "SELECT id FROM jobs WHERE project=? AND json_extract(spec,'$.operation')='health' "
        "AND status IN ('done','failed','blocked') ORDER BY created DESC,id DESC LIMIT 1", (project.id,)
    ).fetchone()
    notices = [dict(row, message=NOTICES[row["event"]]) for row in queue.db.execute(
        "SELECT e.seq,e.job,e.time,e.event FROM events e JOIN jobs j ON j.id=e.job "
        "WHERE j.project=? AND e.event IN ('done','failed','blocked','automatic_pause','interrupted') "
        "ORDER BY e.seq DESC LIMIT 30", (project.id,)
    )]
    approvals = queue.db.execute(
        "SELECT id AS job, created AS time FROM jobs WHERE project=? AND fingerprint=? "
        "AND status='queued' AND approved IS NULL AND json_extract(spec,'$.critical')=1 "
        "AND json_extract(spec,'$.operation')!='rollback' ORDER BY created DESC LIMIT 30",
        (project.id, project.fingerprint),
    )
    notices[:0] = [dict(row, message="Требуется разрешение владельца", event="approval_required")
                   for row in approvals]
    budget = queue.db.execute("SELECT reserved FROM budgets WHERE project=?", (project.id,)).fetchone()
    totals = queue.db.execute(
        "SELECT SUM(json_extract(e.detail,'$.input_tokens')), SUM(json_extract(e.detail,'$.output_tokens')), "
        "SUM(json_extract(e.detail,'$.estimated_microdollars')) "
        "FROM events e JOIN jobs j ON j.id=e.job WHERE j.project=? AND e.event='ai_usage'", (project.id,)
    ).fetchone()
    heartbeat = queue.db.execute("SELECT heartbeat FROM runtime WHERE id=1").fetchone()
    codex_budget = {}
    if project.executor == "codex":
        calls = queue.db.execute(
            "SELECT count(*) FROM events e JOIN jobs j ON j.id=e.job "
            "WHERE j.project=? AND e.event='codex_call_reserved'", (project.id,)
        ).fetchone()[0]
        codex_budget = {"calls_reserved": calls, "max_calls": project.budget["max_calls"]}
    return {
        **listing, "project": project.id, "executor": project.executor, "notifications": notices,
        "task_count": queue.db.execute("SELECT COUNT(*) FROM jobs WHERE project=?", (project.id,)).fetchone()[0],
        "operations": sorted(project.permissions & OPERATIONS),
        "business_roles": sorted(role for role in project.roles
                                 if "code" in project.permissions and ROLES[role]["permission"] == "edit"),
        "paused": queue.project_paused(project.id), "dispatcher_paused": queue.paused(),
        "dispatcher_online": heartbeat is not None and time.time() - heartbeat[0] < 8,
        "site": site_view(state, project, [task_view(queue, project, queue.job(health[0]))] if health else []),
        "budget": dict(pick(project.budget, {"model", "total_microdollars", "max_input_tokens", "max_output_tokens"}),
                       limit_microdollars=queue.budget_limit(project),
                       reserved_microdollars=budget[0] if budget else 0,
                       input_tokens=totals[0] or 0, output_tokens=totals[1] or 0,
                       estimated_microdollars=None if codex_budget else totals[2] or 0, **codex_budget),
    }
