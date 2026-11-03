import { getAssignments, getClass, getNotices, getWorkResult, postDraft, publishWork, saveWork } from "./api.js?v=3";
import { renderManage } from "./manage.js";
import { go, refresh, store } from "./store.js";
import {
  classbar,
  confirmDialog,
  mark,
  emptyBlock,
  errorBlock,
  esc,
  firstName,
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

function topbar() {
  const unread = Number(store.notices?.unread) || 0;
  const name = store.displayName || store.report?.display_name || "";
  return classbar({
    title: classTitle(),
    subject: subjectTitle(),
    letter: initials(name),
    unread,
    pickClass: true,
  });
}

const TONES = ["coral", "green", "yellow", "violet"];

function topicTone(row, index) {
  if (row.repeat) return "coral";
  if (row.practice) return "yellow";
  if (row.mastered && !row.none) return "green";
  if (row.mastered || row.practice || row.repeat) return "violet";
  return TONES[index % TONES.length];
}

function topicDetail(row, index, checks) {
  if (!checks) return index === 0 ? "Начните с короткой проверки" : "Материал ещё не проверен";
  if (row.repeat) return `Повторить: ${row.repeat}`;
  if (row.practice) return `Нужна практика: ${row.practice}`;
  if (row.mastered && !row.none) return "Усвоено";
  return "Материал ещё не проверен";
}

function publishedCount() {
  return (store.assignments?.items || []).filter((item) => item.status === "published").length;
}

function faceRow(students) {
  if (!students.length) return "";
  const shown = students.slice(0, 3);
  const extra = students.length - shown.length;
  const faces = shown.map((student) => `<span>${esc(initials(student.display_name))}</span>`).join("");
  return `<div class="faces" aria-hidden="true">${faces}${extra > 0 ? `<span>+${extra}</span>` : ""}</div>`;
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
  const name = firstName(store.displayName || store.report.display_name || "");
  const checks = publishedCount();
  const fresh = !checks && !info.known;
  const rows = rollup(store.report);
  const lead = fresh
    ? "Класс только начинает работу. Создайте первую проверку, чтобы увидеть общую картину."
    : (info.weak.length
      ? "По проверкам уже видно, каким темам нужна практика."
      : "Проверки уже были. Новая работа дополнит карту класса.");
  const heroTitle = fresh
    ? "Узнайте, что классу стоит повторить"
    : (info.ranked[0] ? `Стоит вернуться к теме «${info.ranked[0][0]}»` : "Можно дать ещё одну короткую проверку");
  const heroCopy = fresh
    ? "Короткая проверка покажет сильные темы и точки роста каждого ученика."
    : "Короткая работа покажет, кто уже держит тему и кому нужна поддержка.";
  const topics = rows.slice(0, 3).map((row, index) => `<button class="topic-preview__item" type="button" data-act="focus-topic" data-topic="${esc(row.title)}">
      <span class="topic-number topic-number--${topicTone(row, index)}">${String(index + 1).padStart(2, "0")}</span>
      <span><strong>${esc(row.title)}</strong><small>${esc(topicDetail(row, index, checks || info.known))}</small></span>
      <span class="topic-preview__arrow">${icon("arrow")}</span>
    </button>`).join("");
  return `<div class="fig">
    ${topbar()}
    <div class="fig-page page--overview">
      <div class="welcome">
        <div>
          <span class="eyebrow">Обзор класса</span>
          <h1 id="page-title">${name ? `Добрый день, ${esc(name)}` : "Добрый день"}</h1>
          <p>${lead}</p>
        </div>
      </div>
      <div class="overview-grid">
        <article class="hero-card">
          <div class="hero-card__top">
            <span class="status-pill"><span></span>${fresh ? "Можно начинать" : "Можно продолжить"}</span>
            ${mark(true)}
          </div>
          <div class="hero-card__copy">
            <span class="eyebrow eyebrow--light">${fresh ? "Первая работа" : "Следующая работа"}</span>
            <h2>${esc(heroTitle)}</h2>
            <p>${heroCopy}</p>
          </div>
          <button class="primary-button primary-button--light" type="button" data-act="compose">Создать работу<span>${icon("arrow")}</span></button>
        </article>
        <div class="stats-column">
          <article class="stat-card">
            <div>
              <span class="stat-card__label">Ученики</span>
              <strong>${info.students}</strong>
              <small>${info.students ? "в классе" : "пока никого нет"}</small>
            </div>
            ${faceRow(store.report.students || [])}
          </article>
          <article class="stat-card stat-card--accent">
            <span class="stat-card__label">Проверки</span>
            <strong>${checks}</strong>
            <small>${checks ? "уже проводились" : "пока не проводились"}</small>
          </article>
        </div>
      </div>
      <div class="section-heading">
        <div>
          <span class="eyebrow">Фокус недели</span>
          <h2>Темы класса</h2>
        </div>
        <button class="text-button" type="button" data-act="nav" data-screen="class">Вся карта ${icon("arrow")}</button>
      </div>
      ${topics ? `<div class="topic-preview">${topics}</div>` : `<p class="quiet">В программе класса пока нет тем.</p>`}
      ${store.report.frequent_mistakes ? `<p class="quiet">${esc(store.report.frequent_mistakes)}</p>` : ""}
    </div>
  </div>`;
}

export function renderClass() {
  if (!store.report) return errorBlock(store.reportError?.message, "retry");
  const report = store.report;
  const rows = rollup(report);
  const filters = [
    ["all", "Все темы"],
    ["mastered", "Усвоено"],
    ["needs_practice", "Практика"],
    ["repeat", "Повторить"],
  ];
  const selected = store.filters.topic !== "all" ? rows.find((row) => row.title === store.filters.topic) : null;
  const weakNames = selected
    ? (report.students || []).filter((student) => (student.topics || []).some((topic) => topic.title === selected.title && (topic.status === "repeat" || topic.status === "needs_practice"))).map((student) => student.display_name)
    : [];
  const visible = rows.filter((row) => {
    if (store.filters.status === "mastered") return row.mastered > 0;
    if (store.filters.status === "needs_practice") return row.practice > 0;
    if (store.filters.status === "repeat") return row.repeat > 0;
    return true;
  });
  const shareLabel = stats(report).known ? "Есть проверенные ответы" : "Пока нет данных";
  return `<div class="fig">
    ${topbar()}
    <div class="fig-page">
    <div class="page-heading">
      <span class="eyebrow">Прогресс ${esc(classTitle())}</span>
      <h1 id="page-title">Карта класса</h1>
      <p>${report.frequent_mistakes ? esc(report.frequent_mistakes) : "Здесь появится общая картина знаний после первой проверки."}</p>
    </div>
    <div class="filter-row" role="tablist" aria-label="Фильтр тем">
      ${filters.map(([id, label]) => `<button class="filter-chip ${store.filters.status === id ? "filter-chip--active" : ""}" type="button" data-act="filter-status" data-status="${id}">${label}</button>`).join("")}
    </div>
    <div class="map-summary">
      <div><span>Общий прогресс</span><strong>${shareLabel}</strong></div>
      <div class="map-summary__visual" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
    </div>
    <div class="topic-list">
      ${visible.map((row, index) => `<article class="topic-row">
        <div class="topic-row__marker topic-row__marker--${topicTone(row, index)}">${String(index + 1).padStart(2, "0")}</div>
        <div class="topic-row__content">
          <strong>${esc(row.title)}</strong>
          <span>${esc(topicDetail(row, index, publishedCount()))}</span>
          <div class="progress-track"><i style="width:${row.mastered + row.practice + row.repeat + row.none ? Math.max(4, Math.round((row.mastered / Math.max(1, row.mastered + row.practice + row.repeat + row.none)) * 100)) : 4}%"></i></div>
        </div>
        <button type="button" aria-label="Открыть тему ${esc(row.title)}" data-act="focus-topic" data-topic="${esc(row.title)}">${icon("arrow")}</button>
        ${store.filters.topic === row.title ? `<div class="reveal-body"><p>${weakNames.length ? `Нужна работа: ${esc(weakNames.join(", "))}.` : "По этой теме нет учеников со статусом «повторить» или «нужна практика»."}</p><button class="btn btn-primary" type="button" data-act="compose" data-topic="${esc(row.title)}">Собрать задание по теме</button></div>` : ""}
      </article>`).join("") || `<p class="quiet">Таких тем пока нет.</p>`}
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
  const empty = `<article class="empty-task-card">
      <div class="empty-task-card__art" aria-hidden="true">
        <div class="task-sheet task-sheet--back"></div>
        <div class="task-sheet task-sheet--front"><i></i><i></i><i></i></div>
        <span class="art-dot art-dot--one"></span>
        <span class="art-dot art-dot--two"></span>
      </div>
      <span class="eyebrow">Всё готово к старту</span>
      <h2>Работ ещё не было</h2>
      <p>Первая проверка поможет понять, кто уже держит тему, а кому нужна поддержка.</p>
      <button class="primary-button" type="button" data-act="compose">Создать первую работу ${icon("arrow")}</button>
    </article>
    <div class="tip-card">
      <div class="tip-card__icon">${icon("spark")}</div>
      <div><strong>Начните с 5–7 вопросов</strong><p>Так ученики не устанут, а вы быстро получите первую картину класса.</p></div>
    </div>`;
  return `<div class="fig">
    ${topbar()}
    <div class="fig-page">
      <div class="page-heading page-heading--row">
        <div>
          <span class="eyebrow">Работы класса</span>
          <h1 id="page-title">Задания</h1>
        </div>
        <button class="round-add" type="button" data-act="compose" aria-label="Создать задание">${icon("plus")}</button>
      </div>
      ${failed ? errorBlock(store.assignmentsError.message, "retry") : ""}
      ${items.length ? `${block("Активные", active)}${block("Черновики", drafts)}${block("Завершённые", done)}` : empty}
    </div>
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
  const samples = ["Собери короткую проверку по дробям", "Какие темы класса сейчас слабее?", "Придумай устный вопрос на дискриминант"];
  return `<div class="fig">
    ${topbar()}
    <div class="fig-page assistant-page">
      <div class="assistant-intro">
        <div class="assistant-intro__icon">${icon("spark")}</div>
        <div>
          <span class="eyebrow">Помощник учителя</span>
          <h1 id="page-title">С чего начнём?</h1>
          <p>Помогу подготовить задание или разобраться, чему уделить внимание.</p>
        </div>
      </div>
      <div class="prompt-grid">
        ${samples.map((text, index) => `<button type="button" data-act="stimul-sample" data-text="${esc(text)}"><span>${String(index + 1).padStart(2, "0")}</span><strong>${esc(text)}</strong>${icon("arrow")}</button>`).join("")}
      </div>
      ${store.stimulNote ? `<div class="assistant-notice" role="status">${icon("check")}<span>${esc(store.stimulNote)}</span></div>` : ""}
      <form id="stimul-form" class="composer">
        <button class="composer__attach" type="button" disabled aria-label="Добавить фото">${icon("camera")}</button>
        <input id="stimul-input" value="${esc(store.stimulDraft)}" placeholder="Спросите помощника" aria-label="Запрос помощнику">
        <button class="composer__send" type="submit" aria-label="Отправить">${icon("arrow")}</button>
      </form>
    </div>
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
  if (!store.wizard) startCompose();
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
  const name = store.displayName || store.report?.display_name || "";
  const admin = Boolean(store.report?.can_manage_school || store.canManage);
  const reviewer = store.report?.claims_reviewer;
  const subject = subjectTitle();
  const claimsAct = admin ? `data-act="nav" data-screen="manage"` : `data-act="class-info"`;
  return `<div class="fig">
    ${topbar()}
    <div class="fig-page">
      <div class="profile-card">
        <div class="profile-card__avatar">${esc(initials(name))}</div>
        <div>
          <span class="eyebrow">Учитель</span>
          <h1 id="page-title">${esc(firstName(name) || name || "Имя не пришло из профиля")}</h1>
          <p>Куратор класса ${esc(classTitle())}</p>
        </div>
        ${store.nameChanged ? "" : `<button class="profile-card__edit" type="button" data-act="profile-note">Изменить имя</button>`}
      </div>
      <div class="settings-card">
        <div class="settings-card__heading">
          <span class="eyebrow">Настройки</span>
          <h2>Класс и предмет</h2>
        </div>
        <button class="setting-row" type="button" data-act="class-sheet"><span>Класс</span><strong>${esc(classTitle())}</strong>${icon("arrow")}</button>
        <button class="setting-row" type="button" data-act="class-sheet"><span>Предмет</span><strong>${esc(subject || "не указан")}</strong>${icon("arrow")}</button>
        <button class="setting-row" type="button" ${claimsAct}><span>Заявки проверяет</span><strong>${esc(reviewer || "Ответственный не назначен")}</strong>${icon("arrow")}</button>
      </div>
      <div class="privacy-card">
        <div class="privacy-card__icon">${icon("bell")}</div>
        <div>
          <strong>Уведомления</strong>
          <p>Личные вопросы учеников в кабинет не приходят.</p>
        </div>
        <button type="button" data-act="notices">Настроить</button>
      </div>
    </div>
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
  if (store.screen !== "compose") go("compose");
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
