<p align="center">
  <img src="design/logo.png" width="140" alt="Стимул">
</p>

<h1 align="center">Стимул</h1>

<p align="center">
Делаем учёбу проще<br>
  <br>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white&labelColor=1f2937" alt="Python 3.12">
  <img src="https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white&labelColor=1f2937" alt="FastAPI">
  <img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white&labelColor=1f2937" alt="PostgreSQL 16">
  <img src="https://img.shields.io/badge/Docker-образ-2496ED?logo=docker&logoColor=white&labelColor=1f2937" alt="Docker">
</p>

---

## Что умеет

**Ученик**

- Пишет вопрос нейросети → получает объяснение простым языком, похожий пример и короткую практику
- Ответы на задания принимает и проверяет код; модель отвечает только за объяснение и разбор ошибки
- Видит свой прогресс: статусы тем, доля верных ответов

**Учитель**

- Карта тем класса: кто сделал задания, кому нужна практика, и кто остаёт 
- Работы: тема задаётс словами в кабинете, черновик с ответами проверяется и отправляется кнопкой
- Задания: учитель может: использовать встроенную нейросеть "Стимул" для составления следующих тем для класса, загрузить документ с темой и по ней составить тест
(ИИ полностью собирает тест сам), выбрать определенных учеников кому отправить тест и ТД.
- Никогда не видит текст личных вопросов и переписку тренировки

**Общее**

- Личный помощник с историей чата
- Материалы урока (PDF, DOCX, PPTX, TXT, фото) — генерация «по загруженному»
- Вход по коду класса или через MAX (пока что в прототипе вход просто по выбору Учитель/Ученик, класс тоже единый).

**Главные фишки**

🤖 ИИ-репетитор

Персональный помощник, который не просто выдаёт готовые ответы, а помогает разобраться в материале. Объясняет сложные темы простым языком, показывает аналогичные примеры и предлагает небольшую практику для закрепления знаний.

🧠 Интеллектуальная проверка знаний

Проверка ответов отделена от генерации объяснений нейросетью. Система самостоятельно оценивает результаты попыток, отслеживает ошибки и определяет степень освоения каждой темы.

📊 Карта знаний класса

Учитель получает наглядную картину успеваемости: видит освоенные темы, выявляет пробелы в знаниях и определяет учеников, которым требуется дополнительная практика.

📚 Генерация заданий по материалам урока

Учитель может загрузить учебный документ (PDF, DOCX, PPTX, TXT или изображение), после чего нейросеть проанализирует материал и автоматически подготовит тест на его основе. Доступна отправка заданий выбранным ученикам.

🎯 Индивидуальный подход

Система отслеживает результаты ученика по каждой теме, учитывает предыдущие попытки и помогает определить, какие знания требуют повторения и закрепления.

🔒 Конфиденциальность личного обучения

Личные вопросы ученика и переписка с ИИ-помощником отделены от учительской аналитики. Учитель может отслеживать учебные результаты, не получая доступа к содержанию личных обращений ученика.

## Как устроено

| Слой | Технология |
| --- | --- |
| API и бот | Python 3.12, async FastAPI; вход из MAX — webhook `POST /webhook` или long polling |
| База | PostgreSQL 16, миграции Alembic |
| Модель | Интерфейс `app/llm` — GigaChat (от qwen отказались, так как openrouter отдаёт модели через cloudflare) |
| Фронт | Мини-приложение MAX (vanilla JS), статика в `app/web` |
| Деплой | Timeweb App Platform + PostgreSQL, Docker-образ из `Dockerfile` |

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

Секреты лежат только в `.env`: `MAX_TOKEN`, `MAX_WEBHOOK_SECRET`, `SESSION_SECRET`, `DATABASE_URL`, ключ модели. Сюда мы это не коммитили.

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

Класс 8Б, предмет Математика и Физика (Темы и предметы можно создавать Учителю вручную). При отправке новых заданий ученикам приходит сообщение в чате бота max.

Повторный `python -m app.db.seed` не плодит строки.

## Статусы

Считаются кодом по всем попыткам темы, без скользящего окна. Пороги в настройках, старт: ниже 50% или две ошибки подряд — `repeat`, от 80% и есть верная повторная проверка — `mastered`, иначе `needs_practice`. Нет попыток — нет статуса.

Доля верных на экране — из тех же попыток.

Эталон числового ответа сравнивает код. Короткий текст объяснения может дописать модель, если задан `LLM_BASE_URL`; задания и верный ответ берутся из банка 8 класса. В промпт не уходит текст личного вопроса. Если модель возвращает эталон практического задания, ответ отбрасывается.

Личные реплики тренировки пишутся с видимостью `private`. Кабинет их не читает.

## Тесты

```bash
pytest
```
