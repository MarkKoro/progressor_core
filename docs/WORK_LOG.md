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


## 2026-10-12 — live backup sidecar race

The documentation closure attempt stopped before switching any service:FileNotFoundError while archiving Gym after its docs. Its four SQLite copies were valid; attempted_repositories was empty and switch_started was false. A deterministic regression reproduced TarFile.add listing a WAL/SHM and then trying gettarinfo after the SQLite checkpoint removed it; the tar filter ran after that metadata read. Filename exclusions now run before metadata, with nonrecursive archival and explicit descent. The related size-estimation stat race is handled for WAL/SHM only. Missing ordinary code/configuration still aborts; excluded runtimes are skipped before stat and symlinks are not traversed.

All219 Core tests passed, including4 new real temporary-file regression cases; original205 domain tests cover unchanged runtime. Updater SHA256 `f8f08d4556d58ba9ac4b15bce3d7779cf2668250f89408ca5d9f60368b49198f`; test SHA256 `69b7e7b46ef334a0fb69c65ec1c0a65ba3122d7566114b416131260de41de865`. This is an operational code fix in addition to the earlier documentation-only commit; native feature code, helpers,permissions,financial protocol and live databases are unchanged. Final coordinated424-test deployment and bounded server/off-server post-checkpoint results are recorded in the private operational journal.


## Quality program — 2026-10-16

Technical and UI review rules, repaired failure patterns and next-agent constraints are documented in [QUALITY_PROGRAM.md](QUALITY_PROGRAM.md). The quality release is checked on synthetic SQLite databases, isolated providers, clean declared dependencies and actual HTML/API browser emulation. Operational deployment revisions, consistent backup/restore receipts and source-specific verification results are retained in the private action journal. This entry does not assert a physical Telegram/device test or a completed production switch.


### Проверенный состав выпуска качества

