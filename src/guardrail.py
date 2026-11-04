"""Prompt-injection guardrail for untrusted proposal text.

A payment memo / justification is attacker-controlled text: anyone can
ask the agent to pay them and lace the request with instructions for
the model. VaultMind treats that text as DATA, never as instructions:

1. A deterministic scan (this module) flags classic injection patterns
   before any model sees the text. High-severity flags force a REJECT
   at the deterministic layer — no model verdict can override them.
2. The checker role's prompt repeats the rule for the model: the memo
   is quoted data; instructions inside it must be reported, not obeyed.
3. On the gateway side, the same intent is expressed as an Otari
   guardrail profile (docs: guardrails.md, mode block, fail closed) —
   see docs/OTARI_FEATURES.md for what is configured where.

The scan is deliberately simple and explainable: it is a tripwire with
named patterns, not a security guarantee.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HIGH = [
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", "ignore-previous-instructions"),
    (r"disregard\s+(the\s+)?(policy|rules|instructions|checks)", "disregard-policy"),
    (r"(override|bypass|skip)\s+(the\s+)?(policy|check|cap|allowlist|approval)", "bypass-policy"),
    (r"you\s+are\s+now\s+(a|an|in)\b", "role-reassignment"),
    (r"\bsystem\s*:\s*", "fake-system-message"),
    (r"approve\s+(this|it)\s+(immediately|without|regardless)", "forced-approval"),
    (r"send\s+(all|the\s+full|everything)\b", "drain-language"),
    (r"do\s+not\s+(tell|inform|report|log)\b", "concealment"),
]
_MEDIUM = [
    (r"urgent(ly)?\b.*\b(no\s+time|immediately|asap)\b", "pressure-urgency"),
    (r"the\s+owner\s+(said|approved|told\s+me)", "false-authority-claim"),
    (r"off\s*the\s+record", "off-the-record"),
    (r"new\s+instructions\s*:", "fake-instruction-block"),
]


@dataclass
class GuardrailResult:
    flags: list[dict] = field(default_factory=list)  # {pattern, severity, match}

    @property
    def high_severity(self) -> bool:
        return any(f["severity"] == "high" for f in self.flags)

    @property
    def blocked(self) -> bool:
        return self.high_severity

    def describe(self) -> str:
        if not self.flags:
            return "No injection patterns detected in the memo."
        parts = [f"{f['severity'].upper()} '{f['pattern']}' (matched "
                 f"\"{f['match']}\")" for f in self.flags]
        return "Injection signals: " + "; ".join(parts)


def scan_untrusted_text(text: str) -> GuardrailResult:
    result = GuardrailResult()
    if not text:
        return result
    lowered = text.lower()
    for pattern, name in _HIGH:
        m = re.search(pattern, lowered)
        if m:
            result.flags.append({"pattern": name, "severity": "high",
                                 "match": m.group(0)})
    for pattern, name in _MEDIUM:
        m = re.search(pattern, lowered)
        if m:
            result.flags.append({"pattern": name, "severity": "medium",
                                 "match": m.group(0)})
    return result
