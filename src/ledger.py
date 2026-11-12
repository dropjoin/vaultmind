"""Usage ledger — every Otari call VaultMind makes, one JSON object per line.

Fields per entry: ts, role, virtual_key, model_requested, model_used,
status (ok | error | blocked), prompt_tokens, completion_tokens,
total_tokens, est_cost_usd, note.

The ledger is the local source of truth for per-role budget tracking
(the thrifty downgrade reads it) and for the demo's "what did the
copilot's brain cost?" report. Costs are estimates from the public
list prices in config/otari-routing.yml — the Otari dashboard / /v1/usage
is the billing source of truth.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfg


def _num(value: object, default: float = 0.0) -> float:
    """Best-effort number for a ledger/config field; garbage reads as default."""
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def estimate_cost_usd(model: str, usage: dict, routing: dict) -> float:
    prices = routing.get("prices_usd_per_1m_tokens", {})
    if not isinstance(prices, dict):
        prices = {}
    price = prices.get(model) or prices.get("default",
                                            {"input": 1.0, "output": 3.0})
    if not isinstance(price, dict):
        price = {"input": 1.0, "output": 3.0}
    return (_num(usage.get("prompt_tokens")) / 1_000_000
            * _num(price.get("input"), 1.0)
            + _num(usage.get("completion_tokens")) / 1_000_000
            * _num(price.get("output"), 3.0))


class UsageLedger:
    def __init__(self, path: Path | None = None):
        self.path = path or cfg.LEDGER_PATH

    def append(self, *, role: str, virtual_key: str, model_requested: str,
               model_used: str, status: str, usage: dict | None,
               est_cost_usd: float, note: str = "") -> dict:
        usage = usage or {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0}
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "role": role,
            "virtual_key": virtual_key,
            "model_requested": model_requested,
            "model_used": model_used,
            "status": status,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "est_cost_usd": round(est_cost_usd, 8),
            "note": note,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return entry

    def entries(self) -> list[dict]:
        """All parseable entries; corrupt lines are skipped, not fatal.

        The ledger is append-only local data: a partial write from a
        killed run (or a hand edit) used to make every read — budget
        mirror, thrifty downgrade, `usage` — crash on one bad line.
        Skipping the line keeps the budget mirror running on the
        entries that did parse; the gateway's own budgets remain the
        hard enforcement, so a skipped line can only undercount the
        local estimate, never overspend past the gateway.
        """
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("role"):
                out.append(entry)
        return out

    def role_spend_usd(self, role: str) -> float:
        return sum(_num(e.get("est_cost_usd")) for e in self.entries()
                   if e.get("role") == role and e.get("status") == "ok")

    def summary(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for e in self.entries():
            bucket = out.setdefault(e["role"], {
                "calls": 0, "errors": 0, "total_tokens": 0,
                "est_cost_usd": 0.0})
            bucket["calls"] += 1
            if e.get("status") != "ok":
                bucket["errors"] += 1
            bucket["total_tokens"] += int(_num(e.get("total_tokens")))
            bucket["est_cost_usd"] = round(
                bucket["est_cost_usd"] + _num(e.get("est_cost_usd")), 8)
        return out
