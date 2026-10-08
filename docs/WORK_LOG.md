# Журнал Progressor Core

2026-10-08: выделен единственный канонический Core в MarkKoro/progressor_core main; прежняя копия приложения удаляется из Gym. Сохранены отдельные базы/процессы всех трёх ботов и Core.

Подготовлены детерминированные метрики силы/сравнимой нагрузки/MET, контекстные inline подсказки с покрытием/происхождением/подписками и скрытием на 7 дней, ограниченный AI context v2 и owner-local попытки ИИ. Добавлены ручные действия родных интерфейсов без автоназначения доз.

Проверка Linux с отдельным venv Core: 83 Core + 52 Food + 49 Gym + 6 Supply = 190 тестов, все passed; только mocks/временные базы. Реальные три WebApps: 15 сценариев, 0 AI POST; прежние 9 переходов launch/target также прошли. Сценарии физического Telegram и реальные платежи не заявляются.

В deploy/ подготовлены update-progressor/updatecore: проверенная staging версия с собственным runtime, онлайн backup/restore verification, атомарное переключение, health/readiness, rollback кода без перезаписи живого ledger. Неизменённый main — no-op. Операционные инструкции docs/DEPLOYMENT.md.

80 дополнительных предложений по 23 продуктам/2 платформам — docs/OPPORTUNITIES.md; идеи не внедрены. Научные основания/границы — docs/ENERGY_EVIDENCE.md; UX — docs/UX_REVIEW.md. Production rollout и фактические ревизии/архивы регистрируются в закрытом операционном журнале на сервере и локальном ACTION_JOURNAL.md, а не в открытых runtime-конфигурациях.


## 2026-10-08 Coordinated updater

Added update-all for four fixed main repositories, isolated requirement reconciliation even at unchanged SHA, all nine active units including legacy Food API, common locks/Core-only delegation, durable interrupted recovery, restore-verified application checkpoints, exact changed-path Git recovery preserving tracked Food DB and later ledger writes. Existing update_all_bots handles unrelated projects and stays unchanged. Native targeted command names delegate to the same engine. New marketing previews/user journeys/workout surface+nutrition notifications requested and queued separately; not part of this updater release. Linux dependency staging passed Gym49 tests; full Core/updater suite and live installation evidence recorded in the durable local/server action journal. See docs/UPDATE_ALL.md.
