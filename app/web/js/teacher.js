import { getAssignments, getClass, getNotices, getWorkResult, postDraft, publishWork, saveWork } from "./api.js";
import { renderManage } from "./manage.js";
import { go, refresh, store } from "./store.js";
import {
  brand,
  confirmDialog,
  emptyBlock,
  errorBlock,
  esc,
  icon,
  pill,
  plural,
} from "./ui.js";

const DIFFICULTIES = [
  ["easy", "Проще"],
  ["normal", "Обычная"],
  ["hard", "Сложнее"],
];

function classTitle() {
  return store.report?.class_title || "Класс";
}

function stats(report) {
  const students = report?.students || [];
  let mastered = 0;
  let practice = 0;
  let repeat = 0;
  let known = 0;
  const weak = new Set();
  const byTopic = new Map();
  for (const student of students) {
    let needs = false;
    for (const topic of student.topics || []) {
      if (!topic.status) continue;
      known += 1;
      if (topic.status === "mastered") mastered += 1;
      if (topic.status === "needs_practice") {
        practice += 1;
        needs = true;
      }
      if (topic.status === "repeat") {
        repeat += 1;
        needs = true;
      }
      if (topic.status === "needs_practice" || topic.status === "repeat") {
        const bag = byTopic.get(topic.title) || { repeat: 0, practice: 0 };
        if (topic.status === "repeat") bag.repeat += 1;
        else bag.practice += 1;
        byTopic.set(topic.title, bag);
      }
    }
    if (needs) weak.add(student.display_name);
  }
  const ranked = [...byTopic.entries()].sort(
    (a, b) => b[1].repeat - a[1].repeat || b[1].practice - a[1].practice || a[0].localeCompare(b[0], "ru"),
  );
  return {
    students: students.length,
    mastered,
    practice,
    repeat,
    known,
    share: known ? Math.round((mastered / known) * 100) : null,
    weak: [...weak],
    ranked,
  };
}

function needText(info) {
  if (!info.known) return "Пока нет проверенных попыток.";
  if (!info.weak.length) return "Сейчас никому не нужна дополнительная практика.";
  const count = info.weak.length;
  const mod10 = count % 10;
  const mod100 = count % 100;
  const word = mod10 === 1 && mod100 !== 11 ? "ученику" : "ученикам";
  return `${count} ${word} нужна практика или повтор.`;
}

function subjectTitle() {
  const direct = String(store.report?.subject_title || "").trim();
  if (direct) return direct;
  const titles = [];
  const push = (title) => {
    const clean = String(title || "").trim();
    if (clean && !titles.includes(clean)) titles.push(clean);
  };
  for (const item of store.report?.classes || []) {
    for (const subject of item.subjects || []) push(subject.title);
  }
  for (const subject of store.report?.subjects || []) push(subject.title || subject);
  return titles.join(", ");
}

function roleName() {
  return store.report?.can_manage_school || store.canManage ? "Учитель-администратор" : "Учитель";
}

function topbar() {
  const unread = Number(store.notices?.unread) || 0;
  const subject = subjectTitle();
  return `<header class="mast">
    ${brand()}
    <button class="class-switch" type="button" data-act="class-sheet">
      <b>${esc(classTitle())}</b>
      <span>${esc(subject || "предмет не указан")}</span>
    </button>
    <button class="icon-btn" type="button" data-act="notices" aria-label="Уведомления">${icon("bell")}${unread ? `<i class="dot"></i>` : ""}</button>
    <button class="icon-btn" type="button" data-act="nav" data-screen="profile" aria-label="Профиль">${icon("user")}</button>
  </header>`;
}

function distribution(info) {
  const parts = [
    ["mastered", info.mastered],
    ["needs_practice", info.practice],
    ["repeat", info.repeat],
  ].filter(([, count]) => count > 0);
  if (!parts.length) return "";
  return `<div class="dist" aria-hidden="true">${parts.map(([status, count]) => `<i data-status="${status}" style="flex:${count}"></i>`).join("")}</div>
    <p class="legend"><span><i data-status="mastered"></i>усвоено ${info.mastered}</span><span><i data-status="needs_practice"></i>практика ${info.practice}</span><span><i data-status="repeat"></i>повторить ${info.repeat}</span></p>`;
}

