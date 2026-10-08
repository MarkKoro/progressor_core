# Progressor Core v1

Independent loopback FastAPI process, its own SQLite ledger, read-only source adapters.
Canonical source: [MarkKoro/progressor_core](https://github.com/MarkKoro/progressor_core), main.
Core application code lives only in this repository. Domain apps contain small native adapters and never import Core.
Update all four products with `update-all`; see [coordinated deployment](docs/UPDATE_ALL.md).
`update-progressor` / `updatecore` update Core only through the same transaction engine.
Ownership, event versions, identity mappings and rollout are documented in every repository's
`docs/PROGRESSOR_INTEGRATION.md`. Core user subjects are positive decimal strings, not local user IDs.

## Runtime

Python 3.12, install pinned `requirements.txt` into a separate venv; run
`python -m uvicorn progressor_core.app:app --host 127.0.0.1 --port 8040` from this directory.
Set `PROGRESSOR_DB_PATH=/var/lib/progressor/core.sqlite3`, `PROGRESSOR_SIGNING_KEY_FILE` (32+ chars,
root-readable file outside Git), `PROGRESSOR_{GYM,FOOD,SUPPLY}_DB_RO`, and the corresponding
`PROGRESSOR_{GYM,FOOD,SUPPLY}_BOT_TOKEN`. Never use a domain DB as Core's DB.
`PROGRESSOR_ENABLED_DOMAINS` starts empty; enable `gym,food,supply` after all bridges and native
payment consumers are healthy. Source poll is 30 seconds, fresh cutoff 120 seconds; failures
back off independently. Domain-owned cache workers refresh shared entitlements every 15 seconds.

Only `/health`, `/ready`, `/assets/`, `/subscribe` and `/api/v1/` are public through Nginx.
Always deny `/internal/`, `/metrics`, docs and unknown paths at the public proxy. Private calls
are loopback-only and HMAC bind source, path, body and short timestamp. Client/browser assertions
cannot call them. Source ingest is disabled unless explicit per-source keys are configured.
Overwrite X-Real-IP in the trusted proxy and bound request sizes to 32 KiB. Do not log auth headers,
launch proof, payment/email payloads or raw personal records.

## AI and subscriptions

Cross context requires active subscription for both receiving product and source. Trial/admin
access keeps native features but does not by itself entitle cross-source data. A paid bundle opens
all products. Missing/unpaid sources are absent, never zero-intake hints. Stale data is excluded
from AI. Supply health profile/labs require its existing consent; clinical lab payloads are not sent
to Gym/Food AI. Source provenance and uncertainty remain alongside estimates. Food photo/text
composition depends on products/grams, not the person's body weight. The catalog defines 54
nullable nutrients with canonical units. Never infer a medical deficiency or clinical dose from
partial food records.

## Bundle payments

Native single-product expiry columns never receive bundle grants. Core owns immutable quotes,
receipt ledger, refunds and shared expiry. Domains own `progressor_bundle_cache` and
`progressor_payment_outbox`; APIs write only their own DB. Existing consumers record trusted
successful/refunded Telegram updates before network calls. Core can replay those outboxes read-only.
Duplicate charge/revision updates do not extend access twice; late success cannot resurrect a refund.
Caches survive Core downtime until their real paid expiry. A refund reaches caches after connectivity
returns; native individual subscriptions remain independent. Do not restore old domain DBs for code rollback.

Default prices (30/90/180/365 days): RUB 599/1590/2990/5490, XTR 450/1190/2250/4190.
Override `PROGRESSOR_PRICE_{M1,M3,M6,Y1}_{RUB,XTR}`; RUB values are kopecks. No automatic renewal.
Digital products inside Telegram use XTR exclusively. `/progressor` and the shared WebApp panel
offer all plans from each existing bot. RUB checkout is on `/progressor/subscribe` in a separate
browser, with explicit existing-bot login confirmation and receipt email. The dedicated website
session cannot be replaced by a mini-app assertion. Terms version is `progressor.bundle.v1`.
Configure `PROGRESSOR_YOOKASSA_SHOP_ID/SECRET_KEY/VAT_CODE` using the selected existing merchant;
different product merchants must not be silently treated as the same account. Preserve the original
YooKassa request and idempotence key when the creation response is lost. Retry creation only within
23 hours; later uncertainty requires support, not a new charge. Provider return pages never grant
access. Authenticated provider GET verifies amount/currency/metadata and success. Pending payments
reconcile automatically even if the browser closes. Webhook path:
`/progressor/api/v1/bundle/yookassa/webhook` (payment.succeeded/canceled, refund.succeeded).
Authenticated polling also reconciles refunds, so manual dashboard notification configuration is optional.
`PROGRESSOR_SUPPORT_URL` defaults to the existing Gym support bot; `/paysupport` works in all bots.

## Validation and rollback

`python -m unittest discover -s tests -q` with dummy credentials and temporary databases.
Never start a second consumer or make real test charges with production credentials. Browser
emulation does not prove physical Telegram/iPhone behavior. Local browser smoke checks all 9
launch/target routes, ownership, fixed navigation, no iframe, layout and source gating.
Before deployment create/restore-test consistent SQLite backups plus code/config, record SHA256.
Stop only affected units for code replacement, keep all DB/WAL/SHM and existing user writes.
Deploy Core -> native bridges/cache/payments/prompts -> shared navigation -> enable all domains.
Rollback restores only exact affected code/config files, preserves additive tables and ledger,
then restarts the same affected units. Preserve paid bundle caches during code rollback: the
compatibility helper must continue granting paid access; never revert to code that ignores paid users.


Production isolation: native API workers publish private online backups every 30s to
/var/lib/progressor-sources/{gym,food,supply}/source.sqlite3. Set PROGRESSOR_*_DB_RO to those
files and PROGRESSOR_REQUIRE_FRESH_SNAPSHOTS=1. Reject copies older than 90s. Core's strict
read-only filesystem has only /var/lib/progressor writable, so live SQLite WAL coordination
remains entirely with each source owner. Native flag PROGRESSOR_SOURCE_SNAPSHOT_ENABLED=1.


RUB first-request preflight reads the selected live merchant with GET /me and mirrors its
receipt configuration. Disabled automatic receipts means no receipt field in the provider
request, matching the existing Food flow; email is stored privately in bundle_provider_contacts.
An enabled mode includes the configured VAT data and internet=true. Stored provider bodies
and emails stay immutable on all retries, including legacy bodies created before this change.


## Native guidance and deterministic metrics

Read this repository’s `docs/PROGRESSOR_NATIVE.md` for conditional adult MET estimates, comparable load, coverage-aware inline rules, seven-day account/target dismissal and canonical owner-local AI guards. These features never call an LLM during views or synchronization. AI context prompt v2 uses bounded workout summaries. Additional fields remain optional under envelope schema v1; old source snapshots still work.


Native follow-up: [NATIVE_GROWTH.md](docs/NATIVE_GROWTH.md)
