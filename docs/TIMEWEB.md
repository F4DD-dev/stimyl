# Timeweb Cloud — для агента

Публичный API: `https://api.timeweb.cloud`. Заголовок `Authorization: Bearer <ключ>`. Ключ человек даёт в чат, в репозиторий и в `.env` его не писать. Страница документации: `https://timeweb.cloud/tools/api-docs`. Контракт сверяй ответом API: неверный JSON возвращает список полей, а не молчаливый успех.

## Что уже есть

Два приложения, оба с GitHub `F4DD-dev/stimyl`, ветка `main`. Сборка `pip install .`, запуск `sh docker/entrypoint.sh`, проверка `/health`. Регион `ru-3`.

| Приложение | id | Адрес | Снаружи |
| --- | --- | --- | --- |
| Stimyl | 277859 | `f4dd-dev-stimyl-c213.twc1.net` | Соединение часто обрывается |
| Копия Stimyl | 279257 | `stimyl.online`, `f4dd-dev-stimyl-1cea.twc1.net` | Отвечает. Сюда ставить мини-приложение в MAX |

Одна база PostgreSQL 16, id `4226125`, имя `stimul`, порт `5432`, публичный IP `193.188.23.51`, локальный `192.168.0.4`. Пресет `4753` (ru-3, 1 CPU / 1 ГБ / 8 ГБ, 1200 ₽). Пользователь и имя базы — `stimul`. Пароль в API не читается (`hidden-by-api-key-policy`), он только в панели Timeweb и в переменной приложения.

`DATABASE_URL` для приложения: `postgresql+asyncpg://stimul:<пароль>@193.188.23.51:5432/stimul?ssl=require`. Код сам переписывает `postgresql://` в `postgresql+asyncpg://` и для чужого хоста включает SSL.

## Как менять

- Список: `GET /api/v1/apps`, `GET /api/v1/dbs`.
- Переменные: `PATCH /api/v1/apps/{id}` с полным объектом `envs`. Это замена всей карты, не добавление ключа, и сразу деплой. `GET` значения прячет.
- Повторный деплой: `POST /api/v1/apps/{id}/deploy` с `commit_sha` из 40 hex.
- Логи: `GET /api/v1/apps/{id}/logs`.
- Внешний IP базы: `PATCH /api/v1/dbs/{id}` `{"is_external_ip": true}` только когда статус `started`. Иначе `409 wrong_cluster_status`.
- Админ: `POST /api/v1/databases/{id}/admins` с `login` и `password`. Пароль от 8 символов: латиница, цифра и знак из набора Timeweb. `token_urlsafe` не подходит.
- База внутри кластера: `POST /api/v1/databases/{id}/instances` `{"name": "..."}`. Владелец: `PATCH .../instances/{instanceId}` `{"owner_id": ...}`.
- На PostgreSQL 15+ без владельца схемы `public` Alembic падает с `permission denied for schema public`. После смены владельца деплой нужно запустить ещё раз.

`POST /api/v1/databases` с `type` `postgres14`…`postgres18` и `preset_id` создаёт кластер сразу. Тип `postgres` без версии устарел. Не отправляй такой запрос, чтобы узнать поля: каждый успешный ответ — отдельная платная база. Сейчас лишние кластеры уже удалены, живой один: `4226125`.

Секреты приложения (`MAX_TOKEN`, `MAX_WEBHOOK_SECRET`, `SESSION_SECRET`, `DATABASE_URL`) лежат только в env Timeweb. `MAX_WEBHOOK_URL` задан у приложения 277859. У копии его нет, чтобы два процесса не перехватывали подписку бота друг у друга.
