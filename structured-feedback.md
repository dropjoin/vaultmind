# VaultMind — Structured feedback on building with Otari

**Project:** VaultMind, an AI copilot for AgentVault (a Solidity policy vault on
Arbitrum Sepolia). The copilot reads the vault's live on-chain policy, drafts
and checks proposed agent payments, and explains every decision. Every model
call goes through the hosted Otari gateway, with per-role budgets and
routing enforced client-side; the per-role virtual keys themselves are a
dashboard step (the keys API needs a master key — see section 2.6), and
the funded live run used the shared workspace key while the role split
existed client-side. A `proposer` drafts the justification, a deterministic floor mirrors
the contract's own checks, a `checker` gives the judgment verdict, and a
`reporter` writes the plain-language decision card.

**Builder:** M Aziz Yahya (GitHub `dropjoin`) · Repo:
https://github.com/dropjoin/vaultmind, branch `devs-wilding-otari`

Everything below is from a dated friction log kept while actually building
(`NOTES.md` in the repo). Nothing is reconstructed after the fact.

---

## 1. What went well

- **The gateway corrects you when you get the base URL wrong.** Calling the
  wrong base path returns a JSON 404 that literally says Otari serves its API
  under `/api/v1`. That one message saved real debugging time; more APIs
  should fail this helpfully.
- **The error bodies teach the API.** The unauthenticated response lists the
  accepted auth headers (`Otari-Key`, `Authorization`, `x-api-key`). I learned
  the gateway's flexibility from its errors, which is a sign the errors were
  written by people who have debugged integrations themselves.
- **The `/models` payload carries live per-model pricing.** 159 models were
  listed with plain `vendor/model` IDs and per-model prices in the response
  itself. No doc mentioned this; VaultMind's cost table now comes straight
  from the gateway instead of being hand-maintained.
- **The virtual key model fits how agents should be run.** One scoped,
  revocable key per role, each with its own allowed models and USD limit, is
  exactly the governance shape my on-chain project applies to money. Mapping
  the agent's *brain* onto the same policy shape as its *wallet* was the
  reason this project exists, and Otari is the first gateway I have used where
  that mapping is natural.
- **Once funded, the full flow just worked.** Auth, catalog check, chat
  completions, failover between models: the funded live run completed
  end-to-end with real model verdicts (evidence in `docs/evidence/` in the
  repo), and the whole integration is one OpenAI-compatible client.

## 2. What caused friction

### 2.1 The blog points at `/v1`, the hosted API lives at `/api/v1`

Mozilla's official blog post ("Use the Otari Gateway with OpenCode") points
clients at `https://api.otari.ai/v1`. The current repo quickstart has it right
(`https://api.otari.ai/api/v1`), verified by direct calls on 2026-11-04:
`/api/v1/models` answers 401 (auth), `/v1/...` answers the 404 correction.
Anyone following the blog first hits a wall on their very first call. Filed
upstream: https://github.com/mozilla-ai/otari/issues/2898

### 2.2 Key prefix differs between sources: `tk_` vs `otk_`

Blog-era material describes keys starting `tk_...`; the current quickstart
says the key "starts with `otk_`". Minor, but a builder pattern-matching
their key against the docs can doubt they copied the right secret.

### 2.3 The docs' example models do not exist in the hosted catalog

The blog names a managed provider prefix (`mzai:moonshotai/Kimi-K2.6`). The
string `mzai` appears nowhere in the current repo docs, and against the live
hosted catalog it does not resolve: the blog's example is today's plain
`moonshotai/kimi-k2.6`. Worse, the routing docs' thrifty/failover examples
(`openai:gpt-5-nano`, `anthropic:claude-haiku-4-5`) are absent from the hosted
catalog entirely, so following the docs literally ends in model-not-found at
call time. VaultMind's routing config had to be rebuilt from the live
`/models` response, using only verified catalog IDs.

### 2.4 Routing policies are documented as config, but the hosted surface is not findable

`routing.md` specifies policy YAML (`select`, `budget_used_pct`,
`on_failure`) and a CLI (`otari routing explain ...`). Building against the
hosted platform, I could not tell from the public docs where a hosted user
creates that policy: dashboard, per-workspace YAML, or CLI against the hosted
endpoint. VaultMind therefore implements the same semantics client-side and
ships the policy-shaped YAML in its config as the artifact to configure. The
related trap: the smart/learned router is documented at length in the same
doc while being self-described as "not offered in the dashboard... has not
been validated for general use", with no banner at the top saying so.

### 2.5 The $20 starter credit did not land, and $0.00 refuses even free models