function rollup(report) {
  return (report.topics || []).map((topic) => {
    const cells = [];
    for (const student of report.students || []) {
      const found = (student.topics || []).find((item) => item.title === topic.title);
      if (found) cells.push(found);
    }
    return {
      title: topic.title,
      mastered: cells.filter((cell) => cell.status === "mastered").length,
      practice: cells.filter((cell) => cell.status === "needs_practice").length,
      repeat: cells.filter((cell) => cell.status === "repeat").length,
      none: cells.filter((cell) => !cell.status).length,
    };
  });
}

function meter(row) {
  const parts = [
    ["mastered", row.mastered],
    ["needs_practice", row.practice],
    ["repeat", row.repeat],
    ["none", row.none],
  ].filter(([, count]) => count > 0);
  if (!parts.length) return "";
  return `<div class="meter" aria-hidden="true">${parts.map(([status, count]) => `<i data-status="${status}" style="flex:${count}"></i>`).join("")}</div>`;
}

export function renderOverview() {
  if (!store.report) return errorBlock(store.reportError?.message, "retry");
  const info = stats(store.report);
  const claims = store.report.pending_claims || [];
  const reviewer = store.report.claims_reviewer;
  const name = store.displayName || store.report.display_name || "";
  const subject = subjectTitle();
  return `<div class="stack">
    ${topbar()}
    <div class="who">
      <b>${esc(name || "Имя не пришло из профиля")}</b>
      <span>${esc(roleName())}</span>
    </div>
    <div class="stat-row">
      <div><b>${info.students}</b><span>${info.students ? `${plural(info.students, "ученик", "ученика", "учеников")} в классе` : "учеников пока нет"}</span></div>
      <div><b>${info.known ? info.weak.length : 0}</b><span>${info.known ? "нужна практика" : "проверок ещё нет"}</span></div>
      ${info.known ? distribution(info) : ""}
    </div>
    ${info.known ? `<div class="rows">${info.ranked.slice(0, 4).map(([title, bag]) => `<button class="line" type="button" data-act="focus-topic" data-topic="${esc(title)}"><span><b>${esc(title)}</b><small>повторить ${bag.repeat}, практика ${bag.practice}</small></span></button>`).join("")}</div>` : `<div class="invite"><img src="/assets/logo.jpg" alt=""><div><h1 id="page-title">Проверок ещё не было</h1><p class="quiet">${esc(classTitle())}${subject ? `, ${esc(subject)}` : ""}. После первой работы здесь станет видно, какая тема просела.</p></div><button class="btn btn-primary" type="button" data-act="compose">Создать первую работу</button></div>`}
    ${store.report.frequent_mistakes ? `<p>${esc(store.report.frequent_mistakes)}</p>` : ""}
    ${reviewer ? `<p class="quiet">Заявки проверяет ${esc(reviewer)}.</p>` : ""}
    ${store.report.can_manage_school ? `<button class="line" type="button" data-act="nav" data-screen="manage"><span><b>Заявки</b><small>${claims.length ? `${claims.length} ждут решения` : "новых нет"}</small></span></button>` : ""}
    ${info.known ? `<button class="btn btn-primary" type="button" data-act="compose">Создать работу</button>` : ""}
  </div>`;
}

function visibleTopics(student) {
  return (student.topics || []).filter((topic) => {
    if (store.filters.topic !== "all" && topic.title !== store.filters.topic) return false;
    if (store.filters.status === "all") return true;
    if (store.filters.status === "none") return !topic.status;
    return topic.status === store.filters.status;
  });
}

