"""Fixture tests for the deterministic policy mirror.

The fixtures reproduce the live vault's shape (caps 0.01 / 0.025 ETH,
balance 0.04 ETH, one allowlisted service) and the demo's canonical
cases from the AgentVault README: an in-policy payment passes, an
over-cap payment is rejected.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.policy import Proposal, evaluate  # noqa: E402
from src.vault import Policy, VaultState, ZERO_ADDRESS  # noqa: E402

ETH = 10**18
SERVICE = "0xF04D8eA360eF3097E632a67F4b9a9B11523b3Dc1"
STRANGER = "0x00000000000000000000000000000000DeAdBeef"


def make_state(**overrides) -> VaultState:
    state = VaultState(
        address="0x0344c57616d0ff50608D85B1852C5e3E3C87d1C3",
        owner="0x552859077C21d905708f3B0644514E6b12C21032",
        agent="0x282D13E8351587694dc99B568eAf0d8E9810fB6b",
        frozen=False,
        token=ZERO_ADDRESS,
        policy=Policy(per_tx_cap=ETH // 100, daily_cap=25 * ETH // 1000,
                      spent_today=0, configured=True),
        balance=4 * ETH // 100,
    )
    for key, value in overrides.items():
        if key in ("per_tx_cap", "daily_cap", "spent_today", "configured"):
            setattr(state.policy, key, value)
        else:
            setattr(state, key, value)
    return state


class TestPolicyMirror(unittest.TestCase):
    def test_valid_proposal_passes(self):
        v = evaluate(make_state(), Proposal(SERVICE, ETH // 100), True)
        self.assertEqual(v.verdict, "PASS")

    def test_over_per_tx_cap_rejected(self):
        v = evaluate(make_state(), Proposal(SERVICE, ETH // 2), True)
        self.assertEqual(v.verdict, "REJECT")
        self.assertTrue(any("per-transaction cap" in r for r in v.reasons))

    def test_exactly_at_cap_passes(self):
        # Contract: amount <= perTxCap is allowed.
        v = evaluate(make_state(), Proposal(SERVICE, ETH // 100), True)
        self.assertEqual(v.verdict, "PASS")

    def test_daily_cap_rejected(self):
        state = make_state(spent_today=2 * ETH // 100)
        v = evaluate(state, Proposal(SERVICE, ETH // 100), True)
        self.assertEqual(v.verdict, "REJECT")
        self.assertTrue(any("Daily cap" in r for r in v.reasons))

    def test_daily_cap_exact_boundary_passes(self):
        state = make_state(spent_today=15 * ETH // 1000)
        v = evaluate(state, Proposal(SERVICE, ETH // 100), True)
        self.assertEqual(v.verdict, "PASS")

    def test_non_allowlisted_recipient_rejected(self):
        v = evaluate(make_state(), Proposal(STRANGER, ETH // 1000), False)
        self.assertEqual(v.verdict, "REJECT")
        self.assertTrue(any("allowlist" in r for r in v.reasons))

    def test_frozen_vault_rejected(self):
        v = evaluate(make_state(frozen=True),
                     Proposal(SERVICE, ETH // 1000), True)
        self.assertEqual(v.verdict, "REJECT")
        self.assertTrue(any("FROZEN" in r for r in v.reasons))

    def test_unconfigured_token_rejected(self):
        v = evaluate(make_state(configured=False),
                     Proposal(SERVICE, ETH // 1000), True)
        self.assertEqual(v.verdict, "REJECT")
        self.assertTrue(any("no policy" in r for r in v.reasons))

    def test_amount_above_balance_rejected(self):
        v = evaluate(make_state(balance=5 * ETH // 1000),
                     Proposal(SERVICE, 8 * ETH // 1000), True)
        self.assertEqual(v.verdict, "REJECT")
        self.assertTrue(any("balance" in r for r in v.reasons))

    def test_zero_amount_rejected(self):
        v = evaluate(make_state(), Proposal(SERVICE, 0), True)
        self.assertEqual(v.verdict, "REJECT")

    def test_zero_address_recipient_rejected(self):
        v = evaluate(make_state(), Proposal(ZERO_ADDRESS, ETH // 1000), True)
        self.assertEqual(v.verdict, "REJECT")


if __name__ == "__main__":
    unittest.main()
