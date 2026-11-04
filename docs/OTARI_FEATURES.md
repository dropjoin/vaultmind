# Otari features used by VaultMind

Submission item 4 ("Otari features used") — each feature named the way
the Otari docs name it, where it lives in VaultMind, and its status.
Honesty rule: "implemented" means code in this repo exercises it;
"workspace configuration" means the feature is set up in the hosted
Otari workspace/dashboard and this repo carries the matching config —
the two are never blurred.

| Otari feature (docs wording) | Where in VaultMind | Status |
|---|---|---|
| Chat Completions via the hosted gateway (`https://api.otari.ai/api/v1`) | `src/otari_client.py` — all three roles call only this client | Implemented; verified against the live gateway up to its auth boundary (401 with a fake key, 2026-11-04) |
| Virtual keys — one scoped, revocable key per role (`vm-proposer`, `vm-checker`, `vm-reporter`) | `config/otari-routing.yml` (`virtual_key`, `key_env` per role); `src/config.py` resolves `OTARI_KEY_<ROLE>` → falls back to shared `OTARI_API_KEY` | Implemented client-side; keys themselves are created in the dashboard when the account is set up |
| Budgets — per-key budgets, enforced before dispatch (`budget_exceeded` refusal) | Role budgets in `config/otari-routing.yml`; local mirror in `src/router.py` (blocks at 100% and explains the refusal); spend tracked in `src/ledger.py` | Local mirror implemented + tested; gateway-side per-key budgets are workspace configuration |
| Routing policy — budget-conditional selection ("thrifty": `budget_used_pct >= 80` → cheaper model) | `src/router.py` `select_model` + the same intent written in official policy shape under `gateway_policy:` in the routing config | Implemented client-side + unit-tested; gateway policy YAML included for workspace setup |
| Routing policy — failover (`on_failure`) | `src/router.py` `RoutedCaller.call` tries the role's fallback model once; both attempts ledgered | Implemented; exercised live 2026-11-04 (401 on primary → fallback attempted → both recorded) |
| Prompt-injection guardrails | Deterministic tripwire in `src/guardrail.py` + checker-role prompt contract in `src/roles.py` | Implemented locally. The gateway's own guardrail profile (`guardrails.md`, mode block / fail closed) is workspace configuration — not yet enabled; see NOTES.md |
| Usage tracking (dashboard + `/v1/usage`) | Local JSONL ledger `data/usage-ledger.jsonl` per role/model/tokens/est. cost; `vaultmind.py usage` report | Implemented locally; dashboard usage is the billing source of truth and will be screenshotted for the demo |
| Built-in tools (`otari_web_search`, `otari_web_fetch`, `otari_code_execution`) | — | NOT used yet. Planned: checker verifies payee context (web search/fetch) and payment arithmetic (code execution) in the next build step |
| MCP server beside built-in tools | — | NOT used yet. Planned: expose vault-state reads as an MCP tool the checker calls through Otari |

## The mirror idea

AgentVault caps what the agent's *wallet* may spend (per-tx cap, daily
cap, allowlist). VaultMind caps what the agent's *brain* may spend the
same way: per-role keys, per-role budgets, a downgrade as the budget
runs down, and a hard stop at the cap. Two layers, one policy idea —
the on-chain layer in Solidity, the model layer in Otari.
