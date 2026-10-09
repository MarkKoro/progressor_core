# Instructions for coding agents

This is the canonical Progressor Core repository. Read README.md, docs/PROGRESSOR_NATIVE.md and docs/DEPLOYMENT.md before changing identity, adapters, context, AI guards, billing, source ownership or rollout.

- The user requires publication directly to main. Use ordinary fast-forward updates; never force-push or replace unrelated changes. Local test copies are allowed.
- Core owns only /var/lib/progressor/core.sqlite3. Read native private snapshots, never write Gym/Food/Supply databases or widen Core filesystem permissions to their live WAL directories. Keep each existing bot consumer and database independent.
- Telegram subjects are positive decimal strings below 2^63, not local IDs. Cross context requires receiving/source paid entitlements, freshness and existing Supply health consent. Trainer delegation is Gym-only.
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
