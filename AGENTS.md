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
