#!/usr/bin/env python3
"""VaultMind CLI — a policy copilot for AgentVault, powered by Otari.

Commands:
  state    Read the live AgentVault state from Arbitrum Sepolia.
  propose  Evaluate a proposed payment: proposer drafts (Otari),
           checker decides (deterministic floor + Otari checker),
           reporter writes the decision card (Otari, template fallback).
  usage    Per-role Otari usage + budget report from the local ledger.

Without an Otari key the on-chain reads and the deterministic policy
mirror still run; the model roles are marked SKIPPED, never faked.

Exit codes: 0 = ok / PASS · 3 = proposal REJECTED · 1 = runtime error.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import config as cfg  # noqa: E402
from src.guardrail import scan_untrusted_text  # noqa: E402
from src.ledger import UsageLedger  # noqa: E402
from src.otari_client import OtariError, OtariNotConfigured  # noqa: E402
from src.policy import Proposal, evaluate  # noqa: E402
from src.roles import (draft_justification, render_card_local,  # noqa: E402
                       run_checker, write_card)
from src.router import RoutedCaller  # noqa: E402
from src.vault import VaultReader, ZERO_ADDRESS, wei_to_eth_str  # noqa: E402


def _parse_amount(args) -> int:
    if args.amount_wei is not None:
        return int(args.amount_wei)
    try:
        wei = Decimal(args.amount) * Decimal(10**18)
    except (InvalidOperation, TypeError):
        raise SystemExit(f"Invalid --amount value: {args.amount!r}")
    if wei != wei.to_integral_value():
        raise SystemExit("--amount has more precision than wei (18 decimals).")
    return int(wei)


def cmd_state(args) -> int:
    reader = VaultReader()
    token = args.token or ZERO_ADDRESS
    st = reader.read_state(token)
    print(f"AgentVault {st.address} — Arbitrum Sepolia")
    print(f"  owner          : {st.owner}")
    print(f"  agent (hot key): {st.agent}")
    print(f"  frozen         : {st.frozen}")
    print(f"  token          : {'native ETH' if token == ZERO_ADDRESS else token}")
    p = st.policy
    print(f"  policy         : configured={p.configured} · per-tx cap "
          f"{wei_to_eth_str(p.per_tx_cap)} ETH · daily cap "
          f"{wei_to_eth_str(p.daily_cap)} ETH · spent today "
          f"{wei_to_eth_str(p.spent_today)} ETH")
    print(f"  balance        : {wei_to_eth_str(st.balance)} ETH")
    for who in args.check_recipient or []:
        print(f"  allowlist[{who}] : {reader.allowed_recipient(who)}")
    return 0


def cmd_usage(_args) -> int:
    routing = cfg.load_routing_config()
    ledger = UsageLedger()
    summary = ledger.summary()
    if not summary:
        print("No Otari calls recorded yet (data/usage-ledger.jsonl is empty).")
        return 0
    for role, s in sorted(summary.items()):
        budget = float(routing["roles"][role]["budget_usd"])
        pct = s["est_cost_usd"] / budget * 100 if budget else 0.0
        print(f"{role:9s} calls={s['calls']} errors={s['errors']} "
              f"tokens={s['total_tokens']} est=${s['est_cost_usd']:.4f} "
              f"of ${budget:.2f} budget ({pct:.1f}%)")
    return 0


def cmd_propose(args) -> int:
    routing = cfg.load_routing_config()
    ledger = UsageLedger()
    token = args.token or ZERO_ADDRESS
    amount = _parse_amount(args)

    reader = VaultReader()
    st = reader.read_state(token)
    allowed = reader.allowed_recipient(args.to)
    proposal = Proposal(to=args.to, amount=amount, token=token,
                        memo=args.memo or "")
    det = evaluate(st, proposal, allowed)
    guard = scan_untrusted_text(proposal.memo)

    caller = RoutedCaller(routing, ledger)
    llm_available = True
    proposer_text = None
    try:
        proposer_text = draft_justification(caller, proposal, st, det)
    except OtariNotConfigured as exc:
        llm_available = False
        print(f"[proposer SKIPPED] {exc}")
    except OtariError as exc:
        print(f"[proposer FAILED] {exc}")

    if llm_available:
        try:
            outcome = run_checker(caller, proposal, st, det, guard,
                                  proposer_text)
        except OtariError as exc:
            print(f"[checker LLM FAILED] {exc} — falling back to the "
                  "deterministic mirror.")
            outcome = run_checker(None, proposal, st, det, guard,
                                  proposer_text)
    else:
        outcome = run_checker(None, proposal, st, det, guard, proposer_text)

    record = {
        "final_verdict": outcome.final_verdict,
        "to": proposal.to,
        "amount_eth": wei_to_eth_str(proposal.amount),
        "amount_wei": proposal.amount,
        "memo": proposal.memo,
        "facts": det.facts,
        "reasons": outcome.reasons,
        "guardrail": guard.describe(),
        "checker_source": outcome.source,
        "proposer_justification": proposer_text,
    }

    card = None
    if llm_available:
        try:
            card = write_card(caller, record)
        except OtariError as exc:
            print(f"[reporter FAILED] {exc} — using the template card.")
    if card is None:
        card = render_card_local(record)
    print(card)

    summary = ledger.summary()
    if summary:
        spent = "; ".join(
            f"{r}: ${s['est_cost_usd']:.4f}/{routing['roles'][r]['budget_usd']:.2f}"
            for r, s in sorted(summary.items()))
        print(f"[otari usage] {spent} (local estimates, see `usage`)")
    return 0 if outcome.final_verdict == "PASS" else 3


def main() -> int:
    cfg.load_env()
    parser = argparse.ArgumentParser(prog="vaultmind", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_state = sub.add_parser("state", help="read live vault state")
    p_state.add_argument("--token", help="token address (default: native ETH)")
    p_state.add_argument("--check-recipient", action="append",
                         help="also report allowlist status for an address")
    p_state.set_defaults(fn=cmd_state)

    p_prop = sub.add_parser("propose", help="evaluate a proposed payment")
    p_prop.add_argument("--to", required=True, help="recipient address")
    group = p_prop.add_mutually_exclusive_group(required=True)
    group.add_argument("--amount", help="amount in ETH, e.g. 0.01 (native token)")
    group.add_argument("--amount-wei", type=int, help="amount in wei/base units")
    p_prop.add_argument("--token", help="token address (default: native ETH)")
    p_prop.add_argument("--memo", default="",
                        help="requester memo (untrusted, guardrail-scanned)")
    p_prop.set_defaults(fn=cmd_propose)

    p_use = sub.add_parser("usage", help="per-role Otari usage report")
    p_use.set_defaults(fn=cmd_usage)

    args = parser.parse_args()
    try:
        return args.fn(args)
    except SystemExit:
        raise
    except Exception as exc:  # CLI surface: one clean line, no traceback
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
