# Аккаунты

Вход только через базу. В памяти процесса пользователей нет.

`user.id` из мини-приложения и `user_id` из апдейта бота **не считаются одним числом**, пока это не подтверждено живой парой. Привязка мини-приложения кодом описана ниже и в код не внесена: её нужно подтвердить до реализации.

## Откуда взяты поля

Проверено 2026-10-30:

- Бот, OpenAPI `schema.yaml` репозитория `max-messenger/api-schema`, объект `User`: поле `user_id`, описание «Users identifier», int64. Так же уходит `bot_started.user` и `message.sender`.
- Мини-приложение, `dev.max.ru/docs/webapps/validation` и `dev.max.ru/docs/webapps/bridge`: в `initData` объект `user` с полем `id` (в примере `67890`).
- Ни на одной из этих страниц нет фразы, что `user.id` и `user_id` — одно и то же значение. Имена полей разные.

`POST /api/session` ищет `auth_identities.provider = max_webapp`. Сама по себе цифра из `initData` такую строку не создаёт. Её пишет одноразовый билет из `start_param` или флаг `ALLOW_ID_MATCH`, пока он выключен. Кабинет учителя в браузере открывается ссылкой-билетом и от этого равенства не зависит.

## start_param

В Bridge и в `initData` поле `start_param` есть. Его даёт ссылка `https://max.ru/<бот>?startapp=<payload>` и кнопка `open_app` с `payload`. Сервер видит его только внутри проверенного `initData`, не из `initDataUnsafe`.

Как привязать кабинет без ручного кода, когда числа `user.id` и `user_id` ещё не сверены:

1. Бот по явной кнопке «Мой прогресс» или «Открыть кабинет» создаёт одноразовый билет на 5 минут. `/start` билет не создаёт. В кнопку `open_app` кладётся payload из букв, цифр, `_` и `-` (до 512 знаков).
2. MAX открывает мини-приложение. В `initData` приходит `start_param` = этот payload.
3. Сервер проверяет подпись `initData`, находит билет по хэшу и в одной транзакции пишет `auth_identities(provider=max_webapp, external_id=user.id)` на того пользователя, которому выдан билет.
4. Билет гасится. Повтор не создаёт вторую привязку: мешает `unique(provider, external_id)`.

`ALLOW_ID_MATCH` по умолчанию выключен. Включать его только после живых пар `user.id` и `user_id`: тогда сервер копирует идентификатор и билет не нужен. Пока пар нет, билет остаётся.

Если привязки нет, мини-приложение показывает «Открой приложение кнопкой из чата с ботом» и кнопку «Вернуться в чат» (`WebApp.openMaxLink`). Это не ответ 403. 403 — закрытый или ещё не одобренный доступ, отдельный экран. Ученик поле кода не видит.

## Схема

```mermaid
erDiagram
  users ||--o{ auth_identities : has
  users ||--o{ consents : accepts
  users ||--o{ user_sessions : opens
  users ||--o{ web_login_codes : receives
  users ||--o| teacher_applications : files
  users ||--o{ audit_log : acts
  schools ||--o{ classes : contains
  classes ||--o{ enrollments : has
  classes ||--o{ class_teachers : has
  users ||--o{ enrollments : joins
  users ||--o{ class_teachers : teaches
  users {
    int id
    string role
    string status
    string display_name
    datetime deleted_at
  }
  auth_identities {
    string provider
    string external_id
    datetime revoked_at
  }
  user_sessions {
    string token_hash
    datetime expires_at
    datetime revoked_at
  }
```

`signup_hints` хранит ключ класса до согласия и пользователем не является.

## Сценарии

Ученик:

1. Нажимает старт в MAX. Бота ещё нет в `users`.
2. Бот просит согласие. До кнопки «Согласен» строка не создаётся, текст вопроса не пишется.
3. «Согласен» создаёт `users` и `auth_identities(provider=max)` в одной транзакции. Повтор не создаёт вторую строку.
4. Если ссылка была `https://max.ru/<бот>?start=<join_key>`, после согласия ученик попадает в класс. Без ключа тренировка есть, на карте класса его нет.
5. Код класса можно прислать сообщением (`8BDEMO` у демо-класса).

Учитель:

1. Тот же вход и согласие. Роль пока `student`.
2. Пишет «Я учитель», затем ФИО и школу. Заявка `pending`. Кабинета нет.
3. Админ выполняет `python -m app.admin approve <id>` или учитель присылает код `T######` из `python -m app.admin invite`.
4. Роль становится `teacher`. Команда `/start` кабинет не открывает: она ведёт в то же знакомство, что и у ученика. Ссылку даёт только явная кнопка «Войти в кабинет». В тексте нет цифр кода: кнопка типа `link` ведёт на `/cabinet?ticket=…`. Билет действует 5 минут, один раз, не больше 5 выдач в час.
5. Страница по этой ссылке меняет билет на cookie. Сессия 12 часов простоя, не дольше 7 дней, продлевается при заходе. «Выйти на всех устройствах» — `POST /api/logout-all`.

Админ:

1. Идентификатор MAX указан в `ADMIN_MAX_IDS` до первого согласия: роль `admin`.
2. Дальше консоль: `users`, `schools`, `audit`, `approve`, `block`, `unblock`, `close`, `delete --yes`, `invite`, `transfer`, `add-school`, `add-class`.
3. `block` закрывает бота и API, строки остаются. `close` — мягкое удаление. `delete --yes` стирает ответы, занятия и вход. В `audit_log` остаётся факт без имени.
4. `transfer` печатает `P######`. Его вводят с нового аккаунта MAX. Старая привязка получает `revoked_at`, история остаётся на старом `users.id`.

Ученик в браузер по коду не входит.
