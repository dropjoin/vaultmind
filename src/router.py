"""Budget-conditional routing + failover on top of the Otari client.

Mirrors the two routing behaviors the Otari docs describe for gateway
policies (routing.md), implemented client-side so they are exercisable
and logged even before the same policy is configured in the workspace:

- "Thrifty" selection: once a role's recorded spend reaches
  thrifty_threshold_pct (80%) of its budget, calls route to the role's
  cheap model instead of its primary.
- Failover: if the selected model errors (gateway refusal, outage,
  rate limit, empty choices), the role's fallback model is tried once.
  Every attempt — success or failure — is written to the usage ledger.

Local budget block: at >= 100% of budget the call is refused locally
with the same semantics the gateway applies before dispatch
(403 budget_exceeded, docs: budgets.md). The gateway's own per-key
budgets remain the hard enforcement; this mirror exists so the CLI can
explain the refusal instead of just receiving it.
"""
from __future__ import annotations

from dataclasses import dataclass

from .ledger import UsageLedger, estimate_cost_usd
from .otari_client import OtariClient, OtariError


@dataclass
class RoutedResult:
    content: str
    role: str
    model_used: str
    model_selected: str
    downgraded: bool
    failed_over: bool
    budget_used_pct: float
    usage: dict
    est_cost_usd: float


class BudgetExceeded(OtariError):
    """Local mirror of the gateway's budget_exceeded refusal."""


def select_model(role_cfg: dict, spend_usd: float,
                 threshold_pct: float) -> tuple[str, float, bool]:
    """Return (model, budget_used_pct, downgraded) for the next call."""
    budget = float(role_cfg["budget_usd"])
    pct = (spend_usd / budget * 100.0) if budget > 0 else 100.0
    models = role_cfg["models"]
    if pct >= threshold_pct and models["cheap"] != models["primary"]:
        return models["cheap"], pct, True
    return models["primary"], pct, False


class RoutedCaller:
    def __init__(self, routing: dict, ledger: UsageLedger):
        self.routing = routing
        self.ledger = ledger
        self.threshold = float(routing.get("thrifty_threshold_pct", 80))

    def call(self, role: str, messages: list[dict],
             temperature: float = 0.2) -> RoutedResult:
        role_cfg = self.routing["roles"][role]
        spend = self.ledger.role_spend_usd(role)
        model, pct, downgraded = select_model(role_cfg, spend, self.threshold)
        budget = float(role_cfg["budget_usd"])
        if pct >= 100.0:
            self.ledger.append(
                role=role, virtual_key=role_cfg["virtual_key"],
                model_requested=model, model_used="",
                status="blocked", usage=None, est_cost_usd=0.0,
                note=f"local budget mirror: role spend ${spend:.4f} >= "
                     f"budget ${budget:.2f} (gateway would refuse with "
                     "budget_exceeded)")
            raise BudgetExceeded(
                f"Role '{role}' has used ${spend:.4f} of its ${budget:.2f} "
                "budget (100%). Refusing locally, mirroring the gateway's "
                "pre-dispatch budget check.")

        client = OtariClient(role, role_cfg)
        attempts: list[tuple[str, OtariError | None, dict | None]] = []
        candidates = [model]
        fallback = role_cfg["models"]["fallback"]
        if fallback != model:
            candidates.append(fallback)

        last_error: OtariError | None = None
        for idx, candidate in enumerate(candidates):
            try:
                result = client.chat(candidate, messages,
                                     temperature=temperature)
            except OtariError as exc:
                last_error = exc
                self.ledger.append(
                    role=role, virtual_key=role_cfg["virtual_key"],
                    model_requested=candidate, model_used="",
                    status="error", usage=None, est_cost_usd=0.0,
                    note=f"attempt {idx + 1} failed: {exc}"[:300])
                continue
            cost = estimate_cost_usd(result["model"], result["usage"],
                                     self.routing)
            self.ledger.append(
                role=role, virtual_key=role_cfg["virtual_key"],
                model_requested=candidate, model_used=result["model"],
                status="ok", usage=result["usage"], est_cost_usd=cost,
                note=("thrifty downgrade" if downgraded and idx == 0 else
                      "failover" if idx > 0 else ""))
            return RoutedResult(
                content=result["content"], role=role,
                model_used=result["model"], model_selected=model,
                downgraded=downgraded, failed_over=idx > 0,
                budget_used_pct=pct, usage=result["usage"],
                est_cost_usd=cost)
        raise last_error or OtariError(f"All models failed for role {role}")
