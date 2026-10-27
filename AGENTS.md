# Instructions for coding agents

This is the canonical Progressor Core repository. Read README.md, docs/PROGRESSOR_NATIVE.md and docs/DEPLOYMENT.md before changing identity, adapters, context, AI guards, billing, source ownership or rollout.

- The user requires publication directly to main. Use ordinary fast-forward updates; never force-push or replace unrelated changes. Local test copies are allowed.
- Core owns only /var/lib/progressor/core.sqlite3. Read native private snapshots, never write Gym/Food/Supply databases or widen Core filesystem permissions to their live WAL directories. Keep each existing bot consumer and database independent.
- Telegram subjects are positive decimal strings below 2^63, not local IDs. Cross context requires receiving/source paid entitlements, freshness and existing Supply health consent. Trainer plan/AI delegation is Gym-only. The only nutrition exception is explicit pupil consent for owned aggregate KBJU/top5, documented in docs/SELECTED_FEATURES.md.
- Events/schema v1 and AI prompt v2 must stay backward compatible. Unknown amounts/coverage/duration are absent/null; never replace missing records with zero intake or infer clinical deficiency/doses. Views and synchronization never call AI.
- shared/domain_bridge.py, progressor_client.py, progressor_bot.py, ai_guard.py and workout_metrics.py are canonical. Mirrors in bots require explicit synchronized changes and their tests; update-progressor cannot update bot code for them.
- The former Gym integrations/progressor_core directory is removed. Core application code must remain only here. Review all bot adapters/tests when source schemas change.
- Run python -m unittest discover -s tests -q on Linux with temporary databases/dummy providers. Never start an extra Telegram consumer or make a real paid test.
- Backup and restore-test consistent SQLite plus code/private config before a production switch. Code rollback preserves all subsequent user writes, immutable payment records and paid caches. Keep old releases and their separate runtimes. Secrets/DBs/environments never belong in Git or logs.
- Record completed work, exact revisions, test results, backups and the next action in docs/WORK_LOG.md and the durable local journal. Describe browser emulation accurately.


