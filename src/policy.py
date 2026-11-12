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

from .vault import (VaultState, ZERO_ADDRESS, format_amount,
                    is_valid_address, unit_label)


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
    """Mirror agentSpend's require() chain, collecting every failure.

    Two floor guards beyond the require() chain: the proposal's token
    must be the token the state was read for (a verdict computed from
    another token's policy would be fiction), and the recipient must
    be a well-formed address (the allowlist flag is caller-supplied
    and must never let a malformed address pass on its own).
    """
    reasons: list[str] = []
    p = state.policy
    unit = unit_label(state.token)
    fmt = lambda amount: format_amount(amount, state.token)  # noqa: E731

    if str(proposal.token).lower() != str(state.token).lower():
        reasons.append(
            f"Proposal token {proposal.token} does not match the token "
            f"this vault state was read for ({state.token}) — refusing "
            "to judge one token's payment against another token's policy.")
    if state.frozen:
        reasons.append("Vault is FROZEN by the owner — agent spending is halted.")
    if proposal.amount <= 0:
        reasons.append("Amount must be greater than zero.")
    if not is_valid_address(proposal.to):
        reasons.append(
            f"Recipient {proposal.to!r} is not a valid address "
            "(expected 0x followed by 40 hex characters).")
    elif proposal.to.lower() == ZERO_ADDRESS:
        reasons.append("Recipient is the zero address.")
    elif not recipient_allowed:
        reasons.append(f"Recipient {proposal.to} is NOT on the vault allowlist.")
    if not p.configured:
        reasons.append("Token has no policy configured — the vault treats "
                       "it as not allowed.")
    else:
        if proposal.amount > p.per_tx_cap:
            reasons.append(
                f"Amount {fmt(proposal.amount)} {unit} exceeds the "
                f"per-transaction cap of {fmt(p.per_tx_cap)} {unit}.")
        if p.spent_today + proposal.amount > p.daily_cap:
            reasons.append(
                f"Daily cap exceeded: {fmt(p.spent_today)} {unit} "
                f"already spent today + {fmt(proposal.amount)} {unit} "
                f"proposed > daily cap {fmt(p.daily_cap)} {unit}.")
    if proposal.amount > state.balance:
        reasons.append(
            f"Amount exceeds the vault balance "
            f"({fmt(state.balance)} {unit} available).")

    facts = {
        "per_tx_cap_eth": fmt(p.per_tx_cap),
        "daily_cap_eth": fmt(p.daily_cap),
        "spent_today_eth": fmt(p.spent_today),
        "daily_headroom_eth": fmt(max(p.daily_cap - p.spent_today, 0)),
        "balance_eth": fmt(state.balance),
        "amount_unit": unit,
        "frozen": state.frozen,
        "recipient_allowed": recipient_allowed,
        "policy_configured": p.configured,
    }
    return PolicyVerdict(
        verdict="PASS" if not reasons else "REJECT",
        reasons=reasons or ["All on-chain policy checks pass."],
        facts=facts,
    )
