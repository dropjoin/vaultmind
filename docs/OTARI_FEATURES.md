# Otari features used by VaultMind

Submission item 4 ("Otari features used") — each feature named the way
the Otari docs name it, where it lives in VaultMind, and its status.
Honesty rule: "implemented" means code in this repo exercises it;
"workspace configuration" means the feature is set up in the hosted
Otari workspace/dashboard and this repo carries the matching config —
the two are never blurred.

| Otari feature (docs wording) | Where in VaultMind | Status |
|---|---|---|
| Chat Completions via the hosted gateway (`https://api.otari.ai/api/v1`) | `src/otari_client.py` — all three roles call only this client | Implemented; exercised live 2026-11-04 with the real workspace key: auth + `/models` OK, generation refused 402 `insufficient_funds` (workspace balance $0.00 — the $20 starter credit never landed). Raw outputs in `docs/evidence/` |
| Virtual keys — one scoped, revocable key per role (`vm-proposer`, `vm-checker`, `vm-reporter`) | `config/otari-routing.yml` (`virtual_key`, `key_env` per role); `src/config.py` resolves `OTARI_KEY_<ROLE>` → falls back to shared `OTARI_API_KEY` | Implemented client-side. Creating the keys is the ONE manual dashboard step left (see below): the keys API requires a master key on the hosted deployment (verified: 401 "Invalid master key" with a workspace key) and API-minted secrets are shown once, so they cannot be stored in this project's credential flow |
| Budgets — per-key budgets, enforced before dispatch (`budget_exceeded` refusal) | Role budgets in `config/otari-routing.yml`; local mirror in `src/router.py` (blocks at 100% and explains the refusal); spend tracked in `src/ledger.py` | Local mirror implemented + tested; gateway-side per-key budgets are set in the same dashboard step as the keys (Limit (USD) field on each key) |
| Routing policy — budget-conditional selection ("thrifty": `budget_used_pct >= 80` → cheaper model) | `src/router.py` `select_model` + the same intent written in official policy shape under `gateway_policy:` in the routing config | Implemented client-side + unit-tested; gateway policy YAML included for workspace setup |
| Routing policy — failover (`on_failure`) | `src/router.py` `RoutedCaller.call` tries the role's fallback model once; both attempts ledgered | Implemented; exercised live twice: 2026-11-04 with a fake key (401 on primary → fallback attempted → both recorded) and with the real key (402 on primary → fallback attempted → both recorded, `docs/evidence/usage-ledger-live.jsonl`) |
| Prompt-injection guardrails | Deterministic tripwire in `src/guardrail.py` + checker-role prompt contract in `src/roles.py` | Implemented locally. The gateway's own guardrail profile (`guardrails.md`, mode block / fail closed) is workspace configuration — not yet enabled; see NOTES.md |
| Usage tracking (dashboard + `/v1/usage`) | Local JSONL ledger `data/usage-ledger.jsonl` per role/model/tokens/est. cost; `vaultmind.py usage` report | Implemented locally, exercised live. The gateway's `/api/v1/usage` requires a master key (401 with a workspace key, verified 2026-11-04), so the dashboard usage page is the billing source of truth |
| Built-in tools (`otari_web_search`, `otari_web_fetch`, `otari_code_execution`) | — | NOT used yet. Planned: checker verifies payee context (web search/fetch) and payment arithmetic (code execution) in the next build step |
| MCP server beside built-in tools | — | NOT used yet. Planned: expose vault-state reads as an MCP tool the checker calls through Otari |

## The one manual step: create the three role keys in the dashboard

Everything else in VaultMind runs from the repo. The per-role virtual
keys cannot be created from here: on the hosted deployment the keys
API (`POST /api/v1/organizations/me/keys`) sits behind a master key
(verified 2026-11-04: a workspace API key gets 401 "Invalid master
key" from every management surface), and a freshly minted secret is
shown exactly once, so there is no sanctioned place to park three
API-minted secrets in this project's credential store. Dashboard
steps (from the official api-keys/budgets docs):

1. Otari.ai dashboard → workspace → **API Keys** → **Create key**, once
   per role, with these settings:
   - `vm-proposer` — Advanced → allowed models: `moonshotai/kimi-k2.6`,
     `deepseek/deepseek-v4-flash`, `deepseek/deepseek-v3.2`; Budget →
     Limit (USD) **0.50**, resets Monthly.
   - `vm-checker` — allowed models: `moonshotai/kimi-k2.6`,
     `deepseek/deepseek-v4-flash`, `z-ai/glm-4.7`; Limit (USD) **0.50**.
   - `vm-reporter` — allowed models: `deepseek/deepseek-v4-flash`,
     `openai/gpt-oss-20b`, `moonshotai/kimi-k2.6`; Limit (USD) **0.25**.
2. Store each secret when it is shown (it is shown once), then set
   `OTARI_KEY_PROPOSER` / `OTARI_KEY_CHECKER` / `OTARI_KEY_REPORTER`
   wherever VaultMind runs. Until then every role falls back to the
   shared workspace key, and the split exists client-side (routing
   config, budgets mirror, per-role ledger) exactly as it will
   gateway-side once the keys exist.

## The mirror idea

AgentVault caps what the agent's *wallet* may spend (per-tx cap, daily
cap, allowlist). VaultMind caps what the agent's *brain* may spend the
same way: per-role keys, per-role budgets, a downgrade as the budget
runs down, and a hard stop at the cap. Two layers, one policy idea —
the on-chain layer in Solidity, the model layer in Otari.