Canonical Core source is now [MarkKoro/progressor_core](https://github.com/MarkKoro/progressor_core), published to main. Its production updater is `update-progressor` (`updatecore`). The former Gym integrations/progressor_core package has been removed. Core application code exists only in the separate Core repository; bots contain only their native adapters and owned data/UX logic. Bot-local shared helper copies still require synchronized bot main commits and native tests. Publish bot changes directly to main with a normal fast-forward update, as requested by the owner.

Read docs/UPDATE_ALL.md before rollout changes. deploy/update_all.py is the sole deployment transaction engine; update_progressor.py delegates with --only core. Never restore live databases during recovery or modify an existing runtime in place. Include both Food APIs and Supply worker when active. A busy paid worker must finish before switching; an aborted drain must not kill that job. update_all_bots belongs to unrelated products.

For native subscription examples, both exercise surfaces, profile reconciliation, deterministic nutrition plans and opt-in Food reminders, also read [docs/NATIVE_GROWTH.md](docs/NATIVE_GROWTH.md). Source data stay owner-local; do not add a consumer, diagnose from incomplete logs or retry uncertain Telegram delivery. Canonical nutrition_plan.py is mirrored only to Food and must match.


Native Telegram subscriptions and expiry: read [docs/BOT_NATIVE.md](docs/BOT_NATIVE.md) before payment grants/tariffs, source schedules, notifications or native menus. Canonical native_subscription helper requires synchronized all3 mirrors. After v2 gate/order, forbid Core protocol<2 or client schedule<2 rollback. Always preserve financial/user DB records; use native renderers and defer busy flows.

Subscription screen and camera pipeline: read [docs/SUBSCRIPTIONS_AND_FOOD_PHOTOS.md](docs/SUBSCRIPTIONS_AND_FOOD_PHOTOS.md). Keep a single canonical shared UI in Core, equal RUB/Stars choices and existing external Redirect/provider verification. Ordinary Telegram photos must remain the primary one-step input; file upload is optional. Never remove historical human nutrient records when removing editor controls.


## Selected native connections

Read [docs/SELECTED_FEATURES.md](docs/SELECTED_FEATURES.md) before changing shared profile commands, source-owned caches, reminders, day closure, food atlas/overlap, rhythm, timezone or coach permissions. Shared product_links/ai_cache/day_goal/food_sources/timezone_history are canonical in Core and mirrored together. Trainer aggregate nutrition is a narrow explicit consent exception; native trainer role/link alone never grants it or cross-product AI delegation. Keep source ownership, history/CAS/idempotence, no-replay rest, protocol2 and normal FF main4.


## Quality program — 2026-10-16

Read [docs/QUALITY_PROGRAM.md](docs/QUALITY_PROGRAM.md) before storage, access, AI, native UI or deployment changes. Preserve the request-owned context projection, source-owned doses, read-only GET behavior, durable AI attempts and explicit native readiness. Install declared requirements/constraints into a fresh runtime; retain the old runtime for rollback. Match the change to meaningful tests and record exact source/evidence; no extra consumers or real paid tests.

Critical launch mirrors: `shared/bootstrap.v1.js` is distributed identically into Gym/Supply `webapp/assets/progressor-bootstrap.v1.js` and Food `static/webapp/assets/progressor-bootstrap.v1.js`. Update all copies and test native Core outages, SDK proof changes, storage failure, cross-navigation and foreign-origin headers. The complete UI remains here. `settings_snapshot` serves weight/coach/rhythm settings; do not replace full meal reads needed by expressly consented trainer top-5.


## Native ecosystem journeys — 2026-10-17

Read docs/ECOSYSTEM_CONNECTIONS.md before changing daily summaries, source-health explanations, workout/meal completion or preferences-aware hints. Keep own-account/source+target access, freshness, Supply consent and explicit unknowns. New daily reads must stay small/read-only; never replace them with full history/AI generation. Shared progressor_bot.py stays canonical in Core with identical all3 mirrors. Sleep remains a documented future native connector, not a live source or Telegram permission.

## Bounded journey handoffs — 2026-10-19

Read the canonical [journey contract](https://github.com/MarkKoro/progressor_core/blob/main/docs/JOURNEY_HANDOFFS.md) before changing purpose routing, return, change-goal review or Food goal confirmation. Keep the single Core UI, native owned actions, account/proof binding and read-only navigation. A saved workout/intake does not prove plan review; explicit scoped review is separate from seen/dismissal. Food apply must reference its server preview and preserve concurrent owner edits; see Food docs/GOAL_PREVIEWS.md. Use the frozen JQ-v1 in Core docs/JOURNEY_QUALITY_RUBRIC.md for matched tasks, separate concept and observed evidence. Do not replace agreed 90-minute free-workout completion, Moscow Food day, meal-anchor parameters or native financial/consent contracts as a side effect.


## Verified second journey package — 2026-10-21

Keep the canonical owner-policy boundary and synchronized progressor_client mirrors; read Core docs/SUPPLY_OWNER_POLICY.md before changing source metadata, legal eligibility or updater recovery. The persistent owner-consent-v1-ready gate is independent from financial protocol2 and must survive ordinary code rollback. Supply keeps its single native consent predicate; Core reads only private owner snapshots.

Preserve operation-key retries in Gym /set/add_once (no legacy fallback after an uncertain response), explicit saved-time provenance in Food, and Supply uncertain-delivery suppression (an unknown Telegram response must never trigger a blind retry). Keep native functions available during Core outages.

## Offline contract tests and host readiness boundaries

Core deployment tests run through `deploy/run_core_checks.py`. Its isolated test
subprocess redirects reader default readiness paths before discovery; explicit
strict-mode fixture gates still apply. Application readers never use a test
environment switch. Do not let host owner/next-meal gates select the semantics of
legacy synthetic test databases. Updater fixtures must own their gate paths too.

Read docs/NEXT_MEAL_CHOICES.md before planned meals, canonical preference revisions, Food clear-data epochs or their rollback. A choice is never consumed food. Keep the one Core preferences writer, monotonic revision metadata, explicit owner/proof guards, source/trial/freshness and the independent next-meal-v1-ready recovery gate. Do not activate it before compatible updater/current/fallback and actual running Food services are verified under both updater locks; never roll back to an old Food purger after activation.


## Verified third journey package — 2026-10-22

Preserve the explicit Food next-meal intent boundary in docs/NEXT_MEAL_CHOICES.md: one canonical Core preferences writer and planned choice, monotonic reset/revision receipts, no automatic meal/macronutrient writes, no provider call. Keep the explicit offline deploy/run_core_checks.py entry before test discovery; host readiness state must never change synthetic fixtures. In positive Food meal fixtures derive journal date from the same saved instant in Europe/Moscow, including the 21:00–24:00 UTC date-boundary window; saved time does not prove consumption time.

The exact combined source B passed 863 Linux tests through composed byte-verified runs (Core388 B; unchanged Food147/Gym239/Supply89 A), plus a fresh 58-case browser regression and one separate coexistence scenario on runtime-identical source A. Optional-tour JS17 is a separate pure-VM check. Physical Telegram, real provider/payment and human UX outcomes are not established by these gates. Read the release WORK_LOG entry before rollout; preserve all three gate contracts and verify compatible current/updater/fallback before any next-meal activation under both updater locks.

## Owner reset and late AI results

`shared/ai_cache.py` is canonical and must match all three bot mirrors. Its optional keyword-only `publish_if(connection)` is trusted synchronous owner code, evaluated inside the existing `BEGIN IMMEDIATE` before cache cleanup, insertion or eviction. It must only read that connection; no network, asynchronous work or nested cache connection. A false predicate leaves cache entries unchanged. Default callers retain the existing bounded cache behavior.

Food captures its native data-reset revision before photo/text analysis or voice transcription, includes it in cache identity, and checks it again inside the cache write and native meal transaction before duplicate lookup or meal/nutrient/request/debit writes. A late pre-reset result must never recreate erased data or charge a new request. Ordinary cache hits still require native access/quota/attempt guards. Food owns its bounded photo metadata, explicit resume and current menu; Core does not receive drafts or images. Review [Food recovery](https://github.com/MarkKoro/food_bot/blob/main/docs/PHOTO_RECOVERY.md) and its fault-injection tests before changing this boundary. No new readiness gate or consumer is introduced.

Read docs/SUPPLY_INTAKE_TIMEZONES.md before changing historical Supply event zones.
Keep source day/recorded UTC/dose/identity unchanged. Only continuous owner ledger
intervals after the first transition prove timezone; missing/legacy/cutover-second
lineage stays omitted with timezone_basis=not_recorded. Current profile timezone
still controls today's clock. This resolver is Core-local, not a shared mirror.


## Current source participation and settings request ownership

Canonical shared/connections.v1.js distinguishes saved source preferences from
current target-context Today readiness. The checkbox never grants access or
accepts legal documents. Keep current/loading/unknown/unsaved states explicit;
do not reuse the settings GET health after a preferences POST.
Settings completion belongs to its request and open/render generation. Pending
preferences saves own their captured input/select fields while Close remains
available. The eight-second client acknowledgement budget is not server commit
cancellation: never automatically retry an unconfirmed write. Keep explicit
read-only retry and current409 draft protection. Run the whole-asset regression
`node tests/test_connection_readiness.cjs` for changes to this boundary, alongside
the explicit Linux deploy/run_core_checks.py entry. Node is a test tool, not a
new production dependency. No bot copies of this shared UI should be created.


## Stable participation refresh layout — revision B

During an already loaded participation refresh, batch-read every note height
before DOM writes, reserve that note's measured border-box minimum height only
while loading, and show the short honest Checking marker. Never clip reasons or
use a fixed large height. Success/error restore natural layout; viewport/font
changes invalidate old pixel reservations. Render/open/close dispose their own
listeners and old reservations. Keep view/request ownership, draft/focus and the
eight-second settings acknowledgement contracts. Canonical whole-asset Node23
includes the previous20 response guards plus3 layout/lifecycle cases. Browser
geometry uses a project tolerance of1 CSSpx, not a human-usability threshold.


## Partial preference acknowledgements and local drafts — sixth scope

Canonical connections save(patch) owns only keys in that acknowledged patch.
Keep server current.preferences authoritative and preserve unrelated dirty
preference display values across its rerender. The per-render registry compares
initial displayed values, with semantic array/object ordering and typed values;
it does not add unrelated keys to the POST or save them automatically. Rest
actions may acknowledge themselves while preserving other preference drafts.
Only five preference groups are covered: connections/notifications, weekly,
diet/exclusions, Food day prompt and rest. Coach/rhythm refresh callbacks and
other transient native editors remain separate; never claim all UI writes are
covered. Explicit409 refresh discards drafts as warned; close/open dispose the
registry. Keep old request/view/acknowledgement/field-lock/geometry guards. Run
whole-asset Node35 (previous23 plus12) and the source-bound native partial-write
acceptance; no bot copies, storage, backend or extra provider calls are added.


## Preparatory free-workout notification fallback — seventh scope

Read docs/FREE_WORKOUT_NOTIFICATIONS.md before the future H08 proof/admission
writer or rollback work. This Core-only compatibility guard creates no table,
epoch, admission, trigger, native proof, AI call or sender. Either reserved
SQLite policy/admission object (ASCII NOCASE, any shape), or a SQLite inspection
error, suppresses free/unclassified post-workout triggers. With no object and a
successful read, legacy behavior remains. Only exact ASCII positive numeric
workout identifiers keep the programmed compatibility path. Existing incomplete
session, access, source, opt-in, rest, quiet and delivery guards remain.

Full-H08 free admission and candidate reads must both require source clock T
strictly after max(global adoption E,current Core identities.created_at I).
Missing, invalid or future identity state fails closed; ordinary reads never
create or advance I. This owner-reset floor and its ten planned holdouts are
future design, not implemented/tested by this compatibility-only shim. No full
UTC/calendar fix or writer/owner-erasure/rollback certification is provided here. Future full H08 must preserve the global epoch and terminal decisions and
install its dedicated persistent owner-cleanup trigger. Do not drop reserved
objects or restore live databases to recover old behavior. Install and verify
this shim as the actual retained fallback before the later full release.

Mixed free/numeric energy text uses only retained numeric rows; removing a free
trigger can expose an existing lower-priority nutrient candidate. Do not claim
all mixed messages are byte-identical. No shared/native mirror or UI change is
part of this scope. Compose from fresh main after sixth closeout, record the
release notes and run explicit Linux deploy/run_core_checks.py plus relevant
release gates before ordinary main publication and the existing update-all
rollout.
