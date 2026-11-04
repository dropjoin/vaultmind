"""Deterministic mirror of AgentVault's on-chain policy.

The contract is the source of truth; this module reproduces its checks
(from src/AgentVault.sol `agentSpend`) so the copilot can explain a
verdict *before* anything is signed, and so the checker role's PASS can
never paper over a rule the chain would enforce anyway:

    require(!frozen)                       -> vault not frozen
    require(amount > 0)                    -> amount positive
    require(to != address(0))              -> recipient non-zero
    require(allowedRecipient[to])          -> recipient allowlisted
    require(policy.configured)             -> token has a policy
    require(amount <= perTxCap)            -> per-transaction cap
    require(spentToday + amount <= dailyCap) -> daily cap

plus one check the contract leaves to the transfer itself:
    amount <= vault balance                -> funds actually present
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .vault import VaultState, ZERO_ADDRESS, wei_to_eth_str


@dataclass
class Proposal:
    to: str
    amount: int  # wei / token base units
    token: str = ZERO_ADDRESS
    memo: str = ""  # untrusted free text from the requester (guardrail input)


@dataclass
class PolicyVerdict:
    verdict: str  # "PASS" or "REJECT"
    reasons: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict == "PASS"


def evaluate(state: VaultState, proposal: Proposal,
             recipient_allowed: bool) -> PolicyVerdict:
    """Mirror agentSpend's require() chain, collecting every failure."""
    reasons: list[str] = []
    p = state.policy

    if state.frozen:
        reasons.append("Vault is FROZEN by the owner — agent spending is halted.")
    if proposal.amount <= 0:
        reasons.append("Amount must be greater than zero.")
    if proposal.to.lower() == ZERO_ADDRESS:
        reasons.append("Recipient is the zero address.")
    elif not recipient_allowed:
        reasons.append(f"Recipient {proposal.to} is NOT on the vault allowlist.")
    if not p.configured:
        reasons.append("Token has no policy configured — the vault treats "
                       "it as not allowed.")
    else:
        if proposal.amount > p.per_tx_cap:
            reasons.append(
                f"Amount {wei_to_eth_str(proposal.amount)} ETH exceeds the "
                f"per-transaction cap of {wei_to_eth_str(p.per_tx_cap)} ETH.")
        if p.spent_today + proposal.amount > p.daily_cap:
            reasons.append(
                f"Daily cap exceeded: {wei_to_eth_str(p.spent_today)} ETH "
                f"already spent today + {wei_to_eth_str(proposal.amount)} ETH "
                f"proposed > daily cap {wei_to_eth_str(p.daily_cap)} ETH.")
    if proposal.amount > state.balance:
        reasons.append(
            f"Amount exceeds the vault balance "
            f"({wei_to_eth_str(state.balance)} ETH available).")

    facts = {
        "per_tx_cap_eth": wei_to_eth_str(p.per_tx_cap),
        "daily_cap_eth": wei_to_eth_str(p.daily_cap),
        "spent_today_eth": wei_to_eth_str(p.spent_today),
        "daily_headroom_eth": wei_to_eth_str(max(p.daily_cap - p.spent_today, 0)),
        "balance_eth": wei_to_eth_str(state.balance),
        "frozen": state.frozen,
        "recipient_allowed": recipient_allowed,
        "policy_configured": p.configured,
    }
    return PolicyVerdict(
        verdict="PASS" if not reasons else "REJECT",
        reasons=reasons or ["All on-chain policy checks pass."],
        facts=facts,
    )
