# Журнал Progressor Core

2026-10-08: выделен единственный канонический Core в MarkKoro/progressor_core main; прежняя копия приложения удаляется из Gym. Сохранены отдельные базы/процессы всех трёх ботов и Core.

Подготовлены детерминированные метрики силы/сравнимой нагрузки/MET, контекстные inline подсказки с покрытием/происхождением/подписками и скрытием на 7 дней, ограниченный AI context v2 и owner-local попытки ИИ. Добавлены ручные действия родных интерфейсов без автоназначения доз.

Проверка Linux с отдельным venv Core: 83 Core + 52 Food + 49 Gym + 6 Supply = 190 тестов, все passed; только mocks/временные базы. Реальные три WebApps: 15 сценариев, 0 AI POST; прежние 9 переходов launch/target также прошли. Сценарии физического Telegram и реальные платежи не заявляются.

В deploy/ подготовлены update-progressor/updatecore: проверенная staging версия с собственным runtime, онлайн backup/restore verification, атомарное переключение, health/readiness, rollback кода без перезаписи живого ledger. Неизменённый main — no-op. Операционные инструкции docs/DEPLOYMENT.md.

80 дополнительных предложений по 23 продуктам/2 платформам — docs/OPPORTUNITIES.md; идеи не внедрены. Научные основания/границы — docs/ENERGY_EVIDENCE.md; UX — docs/UX_REVIEW.md. Production rollout и фактические ревизии/архивы регистрируются в закрытом операционном журнале на сервере и локальном ACTION_JOURNAL.md, а не в открытых runtime-конфигурациях.


## 2026-10-08 Coordinated updater

Added update-all for four fixed main repositories, isolated requirement reconciliation even at unchanged SHA, all nine active units including legacy Food API, common locks/Core-only delegation, durable interrupted recovery, restore-verified application checkpoints, exact changed-path Git recovery preserving tracked Food DB and later ledger writes. Existing update_all_bots handles unrelated projects and stays unchanged. Native targeted command names delegate to the same engine. New marketing previews/user journeys/workout surface+nutrition notifications requested and queued separately; not part of this updater release. Linux dependency staging passed Gym49 tests; full Core/updater suite and live installation evidence recorded in the durable local/server action journal. See docs/UPDATE_ALL.md.


## 2026-10-08 Native offers, profiles and opt-in reminders

Added one honest static bundle example, trial/gift copy without widening private access, contextual priority and durable dismissals. Both Gym exercise surfaces now project explicit completed work once; full completion replaces its partial projection. Added owner-entered strength duration. Food owns consented structured profile and opt-in preferences; field reconciliation preserves provenance/conflicts. Goal preview/apply and the survey use the shared deterministic model with no AI. The existing Food consumer sends unseen workout/covered nutrient reminders with quiet hours, durable daily/weekly limits and no uncertain delivery retry.

Validation:132 Core+62 Food+51 Gym+6 Supply=251 Linux tests;52 isolated browser checks (15 native regressions,24 subscription states at three entry points,4 start/trial journeys,6 gift/dismiss/bundle-revocation/fallback/outage journeys,3 mobile profile contrast checks). Actual local APIs/HTML, synthetic launches, temporary DBs and mocked providers; no real AI calls, charges or additional Telegram consumers. Physical Telegram/iPhone is not claimed. Production revisions and verified bounded server/off-server backup evidence are kept in the private durable action journal.40 additional user opportunities in docs/USER_OPPORTUNITIES.md remain proposals.

## 2026-10-08 Native Telegram subscriptions and reminders

Added a single currency-aware calculator for personalized bundle credit, alignment with remaining paid native periods, immutable quotes and component schedules. Source owners export current tariffs and proven paid grants; gift/trial access is preserved without treating it as money. All three Telegram menus, WebApps and the separate RUB website use the same catalogue. Existing receipts remain valid, precheckout reservations and unknown provider outcomes cannot create duplicate charges. First activation waits for the coordinated release; subsequent updater checks reject incompatible financial rollback.

Expiry notices have one durable sender chosen from recent activity, one financial notice per local day and busy-input deferral. Expiry preserves history and independent remaining access. Native menu renderers own interactive messages; accepted-send cleanup cannot cause resend. Food saved photo/text/voice results show paged owned nutrients and fresh remaining goals; Supply reminders page actual positions, preserve current input and provide occasional manual catalogue actions. Food financial notifications run inside its existing consumer even without JobQueue.

Validation uses temporary databases, actual native handlers with fake Telegram, API tests, an isolated Linux suite and 41 actual HTML/API browser checks including personalized pricing from all three entry points and the RUB website. Exact final counts, release hashes, live checks and bounded server/off-server restore verification are recorded in the private operational journal. No real AI calls, charges, new Telegram consumers or physical Telegram execution are claimed. The photo quality/prompt audit remains queued for the next stage. See docs/BOT_NATIVE.md before changing subscriptions, schedules or notification ownership.


## 2026-10-09 Subscription screen and ordinary-camera Food analysis

Added one canonical four-product subscription screen for all three WebApps, owned access/expiry/trial/unknown display and equal RUB/Stars pairs. Native individual payment hooks reuse owner checkout; common menus/website preserve v2 personal prices and existing external YooKassa Redirect. Added owned Food Stars creation using its existing ledger and consumer. Shared status endpoint contains no health data and is independent of checkout availability.

Ordinary Telegram photo now automatically calculates, selects the largest PhotoSize and uses optional caption. Optional image document shares the same path. Food image preparation fixes small-file EXIF orientation, bounds decoded resources and avoids redundant JPEG compression. Unified photo/text/voice composition prompt, strict compatible-model schema, recomputed portion totals, nullable54 nutrients and a single bounded malformed-photo repair. Invalid/semantic/network failures do not save or charge. Existing attempt guards and stable source keys remain. WebApp nutrient editor is replaced by read-only saved composition; historical corrections remain.

Linux tests and actual HTML/API browser journeys use synthetic users, temporary DBs and fake providers; no real charge/AI/extra consumer or physical Telegram execution. Exact tested pack, main revisions, deployment,9-unit checks and bounded off-server backup/restore evidence are maintained in the private operational journal. The earlier queued photo audit is implemented here; a paid photographic accuracy benchmark remains outside this release. See docs/SUBSCRIPTIONS_AND_FOOD_PHOTOS.md for next-agent contracts.


## Selected native connections — prepared

Selected features are implemented as documented in SELECTED_FEATURES.md. Preliminary full Linux regression413/413 passed; subsequent native/menu/style/permission changes require final exact regression. Real local browser8 journeys passed, mobile390/desktop1280; no physical Telegram/real payment/provider benchmark. No publication/production switch recorded here yet. Final exact tested SHA, main revisions and verified backups are retained in the durable deployment report.
