# Обновление Progressor Core

Исходный код: https://github.com/MarkKoro/progressor_core, ветка main.
Серверный checkout: /srv/progressor_core/repository. Служба progressor_core.service
работает из /srv/progressor_core/current — ссылки на неизменяемый выпуск
/srv/progressor_core/releases/<UTC>-<commit> с собственным .venv.

После подключения к серверу выполните `update-progressor` (короткое имя: `updatecore`).
Если вы вошли не под root, используйте `sudo update-progressor`.
`update-progressor --check` проверяет доступность main и текущий статус без переключения.

Команда проверяет чистый checkout/main/remote и обычную историю без переписывания,
получает main, создаёт отдельный выпуск, устанавливает requirements и проверяет
зависимости. Все тесты Core работают с временными базами и тестовыми провайдерами.
Затем команда создаёт онлайн-копию SQLite, проверяет восстановленную копию,
сохраняет прежний код и закрытую конфигурацию с SHA256. Только после этого
переключает ссылку и перезапускает одну службу Core. Проверяет health/ready и
сохранение исправности ранее доступных источников. Ошибка запуска возвращает
прежний код вместе с прежним .venv; живая база не восстанавливается поверх новых записей.
Успешный выпуск сохраняет свой commit в REVISION; повторное обновление той же
версии не перезапускает службу. Одновременные обновления запрещает блокировка.

Резервные копии `/root/progressor-backups/*-core-update.tar.gz` закрытые: содержат
ключи и персональные данные. Их нельзя загружать в GitHub. Команда выводит путь
и SHA256; для защиты от потери всего сервера архив нужно также скачать на
другое устройство. Это копия приложения Core, не образ VPS и не копия всех ботов.
Полную копию четырёх приложений делаем отдельно перед совместным выпуском.
Старые выпуски/окружения не удаляются автоматически.

Код доступен для правок в GitHub. SQLite `/var/lib/progressor/core.sqlite3`,
`/etc/progressor/core.env`, signing.key и токены существуют только на сервере.
Все четыре продукта обновляются командой `update-all`; [инструкция](UPDATE_ALL.md).
Прежние команды ботов сохраняют свои имена и используют тот же механизм. Правка shared helper требует
синхронизации копий и публикации main соответствующих ботов; один update-progressor
обновляет только Core. Ни один git pull не меняет уже запущенный Python-процесс без
перезапуска, поэтому команда Core включает проверенный перезапуск.

Первичная установка команд и release-runtime.conf выполняется после проверенной
полной копии: стабильный launcher в /usr/local/bin/update-progressor, его ссылка
updatecore и проверенная копия deploy/update_progressor.py в /srv/progressor_core/updater.
Службе нужен drop-in deploy/release-runtime.conf; текущий выпуск обязательно уже
имеет .venv. Не применяйте drop-in к старому выпуску без такого окружения.


## Одна точка редактирования

Само приложение Core отсутствует в репозиториях ботов. Для небольших локальных адаптеров канонический код находится в этом репозитории shared/. Скрипт deploy/sync_bot_helpers.py проверяет одинаковость копий в явно указанных локальных checkout (--gym/--food/--supply); --write переносит изменения. Затем запускаются тесты ботов и публикуются их main. Это адаптеры для автономной работы каждого бота, не второй сервер Core.


Core-only entry points now delegate to deploy/update_all.py with --only core. There is one durable recovery engine and common global/Core locks. Initial installation must include both tested updater files and preserve the existing command backups.
