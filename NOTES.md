# NOTES — Otari docs friction log (for the hackathon feedback deliverable)

Only genuine, dated observations from actually building VaultMind.
Nothing here is invented; each entry says how it was hit. Entries marked
[pre-build research] were recorded during the 2026-11-04 research pass
(scoring plan) and are included because they shaped this build.

## 2026-11-04 — building VaultMind

1. **Base URL: blog says `/v1`, the live API says `/api/v1`.**
   Mozilla's official blog post ("Use the Otari Gateway with OpenCode")
   points clients at `https://api.otari.ai/v1`. Calling it returns
   HTTP 404 with a (helpful!) JSON correction: "Otari serves its API
   under /api/v1, not /v1." The current repo quickstart has it right
   (`https://api.otari.ai/api/v1`). The gateway's self-correcting error
   message saved real time — but anyone following the blog first still
   hits the wall. Verified by direct calls, 2026-11-04: `/api/v1/models`
   and `/api/v1/chat/completions` answer 401 (auth), `/v1/...` answers
   the 404 correction.

2. **Key prefix differs between sources: `tk_` vs `otk_`.**
   The blog-era material describes keys starting `tk_...`; the current
   quickstart says the key "starts with `otk_`". Minor, but a builder
   pattern-matching their key against the docs can doubt they copied
   the right secret. VaultMind's client accepts either (it just sends
   the Bearer token).

3. **Auth header flexibility is real and undocumented in the quickstart
   path I took.** The unauthenticated response says the gateway accepts
   `Otari-Key`, `Authorization`, or `x-api-key`. Nice — discovered from
   the error body, not from the docs page I started on.

4. **The hosted model catalog / provider spelling could not be
   confirmed from public docs.** The blog names `mzai:` as the managed
   provider with `mzai:moonshotai/Kimi-K2.6`; the string `mzai` does not
   appear anywhere in the current repo docs (`models.md`,
   `hosted-providers.md`), which instead teach catalog IDs
   (`vendor/model`) and `provider:model` pins with other providers.
   Which spellings the hosted deployment actually accepts is only
   answerable with a key in hand (the smoke test's model-list check is
   built for exactly this). Until then, model IDs in
   `config/otari-routing.yml` are best-effort from official examples.
   [RESOLVED later the same day — see entry 9.]

5. **Routing policies are documented as config, and the hosted surface
   for them was not findable from the docs.** `routing.md` specifies
   policy YAML (`select`, `budget_used_pct`, `on_failure`) and a CLI
   (`otari routing explain ...`). Building for the hosted platform, I
   could not tell from public docs where a hosted user creates that
   policy (dashboard? per-workspace YAML? CLI against the hosted
   endpoint?). VaultMind therefore implements the same semantics
   client-side and ships the policy-shaped YAML in its config as the
   artifact to configure — if the hosted surface exists, this is the
   friction that hid it. [To re-check in the dashboard once the account
   exists.]

6. **Learned/smart routing is documented at length but self-described
   as not offered.** [pre-build research, from routing.md itself]
   The docs say the smart router "is not offered in the dashboard...
   has not been validated for general use". Documenting an unavailable
   feature in the main routing doc without a banner is a trap for
   builders planning around it.

7. **The hackathon onboarding/rubric doc is JS-rendered and was not
   fetchable as text** [pre-build research] — `otari.ai/devs-wilding`
   and the linked rubric could not be read outside a live browser, and
   no mirror exists. The 7 submission items were reconstructed from the
   DoraHacks page itself. A plain-text/markdown version of the rubric
   would remove a whole class of eligibility mistakes.

8. **Tool-call budget holds need a live test.** [pre-build research,
   still open] Docs say gateway-run tool calls are held against budget
   and refused with `budget_exceeded`; whether the hosted platform
   behaves exactly so (and how the refusal looks in the dashboard) is
   on the verify list for the next build step, when built-in tools
   enter the checker.

## 2026-11-04 — live phase (real key, real gateway)

9. **The hosted catalog contains neither the docs' example models nor
   the blog's `mzai:` prefix.** Verified live with the real key:
   `GET /api/v1/models` returns 159 models with plain `vendor/model`
   IDs. The blog's example is today's `moonshotai/kimi-k2.6` (no
   prefix); `openai:gpt-5-nano` and `anthropic:claude-haiku-4-5` —
   the routing docs' thrifty/failover examples — are absent entirely,
   so following the docs literally ends in model-not-found at call
   time. VaultMind's routing config now uses only verified catalog
   IDs. One pleasant surprise in the other direction: the /models
   payload carries live per-model pricing, which no doc mentioned;
   the config's price table now comes from the gateway itself.

10. **The announced $20 starter credit never landed, and a $0.00
    balance refuses even free models.** The dashboard showed $0.00
    after sign-up; the gateway confirms it in its own words: every
    chat completion returns HTTP 402, code `insufficient_funds`,
    "Insufficient funds ($0.00) to serve this request." — including
    catalog models priced $0.00 in / $0.00 out, so the balance gate
    runs before pricing and there is no zero-cost way to smoke-test
    generation on a fresh workspace. For a hackathon whose onboarding
    promises the first 200 sign-ups a $20 token credit, the first-run
    experience is a wall with no in-product explanation of where the
    credit went. (VaultMind's live run hit exactly this; the raw
    outputs are in `docs/evidence/`.)

11. **Management surfaces reject a normal API key: "Invalid master
    key".** With the workspace API key, `GET /api/v1/usage`,
    `GET /api/v1/organizations/me`, `GET /api/v1/organizations/me/keys`
    and `GET /api/v1/wallet` all answer 401 `{"detail":"Invalid
    master key"}`, while `/models` and `/chat/completions` accept the
    same key. The docs present `/v1/usage` as the usage surface and
    document a keys API (`POST /api/v1/organizations/me/keys`) without
    saying a separate master key gates them on the hosted deployment,
    or where a hosted user obtains one. Anyone automating per-role
    key creation — the exact pattern the hackathon encourages —
    finds out only by hitting the wall.

12. **Per-role virtual keys are therefore a dashboard-only workflow
    here.** The keys API exists in the docs but is unreachable with
    the key a hosted user actually holds (entry 11), and an
    API-minted secret is shown exactly once, so it cannot be parked
    in this workspace's credential store after the fact. The exact
    dashboard steps for `vm-proposer` / `vm-checker` / `vm-reporter`
    (names, model restrictions, USD limits) are written out in
    `docs/OTARI_FEATURES.md`; it is the one manual step left in the
    setup, and it is manual because of the platform, not the project.

## Non-Otari friction hit during the same build (context, not feedback)

- Arbitrum's official Sepolia RPC answers 403 to Python urllib's
  default User-Agent; an explicit UA header fixes it. VaultMind's
  reader also fails over across three public endpoints.
- A dropped connection from the gateway's edge ("Remote end closed
  connection without response") escapes urllib as a raw
  `http.client.RemoteDisconnected`, not a `URLError`. The Otari client
  now normalises it into a gateway error so failover engages.
