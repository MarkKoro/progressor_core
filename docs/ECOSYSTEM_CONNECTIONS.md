# Связанные сценарии: общий день и завершение действия

Канонический backend и интерфейс остаются только в этом репозитории. Боты содержат свои предметные операции и согласованные копии `shared/progressor_bot.py`. Новые возможности не создают Telegram consumers, платные запросы, скрытые изменения цели или доз.

## Сегодня вместе

`GET /api/v1/me/connections/today?target=gym|food|supply` — только подписанный собственный аккаунт. Параметр `user_id` не меняет владельца. `/internal/v1/connections/today` — только прежний loopback control protocol; принимающий продукт определяется подписанным source, не полем тела.

`Store.daily_snapshot` читает в одной транзакции собственные membership profiles, факты тренировок текущего московского дня питания, один дневной Food aggregate и полный счётчик отметок Supply в нужном местном дне. Векторы упражнений, блюда по отдельности, анализы и текст дозировок не декодируются. Общий контекст, рекомендации и ИИ ради обзора не рассчитываются. Отметок может быть больше 90: дневное число не ограничивается публичным recent-intakes списком.

Питание и сопоставление тренировок сохраняют прежнюю границу Food — Москва UTC+3. Приёмы Supply относятся к его собственному часовому поясу; дата и пояс видны отдельно. Обзор различает завершённые сессии, незавершённые записи и рабочие подходы; обе поверхности Gym сохраняются. Отсутствие записи остаётся неизвестным фактическим поведением.

Source health отдельно объясняет: профиль ещё не подключён, связь выключена пользователем, нет активного доступа, нужен Supply consent, источник устарел/недоступен, отдых. Только ready-источники оплаченного получателя показывают факты. В ответ не попадают внутренние исключения или секреты; last-sync означает успешное чтение источника, а не время последней активности человека.

В WebApps обзор находится в «Связь продуктов», загружается автоматически при открытии и обновляется раз в30с только при видимом открытом окне. Обновление не перестраивает формы настроек. Запоздалый ответ от старого окна/предыдущей перерисовки не заменяет текущий результат. Ошибка сохраняет предыдущий результат с явной отметкой и безопасным повторным чтением. Закрыть окно можно сверху даже во время ожидания чтения.

Во всех native ботах: «Связь продуктов» → «Сегодня вместе». Используется существующий renderer единственного меню; новых исходящих сообщений от просмотра нет.

## Когда прежнее напоминание больше не нужно

Адаптер Food добавляет необязательный `latest_meal_at` к дневному aggregate из существующего `created_at`. Это время сохранённой записи, не доказательство времени еды или достаточности питания. Оно относится к выбранному дню журнала; внесение вчерашнего блюда сегодня не закрывает сегодняшний сценарий. Старый v1 payload без поля остаётся валиден, timestamp с новым полем обязан иметь timezone.

`journey.workout_follow_up` использует только доступные свежие записи:

- нет завершения — нет напоминания «после тренировки»;
- новая запись еды того же дня после последнего завершённого занятия и не в будущем — прежняя workout-card и Food push больше не нужны;
- явно подтверждённый полный день — прежнее напоминание не повторяется;
- правка/удаление пересчитывает факт; следующее занятие после еды снова может открыть сценарий;
- неполная свободная сессия не превращается в завершённую. При смеси завершённых и свободных сессий inline-сводка сохраняет подходы обеих поверхностей; push не прерывает текущую незавершённую сессию.

Это предотвращение лишнего напоминания. Оно не означает, что нутриенты/энергия/восстановление полностью закрыты, и не меняет цель Food. Остальные существующие причины подсказок, лимиты, seen/dismissal, opt-in, тихие часы, возраст события и no-replay после отдыха сохраняются.

Ответ Food на сохранённую еду проверяет реальное завершение и подписывает, что этот приём уже учтён в собственном итоге. Краткий ответ не ждёт синхронизации Core ради подтверждения собственных КБЖУ.

## Единые пищевые предпочтения

