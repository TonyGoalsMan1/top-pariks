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
from orchestrator.executors import Critical, execute
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


class RemoteContracts(unittest.TestCase):
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
