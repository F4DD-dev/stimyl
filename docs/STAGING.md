# Staging

Отдельный контур, не прод. `main` на прод не выкладывать, пока команда не подтвердит.

## Что отдельное

| | staging | prod |
| --- | --- | --- |
| Домен | свой, не `stimyl.online` | боевой домен |
| Бот MAX | свой токен | свой токен |
| База | своя PostgreSQL | своя PostgreSQL |
| `ENV` | `staging` | `prod` |
| `DEV` | `true`, чтобы снять `user_id` командой `/whoami` | `false`. Вместе с `ENV=prod` сервис не стартует |

`DEV=true` и `ENV=prod` одновременно запрещены: процесс падает на старте.

## Переменные

`DATABASE_URL` со `sslmode=verify-full`, `DATABASE_SSL_CA` на сертификат базы. `MAX_TOKEN`, `MAX_WEBHOOK_SECRET`, `MAX_WEBHOOK_URL=https://<staging-домен>/webhook`, `SESSION_SECRET`, `COOKIE_SECURE=true`, `PUBLIC_BASE_URL=https://<staging-домен>`, `ENV=staging`, `DEV=true`, `SEED_DEMO=false`.

Вебхук только у staging-бота. Long polling этого бота не запускать.

## Как задеплоить

1. Ветка `feature/accounts`.
2. Новая база и новый бот. Пользователь базы не суперпользователь.
3. Сборка `pip install .`, запуск `sh docker/entrypoint.sh`. Скрипт накатывает миграции, затем поднимает воркер и API.
4. Проверка: `GET /health` и `GET /ready`. `/ready` ждёт heartbeat воркера.
5. В MAX мини-приложение staging указывает на `https://<staging-домен>/cabinet`.

## Как откатить

1. Задеплоить предыдущий коммит ветки.
2. Если новая миграция уже применена, на staging: `alembic downgrade -1`, проверить `/ready`, и только потом решать, нужен ли тот же шаг где-то ещё.
3. Откат схемы не возвращает удалённые строки. Перед рискованным шагом нужен свежий бэкап этой базы, не продовой.
