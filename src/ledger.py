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


def estimate_cost_usd(model: str, usage: dict, routing: dict) -> float:
    prices = routing.get("prices_usd_per_1m_tokens", {})
    price = prices.get(model) or prices.get("default",
                                            {"input": 1.0, "output": 3.0})
    return (usage.get("prompt_tokens", 0) / 1_000_000 * price["input"]
            + usage.get("completion_tokens", 0) / 1_000_000 * price["output"])


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
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def role_spend_usd(self, role: str) -> float:
        return sum(e["est_cost_usd"] for e in self.entries()
                   if e["role"] == role and e["status"] == "ok")

    def summary(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for e in self.entries():
            bucket = out.setdefault(e["role"], {
                "calls": 0, "errors": 0, "total_tokens": 0,
                "est_cost_usd": 0.0})
            bucket["calls"] += 1
            if e["status"] != "ok":
                bucket["errors"] += 1
            bucket["total_tokens"] += e["total_tokens"]
            bucket["est_cost_usd"] = round(
                bucket["est_cost_usd"] + e["est_cost_usd"], 8)
        return out
