"""Tests for budget-conditional routing, failover and the ledger.

The Otari client is replaced with a fake — these tests prove the
routing/budget machinery, not the gateway (that is the smoke test's
job, and it needs a real key).
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as cfg  # noqa: E402
from src.ledger import UsageLedger  # noqa: E402
from src.otari_client import OtariError  # noqa: E402
from src.router import BudgetExceeded, RoutedCaller, select_model  # noqa: E402
import src.router as router_mod  # noqa: E402

ROUTING = cfg.load_routing_config()
PROPOSER = ROUTING["roles"]["proposer"]


class FakeClient:
    """Fails for models in fail_for, succeeds otherwise."""

    fail_for: set = set()
    calls: list = []

    def __init__(self, role, role_cfg, **_kw):
        self.role = role

    def chat(self, model, messages, temperature=0.2):
        FakeClient.calls.append(model)
        if model in FakeClient.fail_for:
            raise OtariError(f"fake gateway failure for {model}", status=503)
        return {"content": "ok", "model": model,
                "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                          "total_tokens": 150}}


class TestSelectModel(unittest.TestCase):
    def test_fresh_budget_uses_primary(self):
        model, pct, down = select_model(PROPOSER, 0.0, 80)
        self.assertEqual(model, PROPOSER["models"]["primary"])
        self.assertEqual(pct, 0.0)
        self.assertFalse(down)

    def test_over_threshold_downgrades_to_cheap(self):
        spend = PROPOSER["budget_usd"] * 0.85
        model, pct, down = select_model(PROPOSER, spend, 80)
        self.assertEqual(model, PROPOSER["models"]["cheap"])
        self.assertTrue(down)
        self.assertGreaterEqual(pct, 80)

    def test_exactly_at_threshold_downgrades(self):
        spend = PROPOSER["budget_usd"] * 0.80
        model, _pct, down = select_model(PROPOSER, spend, 80)
        self.assertEqual(model, PROPOSER["models"]["cheap"])
        self.assertTrue(down)


class TestRoutedCaller(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = UsageLedger(Path(self.tmp.name) / "ledger.jsonl")
        self.caller = RoutedCaller(ROUTING, self.ledger)
        FakeClient.calls = []
        FakeClient.fail_for = set()
        self._orig = router_mod.OtariClient
        router_mod.OtariClient = FakeClient

    def tearDown(self):
        router_mod.OtariClient = self._orig
        self.tmp.cleanup()

    def test_primary_success_is_ledgered(self):
        result = self.caller.call("proposer", [{"role": "user",
                                                "content": "hi"}])
        self.assertEqual(result.model_used, PROPOSER["models"]["primary"])
        self.assertFalse(result.failed_over)
        entries = self.ledger.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "ok")
        self.assertEqual(entries[0]["total_tokens"], 150)
        self.assertGreater(entries[0]["est_cost_usd"], 0)

    def test_failover_to_fallback_on_gateway_error(self):
        FakeClient.fail_for = {PROPOSER["models"]["primary"]}
        result = self.caller.call("proposer", [{"role": "user",
                                                "content": "hi"}])
        self.assertTrue(result.failed_over)
        self.assertEqual(result.model_used, PROPOSER["models"]["fallback"])
        statuses = [e["status"] for e in self.ledger.entries()]
        self.assertEqual(statuses, ["error", "ok"])

    def test_thrifty_downgrade_after_budget_spend(self):
        # Seed the ledger so the proposer is at ~90% of budget.
        target = PROPOSER["budget_usd"] * 0.9
        self.ledger.append(role="proposer",
                           virtual_key=PROPOSER["virtual_key"],
                           model_requested="seed", model_used="seed",
                           status="ok",
                           usage={"prompt_tokens": 0,
                                  "completion_tokens": 0, "total_tokens": 0},
                           est_cost_usd=target)
        result = self.caller.call("proposer", [{"role": "user",
                                                "content": "hi"}])
        self.assertEqual(result.model_selected, PROPOSER["models"]["cheap"])
        self.assertTrue(result.downgraded)

    def test_budget_exhausted_blocks_locally(self):
        self.ledger.append(role="proposer",
                           virtual_key=PROPOSER["virtual_key"],
                           model_requested="seed", model_used="seed",
                           status="ok",
                           usage={"prompt_tokens": 0,
                                  "completion_tokens": 0, "total_tokens": 0},
                           est_cost_usd=PROPOSER["budget_usd"])
        with self.assertRaises(BudgetExceeded):
            self.caller.call("proposer", [{"role": "user", "content": "hi"}])
        last = self.ledger.entries()[-1]
        self.assertEqual(last["status"], "blocked")

    def test_role_spend_aggregates_only_that_role(self):
        self.ledger.append(role="checker", virtual_key="vm-checker",
                           model_requested="m", model_used="m", status="ok",
                           usage={"prompt_tokens": 0, "completion_tokens": 0,
                                  "total_tokens": 0}, est_cost_usd=0.05)
        self.assertEqual(self.ledger.role_spend_usd("proposer"), 0.0)
        self.assertAlmostEqual(self.ledger.role_spend_usd("checker"), 0.05)


if __name__ == "__main__":
    unittest.main()
