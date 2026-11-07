# Стимул

Бот в MAX и кабинет учителя для одного класса. Ученик пишет вопрос, получает объяснение и практику. Учитель видит статусы тем, а не переписку.

Сейчас в коде фазы 0–4 из `docs/PLAN.md`: сервис, демо-класс 8Б, цикл тренировки, статусы и кабинет. Работы учителя, материалы урока и масштаб — следующие фазы, когда живой webhook уже доступен снаружи.

## Запуск

Нужны Docker и публичный HTTPS только для боевого webhook. Локально сервис ходит в PostgreSQL из Compose. Зависимости зафиксированы в `requirements.txt` — Dockerfile ставит их через `pip install -r requirements.txt`.

Сборка образа:

```bash
docker build -t stimul .
```

Запуск приложения и PostgreSQL вместе через Compose:

```bash
copy .env.example .env
docker compose up --build
```

Только контейнер приложения (нужна доступная база по `DATABASE_URL`, например `docker compose up -d db` и хост `host.docker.internal`):

```bash
docker run -d --name stimul -p 8000:8000 --env-file .env stimul
```

Локальная разработка без Docker:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
copy .env.example .env
```

В другом процессе, когда база уже поднята:

```bash
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.db.seed
```

`alembic upgrade head` и повторный seed выполняются при старте контейнера `api`.

Проверки:

- `GET /health` — процесс жив
- `GET /ready` — есть соединение с базой

Приложение с хоста, если база проброшена на localhost:

```bash
set DATABASE_URL=postgresql+asyncpg://stimul:stimul@localhost:5432/stimul
alembic upgrade head
python -m app.db.seed
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Секреты лежат только в `.env`: `MAX_TOKEN`, `MAX_WEBHOOK_SECRET`, `SESSION_SECRET`, `DATABASE_URL`, ключ модели. Файл не коммитится.

## MAX

Запросы к API идут на `https://platform-api2.max.ru`, заголовок `Authorization` без слова Bearer. Сертификат хоста выпущен корневым УЦ Минцифры, файл `certs/russian_trusted_root_ca.pem`.

Пока нет публичного HTTPS на порту 443, события забираются long polling:

```bash
python -m app.bot.poll
```

Команда бота `/start`:

```bash
python -m app.max_client.publish
```

Webhook для боя: `POST /webhook` на `https://<домен>/webhook`. Если задан `MAX_WEBHOOK_URL`, стартовый скрипт сам подписывает бота. Секрет приходит в заголовке `X-Max-Bot-Api-Secret`. Long polling и webhook вместе не работают.

## Timeweb App Platform

Вкладка «Приложение», ветка `feature/accounts`, фреймворк FastAPI. Команда сборки: `pip install .`. Команда запуска: `sh docker/entrypoint.sh`. Проверка состояния: `/health`.

В переменные положите `DATABASE_URL` (для облачной PostgreSQL с TLS добавьте в конец `?ssl=require`), `MAX_TOKEN`, `MAX_WEBHOOK_SECRET`, `SESSION_SECRET`, `COOKIE_SECURE=true`, `APP_TIMEZONE=Asia/Vladivostok`, `TEACHER_MAX_USER_ID`, `MAX_ROOT_CA_PATH=certs/russian_trusted_root_ca.pem`.

Когда панель покажет адрес приложения, добавьте `MAX_WEBHOOK_URL=https://<домен>/webhook` и запустите деплой ещё раз. В настройках бота на business.max.ru мини-приложение — `https://<домен>/cabinet`. Перед этой подпиской остановите локальный long polling.

`TEACHER_MAX_USER_ID` — числовой id учителя в MAX. Пока он пустой, в кабинет входит демо-учитель из seed.

Кабинет: `/cabinet`. Прогресс ученика: `/student`. Оба ждут `initData` мини-приложения MAX.

## Демо-данные

Класс 8Б, предмет «Математика», темы: дроби, линейные уравнения, квадратные уравнения и дискриминант, геометрия. Учитель «Марина Сергеевна» и ученики Алексей, Аня, Кирилл, Ольга — вымышленные, их id MAX тоже вымышленные.

Повторный `python -m app.db.seed` не плодит строки.

## Статусы

Считаются кодом по всем попыткам темы, без скользящего окна. Пороги в настройках, старт: ниже 50% или две ошибки подряд — `repeat`, от 80% и есть верная повторная проверка — `mastered`, иначе `needs_practice`. Нет попыток — нет статуса.

Доля верных на экране — из тех же попыток. Серия — дни подряд с хотя бы одной проверенной практикой, часовой пояс `APP_TIMEZONE`.

Эталон числового ответа сравнивает код. Короткий текст объяснения может дописать модель, если задан `LLM_BASE_URL`; задания и верный ответ берутся из банка 8 класса. В промпт не уходит текст личного вопроса. Если модель возвращает эталон практического задания, ответ отбрасывается.

Личные реплики тренировки пишутся с видимостью `private`. Кабинет их не читает.

## Тесты

```bash
pytest
```

На этой машине Docker не установлен, поэтому автоматические тесты гоняют те же миграции Alembic на временном SQLite. Боевая база в `compose.yaml` — PostgreSQL.
