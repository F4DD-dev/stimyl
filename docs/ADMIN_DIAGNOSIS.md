# Почему заявка может остаться без ответственного

Заявка лежит в `join_applications` со статусом `pending`. Она не приходит учителю в переписку сама по себе. Сообщение в MAX уходит только действующему учителю с `users.can_manage_school = true`, ролью `teacher` и статусом `active`.

Если такого человека нет, заявка всё равно сохраняется. Бот говорит ученику, что ответственный не назначен. В `audit_log` появляется действие `claims_without_manager`. Флаг `runtime_flags.prototype_bootstrap = open` сам прав не выдаёт: первый номер становится учителем-администратором только когда одновременно `ENV` не `prod` и `FIRST_TEACHER_BOOTSTRAP=true`. На живом Timeweb этот флаг выключен, поэтому `open` никого не назначает. Удаление или блокировка ответственного не возвращает флаг в `open`.

`ADMIN_MAX_IDS` даёт роль `admin` при согласии. Эта роль не открывает кабинет и не ставит `can_manage_school`.

## Как проверить

Из корня репозитория, с `DATABASE_URL` нужной базы:

```text
python -m app.admin class
python -m app.admin claims
python -m app.admin users
python -m app.admin audit
```

Плохой признак: в `class` строка «Ответственный: не назначен», а `claims` печатает людей. В `users` ни у кого нет `manage да`.

Тот же смысл в SQL, только для чтения:

```sql
SELECT id, display_name, role, status, can_manage_school
FROM users
WHERE deleted_at IS NULL
ORDER BY id;

SELECT key, value FROM runtime_flags WHERE key = 'prototype_bootstrap';

SELECT u.id, u.display_name, u.role, j.status, j.created_at, c.title
FROM join_applications j
JOIN users u ON u.id = j.user_id
LEFT JOIN classes c ON c.id = j.class_id
WHERE j.status = 'pending'
ORDER BY j.created_at;

SELECT created_at, action, target_user_id
FROM audit_log
WHERE action = 'claims_without_manager'
ORDER BY id DESC
LIMIT 20;
```

Этими запросами людей не назначают. Назначение: `python -m app.admin grant-school-manager MAX_ID`, затем та же команда с `--yes`. Id берётся из колонки `max` команды `users`.

После назначения уже лежащие заявки видны по команде `claims` и в боте по слову «заявки». Отдельное сообщение о старых заявках приходит новому ответственному, если на момент назначения очередь была не пуста.