Финальная серверная прогонка: 640/640, без ошибок и пропусков; этот компонент — 246 тестов. Финальная прогонка HTML/API — 153 сценария в 13 группах. Копия до обновления скачана с сервера и восстановлена вне сервера для всех четырёх баз. Фактическое переключение и последующая проверка фиксируются отдельно; эта запись не утверждает завершение рабочего развёртывания. [Состав и ограничения выпуска](https://github.com/MarkKoro/progressor_core/blob/main/docs/QUALITY_RELEASE.md).


## 2026-10-17 — factual cross-product journeys

Added Today Together in existing native menus and canonical shared WebApp, explainable source states and completion-aware workout→Food follow-up. Existing single-menu renderers, paid gates, quiet hours, ownership and financial protocol2 remain. Core owns light daily projection, source metadata and preferences-filtered food hints; Food saved replies acknowledge the current meal. Full isolated Linux candidate: 656 passing tests, zero skips, external network denied; source archive SHA256 9e791ad555c84be0d0a7bc3a37833b53cc50733dd214a5d9e759ca309051d7b4. Browser source/evidence and current rollout revisions are recorded in the durable local ecosystem journal. No real payment, paid AI or physical Telegram test. See docs/ECOSYSTEM_CONNECTIONS.md; future sleep support is design-only.

Final validation: Core258 on indexed checks3 snapshot SHA256 88f8a5dc9797e410b3135d9f4529ee3a4cc7ca6a59f7efc9bec57339bd44888c; unchanged native code/tests byte-identical to checks2 (Gym222/Food113/Supply63). 656 passed total, zero skips. Final frontend154 scenarios/10 groups, plus24 interactive diagram states. New day p95 small35.274ms/large79.472ms; full large context876.958ms, no budget relaxation. Pre-deploy checkpoint153280387B SHA256 3f99619b5cf7817da2c79eefc3de8e113a0b24fc153f9c800fff769014bd6f69 restored off-server4/4.


## 2026-10-20 — bounded native journey handoffs, verified candidate

This package separates opening a plan from saving it or confirming review. Food stores owner-bound expiring previews with exact targets, profile/goal revisions and an atomic applied receipt. Concurrent owner edits require a fresh preview; replay never replaces a later goal. Core records explicit review only for the current weight/goal change and target. A routine workout/intake is not proof that the plan was reviewed.

The canonical Core navigation opens the promised native section, with a voluntary bounded return. A tab-local allowlisted handoff is matched to the verified original account/proof, destination and expiry. Navigation writes no meal, workout, dose or goal. Gym transferred launches obtain the native verified identity from whoami even when Telegram SDK unsafe user data are absent; mismatched accounts/proofs, acting mode, onboarding and intervening input remain guarded. See the canonical [journey contract](https://github.com/MarkKoro/progressor_core/blob/main/docs/JOURNEY_HANDOFFS.md), Food [preview contract](https://github.com/MarkKoro/food_bot/blob/main/docs/GOAL_PREVIEWS.md) and Core JQ-v1 with linked research. No second Core application or shared UI is added to a bot.

Linux checks1 passed693 tests without errors/failures/skips (Core275, Gym222, Food133, Supply63), archive SHA256 1a4adb487d4961506f4332cd7e65bad021732a6555eca211f0b4320141e9f237. The later Food confirmation-route correction added2 tests; full Food135 passed on checks2 SHA256 a0cd0d6cd57c6bc0d0479fdc5b4add0b74791f39b9943c423ce0fb2c23955788. Core275/Gym222/Supply63 Python files remain byte-identical to checks1: the combined current backend coverage is695 tests, not two independent full runs. Final Gym HTML identity and Food native header wrapping corrections were separately browser-tested. Native JS checks include four script syntax parses and36 measured assertions,8 Food preview UI cases and8 layout cases. The actual local HTML/API browser report passed 46 recorded cases, with source hashes and fault/layout coverage retained in the operational journal. Browser SDK/user/providers are synthetic; no physical Telegram/iPhone, real payment, paid AI accuracy or full accessibility certification is claimed.

Gym personal last values, workout drafts and pending AI proposals now use verified native viewer/acting-owner namespaces. Unbound legacy guest records are not guessed or imported. A missing verified identity skips personal cache without blocking the native day; the shared own-identity probe has an1800ms request bound and2500ms total deadline including response decoding. Expired responses cannot replace a later successful probe. D04 passed16 shipped-function JS cases and7 actual local Gym/Core cases, including two-account partial-outage isolation, own recovery, Core failure and bounded whoami failure/retry. Exact checks3 archive SHA256 7d8075d27adb656ec4b51ab7b58cce0ea49844b103b887466ba07af918d682ec contains this frontend change; all backend Python matches the immutable Linux evidence described above.

Known follow-up: Gym's existing optional first-visit walkthrough can overlay an incoming plan screen. Route/return checks do not claim that every first-use guide is already coordinated with a purposeful cross-product visit. Preserve mandatory onboarding and do not mark an optional tour completed merely by navigation; a separate follow-up can defer it with an explicit way to resume.

Pre-switch application backup 20261020T094455Z-pre-journeys.tar.gz (159247991B), SHA256 698aced56f0900f2239be97190b03b45950fe2ce115ad70c94ace72d632302f3, was downloaded and restored off-server for all4 SQLite databases, with schema/count/integrity, code/configuration, commands, financial-v2 gate and private SQLite runtime checks. These are application checkpoints, not a globally atomic disk image. Main publication, update-all transaction, installed revisions and post-switch verification are recorded separately in the durable deployment journal; this entry does not assert a completed switch. Additive tables/triggers remain on code rollback; later user/financial writes must be preserved. D06 Supply uncertain-send and D07 Gym add-set retry are separate following packages.
# 2026-10-20 — isolated weekly freshness candidate

Supply weekly aggregate now requires the existing currently permitted projection
and source status `ok`; a degraded shell no longer triggers a SQL count of stale
intakes or a misleading zero active-supplement count. Complete allowed aggregates
beyond the public recent-90 list remain intact. Native consent/financial policy
and source history are unchanged. See [WEEKLY_FRESHNESS.md](WEEKLY_FRESHNESS.md).

Before: three targeted stale/aged/config-disabled regressions failed on the
previous source. Candidate: 13 new cases plus related context/day/permission/review
suites, 92 tests passed with zero skips on isolated Windows/ASGI; reused 13-state
permission fixture passed with stale Supply now null. No Telegram/AI/provider calls,
production writes, publication or rollout. Linux release verification remains pending.



## D09 — Food journal date and saved-time provenance — 2026-10-21

Historical/future Food journal entries no longer become fresh meal anchors just
because they were added now. UTC save provenance remains separate from the
Moscow diary date and unknown consumption time. The inclusive ten-minute age
window, the existing 90-minute Supply slot policy, own access/consent/rest gates,
history, macro/nutrient totals and native schema are unchanged. Previous adapter
payloads remain supported with the same journal-day guard. See
[MEAL_RECORD_TIME.md](MEAL_RECORD_TIME.md).

Validation on isolated Windows databases: 88 related Core tests (including 15
new recorded-time cases), 4 Food API/export cases and 4 actual native HTML
rendering cases passed. The real native Food save → owner snapshot → adapter →
signed Core ASGI probe passed 11 checks; the baseline includes the historical
entry and fails that causal check. No providers, Telegram delivery, consumer,
production or Git changes were made by this isolated implementation. Linux and
combined owner-consent integration remain release gates. The native writer
supports a historical day; no existing end-user backdate UI was demonstrated.


## Combined second journey release gates — 2026-10-21

Candidate D06 delivery outcomes, D07 idempotent set writes, D08 owner metadata/read policy and weekly permission correction, D09 saved-time provenance passed 808 Linux tests with no failures/errors/skips (Core341 checks5; byte-identical Food139/Gym239/Supply89 checks4), plus 58 fresh actual-browser scenarios (46 shadow +12 strict). Runtime/test source freeze SHA256 fcb1a9ece235533d38d6d2c5c4032da5b79f1822500ddd9ca271a5fe214355ef; browser report SHA256 ad288e7b9f75a14dc94af87b3ff2b1c547677691313b0ab5ae068030be916b4c. Browser emulation is not physical Telegram/device testing. Zero provider/AI/payment calls and no extra consumers.

The initial full run exposed an outdated historical-day fixture; its old failure is retained and the corrected Core suite passed. Browser recovery corrected test-only Windows SQLite replacement waiting and an async condition wait; prior negative reports remain preserved. Only Markdown release notes and own-account Food/Gym control-plane scope clarification changed after freeze. The native save timestamp is not claimed to be consumption time.

Publication and controlled rollout are separate from these completed gates. Install owner metadata and protocol1 reader/updater in bounded shadow, verify the compatible new current/fallback, private fresh exports and backup restore, then activate owner gate under both updater locks; preserve financial2 and user writes. Capture and off-server restore-test a post-activation backup containing both persistent gates. Do not use a pre-protocol Core fallback after activation. D05 next-meal choices and optional tour coordination remain a separate third package.

## 2026-10-21 — isolate offline contract readiness from host state

Before activating owner policy, an existing temporary multi-owner weight fixture
was run with absent/present simulated default markers. Only the present case
failed (`owner_sync` returned zero commands), proving that host readiness could
break future updater tests. Added a Core-only explicit test runner, test-owned
updater gates and causal regressions; production reader code/gates are untouched.
Linux full-candidate verification is required before publishing this correction.

## D05 — Explicit next-meal choice, isolated candidate — 2026-10-21

Food can explicitly open up to three qualitative ingredient ideas using the one
canonical Core diet/exclusion preferences. Core owns one Moscow-day planned
choice and bounded idempotent receipts; choose/replace/cancel do not record food,
nutrients, targets or AI attempts. Native Food trial/paid access, source freshness,
owner/proof, concurrent preference edits, lost responses and account changes stay
guarded. Food clear-data atomically advances a monotonic owner reset epoch so old
snapshots and receipts cannot restore a cleared plan. The independent readiness
gate prevents rollback to an older Food purger. See [NEXT_MEAL_CHOICES.md](NEXT_MEAL_CHOICES.md).

Exact isolated current sources: full Windows Core discovered 382 tests, with zero
assertion failures, two pre-existing Windows open-file replacement/cleanup errors
in test_source_snapshots, and 27 explicit Linux-only skips; all 41 new D05
SQLite/ASGI/updater cases passed. Full Food passed147 tests without skips/errors.
Playwright UI tests passed20 cases using actual shipped Food markup/script and
controlled offline responses, including pending-operation reload, reset/proof/
owner races, conflicts, storage refusal, focus and320/390px at100/200% text in
both themes. This UI suite is not an actual running Food→Core backend/browser
integration or physical Telegram/iPhone test. Earlier failed/interrupted reports
are retained. Full Linux and combined actual integration are required separately;
no production feature gate, Git, server, payment, provider or consumer was changed.


## Combined third journey release gates — 2026-10-22

The combined candidate passed 863 Linux Python tests with no errors/failures/skips: full Core388 on immutable source B, plus byte-identical Food147/Gym239/Supply89 from immutable source A. Source B freeze SHA256 5cfc0a7b0b3de71cde582d2f23409cc4a876380f87a8f4844bbd05d69a5845b5; full B archive SHA256 30b0b0a5853a3ea8e1cada25e8e5aff60b32d4e7a99e4392e85767c1caba292b. The first Core run's single failed fixture is retained: its freshly saved Food meal used a UTC journal date when Moscow was already on the following date. Only test_owner_policy.py was corrected to derive Food day from the same saved instant in Europe/Moscow, including the 21:00–24:00 UTC boundary window; original assertions, runtime and frontend bytes were preserved. This is not a claim that save time equals consumption time.

Fresh combined browser evidence on runtime-identical source A passed 58 regressions (46 baseline/shadow +12 strict-owner cases), report SHA256 04970a08170774ad32cefafb0786cf5b837fbe85f25a99f63c4e7548b70b55b9. The temporary next-meal gate was absent during these 58 cases. One separately counted positive coexistence scenario then enabled only the temporary gate and checked real native Food choice -> subscriptions/product switching -> native Gym -> Food return, preserving the planned choice and native meal/nutrient/request counts and macros; report SHA256 721af9d52cab9bc8449206532abe5f152f59481ee8d9576abfba5a9884ec2546. Optional-tour JS17 is counted separately. Earlier D05 actual10 and optional-tour actual10 remain source-scoped, separate evidence; they are not re-counted as fresh combined cases. Browser emulation and synthetic CSS text doubling are not physical Telegram/device tests, browser zoom, WCAG certification, or conversion evidence. No real AI/provider/payment calls or extra bot consumers were used.

These are completed release gates, not proof of a completed deployment or activation. Before publication the four-database off-server restore-tested backup b5c3cc16befec2650b67afb5271210dc1bdb0e70d275b787c3011ff00442734b contains financial2 and owner-consent1; it does not establish next-meal readiness. Install through the existing coordinated updater with next-meal gate absent, verify the completed transaction, new actually running Food/Core services, fresh private Food reset projection, compatible current/updater/fallback and a new compatible backup. Activate next-meal-v1-ready only under both updater locks and then capture/restore-test a post-activation backup containing all three gates. Never remove persistent gates or restore databases over later user writes during ordinary code rollback.

Core retains the single canonical preference store and planned next-meal choice. Keep the choice separate from consumed Food records, preserve reset/ABA/idempotency guards and enforce compatible Food reset purger plus Core/updater protocol1 on recovery.


## 2026-10-23 — fourth journey recovery and read boundaries

The canonical bounded AI cache has a trusted optional synchronous publication
predicate, evaluated in its existing write transaction before cleanup, insert
and eviction. It is byte-identical in all three bots. Food captures its native
reset revision before asynchronous photo/text/voice work and fences both cache
publication and the final native meal transaction; this does not claim a fix
for other-domain purge paths. Food owns its six-hour photo metadata and saved
result recovery; Core receives no draft or image. See Food PHOTO_RECOVERY.md.

Root reviewed the immutable Food12-path overlay (192 local tests, 11 synthetic
process-exit scenarios/36 phases), Gym5-path boundary (Linux58 and separate UI9),
Supply6-path explanation/split fix (94 local tests and separate UI10), and one
Supply Berlin-fold/rest/next-two-reminder holdout. Root's five canonical cache
regressions check publication/reset ordering and default-caller TTL behavior.
These are separately scoped gates, not an additive human UX sample or proof of
physical Telegram/payments/providers. The complete assembled Linux regression
is required on the final freeze before publication; exact results, archive,
normal main revisions, backup restores and deployment are in the durable task
journal and coordinated updater transaction. No new activation gate is added.

## Supply historical timezone provenance — 2026-10-23 candidate

A native owner-CAS holdout reproduced Core relabeling the timezone of a saved
Supply intake when the current profile changed. Source day, recorded UTC,
identity, dose and paid state were unchanged. The Supply-scoped read adapter
now uses only continuous owner-ledger intervals after their first recorded
transition. Missing/legacy/broken lineage or a cutover in the saved second
emits explicit unknown metadata, with no timezone fallback or owner write.
Current profile time still controls the ordinary daily clock; see
docs/SUPPLY_INTAKE_TIMEZONES.md. Shared helpers, mirrors and Gym are unchanged.

An actual frozen-to-candidate reconciliation also exposed a false account-
timezone change notice from repaired historical metadata. That retained failed
holdout is covered by a base profile.updated/type/id/kind guard. A genuine
profile timezone edit still produces its normal notice; other change kinds
keep their existing predicates.

Twelve focused Core regressions use private SQLite and no sockets. A separate
native Supply owner writer/CAS fixture checks old-prefix unknown stability,
new proven-interval stability, return/same-zone/stale-CAS and transaction abort
with nine full snapshots. Local SQLite is3.49.1; target Linux3.54 and the full
assembled release gate are separate required evidence. These scoped checks do
not add924 tests, prove physical Telegram/human behavior, or close every H08
calendar path. A read-only Gym pattern map records further untested leads;
there is no speculative shared-helper rewrite or new consumer/provider call.


## Fifth journey composition — 2026-10-23

The canonical connections window now explains current participation beside the
saved source choice, without implicitly changing access/consent or adding
per-load provider/API work. Reproduced stale settings completions, failed-open
retry and same-view edit loss during a pending save are covered by request/view
ownership, explicit retry and an owned temporary field lock. Eight seconds is
a client acknowledgement budget for settings GET/preferences POST; unknown
write outcome never claims success, cancels a server commit or auto-retries.

The exact UI was reviewed independently with whole-asset Node20 and four Edge
seams (native disabled/pointer behavior, real GET/POST deadlines and409). Owner
paired/unit/fault15, ordering2 and budget3 are distinct scoped evidence, not a
human sample or full native-host/device certification. The six-path historical
Supply candidate has separate12 focused regressions, native9 snapshots and a
retained failed then corrected actual upgrade check. Current-profile timezone
notices remain; repaired old metadata does not create one.

Only Core changes in this composition; all selected native bot bytes and pinned
requirements/constraints stay at the verified fourth release. Shared Python
helpers/mirrors and the three existing gates are unchanged. A new exact source
freeze, full Linux and actual three-host UI gates, bounded four-DB off-server
restore, normal changed-main publication and existing update-all/strict/post
verification are required. Exact final results/revisions/backups are recorded
in the durable journal and updater transaction. A separate Gym timezone baseline
is future scope and is not silently claimed fixed by this release.


## Separate fifth revision B — 2026-10-24

A remains unpublished and immutable. Its936 Linux tests and24 native functional
states passed, but same-health repeated refresh shifted notes by up to150 CSSpx
normally and600 with CSSx2. Root held publication. B changes only canonical
connections JS/test and these notes on top of the reviewed fifth composition.
Measured loading-only note reservations plus the short Checking marker avoid
the old growth/collapse without clipping genuine reason text. Lifecycle cleanup
invalidates reservations on resize/fonts/render/open/close.

The reviewed overlay has Node23 (previous20 plus3),24 paired asset A/B contexts
with0 measured displacement for B, one separately waited actual30s interval,
and independent pointer/error/old-response seams. These are exact synthetic
asset checks; they are separate from the final B Linux936/native24 acceptance,
which must be bound to the new freeze before publication. Existing Supply
historical provenance changes remain unchanged, as do all three native bot
repositories and their pinned dependencies/mirrors. Publish only the changed
Core main by normal FF, preserve all other main refs and three existing gates,
and use fresh four-DB restore-tested backups plus the existing update-all and
strict verifier. No additional consumer, activation, payment or provider test.


## Sixth preference-draft composition — 2026-10-24

Based on completed B Core83ace5c4 with unchanged three bot refs. Three controlled
whole-asset partial-save routes reproduced unrelated local draft loss while
each intended own-section acknowledgement succeeded; these are three routes
with positive conditions, not six independent cases. The exact false baseline
remains retained. A minimal canonical preference registry preserves unrelated
dirty keys across successful partial saves and reports partial success honestly.
Server preferences, write keys, revision, errors, explicit refresh/discard,
request/view ownership and eight-second unknown-write handling remain intact.

Owner held Node35 keeps all previous23 cases and adds12 preference boundaries;
the captured three-route replay passes on the held asset. Independent review,
new frozen Node/Linux/native acceptance and normal rollout are bound in the
durable journal. Planned native acceptance has24 read-only geometry states and
13 owned Core-preference write states (9cross-section routes,3rest,1Food day
prompt),37 mixed states; they must never be called37 read-only checks. Journals
and paid projections stay unchanged. No native source/dependency/helper, payment,
consumer, gate or H08-D change belongs here. Only the three documentation notes
and canonical JS/CJS differ; final source/gates must precede publication, fresh
four-DB off-server backup restores, existing update-all/strict and postbackup.


## Seventh H08 compatibility-only preparation — 2026-10-26

Local preparation uses the exact sixth publication source364/freeze5aab34f2,
Core main c4ee51193421e05797442531dbc79c43889827e5 and unchanged three bot refs.
Sixth installed transaction20261026T153235Z-1890433 passed strict verification
SHA256 3af48df573feae1b32e11282ffd8f59c3f44b46c6f6372a3d97af44ca37ac3de.
Sixth close is now complete, bound by receipt SHA256
36aeb2be87ad2acc09a1730e3d711a45b6676648a8b36e6a8faec5213dba4eb3.
Post-backup bundle SHA256
0a7bca894beb08a7933793366271d7ab0a68f126944e74f468e7aed46ee2a25a
passed all four off-server restores. Exactly two verified expanded copies were
removed (544587640 bytes); archives/off-server copies remain. Root final15:59UTC
GitHub4 observation matched installed c4ee/Core and the three unchanged bot heads.
Fresh exact Git metadata binding is still required before the next release
freeze; this local candidate has not itself been frozen, tested or published.

The independently reviewed four-path shim (review10da74af) adds a read-only
reserved-object presence guard and filters only nonnumeric/free notification
triggers after adoption or inspection failure. The fallback deliberately
suppresses even genuinely new free sessions until full H08 runs again. No schema,
epoch, admission/writer, sourcebot, dependency, UI, AI, sender or delivery-key
change is introduced. Numeric-only behavior and existing guards remain; mixed
energy estimates narrow to retained numeric rows, and the pre-existing later
nutrient priority can become selected. Full-H08 owner-reset design e55c7996 /
addendum88f3d0b4 requires T>max(global epoch,current Core identity creation) in
both future admission and candidate. Its ten holdouts remain planned and no
writer, full UTC fix or owner-reset implementation/testing is claimed here.

Accepted shim evidence is19 portable Windows unit methods and an independent
8-method/75-observation controlled SQLite/old-new review, with overlap explicitly
declared. A missing-tzdata base-Python failure is retained; the unchanged cases
passed in the existing declared venv. No native/provider/delivery or full Linux
claim follows from these pure checks. Proposed next acceptance is Core424 plus
unchanged Food192/Gym244/Supply95,955 total, and the unchanged canonical Node35.
These proposed release gates have not run for this composition. Shared JS/CJS
and all three native products are byte-identical to sixth, so no repeat native
UI37 is required by this backend-only scope; earlier evidence is not renamed as
a newly executed run. A new source freeze, appropriate Linux/rollback checks,
fresh bounded four-DB backup/off-server restore, normal FF main, existing
update-all/strict verification and post-backup restore remain root release work.