export function renderClass() {
  if (!store.report) return errorBlock(store.reportError?.message, "retry");
  const report = store.report;
  const rows = rollup(report);
  const filters = [
    ["all", "Все"],
    ["mastered", "Усвоено"],
    ["needs_practice", "Практика"],
    ["repeat", "Повторить"],
    ["none", "Пусто"],
  ];
  const people = (report.students || [])
    .map((student) => ({ student, topics: visibleTopics(student) }))
    .filter((item) => item.topics.length);
  const selected = store.filters.topic !== "all" ? rows.find((row) => row.title === store.filters.topic) : null;
  const weakNames = selected
    ? (report.students || []).filter((student) => (student.topics || []).some((topic) => topic.title === selected.title && (topic.status === "repeat" || topic.status === "needs_practice"))).map((student) => student.display_name)
    : [];
  return `<div class="stack">
    ${topbar()}
    <div class="who"><b>Карта класса</b><span>${esc(classTitle())}${subjectTitle() ? `, ${esc(subjectTitle())}` : ""}</span></div>
    ${report.frequent_mistakes ? `<p>${esc(report.frequent_mistakes)}</p>` : `<p class="quiet">Личные вопросы учеников на эту карту не попадают.</p>`}
    <div class="filters" role="tablist" aria-label="Статус">
      ${filters.map(([id, label]) => `<button class="chip ${store.filters.status === id ? "is-on" : ""}" type="button" data-act="filter-status" data-status="${id}">${label}</button>`).join("")}
    </div>
    <div class="rows">
      ${rows.map((row) => `<div>
        <button class="topic-row ${store.filters.topic === row.title ? "is-on" : ""}" type="button" data-act="focus-topic" data-topic="${esc(row.title)}">
          <strong>${esc(row.title)}</strong>
          ${meter(row)}
          <span class="meta">усвоено ${row.mastered}, практика ${row.practice}, повтор ${row.repeat}</span>
        </button>
        ${store.filters.topic === row.title ? `<div class="reveal-body"><p>${weakNames.length ? `Нужна работа: ${esc(weakNames.join(", "))}.` : "По этой теме нет учеников со статусом «повторить» или «нужна практика»."}</p><button class="btn btn-primary" type="button" data-act="compose" data-topic="${esc(row.title)}">Собрать задание по теме</button></div>` : ""}
      </div>`).join("")}
    </div>
    ${(report.priorities || []).length ? `<div><h2>Кому помочь</h2><ul class="plain">${report.priorities.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></div>` : ""}
    <div class="table-wrap map-table">
      <table>
        <thead><tr><th>Ученик</th>${(report.topics || []).filter((topic) => store.filters.topic === "all" || topic.title === store.filters.topic).map((topic) => `<th>${esc(topic.title)}</th>`).join("")}</tr></thead>
        <tbody>
          ${(report.students || []).map((student) => {
            const topics = (student.topics || []).filter((topic) => store.filters.topic === "all" || topic.title === store.filters.topic);
            const cells = topics.filter((topic) => store.filters.status === "all" || (store.filters.status === "none" ? !topic.status : topic.status === store.filters.status));
            if (store.filters.status !== "all" && !cells.length) return "";
            return `<tr><th>${esc(student.display_name)}</th>${topics.map((topic) => `<td>${pill(topic.status)}</td>`).join("")}</tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>
  </div>`;
}

function workLine(item) {
  const published = item.status === "published";
  const finished = published && item.recipients && item.done >= item.recipients;
  const label = !published ? "черновик" : finished ? "завершено" : `сдали ${item.done || 0} из ${item.recipients || 0}`;
  return `<button class="line" type="button" data-act="open-result" data-id="${item.id}"><span><b>${esc(item.title)}</b><small>${esc(item.subject || "")} · ${label}</small></span></button>`;
}

export function renderTasks() {
  const failed = store.assignmentsError && !store.assignments;
  const items = store.assignments?.items || [];
  if (store.resultView) return renderResult(store.resultView);
  const drafts = items.filter((item) => item.status !== "published");
  const active = items.filter((item) => item.status === "published" && !(item.recipients && item.done >= item.recipients));
  const done = items.filter((item) => item.status === "published" && item.recipients && item.done >= item.recipients);
  const block = (title, list) => list.length ? `<div><p class="group-label">${title}</p><div class="rows">${list.map(workLine).join("")}</div></div>` : "";
  return `<div class="stack">
    ${topbar()}
    <div class="row-between">
      <h1>Задания</h1>
      ${items.length ? `<button class="btn btn-primary" type="button" data-act="compose">Создать работу</button>` : ""}
    </div>
    ${failed ? errorBlock(store.assignmentsError.message, "retry") : ""}
    ${items.length ? `${block("Активные", active)}${block("Черновики", drafts)}${block("Завершённые", done)}` : `<div class="invite"><img src="/assets/logo.jpg" alt=""><div><h2>Работ ещё нет</h2><p class="quiet">Первая проверка покажет, кто в ${esc(classTitle())} уже держит тему.</p></div><button class="btn btn-primary" type="button" data-act="compose">Создать первую работу</button></div>`}
  </div>`;
}

function renderResult(work) {
  const people = work.people || [];
  const waiting = people.filter((person) => person.status !== "done");
  return `<div class="stack">
    ${topbar()}
    <button class="text-btn" type="button" data-act="close-result">К списку</button>
    <h1 id="page-title" tabindex="-1">${esc(work.title)}</h1>
    <p class="quiet">${esc(work.subject)} · ${esc(work.topic)}</p>
    ${people.length ? `<section class="sheet-block">${people.map((person) => `<div class="line"><span><b>${esc(person.display_name)}</b><small>${person.status === "done" ? `сдано, верно ${person.correct} из ${person.answered}` : "ещё не сдано"}</small></span></div>`).join("")}</section>` : `<p class="quiet">Получателей нет.</p>`}
    ${waiting.length ? `<p class="quiet">Ещё не сдали: ${esc(waiting.map((person) => person.display_name).join(", "))}.</p>` : ""}
  </div>`;
}

export function renderStimul() {
  const samples = ["Собери короткую проверку по дробям", "Какие темы класса сейчас слабее", "Придумай устный вопрос на дискриминант"];
  return `<div class="stimul">
    ${topbar()}
    <div class="who"><b>Помощник учителя</b><span>модель ещё не подключена</span></div>
    <div class="stimul-thread">
      ${store.stimulDraft ? `<div class="bubble me">${esc(store.stimulDraft)}</div>` : `<p class="quiet">Здесь будет диалог про задания и типичные ошибки класса. Ответ модели сейчас не генерируется.</p>`}
      ${store.stimulNote ? `<div class="bubble">${esc(store.stimulNote)}</div>` : ""}
    </div>
    <div class="prompt-list">${samples.map((text) => `<button type="button" data-act="stimul-sample" data-text="${esc(text)}">${esc(text)}</button>`).join("")}</div>
    <form id="stimul-form" class="composer">
      <label class="btn btn-ghost file">Фото<input type="file" accept="image/*" disabled aria-label="Вложение появится вместе с моделью"></label>
      <input id="stimul-input" class="field" placeholder="Запрос помощнику" value="${esc(store.stimulDraft)}" aria-label="Запрос помощнику">
      <button class="btn btn-primary" type="submit">Отправить</button>
    </form>
  </div>`;
}

function wizardBody() {
  const wizard = store.wizard;
  const topics = (store.report?.topics || []).map((topic) => topic.title);
  if (!wizard) return "";
  const titles = ["Тема и цель", "Объём и сложность", "Кому отправить", "Просмотр"];
  const students = store.report?.students || [];
  let body = "";
  if (wizard.step === 1) {
    body = `<label class="field-label" for="topic">Тема</label>
      <select id="topic" class="field">${topics.map((title) => `<option value="${esc(title)}" ${title === wizard.topic ? "selected" : ""}>${esc(title)}</option>`).join("")}</select>
      <label class="field-label" for="goal">Цель проверки</label>
      <textarea id="goal" class="area" placeholder="Например: проверить общий знаменатель">${esc(wizard.goal)}</textarea>
      <label class="check"><input id="material" type="checkbox" ${wizard.useMaterial ? "checked" : ""}><span>Собрать по загруженному материалу</span></label>
      ${wizard.useMaterial ? `<p class="hint">Фрагментов урока на сервере нет. С этой отметкой черновик не соберётся — параграф не выдумываю.</p>` : `<p class="hint">Пока задания берутся из банка 8 класса, не из учебника.</p>`}`;
  } else if (wizard.step === 2) {
    body = `<p class="field-label">Сколько заданий</p>
      <div class="chips">${[1, 2, 3, 4, 5, 6].map((count) => `<button class="chip ${wizard.count === count ? "is-on" : ""}" type="button" data-act="count" data-value="${count}">${count}</button>`).join("")}</div>
      <p class="field-label">Сложность</p>
      <div class="chips">${DIFFICULTIES.map(([id, label]) => `<button class="chip ${wizard.difficulty === id ? "is-on" : ""}" type="button" data-act="difficulty" data-value="${id}">${label}</button>`).join("")}</div>
      <p class="hint">В банке каждой темы два задания. Если попросить больше, пункты повторятся — это будет видно в просмотре.</p>`;
  } else if (wizard.step === 3) {
    body = `<div class="segment">
        <button type="button" class="${wizard.audience === "class" ? "is-on" : ""}" data-act="audience" data-value="class">Весь класс</button>
        <button type="button" class="${wizard.audience === "selected" ? "is-on" : ""}" data-act="audience" data-value="selected">Выбранные</button>
      </div>
      ${wizard.audience === "selected" ? `<p class="hint">Отдельных групп на сервере нет. Отметьте учеников ${esc(classTitle())}.</p>
        <div class="stack tight">${students.map((student) => {
          const on = wizard.students.includes(student.display_name);
          return `<button class="choice ${on ? "is-on" : ""}" type="button" data-act="toggle-student" data-name="${esc(student.display_name)}" aria-pressed="${on}">${esc(student.display_name)}</button>`;
        }).join("")}</div>` : `<p class="hint">Работа уйдёт ученикам ${esc(classTitle())}.</p>`}`;
  } else {
    const draft = wizard.draft;
    body = `${wizard.draftError ? `<div class="banner banner-bad"><p>${esc(wizard.draftError.message)}</p></div>` : ""}
      ${store.busy ? `<p class="statusline" role="status">Собираю черновик…</p>` : ""}
      ${draft ? `<p class="hint">Источник: банк 8 класса. На сервер попадёт только после «Сохранить черновик» или «Опубликовать». Эталон виден только вам.</p>
        ${draft.note ? `<div class="banner banner-warn"><p>${esc(draft.note)}</p></div>` : ""}
        <p><strong>${esc(draft.topic)}</strong></p>
        <p>${esc(draft.goal)}</p>
        <p class="hint">${draft.audience === "class" ? "Весь класс" : "Выбранные"}: ${esc((draft.students || []).join(", ") || "никто")}</p>
        <div class="stack tight">${(draft.items || []).map((item, index) => `<article class="card card-flat">
          <h2>Задание ${item.number}</h2>
          <label class="field-label" for="prompt-${index}">Формулировка</label>
          <textarea id="prompt-${index}" class="area" data-prompt="${index}">${esc(item.prompt)}</textarea>
          ${item.choices?.length ? `<p>${item.choices.map((choice) => esc(choice)).join(" · ")}</p>` : `<p class="hint">Вариантов нет: ответ число или дробь.</p>`}
          <p class="hint">Эталон: ${esc(item.reference)}</p>
        </article>`).join("")}</div>
        <p class="hint">Пока вы не нажали кнопку, правки живут только на этом экране.</p>` : ""}
      ${wizard.sendError ? `<div class="banner banner-warn" role="status"><strong>Отправка не выполнена</strong><p>${esc(wizard.sendError)}</p></div>` : ""}
      <button class="text-btn" type="button" data-act="redraft" ${store.busy ? "disabled" : ""}>Собрать заново</button>`;
  }
  const actions = wizard.step < 4
    ? `${wizard.step > 1 ? `<button class="btn btn-ghost" type="button" data-act="wizard-back">Назад</button>` : `<button class="btn btn-ghost" type="button" data-act="nav" data-screen="tasks">Закрыть</button>`}
        <button class="btn btn-primary" type="button" data-act="wizard-next">Дальше</button>`
    : `<button class="btn btn-ghost" type="button" data-act="save-draft" ${!wizard.draft || store.busy ? "disabled" : ""}>Черновик</button>
        <button class="btn btn-primary" type="button" data-act="send-assignment" ${!wizard.draft || store.busy ? "disabled" : ""}>Опубликовать</button>`;
  return `<div class="stack flow">
    <header class="flow-head">
      <div class="who"><b>${titles[wizard.step - 1]}</b><span>Шаг ${wizard.step} из 4</span></div>
      <ol class="steps" aria-label="Этапы">${titles.map((title, index) => `<li class="${index + 1 < wizard.step ? "is-done" : index + 1 === wizard.step ? "is-now" : ""}" title="${esc(title)}"></li>`).join("")}</ol>
    </header>
    ${wizard.fieldError ? `<p class="field-error">${esc(wizard.fieldError)}</p>` : ""}
    ${body}
    <div class="flow-bar">${actions}</div>
  </div>`;
}

export function renderCompose() {
  if (!store.report) return errorBlock(store.reportError?.message, "retry");
  if (!(store.report.topics || []).length) return emptyBlock("Нет тем", "В программе класса пока нет тем для проверки.");
  return wizardBody();
}

export function renderResults() {
  if (!store.report) return errorBlock(store.reportError?.message, "retry");
  const info = stats(store.report);
  const rows = [
    ["mastered", "Усвоено", info.mastered],
    ["needs_practice", "Нужна практика", info.practice],
    ["repeat", "Повторить", info.repeat],
  ];
  return `<div class="stack">
    ${topbar()}
    <div>
      <p class="kicker">${esc(classTitle())}</p>
      <h1 id="page-title" tabindex="-1">Результаты</h1>
      <p class="hint">Сводка по статусам. Это не оценки и не рейтинг учеников.</p>
    </div>
    ${info.known ? `<section class="card stack tight">${rows.map(([status, label, count]) => {
      const width = Math.round((count / info.known) * 100);
      return `<div class="bar-row"><span>${label}</span><div class="track" data-status="${status}"><span style="width:${width}%"></span></div><b>${count}</b></div>`;
    }).join("")}</section>` : emptyBlock("Пока нет попыток", "Распределение появится, когда ученики проверят хотя бы одно задание.")}
    <section class="card">
      <h2>Сложные темы</h2>
      ${info.ranked.length ? `<ul class="plain">${info.ranked.map(([title, bag]) => `<li><button type="button" data-act="compose" data-topic="${esc(title)}"><strong>${esc(title)}</strong><span class="hint">повторить ${bag.repeat}, практика ${bag.practice}</span></button></li>`).join("")}</ul>` : `<p class="hint">Нет тем, где статус слабее «усвоено».</p>`}
    </section>
    <section class="card">
      <h2>Работы</h2>
      <p>${esc(store.assignments?.detail || store.assignmentsError?.message || "Список работ недоступен.")}</p>
    </section>
  </div>`;
}

export function renderProfile() {
  const name = store.displayName || "";
  const admin = Boolean(store.report?.can_manage_school || store.canManage);
  const reviewer = store.report?.claims_reviewer;
  const subject = subjectTitle();
  return `<div class="stack">
    ${topbar()}
    <h1>${esc(name || "Имя не пришло из профиля")}</h1>
    <p>${admin ? "Учитель-администратор" : "Учитель"}</p>
    <div class="rows">
      <div class="line"><span><b>Класс</b><small>${esc(classTitle())}</small></span></div>
      <div class="line"><span><b>Предмет</b><small>${esc(subject || "в назначении не указан")}</small></span></div>
      <div class="line"><span><b>Заявки проверяет</b><small>${esc(reviewer || "ответственный не назначен")}</small></span></div>
    </div>
    <p class="quiet">Личные вопросы учеников в кабинет не приходят.</p>
    <button class="btn btn-ghost" type="button" data-act="notices">Уведомления</button>
    ${admin ? `<button class="btn btn-primary" type="button" data-act="nav" data-screen="manage">Заявки и пользователи</button>` : ""}
  </div>`;
}

export function renderTeacher() {
  if (store.screen === "class") return renderClass();
  if (store.screen === "tasks") return renderTasks();
  if (store.screen === "compose") return renderCompose();
  if (store.screen === "results") return renderResults();
  if (store.screen === "profile") return renderProfile();
  if (store.screen === "stimul") return renderStimul();
  if (store.screen === "manage") return renderManage();
  return renderOverview();
}

export function focusTopic(title) {
  if (!title) return;
  store.filters = { ...store.filters, topic: store.filters.topic === title ? "all" : title };
  if (store.screen !== "class") go("class");
  else refresh();
}

export function setFilter(status) {
  store.filters = { ...store.filters, status };
  refresh();
}

export function startCompose(topic) {
  const topics = (store.report?.topics || []).map((item) => item.title);
  const preset = topic && topics.includes(topic) ? topic : topics[0] || "";
  store.wizard = {
    step: 1,
    topic: preset,
    goal: "",
    count: 3,
    difficulty: "normal",
    audience: "class",
    students: [],
    useMaterial: false,
    draft: null,
    draftError: null,
    sendError: null,
    fieldError: "",
  };
  go("compose");
}

function readWizardFields() {
  const wizard = store.wizard;
  if (!wizard) return;
  const topic = document.querySelector("#topic");
  const goal = document.querySelector("#goal");
  if (topic) wizard.topic = topic.value;
  if (goal) wizard.goal = goal.value;
  document.querySelectorAll("[data-prompt]").forEach((node) => {
    const index = Number(node.dataset.prompt);
    if (wizard.draft?.items?.[index]) wizard.draft.items[index].prompt = node.value;
  });
}

export function wizardNext() {
  const wizard = store.wizard;
  if (!wizard) return;
  readWizardFields();
  wizard.fieldError = "";
  if (wizard.step === 1) {
    if (!wizard.topic) {
      wizard.fieldError = "Выберите тему.";
      refresh();
      return;
    }
    if (wizard.goal.trim().length < 3) {
      wizard.fieldError = "Напишите цель проверки.";
      refresh();
      return;
    }
  }
  if (wizard.step === 3 && wizard.audience === "selected" && !wizard.students.length) {
    wizard.fieldError = "Отметьте хотя бы одного ученика.";
    refresh();
    return;
  }
  wizard.step += 1;
  refresh();
  if (wizard.step === 4) loadDraft();
}

export function wizardBack() {
  const wizard = store.wizard;
  if (!wizard) return;
  readWizardFields();
  wizard.fieldError = "";
  wizard.sendError = null;
  if (wizard.step === 4) wizard.step = 1;
  else wizard.step = Math.max(1, wizard.step - 1);
  refresh();
}

export function setCount(value) {
  if (!store.wizard) return;
  store.wizard.count = Number(value) || 1;
  refresh();
}

export function setDifficulty(value) {
  if (!store.wizard) return;
  store.wizard.difficulty = value;
  refresh();
}

export function setAudience(value) {
  if (!store.wizard) return;
  store.wizard.audience = value === "selected" ? "selected" : "class";
  refresh();
}

export function toggleStudent(name) {
  const wizard = store.wizard;
  if (!wizard || !name) return;
  wizard.students = wizard.students.includes(name)
    ? wizard.students.filter((item) => item !== name)
    : [...wizard.students, name];
  refresh();
}

export function toggleMaterial(checked) {
  if (!store.wizard) return;
  store.wizard.useMaterial = Boolean(checked);
  refresh();
}

function draftPayload() {
  const wizard = store.wizard;
  return {
    topic: wizard.topic,
    goal: wizard.goal.trim(),
    count: wizard.count,
    difficulty: wizard.difficulty,
    audience: wizard.audience,
    students: wizard.audience === "selected" ? wizard.students : [],
    use_material: wizard.useMaterial,
  };
}

export async function loadDraft() {
  const wizard = store.wizard;
  if (!wizard || store.busy) return;
  readWizardFields();
  wizard.draftError = null;
  wizard.sendError = null;
  store.busy = true;
  refresh();
  try {
    if (store.preview) {
      wizard.draft = null;
      wizard.draftError = { message: "В демонстрационном просмотре черновик с сервера не собирается." };
      return;
    }
    wizard.draft = await postDraft(draftPayload());
  } catch (error) {
    wizard.draft = null;
    wizard.draftError = error;
  } finally {
    store.busy = false;
    refresh();
  }
}

function workBody() {
  const payload = draftPayload();
  return {
    ...payload,
    prompts: (store.wizard.draft?.items || []).map((item) => item.prompt),
    work_id: store.wizard.workId || null,
  };
}

export async function saveDraft() {
  const wizard = store.wizard;
  if (!wizard?.draft || store.busy) return;
  readWizardFields();
  if (store.preview) {
    wizard.sendError = "В демонстрации черновик на сервер не пишется.";
    refresh();
    return;
  }
  store.busy = true;
  wizard.sendError = null;
  refresh();
  try {
    const saved = await saveWork(workBody());
    if (!saved?.persisted || !saved.id) {
      wizard.sendError = "Сервер не сохранил черновик.";
      return;
    }
    wizard.workId = saved.id;
    wizard.sendError = null;
    await confirmDialog({ title: "Черновик сохранён", text: "Ученикам работа ещё не отправлена.", confirm: "Хорошо" });
  } catch (error) {
    wizard.sendError = error.message;
  } finally {
    store.busy = false;
    refresh();
  }
}

export async function sendAssignment() {
  const wizard = store.wizard;
  if (!wizard?.draft || store.busy) return;
  readWizardFields();
  const empty = wizard.draft.items.some((item) => !String(item.prompt || "").trim());
  if (empty) {
    wizard.sendError = "Заполните текст каждого задания.";
    refresh();
    return;
  }
  store.busy = true;
  wizard.sendError = null;
  refresh();
  try {
    if (store.preview) {
      wizard.sendError = "В демонстрационном просмотре отправка выключена. Работа ученикам не ушла.";
      return;
    }
    const saved = await saveWork(workBody());
    if (!saved?.persisted || !saved.id) {
      wizard.sendError = "Сервер не сохранил работу. Ученикам ничего не ушло.";
      return;
    }
    const published = await publishWork(saved.id);
    if (!published?.persisted) {
      wizard.sendError = "Черновик записан, публикация не подтверждена. Ученикам ничего не ушло.";
      wizard.workId = saved.id;
      return;
    }
    wizard.workId = saved.id;
    await confirmDialog({
      title: "Работа опубликована",
      text: `Сервер записал работу и поставил уведомления: ${published.recipients}.`,
      confirm: "Хорошо",
    });
    go("tasks");
  } catch (error) {
    wizard.sendError = error.message;
  } finally {
    store.busy = false;
    refresh();
  }
}

export async function openResult(id) {
  if (store.preview) {
    store.assignmentsError = { message: "В демонстрации результатов с сервера нет." };
    refresh();
    return;
  }
  store.busy = true;
  refresh();
  try {
    store.resultView = await getWorkResult(id);
  } catch (error) {
    store.assignmentsError = error;
  } finally {
    store.busy = false;
    refresh();
  }
}

export async function showClassInfo() {
  const title = classTitle();
  await confirmDialog({
    title: title,
    text: `Сейчас в кабинете один класс: ${title}. Других классов в данных нет, поэтому переключать не на что.`,
    confirm: "Понятно",
  });
}

export async function reloadTeacher() {
  store.loading = true;
  refresh();
  try {
    store.report = await getClass(store.classId || undefined);
    store.reportError = null;
  } catch (error) {
    store.reportError = error;
  }
  try {
    store.assignments = await getAssignments();
    store.assignmentsError = null;
  } catch (error) {
    store.assignmentsError = error;
  }
  try {
    store.notices = await getNotices();
  } catch {
    store.notices = { unread: 0, items: [] };
  }
  store.canManage = Boolean(store.report?.can_manage_school);
  store.loading = false;
  refresh();
}
