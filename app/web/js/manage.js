import { acceptClaim, appointTeacher, getCatalog, getClaims, getPeople, rejectClaim, savePerson } from "./api.js";
import { refresh, store } from "./store.js";
import { emptyBlock, errorBlock, esc } from "./ui.js";

export function renderManage() {
  if (!store.report?.can_manage_school && !store.canManage) {
    return errorBlock("Недостаточно прав", "nav");
  }
  if (store.manageError && !store.claims && !store.people) return errorBlock(store.manageError.message, "reload-manage");
  const claims = store.claims?.items || [];
  const people = store.people?.items || [];
  const classes = store.catalog?.classes || [];
  const subjects = store.catalog?.subjects || [];
  return `<div class="stack">
    <h1 id="page-title" tabindex="-1">Управление</h1>
    <p class="quiet">Заявки, люди и назначения. Обычная успеваемость живёт на карте класса.</p>
    <section>
      <h2>Заявки</h2>
      ${claims.length ? `<section class="sheet-block">${claims.map((item) => `<article class="line">
        <span><b>${esc(item.display_name)}</b><small>${esc(item.class_title)} · ${esc(item.phone_mask || "номер скрыт")} · ${esc(item.created_at || "")}</small></span>
        <span>
          <button class="btn btn-primary" type="button" data-act="accept-claim" data-id="${item.user_id}">Принять</button>
          <button class="btn btn-ghost" type="button" data-act="reject-claim" data-id="${item.user_id}">Отклонить</button>
        </span>
      </article>`).join("")}</section>` : emptyBlock("Новых заявок нет", "Когда ученик подтвердит номер, заявка появится здесь.")}
    </section>
    <section>
      <h2>Пользователи</h2>
      <input id="people-q" class="field" placeholder="Поиск по имени" value="${esc(store.peopleQuery)}" aria-label="Поиск по имени">
      <div class="chips">
        ${["", "student", "teacher"].map((role) => `<button class="chip ${store.peopleRole === role ? "is-on" : ""}" type="button" data-act="people-role" data-role="${role}">${role === "student" ? "Ученики" : role === "teacher" ? "Учителя" : "Все"}</button>`).join("")}
      </div>
      ${people.length ? `<section class="sheet-block">${people.map((person) => `<article class="line">
        <span><b>${esc(person.display_name)}</b><small>${esc(person.role === "teacher" ? "учитель" : "ученик")} · ${esc(person.status)} · ${(person.classes || []).map(esc).join(", ") || "без класса"} · ${(person.subjects || []).map(esc).join(", ")}</small></span>
        <span>
          ${person.role === "student" ? `<button class="btn btn-ghost" type="button" data-act="make-teacher" data-id="${person.id}">Сделать учителем</button>` : ""}
          ${person.status === "blocked" ? `<button class="btn btn-ghost" type="button" data-act="unblock-person" data-id="${person.id}">Разблокировать</button>` : `<button class="btn btn-ghost" type="button" data-act="block-person" data-id="${person.id}">Заблокировать</button>`}
        </span>
      </article>`).join("")}</section>` : `<p class="quiet">Никого не нашли.</p>`}
    </section>
    <section>
      <h2>Назначение учителя</h2>
      <p class="quiet">Один учитель получает только выбранные класс и предмет.</p>
      <label class="field-label" for="appoint-user">Учитель</label>
      <select id="appoint-user" class="field">${people.filter((person) => person.role === "teacher").map((person) => `<option value="${person.id}">${esc(person.display_name)}</option>`).join("")}</select>
      <label class="field-label" for="appoint-class">Класс</label>
      <select id="appoint-class" class="field">${classes.map((item) => `<option value="${item.id}">${esc(item.title)}</option>`).join("")}</select>
      <label class="field-label" for="appoint-subject">Предмет</label>
      <select id="appoint-subject" class="field">${subjects.map((item) => `<option value="${item.id}">${esc(item.title)}</option>`).join("")}</select>
      <button class="btn btn-primary" type="button" data-act="appoint">Назначить</button>
    </section>
  </div>`;
}

export async function loadManage() {
  if (store.preview) {
    store.manageError = { message: "В демонстрации управление школой не ходит на сервер." };
    refresh();
    return;
  }
  store.manageError = null;
  try {
    const [claims, people, catalog] = await Promise.all([
      getClaims(),
      getPeople(store.peopleQuery, store.peopleRole),
      getCatalog(),
    ]);
    store.claims = claims;
    store.people = people;
    store.catalog = catalog;
  } catch (error) {
    store.manageError = error;
  }
  refresh();
}

export async function acceptOne(id) {
  await acceptClaim(id);
  await loadManage();
}

export async function rejectOne(id) {
  await rejectClaim(id);
  await loadManage();
}

export async function changePerson(id, body) {
  await savePerson(id, body);
  await loadManage();
}

export async function appoint() {
  const userId = Number(document.querySelector("#appoint-user")?.value);
  const classId = Number(document.querySelector("#appoint-class")?.value);
  const subjectId = Number(document.querySelector("#appoint-subject")?.value);
  if (!userId || !classId || !subjectId) return;
  await appointTeacher({ user_id: userId, class_id: classId, subject_id: subjectId });
  await loadManage();
}