After sign-up the dashboard showed $0.00, and the gateway confirmed it in its
own words: every chat completion returned HTTP 402, code
`insufficient_funds`, including catalog models priced $0.00 in / $0.00 out.
The balance gate runs before pricing, so there was no zero-cost way to
smoke-test generation on a fresh workspace, and nothing in-product explained
where the announced first-200-sign-ups credit had gone. Credit where due:
after I raised it through the hackathon channel, the organizer (Marcus,
via DoraHacks message) got the credit applied, and the full model-backed run
then completed unchanged. But a hackathon participant who did not ask would
have stayed walled.

### 2.6 Management surfaces reject a normal API key: "Invalid master key"

With the workspace API key, `GET /api/v1/usage`,
`GET /api/v1/organizations/me`, `GET /api/v1/organizations/me/keys` and
`GET /api/v1/wallet` all answer 401 `{"detail":"Invalid master key"}`, while
`/models` and `/chat/completions` accept the same key. The docs present
`/v1/usage` as the usage surface and document a keys API
(`POST /api/v1/organizations/me/keys`) without saying a separate master key
gates them on the hosted deployment, or where a hosted user obtains one.
The direct consequence for this build: creating the per-role virtual keys,
the exact pattern the hackathon encourages, is a dashboard-only manual step,
because the keys API is unreachable with the key a hosted user actually
holds (and an API-minted secret is shown exactly once, so it cannot be
parked in a credential store after the fact). The exact dashboard steps are
written out in `docs/OTARI_FEATURES.md` in the repo.

### 2.7 The hackathon onboarding/rubric page is JS-rendered only

`otari.ai/devs-wilding` and the linked rubric could not be read outside a
live browser, and no mirror exists. The seven submission items had to be
reconstructed from the DoraHacks page itself. For a document whose omissions
make a submission ineligible, that is a real risk to participants.

### 2.8 Still open on my verify list

The docs say gateway-run tool calls are held against budget and refused with
`budget_exceeded`. I have not yet verified live how the hosted platform
behaves there or how the refusal surfaces in the dashboard; built-in tools
enter VaultMind's checker in the next build step, and I would rather report
this as unverified than guess.

## 3. The three written questions

**When were you most tempted to skip Otari and call a provider directly,
and what happened?**
Twice. First at the 402 wall (section 2.5): with a $0.00 balance and every
completion refused, the fastest path to a working demo was a direct provider
key. Second at the master-key wall (section 2.6), when per-role keys turned
into a manual dashboard errand. I stayed both times, because per-role keys
and budgets were not plumbing for this project, they were the subject of it:
dropping the gateway would have deleted the thing being demonstrated. While
the workspace was unfunded, the deterministic policy mirror carried the
verdicts and the decision cards said so on their face; nothing was faked to
make the demo look model-backed.

**What did you end up building yourself that Otari should have provided?**
The client-side routing layer: budget-conditional model selection (downgrade
to the cheap model at 80% budget used), single-attempt failover, a local
budget mirror that blocks at 100% and explains the refusal, and a per-role
JSONL usage ledger with a `usage` report. All of it exists because the
hosted routing-policy surface was not findable (2.4) and the gateway's own
usage surface sits behind a master key I do not hold (2.6). The policy
mirror and the prompt-injection tripwire I would have built anyway; those
are the project's own logic. The routing and usage reporting are the parts
that feel like they belong to the gateway.

**If the rules did not require Otari, would you still use it?**
Yes, for multi-role agent systems, which is most of what I build: one
revocable, model-scoped, budget-capped key per role, enforced before
dispatch, is a genuinely better shape than one provider key with the run of
the machine, and it composes with on-chain policy in a way judges and users
can actually audit. For a single-model toy or a one-off script, a direct
provider call is still less machinery. My answer would get stronger if the
friction above were fixed, especially the catalog/docs alignment and the
master-key story, because none of it is architectural; it is finish.

## 4. Suggestions, in the order I would fix them

1. Make the blog, quickstart, and hosted gateway agree on `/api/v1` and the
   `otk_` prefix (issue #2898), and pin the docs' example models to ones
   that exist in the hosted catalog today.
2. Say plainly, in the quickstart, which surfaces need a master key, and
   give hosted users a path to one (or scope workspace keys so `usage` and
   key creation work with them). Per-role key creation via API is the
   hackathon's own recommended pattern; it should not end at a dashboard.
3. Link the hosted routing-policy surface from `routing.md`, or state that
   hosted policies are dashboard-only, and put a "not offered yet" banner on
   the smart-routing section.
4. When a workspace balance is $0.00, let $0-priced models run, or return an
   error that says the starter credit state out loud. A first-run wall with
   no explanation is the worst possible first impression.
5. Publish a plain-text/markdown mirror of the hackathon rubric and
   onboarding checklist.
