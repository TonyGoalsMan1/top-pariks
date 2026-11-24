"""Focused scheduler and remote adapter contract tests. No external calls."""

import contextlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orchestrator.executors import Critical, Retryable, execute, model_access
from orchestrator import codex
from orchestrator.integrations import Integrations
from orchestrator.queue import Queue, QueueError


class Scheduler(unittest.TestCase):
    def setUp(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        self.queue = Queue(Path(root) / "queue.sqlite3")
        self.addCleanup(self.queue.db.close)
        self.alpha = SimpleNamespace(id="alpha", fingerprint="alpha", resource=lambda task: "repo:a",
                                     budget={"total_microdollars": 10})
        self.beta = SimpleNamespace(id="beta", fingerprint="beta", resource=lambda task: "repo:b")

    def test_priority_resource_and_transitive_dependency_failure(self):
        spec = {"operation": "code", "critical": False}
        first, follow, last = self.queue.add(self.alpha, [spec, spec, spec], 20, [])
        same_resource, = self.queue.add(self.alpha, [spec], 10, [])
        independent, = self.queue.add(self.beta, [spec], 0, [])
        self.assertEqual(self.queue.claim()["id"], first)
        self.assertEqual(self.queue.claim()["id"], independent)
        self.assertIsNone(self.queue.claim())
        self.queue.finish(first, "queued", "publish", {"head": "updated"}, 30)
        self.assertIsNone(self.queue.claim())
        self.queue.cancel(first)
        self.assertEqual(self.queue.claim()["id"], same_resource)
        self.assertEqual(self.queue.job(follow)["status"], "blocked")
        self.assertEqual(self.queue.job(last)["status"], "blocked")

    def test_critical_restart_requires_recovery_and_operator_resume(self):
        spec = {"operation": "restore", "critical": True, "backup": "pinned"}
        first, = self.queue.add(self.alpha, [spec], 20, [])
        self.assertIsNone(self.queue.claim())
        with self.assertRaises(QueueError):
            self.queue.approve(first, "deploy")
        self.queue.approve(first, "restore")
        self.assertEqual(self.queue.claim()["id"], first)
        self.queue.recover()
        self.assertTrue(self.queue.paused())
        self.assertEqual(self.queue.job(first)["status"], "blocked")
        self.queue.pause(False)
        self.assertIsNone(self.queue.claim())

    def test_budget_is_reserved_across_open_connections(self):
        self.queue.reserve(self.alpha, 6)
        with contextlib.closing(Queue(self.queue.db.execute("PRAGMA database_list").fetchone()[2]).db) as other:
            self.assertEqual(other.execute("SELECT reserved FROM budgets").fetchone()[0], 6)
        with self.assertRaises(QueueError):
            self.queue.reserve(self.alpha, 5)
        self.queue.reserve(self.alpha, 4)

    def test_owner_budget_cap_cannot_increase_registry_ceiling(self):
        self.queue.set_budget_cap(self.alpha.id, 0)
        with self.assertRaises(QueueError):
            self.queue.reserve(self.alpha, 1)
        self.queue.set_budget_cap(self.alpha.id, 4)
        self.queue.reserve(self.alpha, 4)
        with self.assertRaises(QueueError):
            self.queue.reserve(self.alpha, 1)
        self.queue.set_budget_cap(self.alpha.id, 100)
        self.assertEqual(self.queue.budget_limit(self.alpha), 10)

    def test_codex_call_ceiling_keeps_unknown_cost(self):
        self.alpha.budget["max_calls"] = 1
        job, = self.queue.add(self.alpha, [{"operation": "code", "critical": False}], 0, [])
        self.queue.reserve_codex(self.alpha, job)
        with self.assertRaises(QueueError):
            self.queue.reserve_codex(self.alpha, job)
        self.queue.record_usage(job, {"input_tokens": 10, "output_tokens": 20}, None)
        events = self.queue.history(job)
        self.assertEqual(events[-2]["detail"], {"calls_reserved": 1})
        self.assertIsNone(events[-1]["detail"]["estimated_microdollars"])

    def test_interrupted_preview_requires_factory_recovery(self):
        job, = self.queue.add(self.alpha, [{"operation": "code", "critical": False}], 0, [])
        self.queue.claim()
        self.queue.finish(job, "queued", "preview", {"head": "reviewed"})
        self.assertEqual(self.queue.claim()["phase"], "preview")
        self.queue.recover()
        self.assertTrue(self.queue.paused())
        self.assertEqual(self.queue.job(job)["status"], "blocked")
        with self.assertRaises(QueueError):
            self.queue.retry_job(self.alpha, job)


class RemoteContracts(unittest.TestCase):
    def test_codex_refuses_before_login_or_execution_without_consent(self):
        with patch.dict("os.environ", {}, clear=True), patch("orchestrator.codex.run") as run:
            with self.assertRaisesRegex(Critical, "explicit owner authorization"):
                codex.check(Path("/tmp"))
            run.assert_not_called()

    def test_responses_authorization_and_token_ceiling(self):
        project = SimpleNamespace(executor="responses", timeout=5, budget={
            "model": "configured-model", "max_input_tokens": 100, "max_output_tokens": 50,
            "input_microdollars_per_million": 1_000_000, "output_microdollars_per_million": 2_000_000,
        })
        with patch.dict("os.environ", {}, clear=True), patch("orchestrator.executors.exchange") as api:
            with self.assertRaises(Critical):
                execute(project, {}, "wordpress", {}, Mock(), 0)
            api.assert_not_called()
        with patch.dict("os.environ", {"OPENAI_API_KEY": "dummy", "FACTORY_AUTHORIZE_PAID_AI": "1"}), patch(
            "orchestrator.executors.exchange", return_value={"input_tokens": 101}
        ) as api:
            reserve = Mock()
            with self.assertRaisesRegex(QueueError, "input token limit"):
                execute(project, {}, "wordpress", {}, reserve, 0)
            reserve.assert_called_once_with(200)
            self.assertEqual(api.call_count, 1)

    def test_model_preflight_distinguishes_transport_and_auth_failures(self):
        with patch("orchestrator.executors.subprocess.run") as curl:
            curl.return_value = SimpleNamespace(returncode=6, stdout=b"")
            with self.assertRaisesRegex(Retryable, "transport failed"):
                model_access("dummy", "sample-model", 5)
            curl.return_value = SimpleNamespace(returncode=0, stdout=b"private detail\n401")
            with self.assertRaisesRegex(Critical, r"permissions \(HTTP 401\)$"):
                model_access("dummy", "sample-model", 5)
            curl.return_value = SimpleNamespace(returncode=0, stdout=b'{"id":"sample-model"}\n200')
            model_access("dummy", "sample-model", 5)
            self.assertNotIn("dummy", curl.call_args.args[0])
            self.assertNotIn("--data-binary", curl.call_args.args[0])

    def test_responses_records_confirmed_token_usage(self):
        project = SimpleNamespace(executor="responses", timeout=5, budget={
            "model": "configured-model", "max_input_tokens": 100, "max_output_tokens": 50,
            "input_microdollars_per_million": 1_000_000, "output_microdollars_per_million": 2_000_000,
        })
        usage = {"input_tokens": 80, "output_tokens": 30}
        response = {"usage": usage, "status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": '{"summary":"Fixture"}'}]},
        ]}
        with patch.dict("os.environ", {"OPENAI_API_KEY": "dummy", "FACTORY_AUTHORIZE_PAID_AI": "1"}), patch(
            "orchestrator.executors.exchange", side_effect=[{"input_tokens": 80}, response]
        ) as api:
            record = Mock()
            self.assertEqual(execute(project, {}, "architect", {}, Mock(), 0, record_usage=record),
                             {"summary": "Fixture"})
            record.assert_called_once_with(usage, 140)
            self.assertEqual(api.call_args_list[0].args[0], "/input_tokens")
            self.assertIs(api.call_args_list[1].args[2]["store"], False)

    def test_checks_keep_pending_and_failed_distinct(self):
        project = SimpleNamespace(slug="sample/repo", github={"required_checks": ["one", "two"]})
        adapter = Integrations(project, Path("/test"), {"id": "a" * 32}, 0)
        adapter.gh = Mock(return_value=json.dumps({
            "total_count": 2, "check_runs": [
                {"name": "one", "status": "completed", "conclusion": "failure"},
                {"name": "two", "status": "in_progress", "conclusion": None},
            ],
        }))
        self.assertEqual(adapter.checks("a" * 40), (True, {"one": "failure"}))
        self.assertIn(f"/commits/{'a' * 40}/check-runs", adapter.gh.call_args.args[1])

    def test_merge_stops_before_write_without_enforced_protection(self):
        project = SimpleNamespace(slug="sample/repo", base="main", github={"required_checks": ["one"]})
        adapter = Integrations(project, Path("/test"), {"id": "a" * 32}, 0)
        adapter.gh = Mock(side_effect=['{"protected": true}', '{"enforce_admins":{"enabled":false}}'])
        with self.assertRaisesRegex(Critical, "enforced strict checks"):
            adapter.merge({}, {})
        self.assertEqual(adapter.gh.call_count, 2)

    def test_merge_uses_the_reviewed_head_after_rechecking_ci(self):
        head = "b" * 40
        project = SimpleNamespace(slug="sample/repo", base="main", github={
            "required_checks": ["one"], "reviewer": "reviewer",
        })
        adapter = Integrations(project, Path("/test"), {"id": "a" * 32}, 0)
        adapter.gh = Mock(side_effect=map(json.dumps, [
            {"protected": True},
            {"enforce_admins": {"enabled": True},
             "required_status_checks": {"strict": True, "contexts": ["one"]},
             "required_pull_request_reviews": {"dismiss_stale_reviews": True,
                                               "require_last_push_approval": True,
                                               "required_approving_review_count": 1}},
            {"login": "dispatcher"},
            [{"user": {"login": "reviewer"}, "state": "APPROVED", "commit_id": head}],
            {"merged": True},
        ]))
        adapter.checks = Mock(return_value=(False, {}))
        adapter.pull_status = Mock(return_value={"mergeStateStatus": "CLEAN"})
        result = {"head": head}
        self.assertTrue(adapter.merge({"number": 3, "author": {"login": "author"}}, result))
        adapter.checks.assert_called_once_with(head)
        self.assertEqual(adapter.gh.call_args.args, (
            "api", "--method", "PUT", "repos/sample/repo/pulls/3/merge",
            "-f", f"sha={head}", "-f", "merge_method=squash",
        ))

    def test_file_proposal_cannot_escape_the_allowlist(self):
        project = SimpleNamespace(editable={"fixture.js"})
        adapter = Integrations(project, Path("/test"), {"id": "a" * 32}, 0)
        with self.assertRaisesRegex(Critical, "unauthorized"):
            adapter.apply([{"path": "../../fixture.js", "content": "ignored"}], "base")

    def test_factory_backup_uses_the_emitted_identifier(self):
        with tempfile.TemporaryDirectory() as state:
            project = SimpleNamespace(profile="fixture.json", factory_source="/fixture")
            job = {"id": "a" * 32, "spec": {"operation": "backup", "critical": True, "ref": None, "backup": None}}
            adapter = Integrations(project, Path(state), job, 0)
            adapter.command = Mock(return_value=SimpleNamespace(
                returncode=0, stdout="Backup verified: 20261124T045249Z-f828c3506cc5\n"
            ))
            self.assertEqual(adapter.factory(), {"backup": "20261124T045249Z-f828c3506cc5"})
