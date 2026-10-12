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


## 2026-10-12 — selected connections deployed and independently verified

This entry supersedes the earlier prepared-stage status. The selected runtime was published with normal fast-forward main updates and deployed through the existing update-all transaction 20261012T074556Z-1083507. Runtime revisions:

- progressor_core: `46821619f99796569632ab62716502de89bcd6ac`
- gym_diary_bot: `a80e50d6d7b84b26adad898d6290af7017d144dd`
- food_bot: `b9023113dcc4ec1a03fda80b69ee16f09124b9a9`
- supply_bot: `c9897e78bcdfe17a43275c93a386ad812f960b1f`

Exact tested archive SHA256: `b0eb9445ecb5975a45df0af0f0daf79dc81013f8a40951a456ba152b386cd38e`. Linux420/420 passed (Core215, Food105, Gym70, Supply30);175 Python sources compile;32 canonical helper mirrors match.54 actual local HTML/API browser checks passed, including all subscription states at all entry points, owned actions and trainer privacy. Empty-workout Gym menu12 cases were repeated. Browser Telegram SDK and providers were synthetic; physical Telegram/iPhone, real charges and paid photo accuracy are not claimed.

Subscription-menu root cause: the product render replaced the clicked DOM node before the document outside-click handler checked shell.contains(event.target). The original event.composedPath now decides whether the click originated inside. The shared header is compact while preserving44px navigation touch targets. The requested pattern audit found an additional asynchronous own→other→own selection race: comparing only the selected product allowed an old tariff response to appear after returning to the same product. A monotonically increasing purchaseOptionsRevision now guards responses. Foreground connection settings clicks and Escape preserve the underlying menu.6 forced-latency/foreground regressions passed across all3 WebApps.

Independent live checks passed:99 changed file hashes,32 helper mirrors,9 stable services/zero automatic restarts,4 SQLite integrity checks,3 fresh private DELETE-journal exports,9 signed audience bridges,one consumer per bot,financial protocol/gate2 and zero dead letters. Repeating update-all at unchanged main kept all9 service PIDs and the current immutable Core release; no database was restored.

Fresh pre-release archive `20261012T070557Z-pre-selected-features.tar.gz`, SHA256 `cfa402a6d8a44493ec0c6e7c9ce85d4de6063a78ea478402bcc94b230013a80a`, was downloaded off-server and its4 databases/schema/counts/code/config/commands/gate were restore-verified. The updater additionally verified `20261012T074556Z-1083507-all-update.tar.gz`, SHA256 `dcdd714cdf2b1f6ab39fb715ec5cea9e41d22a8e40f4ac7c36d71e76a9556dde`. Private post-checkpoint and final documentation revision evidence belong in the durable operational journal; databases, keys and private archives never belong in Git.

Selected behavior and next-agent contracts: [SELECTED_FEATURES.md](SELECTED_FEATURES.md). User-facing release guide: [canonical Core guide](https://github.com/MarkKoro/progressor_core/blob/main/docs/SELECTED_RELEASE.md). P20 shopping lists remain excluded by the user. P2/P4/P18 follow the later approved choices; P36 pauses hints/reminders while paid terms continue. Source-local dates, nullable nutrient estimates and explicit aggregate coach consent remain as documented.

These closing changes update documentation only. Runtime files retain the tested bytes. Future work must read current main and these contracts, preserve native ownership/consent/freshness, synchronize canonical shared helpers and use update-all for coordinated changes. Historical prepared/paused records above remain dated evidence, not outstanding blockers.