`native_hints` использует тот же curated `shared/food_sources.py`, что справочник и недельный план. Веганский/вегетарианский выбор и группы исключений применяются к примерам белка, железа и B12. При отсутствии проверенного примера он не выдумывается; обогащённые продукты при неизвестном составе требуют этикетки. Числа остаются оценками состава записанных блюд, а не диагнозом. Пороги показа не менялись.

## Проверка и развитие

Регрессии: `tests/test_ecosystem_day.py`, обе поверхности `test_workout_surfaces.py`, прежние notification/permission/ownership tests, реальные native handlers всех трёх ботов, Food `test_native_meal_reply.py`. Изолированная Linux-регрессия: 656 тестов,0 пропусков. Браузер: actual HTML/API с synthetic Telegram proof; реальные устройства и платежи не имитируются как проверенные.

Исследование и воспроизводимая кодировочная таблица: [ECOSYSTEM_RESEARCH.md](ECOSYSTEM_RESEARCH.md), [будущий сон](ECOSYSTEM_SLEEP_DESIGN.md). Прежние функции не считаются добавленными повторно. Будущий sleep connector не включён в текущие source allowlists и не выдаёт несуществующую поддержку HealthKit из Telegram.


## Проверка окончательного чтения

Частичный `intake_owner_day` индекс принадлежит Core и включает только текущие Supply intake entities. Он помогает выбирать последние90 отметок и считать нужный местный день, не меняя данные или историю. На копии большого набора ответы до/после совпали; затем проверены все258 Core tests. Native code/tests совпадают с успешным checks2 (Gym222/Food113/Supply63). Итог656 без пропусков. Финальный Core snapshot SHA256: 88f8a5dc9797e410b3135d9f4529ee3a4cc7ca6a59f7efc9bec57339bd44888c.

На Linux/ASGI после10 прогревов,100 измерений и5 конкурентных запросов: обзор дня p95 малый35,274/большой79,472мс; настройки64,999/97,675мс; общий контекст78,766/876,958мс. Большой набор:1004 сессии,20060 подходов,4122 блюда,10000 отметок. Все ответы200. Это лабораторный backend-замер, не задержка Telegram/мобильной сети. Первоначальные неоптимизированные результаты сохранены; бюджет не повышался.


## Saved choice and current participation — 2026-10-23

The shared settings window keeps each saved source checkbox and shows a separate
current status/reason beside it, from fresh target-context Today health. An
enabled checkbox does not promise current paid access, freshness or Supply legal
consent. The existing expandable provenance remains available. Unknown/missing
status and read errors never appear as ready; an unsaved toggle is labelled as
unsaved. There is no extra per-load API or AI call and no new payment/consent CTA.

Old settings GET/POST completions cannot replace a newer reopened form. While a
preferences save is pending, its own input/select fields are temporarily disabled
and Close stays available. On a current error the choice remains and its fields
are restored; an old completion cannot unlock a new view. GET settings and POST
preferences have an eight-second client acknowledgement budget. This design
limit does not cancel or undo a server commit, and never automatically retries
a write. Failed opens clear obsolete controls and offer a focused read-only
retry. A409 preserves the choice and explicitly warns that refresh resets it.

The canonical regression is tests/test_connection_readiness.cjs. Synthetic
asset-only DOM/fault cases are separate from actual native HTML/API checks,
physical Telegram/device tests and human comprehension measurements.


## Stable repeated refresh — revision B, 2026-10-24

The unpublished A passed its functional gates but repeated checking text caused
measured temporary layout shifts. B keeps each currently measured note height
while showing a short Checking marker. All measurements happen before writes.
The minimum height is loading-only, never a maximum or clipping rule; a truly
new reason or an error returns to natural layout. Resize/font loading invalidates
old pixel reservations, and render/open/close remove their own listeners. No
extra request, provider, UI preference, entitlement or consent action is added.

Node23 preserves all20 request/draft/acknowledgement cases and adds3 scoped
reservation/lifecycle cases. Separate paired asset geometry and one actual30s
timer case are synthetic browser evidence; the final frozen composition also
requires its own actual three-host checks. Neither is physical Telegram or a
human comprehension study. Exact source-bound results live in the durable
release journal; no result from A is renamed as B.
