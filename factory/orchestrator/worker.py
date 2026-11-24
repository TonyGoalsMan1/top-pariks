"""Advance durable tasks through execution, publication, checks and review."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import time

from .executors import Critical, Retryable, execute, schema
from .integrations import Integrations, MAX_CONTEXT
from .projects import FACTORY
from .queue import Queue, QueueError


def next_step(status, phase, result, delay=0):
    return status, phase, result, delay


class ReviewRejected(Retryable):
    pass


class Worker:
    def __init__(self, db_path, state, projects, lease):
        self.db_path = db_path
        self.state = state
        self.projects = projects
        self.lease = lease

    def response(self, project, job, role, payload, review=False):
        if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_CONTEXT:
            raise QueueError("Selected files, diff and objective exceed the context size limit")

        def reserve(amount):
            queue = Queue(self.db_path)
            try:
                queue.reserve(project, amount)
            finally:
                queue.db.close()

        outcome = execute(project, job, role, payload, reserve, self.lease, review=review)
        definition = schema(job["spec"]["operation"] == "code" and not review, review)
        if (not isinstance(outcome, dict) or set(outcome) != set(definition["required"])
                or not isinstance(outcome["summary"], str)
                or (review and type(outcome["passed"]) is not bool)
                or ("files" in outcome and not isinstance(outcome["files"], list))):
            raise Critical("Executor returned an invalid structured result")
        outcome["summary"] = outcome["summary"][:2000]
        return outcome

    def review(self, project, job, diff, checks):
        result = self.response(project, job, project.reviewer, {
            "objective": job["spec"]["objective"], "diff": diff, "checks": checks,
        }, review=True)
        if not result["passed"]:
            raise ReviewRejected("Independent review requested corrections: " + result["summary"])
        return result["summary"]

    def step(self, project, job):
        phase, result = job["phase"], job["result"]
        spec = job["spec"]
        tool = Integrations(project, self.state, job, self.lease)
        if spec["operation"] in FACTORY:
            return next_step("done", phase, tool.factory())
        if result.get("ci_deadline", float("inf")) <= time.time():
            raise QueueError("GitHub publication, CI or review deadline exceeded")
        if phase == "execute":
            if job["attempt"] > project.max_attempts:
                raise QueueError("Retry limit exhausted during restart recovery")
            base = tool.ensure_checkout(result)
            payload = tool.payload()
            queue = Queue(self.db_path)
            try:
                payload["prior_reports"] = queue.previous_reports(job["id"])
            finally:
                queue.db.close()
            payload["previous_failure"] = result.get("failure")
            if result.get("head"):
                payload["prior_diff"] = tool.diff(base, result["head"])
            outcome = self.response(project, job, spec["role"], payload)
            if spec["operation"] == "report":
                return next_step("done", phase, {"summary": outcome["summary"]})
            diff, head = tool.apply(outcome["files"], base)
            if project.github:
                return next_step("queued", "publish", {
                    "base": base, "head": head, "summary": outcome["summary"],
                    "ci_deadline": result.get("ci_deadline") or tool.deadline(),
                })
            review = self.review(project, job, diff, {"git diff --check": "passed"})
            return next_step("done", phase, {"base": base, "head": head, "branch": tool.branch,
                                             "checkout": str(tool.checkout), "summary": outcome["summary"],
                                             "review": review})

        if phase == "publish":
            return next_step("queued", "ci", dict(result, pr=tool.publish(result)), 5)

        pr = tool.pull_status(result)
        if pr["state"] == "MERGED":
            if phase != "merge":
                raise Critical("Pull request merged before the orchestrator completed its review")
            return next_step("done", phase, dict(result, merged=True, merge_source="GitHub"))
        if phase == "ci":
            pending, failures = tool.checks(result["head"])
            if failures:
                return self.retry(project, job, f"GitHub CI failed: {json.dumps(failures, sort_keys=True)}",
                                  phase="execute")
            if pending:
                return next_step("queued", phase, result, 5)
            review = self.review(project, job, tool.diff(result["base"], result["head"]),
                                 {name: "success" for name in project.github["required_checks"]})
            return next_step("queued", "merge", dict(result, review=review,
                                                      merge_state=pr["mergeStateStatus"]))
        if (project.github.get("auto_merge") and job["approved"] == result["head"]
                and pr["mergeStateStatus"] == "CLEAN" and tool.merge(pr, result)):
            return next_step("done", phase, dict(result, merged=True, merge_source="orchestrator"))
        return next_step("queued", phase, dict(result, merge_state=pr["mergeStateStatus"]), 10)

    def retry(self, project, job, reason, phase=None):
        phase = phase or job["phase"]
        result = dict(job["result"], failure=reason)
        if phase != "execute":
            result["transport_failures"] = result.get("transport_failures", 0) + 1
            if result["transport_failures"] >= project.max_attempts:
                return next_step("failed", phase, result)
            return next_step("queued", phase, result, max(1, project.backoff))
        if job["attempt"] >= project.max_attempts:
            return next_step("failed", phase, result)
        return next_step("queued", phase, result, project.backoff)

    def perform(self, job):
        project = self.projects.get(job["project"])
        critical = job["spec"]["critical"]
        try:
            if project is None or job["fingerprint"] != project.fingerprint:
                raise Critical("Project registration changed after submission")
            if critical and job["spec"]["operation"] != job["approved"]:
                raise Critical("A matching approval is required")
            status, phase, result, delay = self.step(project, job)
            critical = False
        except Retryable as error:
            if job["phase"] == "ci" and isinstance(error, ReviewRejected):
                status, phase, result, delay = self.retry(project, job, str(error), phase="execute")
            elif critical:
                status, phase, result, delay = "blocked", job["phase"], {"failure": str(error)}, 0
            else:
                status, phase, result, delay = self.retry(project, job, str(error))
        except (QueueError, Critical) as error:
            critical = critical or isinstance(error, Critical)
            status, phase, result, delay = ("blocked" if critical else "failed"), job["phase"], {
                **job["result"], "failure": str(error),
            }, 0
        except Exception as error:
            critical = True
            status, phase, result, delay = "blocked", job["phase"], {
                **job["result"], "failure": f"Unexpected {type(error).__name__}",
            }, 0
        return status, phase, result, delay, critical

    def run(self, queue, workers, once):
        queue.recover()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            active = {}
            while True:
                while len(active) < workers:
                    job = queue.claim()
                    if not job:
                        break
                    active[pool.submit(self.perform, job)] = job["id"]
                if not active:
                    if once:
                        return
                    time.sleep(0.5)
                    continue
                completed, _ = wait(active, timeout=0.5, return_when=FIRST_COMPLETED)
                for future in completed:
                    queue.finish(active.pop(future), *future.result())
