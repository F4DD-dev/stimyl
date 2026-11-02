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
  initials,
  pill,
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

function topbar() {
  const name = store.displayName || "Учитель";
  const subject = store.report?.subject_title || "";
  const unread = Number(store.notices?.unread) || 0;
  return `<header class="mast">
    ${brand()}
    <button class="class-pill" type="button" data-act="class-sheet">${esc(classTitle())}${subject ? ` · ${esc(subject)}` : ""}</button>
    <button class="bell" type="button" data-act="notices" aria-label="Уведомления">${icon("bell")}${unread ? `<i class="dot"></i>` : ""}</button>
    <button class="avatar" type="button" data-act="nav" data-screen="profile" aria-label="Профиль">${esc(initials(name))}</button>
  </header>`;
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
  return `<div class="stack">
    ${topbar()}
    <section>
      <h1 id="page-title" tabindex="-1">${esc(classTitle())}</h1>
      <p class="quiet">${esc(store.report.subject_title || "Предмет появится после назначения")}</p>
    </section>
    <section>
      <p class="figure">${info.students}</p>
      <p class="figure-label">${info.students ? "учеников в классе" : "Учеников пока нет"}</p>
    </section>
    ${info.known ? `<section class="sheet-block">
      <button class="line" type="button" data-act="nav" data-screen="class"><span><b>${info.share}%</b><small>тем со статусом «усвоено» среди уже проверенных</small></span></button>
      <button class="line" type="button" data-act="nav" data-screen="class"><span><b>${info.weak.length}</b><small>нужна практика или повтор</small></span></button>
      ${info.ranked.slice(0, 3).map(([title, bag]) => `<button class="line" type="button" data-act="focus-topic" data-topic="${esc(title)}"><span><b>${esc(title)}</b><small>повторить ${bag.repeat}, практика ${bag.practice}</small></span></button>`).join("")}
    </section>` : `<section>
      <h2>Класс готов к работе</h2>
      <p class="quiet">Здесь появятся результаты учеников после первых проверок.</p>
      <button class="btn btn-primary" type="button" data-act="compose">Создать первое задание</button>
    </section>`}
    ${reviewer ? `<p class="quiet">Заявки проверяет ${esc(reviewer)}. ${store.report.can_manage_school ? "Учитель-администратор" : ""}</p>` : ""}
    ${store.report.can_manage_school ? `<button class="line" type="button" data-act="nav" data-screen="manage"><span><b>Заявки</b><small>${claims.length ? `${claims.length} ждут` : "новых нет"}</small></span></button>` : ""}
    ${store.report.frequent_mistakes ? `<p>${esc(store.report.frequent_mistakes)}</p>` : ""}
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
    ["none", "Без попыток"],
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
    <div>
      <p class="kicker">${esc(classTitle())}</p>
      <h1 id="page-title" tabindex="-1">Карта класса</h1>
      <p class="hint">Три статуса. Тексты вопросов учеников сюда не попадают.</p>
    </div>
    ${(report.pending_students || []).length ? `<section class="card"><h2>Ждут подтверждения</h2>${report.pending_students.map((student) => `<button class="btn btn-ghost" type="button" data-act="approve-join" data-id="${student.id}">${esc(student.display_name)}</button>`).join("")}</section>` : ""}
    <p class="hint">Код класса ${esc(report.join_code || "")}. ${report.join_open ? "Набор открыт." : "Набор закрыт."}</p>
    ${report.frequent_mistakes ? `<div class="banner banner-warn"><p>${esc(report.frequent_mistakes)}</p></div>` : ""}
    <div class="chips" role="tablist" aria-label="Статус">
      ${filters.map(([id, label]) => `<button class="chip ${store.filters.status === id ? "is-on" : ""}" type="button" data-act="filter-status" data-status="${id}">${label}</button>`).join("")}
    </div>
    <label class="field-label" for="topic-filter">Тема</label>
    <select id="topic-filter" class="field" aria-label="Тема">
      <option value="all" ${store.filters.topic === "all" ? "selected" : ""}>Все темы</option>
      ${(report.topics || []).map((topic) => `<option value="${esc(topic.title)}" ${store.filters.topic === topic.title ? "selected" : ""}>${esc(topic.title)}</option>`).join("")}
    </select>
    <div class="topic-grid">
      ${rows.map((row) => `<button class="card topic-card ${store.filters.topic === row.title ? "is-on" : ""}" type="button" data-act="focus-topic" data-topic="${esc(row.title)}">
        <strong>${esc(row.title)}</strong>
        ${meter(row)}
        <span class="hint">усвоено ${row.mastered} · практика ${row.practice} · повтор ${row.repeat}</span>
      </button>`).join("")}
    </div>
    ${selected ? `<section class="card">
      <h2>${esc(selected.title)}</h2>
      <p>${weakNames.length ? `Дополнительная работа: ${esc(weakNames.join(", "))}.` : "По этой теме нет учеников со статусом «повторить» или «нужна практика»."}</p>
      <button class="btn btn-primary" type="button" data-act="compose" data-topic="${esc(selected.title)}">Собрать задание по теме</button>
    </section>` : ""}
    ${people.length ? `<div class="people">${people.map(({ student, topics }) => `<article class="card person">
      <h2>${esc(student.display_name)}</h2>
      <ul class="plain">${topics.map((topic) => `<li><span>${esc(topic.title)}</span>${pill(topic.status)}${topic.correct_percent == null ? "" : `<span class="hint">${topic.correct_percent}%</span>`}</li>`).join("")}</ul>
    </article>`).join("")}</div>` : emptyBlock("Никого не нашли", "Смените фильтр — по этим условиям в классе пусто.")}
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
    ${(report.priorities || []).length ? `<section class="card"><h2>Кому помочь</h2><ul class="plain">${report.priorities.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></section>` : ""}
  </div>`;
}

export function renderTasks() {
  const failed = store.assignmentsError && !store.assignments;
  const items = store.assignments?.items || [];
  if (store.resultView) return renderResult(store.resultView);
  return `<div class="stack">
    ${topbar()}
    <div class="row-between">
      <h1 id="page-title" tabindex="-1">Задания</h1>
      <button class="btn btn-primary" type="button" data-act="compose">Создать</button>
    </div>
    ${failed ? errorBlock(store.assignmentsError.message, "retry") : ""}
    ${items.length ? `<section class="sheet-block">${items.map((item) => `<button class="line" type="button" data-act="open-result" data-id="${item.id}"><span><b>${esc(item.title)}</b><small>${esc(item.status === "published" ? "опубликовано" : "черновик")} · сдали ${item.done || 0} из ${item.recipients || 0}</small></span></button>`).join("")}</section>` : emptyBlock("Работ пока нет", store.assignments?.detail || "Создай первое задание для класса.")}
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
  return `<div class="stack">
    ${topbar()}
    <section class="focus">
      <h1 id="page-title" tabindex="-1">Стимул</h1>
      <div class="pulse-line" aria-hidden="true"></div>
      <p>Помощник учителя готовится к запуску.</p>
      <p class="quiet">Это отдельный контекст учителя. Ответы модели не имитируются.</p>
    </section>
    <div class="chat">
      ${store.stimulDraft ? `<div class="bubble me">${esc(store.stimulDraft)}</div>` : ""}
      ${store.stimulNote ? `<div class="bubble">${esc(store.stimulNote)}</div>` : ""}
    </div>
    <div class="chips">${samples.map((text) => `<button class="chip" type="button" data-act="stimul-sample" data-text="${esc(text)}">${esc(text)}</button>`).join("")}</div>
    <form id="stimul-form" class="composer">
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
      <div class="actions">
        <button class="btn btn-ghost" type="button" data-act="wizard-back">Изменить параметры</button>
        <button class="btn btn-ghost" type="button" data-act="redraft" ${store.busy ? "disabled" : ""}>Собрать заново</button>
        <button class="btn btn-ghost" type="button" data-act="save-draft" ${!draft || store.busy ? "disabled" : ""}>Сохранить черновик</button>
        <button class="btn btn-primary" type="button" data-act="send-assignment" ${!draft || store.busy ? "disabled" : ""}>Опубликовать</button>
      </div>`;
  }
  const nav = wizard.step < 4
    ? `<div class="wizard-nav">
        ${wizard.step > 1 ? `<button class="btn btn-ghost" type="button" data-act="wizard-back">Назад</button>` : ""}
        <button class="btn btn-primary" type="button" data-act="wizard-next">Дальше</button>
      </div>`
    : "";
  return `<div class="stack">
    ${topbar()}
    <p class="kicker">Шаг ${wizard.step} из 4</p>
    <div class="track"><span style="width:${wizard.step * 25}%"></span></div>
    <h1 id="page-title" tabindex="-1">${titles[wizard.step - 1]}</h1>
    ${wizard.fieldError ? `<p class="field-error">${esc(wizard.fieldError)}</p>` : ""}
    ${body}
    ${nav}
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
  const name = store.displayName || "Учитель";
  const admin = Boolean(store.report?.can_manage_school || store.canManage);
  return `<div class="stack">
    ${topbar()}
    <section class="profile-card">
      <span class="avatar avatar-lg" aria-hidden="true">${esc(initials(name))}</span>
      <h1 id="page-title" tabindex="-1">${esc(name)}</h1>
      <p class="quiet">${admin ? "Учитель-администратор" : "Учитель"} · ${esc(classTitle())}</p>
      <p>В кабинете статусы тем и итоги работ. Личные вопросы учеников сюда не приходят.</p>
      <button class="btn btn-ghost" type="button" data-act="notices">Уведомления</button>
      ${admin ? `<button class="btn btn-primary" type="button" data-act="nav" data-screen="manage">Управление школой</button>` : ""}
    </section>
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
