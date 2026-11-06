import { acceptClaim, appointTeacher, getCatalog, getClaims, getPeople, rejectClaim, savePerson } from "./api.js?v=4";
import { refresh, store } from "./store.js?v=2";
import { emptyBlock, errorBlock, esc } from "./ui.js";

function when(value) {
  const text = String(value || "");
  return text ? text.slice(0, 16).replace("T", " ") : "дата не указана";
}

function peopleRows(people) {
  return `<section class="sheet-block">${people.map((person) => `<article class="line manage-line">
        <span><b>${esc(person.display_name)}</b><small>${esc(person.role === "teacher" ? (person.can_manage_school ? "учитель-администратор" : "учитель") : "ученик")} · ${esc(person.status)} · ${(person.classes || []).map(esc).join(", ") || "без класса"} · ${(person.subjects || []).map(esc).join(", ") || "предмет не назначен"}</small></span>
        <span>
          ${person.role === "student" ? `<button class="btn btn-ghost" type="button" data-act="make-teacher" data-id="${person.id}">Сделать учителем</button>` : ""}
          ${person.status === "blocked" ? `<button class="btn btn-ghost" type="button" data-act="unblock-person" data-id="${person.id}">Разблокировать</button>` : `<button class="btn btn-ghost" type="button" data-act="block-person" data-id="${person.id}">Заблокировать</button>`}
        </span>
      </article>`).join("")}</section>`;
}

export function renderManage() {
  if (!store.report?.can_manage_school && !store.canManage) {
    return errorBlock("Недостаточно прав", "nav");
  }
  if (store.manageError && !store.claims && !store.people) return errorBlock(store.manageError.message, "reload-manage");
  const claims = store.claims?.items || [];
  const people = store.people?.items || [];
  const students = people.filter((person) => person.role === "student");
  const teachers = people.filter((person) => person.role === "teacher");
  const classes = store.catalog?.classes || [];
  const subjects = store.catalog?.subjects || [];
  const reviewer = store.report?.claims_reviewer;
  const joinCode = store.report?.join_code || "";
  return `<div class="stack">
    <h1 id="page-title" tabindex="-1">Управление классом</h1>
    <p class="quiet">Заявки, люди и назначения. Успеваемость остаётся на карте класса.</p>
    <section>
      <h2>Заявки</h2>
      <p class="quiet">${claims.length ? `${claims.length} ждут решения` : "Новых нет"}</p>
      ${claims.length ? `<section class="sheet-block">${claims.map((item) => `<article class="line manage-line">
        <span><b>${esc(item.display_name)}</b><small>${esc(item.class_title)} · ${esc(when(item.created_at))} · ждёт</small></span>
        <span>
          <button class="btn btn-primary" type="button" data-act="accept-claim" data-id="${item.user_id}">Принять</button>
          <button class="btn btn-ghost" type="button" data-act="reject-claim" data-id="${item.user_id}">Отклонить</button>
        </span>
      </article>`).join("")}</section>` : emptyBlock("Новых заявок нет", "Когда ученик подтвердит номер, заявка появится здесь.")}
    </section>
    <section>
      <h2>Ученики</h2>
      ${students.length ? peopleRows(students) : `<p class="quiet">Учеников пока нет.</p>`}
    </section>
    <section>
      <h2>Учителя</h2>
      ${teachers.length ? peopleRows(teachers) : `<p class="quiet">Других учителей нет.</p>`}
    </section>
    <section>
      <h2>Предметы</h2>
      ${subjects.length ? `<div class="rows">${subjects.map((item) => `<div class="line"><span><b>${esc(item.title)}</b></span></div>`).join("")}</div>` : `<p class="quiet">Предметы ещё не заведены.</p>`}
      <p class="quiet">Назначение добавляет учителю один класс и один предмет.</p>
      <label class="field-label" for="appoint-user">Учитель</label>
      <select id="appoint-user" class="field">${teachers.map((person) => `<option value="${person.id}">${esc(person.display_name)}</option>`).join("")}</select>
      <label class="field-label" for="appoint-class">Класс</label>
      <select id="appoint-class" class="field">${classes.map((item) => `<option value="${item.id}">${esc(item.title)}</option>`).join("")}</select>
      <label class="field-label" for="appoint-subject">Предмет</label>
      <select id="appoint-subject" class="field">${subjects.map((item) => `<option value="${item.id}">${esc(item.title)}</option>`).join("")}</select>
      <button class="btn btn-primary" type="button" data-act="appoint">Назначить</button>
    </section>
    <section>
      <h2>Настройки класса</h2>
      <div class="rows">
        <div class="line"><span><b>Класс</b><small>${esc(store.report?.class_title || "8Б")}</small></span></div>
        <div class="line"><span><b>Код входа</b><small>${esc(joinCode || "не задан")}</small></span></div>
        <div class="line"><span><b>Заявки проверяет</b><small>${esc(reviewer || "ответственный не назначен")}</small></span></div>
      </div>
    </section>
  </div>`;
}

export async function loadManage() {
  if (store.preview) {
    store.manageError = null;
    store.claims = { items: store.report?.pending_claims || [] };
    store.people = {
      items: [
        {
          id: 1,
          display_name: "Марина Сергеевна",
          role: "teacher",
          status: "active",
          can_manage_school: true,
          classes: ["8Б"],
          subjects: ["Математика"],
        },
        {
          id: 8,
          display_name: "Егор",
          role: "student",
          status: "pending",
          can_manage_school: false,
          classes: ["8Б"],
          subjects: [],
        },
      ],
    };
    store.catalog = {
      classes: store.report?.classes || [{ id: 1, title: "8Б" }],
      subjects: [{ id: 1, title: "Математика" }],
    };
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
