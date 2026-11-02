# Прототип: один класс 8Б

Инструкция по таблицам, которые уже есть в коде. Боевую базу и Timeweb она не трогает. Скрипт сброса по умолчанию ничего не удаляет и на `ENV=prod` удалять отказывается.

Мини-приложение по-прежнему ходит только в FastAPI. Телефон хранится как `users.phone_hash` и маска `users.phone_mask`. Полный номер в кабинет и в логи не пишется.

## Как включается первый учитель

Флаг `runtime_flags.key = prototype_bootstrap`.

- `open` — первый подтверждённый номер ещё может стать учителем-администратором.
- `consumed` — место уже занято. Удаление учителя это значение не возвращает в `open`, следующий человек становится учеником.

Назначение срабатывает только если одновременно `ENV` не `prod` и `FIRST_TEACHER_BOOTSTRAP=true`. В проде флаг игнорируется: первый посетитель учителем не становится.

Роль при этом `users.role = teacher`, а не `admin`. Право управления школой — отдельная колонка `users.can_manage_school`. Роль `admin` по-прежнему не открывает ни учительские, ни ученические ручки.

## Таблицы

| Таблица | Зачем |
| --- | --- |
| `users` | Человек. `role`, `status`, `display_name`, `can_manage_school`, `phone_hash`, `phone_mask`, `test_signup` |
| `auth_identities` | `provider=max` — id из чата, `provider=max_webapp` — id мини-приложения. Это разные числа, пока нет сверки |
| `schools` | Школа |
| `classes` | Класс. Демо: `title=8Б`, `join_code=8BDEMO` |
| `subjects` | Предмет. Для прототипа `Математика` |
| `topics` | Темы предмета |
| `enrollments` | Ученик в классе, `status` `pending` или `active` |
| `class_teachers` | Учитель видит класс |
| `class_subject_teachers` | Учитель ведёт конкретный предмет в конкретном классе |
| `join_applications` | Заявка. `status`: `draft`, `pending`, `approved`, `rejected`. Кто принял: `reviewed_by`, `reviewed_at` |
| `works`, `work_items`, `work_recipients`, `work_answers` | Проверочная работа, пункты, кому назначена, ответы |
| `notices` | Уведомления внутри кабинета |
| `outbound_notices` | Очередь в MAX. В `button_payload` нет билета, только `progress` или `open_work:<id>` |
| `runtime_flags` | В том числе `prototype_bootstrap` |

Миграция этих колонок и таблиц: `20261102_0011`.

## Пустая тестовая база

На изолированной базе, не на общей:

```text
alembic upgrade head
```

Переменные процесса, не файл в git:

```text
ENV=dev
FIRST_TEACHER_BOOTSTRAP=true
DATABASE_URL=postgresql+asyncpg://.../stimul_proto
```

После миграции людей нет. Первый человек в боте жмёт «Согласен», затем штатную кнопку «Поделиться номером». Сервер проверяет HMAC контакта ключом `MAX_TOKEN`. Этот человек становится учителем-администратором класса 8Б по математике. Следующие подтверждённые номера получают заявку ученика со статусом `pending`.

Класс и предмет создаются функцией `ensure_prototype`, если строки ещё нет: школа «Тестовая школа», класс `8Б`, предмет «Математика», темы из банка 8 класса. Имена учеников из MAX, телефоны в открытом виде не записываются.

Проверка флага:

```sql
SELECT key, value FROM runtime_flags WHERE key = 'prototype_bootstrap';
```

## Посмотреть класс, учеников и заявки

```sql
SELECT id, title, join_code, join_open FROM classes WHERE title = '8Б';

SELECT u.id, u.display_name, u.status, u.phone_mask, e.status AS enrollment
FROM users u
JOIN enrollments e ON e.user_id = u.id
JOIN classes c ON c.id = e.class_id
WHERE c.title = '8Б'
ORDER BY u.id;

SELECT u.id, u.display_name, u.phone_mask, j.status, j.created_at, c.title
FROM join_applications j
JOIN users u ON u.id = j.user_id
LEFT JOIN classes c ON c.id = j.class_id
WHERE j.status = 'pending'
ORDER BY j.created_at;
```

В кабинете это экраны «Заявки» и «Пользователи» у учителя с `can_manage_school = true`.

## Создать класс и предмет вручную

Подставьте реальные `school_id`. Повторять `8Б`, если он уже есть, не нужно: пара `(school_id, title)` уникальна.

```sql
INSERT INTO schools (title, created_at)
VALUES ('Тестовая школа', now())
RETURNING id;

INSERT INTO classes (school_id, title, join_key, join_code, join_open, timezone)
VALUES (1, '9А', 'class-9a', '9ADEMO', true, 'Asia/Vladivostok')
RETURNING id;

INSERT INTO subjects (title)
VALUES ('Русский язык')
ON CONFLICT (title) DO NOTHING
RETURNING id;
```

`subjects.title` уникален. Если предмет уже есть, `RETURNING` ничего не вернёт, id берите так:

```sql
SELECT id, title FROM subjects ORDER BY id;
```

Темы добавляются строками `topics` с уникальными `subject_id + position` и `subject_id + title`. Для математики их уже создаёт банк 8 класса. Новый предмет без тем в проверку не попадёт: работа собирается только из сохранённого банка, не из головы модели.

## Назначить ученика

Человек уже должен быть в `users` и `auth_identities`. Идентификатор MAX лежит в `auth_identities.external_id`, не в `users.id`.

```sql
UPDATE users
SET role = 'student', status = 'active', can_manage_school = false
WHERE id = 12;

INSERT INTO enrollments (class_id, user_id, status)
VALUES (1, 12, 'active')
ON CONFLICT (class_id, user_id) DO UPDATE SET status = 'active';

UPDATE join_applications
SET status = 'approved', reviewed_at = now()
WHERE user_id = 12;
```

`ON CONFLICT` сработает, потому что первичный ключ `enrollments` — пара `(class_id, user_id)`.

## Назначить учителя на класс и предмет

Учитель не получает все классы сам. Нужны обе связи: `class_teachers` и `class_subject_teachers`.

```sql
UPDATE users
SET role = 'teacher', status = 'active'
WHERE id = 15;

INSERT INTO class_teachers (class_id, user_id)
VALUES (1, 15)
ON CONFLICT DO NOTHING;

INSERT INTO class_subject_teachers (class_id, user_id, subject_id)
VALUES (1, 15, 1)
ON CONFLICT DO NOTHING;
```

Второй учитель математики в том же 8Б — тот же `class_id` и `subject_id`, другой `user_id`. Третий учитель другого предмета — другой `subject_id`. Один человек может иметь несколько таких строк.

Снять предмет:

```sql
DELETE FROM class_subject_teachers
WHERE class_id = 1 AND user_id = 15 AND subject_id = 1;
```

Если предметов в классе не осталось, уберите и строку `class_teachers`, иначе кабинет откроется без предмета.

## Кто администратор

Это не роль `admin`.

```sql
UPDATE users
SET role = 'teacher', status = 'active', can_manage_school = true
WHERE id = 15;
```

Снять флаг можно только если остаётся другой активный учитель с `can_manage_school = true`. Иначе кабинет ответит отказом. Так сделано и в `POST /api/manage/people/{id}`.

Посмотреть текущих:

```sql
SELECT id, display_name, role, status, can_manage_school
FROM users
WHERE deleted_at IS NULL
ORDER BY id;
```

Заблокировать:

```sql
UPDATE users SET status = 'blocked' WHERE id = 12;
```

## После демонстрации

На общей базе этот скрипт не запускать. На отдельной тестовой базе сначала посмотрите план:

```text
python -m scripts.reset_prototype
```

Он печатает имя базы, `ENV` и число строк. Удаления нет.

Удаление строк, без миграций и без `alembic_version`:

```text
ENV=dev
STIMUL_ALLOW_RESET=1
STIMUL_RESET_DATABASE=stimul_proto
python -m scripts.reset_prototype --yes
```

`STIMUL_RESET_DATABASE` должен буквально совпасть с именем базы в `DATABASE_URL`. Имена `postgres`, `template0`, `template1` и любое имя с `prod` скрипт отвергает. После сброса снова включите `FIRST_TEACHER_BOOTSTRAP=true` только на этом контуре и заново пройдите подтверждение номера: флаг `prototype_bootstrap` будет удалён вместе с остальными строками `runtime_flags`, поэтому первый новый вход снова может стать учителем-администратором.

## Что ещё не подключено

Языковая модель во вкладке «Стимул» не вызывается. Экран прямо говорит, что помощник готовится к запуску, и не показывает выдуманный ответ. Генерация заданий «по загруженному материалу» по-прежнему отказывается, если фрагментов урока нет.
