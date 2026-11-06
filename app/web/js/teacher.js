import { attachWorkResource, createSubject, createTopic, deleteMaterial, deleteWorkResource, getAssignments, getClass, getMaterials, getNotices, getProgram, getWorkResult, postDraft, publishWork, saveWork, uploadMaterial } from "./api.js?v=7";
import { chatTitle, clearChatPhoto, loadChats, newChat, openChat, sendChat, showChatList } from "./chat.js?v=4";
import { renderManage } from "./manage.js?v=12";
import { go, refresh, store } from "./store.js?v=5";
import { themePref } from "./theme.js?v=1";
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
  nl,
  pill,
  plural,
  themeSwitch,
  toast,
} from "./ui.js?v=5";

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
  if (!checks) return index === 0 ? "Начните с короткой проверки" : "Нет заданий по теме";
  if (row.repeat) {
    const n = row.repeat;
    return `${n} ${plural(n, "ученик", "ученика", "учеников")} повторяют`;
  }
  if (row.practice) {
    const n = row.practice;
    return `${n} ${plural(n, "ученик", "ученика", "учеников")} с ошибками`;
  }
  if (row.mastered && !row.none) return "Усвоено";
  return "Нет заданий по теме";
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

function subjectOptions() {
  const raw = store.program?.subjects?.length ? store.program.subjects : store.report?.subjects || [];
  return raw
    .map((item) => ({ id: Number(item.id) || 0, title: item.title || String(item) }))
    .filter((item) => item.id && item.title);
}

function activeSubjectId() {
  return Number(store.subjectId) || null;
}

function sameSubject(a, b) {
  const left = a == null ? null : Number(a);
  const right = b == null ? null : Number(b);
  return left == null || right == null || left === right;
}

function inActiveSubject(topic) {
  return sameSubject(topic?.subject_id, activeSubjectId());
}

function rollup(report) {
  return (report.topics || []).map((topic) => {
    const cells = [];
    for (const student of report.students || []) {
      const found = (student.topics || []).find(
        (item) => item.title === topic.title && sameSubject(item.subject_id, topic.subject_id),
      );
      if (found) cells.push(found);
    }
    return {
      title: topic.title,
      subject_id: topic.subject_id ?? null,
      subject_title: topic.subject_title || "",
      mastered: cells.filter((cell) => cell.status === "mastered").length,
      practice: cells.filter((cell) => cell.status === "needs_practice").length,
      repeat: cells.filter((cell) => cell.status === "repeat").length,
      none: cells.filter((cell) => !cell.status).length,
    };
  });
}

function claimsBlock() {
  const items = store.report?.pending_claims || [];
  if (!items.length) return "";
  return `<section class="sheet-block">
    <h2>Заявки</h2>
    <div class="rows">${items.map((item) => `<div class="line"><span><b>${esc(item.display_name)}</b><small>${esc(item.class_title)} · ${item.wanted_role === "teacher" ? "учитель" : "ученик"}</small></span><span class="attach"><button class="btn btn-primary" type="button" data-act="accept-claim" data-id="${item.user_id}">Принять</button><button class="btn btn-ghost" type="button" data-act="reject-claim" data-id="${item.user_id}">Отклонить</button></span></div>`).join("")}</div>
  </section>`;
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
    ? "Класс ещё без проверок. Соберите первую, и на карте будет видно, кто что сдал."
    : (info.weak.length
      ? "По ответам уже видно, какие темы стоит повторить."
      : "Проверки уже были. Новая работа дополнит карту.");
  const heroTitle = fresh
    ? "Первая проверка по вашей теме"
    : (info.ranked[0] ? `Стоит вернуться к теме «${info.ranked[0][0]}»` : "Можно дать ещё одну короткую проверку");
  const heroCopy = fresh
    ? "После неё на карте класса будет видно, кто тему уже держит."
    : "Короткая работа покажет, кто тему держит и кому она ещё трудна.";
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
      ${claimsBlock()}
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
            <small>${checks ? `Проведено ${checks} ${plural(checks, "проверка", "проверки", "проверок")}` : "Ещё не проводились"}</small>
          </article>
        </div>
      </div>
      <div class="section-heading">
        <div>
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
  const allRows = rollup(report);
  const rows = allRows.filter((row) => sameSubject(row.subject_id, activeSubjectId()));
  const subjectChips = subjectOptions().length > 1
    ? `<div class="filter-row" role="tablist" aria-label="Предмет">
      <button class="filter-chip ${!activeSubjectId() ? "filter-chip--active" : ""}" type="button" data-act="class-subject" data-id="">Все предметы</button>
      ${subjectOptions().map((item) => `<button class="filter-chip ${activeSubjectId() === item.id ? "filter-chip--active" : ""}" type="button" data-act="class-subject" data-id="${item.id}">${esc(item.title)}</button>`).join("")}
    </div>`
    : "";
  const filters = [
    ["all", "Все темы"],
    ["mastered", "Усвоено"],
    ["needs_practice", "Практика"],
    ["repeat", "Повторить"],
  ];
  const selected = store.filters.topic !== "all" ? rows.find((row) => row.title === store.filters.topic) : null;
  const weakNames = selected
    ? (report.students || []).filter((student) => (student.topics || []).some((topic) => topic.title === selected.title && sameSubject(topic.subject_id, selected.subject_id) && (topic.status === "repeat" || topic.status === "needs_practice"))).map((student) => student.display_name)
    : [];
  const visible = rows.filter((row) => {
    if (store.filters.status === "mastered") return row.mastered > 0;
    if (store.filters.status === "needs_practice") return row.practice > 0;
    if (store.filters.status === "repeat") return row.repeat > 0;
    return true;
  });
  return `<div class="fig">
    ${topbar()}
    <div class="fig-page">
    <div class="page-heading">
      <h1 id="page-title">Карта класса</h1>
      <p>${report.frequent_mistakes ? esc(report.frequent_mistakes) : "Нажмите на кружок. Зелёный: усвоено. Жёлтый: нужна практика. Красный: повторить."}</p>
    </div>
    ${subjectChips}
    <div class="filter-row" role="tablist" aria-label="Фильтр тем">
      ${filters.map(([id, label]) => `<button class="filter-chip ${store.filters.status === id ? "filter-chip--active" : ""}" type="button" data-act="filter-status" data-status="${id}">${label}</button>`).join("")}
    </div>
    <div class="roster" role="list">${rosterPeople(report)}</div>
    ${studentSheet(report)}
    <div class="topic-list">
      ${visible.map((row, index) => `<article class="topic-row">
        <div class="topic-row__marker topic-row__marker--${topicTone(row, index)}">${String(index + 1).padStart(2, "0")}</div>
        <div class="topic-row__content">
          <strong>${esc(row.title)}</strong>
          <span>${esc(topicDetail(row, index, publishedCount() || stats(report).known))}</span>
          <div class="progress-track"><i style="width:${row.mastered + row.practice + row.repeat + row.none ? Math.max(4, Math.round((row.mastered / Math.max(1, row.mastered + row.practice + row.repeat + row.none)) * 100)) : 4}%"></i></div>
        </div>
        <button type="button" aria-label="Открыть тему ${esc(row.title)}" data-act="focus-topic" data-topic="${esc(row.title)}">${icon("arrow")}</button>
        ${store.filters.topic === row.title ? `<div class="reveal-body"><p>${weakNames.length ? `Нужна работа: ${esc(weakNames.join(", "))}.` : "По этой теме нет учеников со статусом «повторить» или «нужна практика»."}</p><div class="flow-bar"><button class="btn btn-ghost" type="button" data-act="compose" data-mode="own" data-topic="${esc(row.title)}">Написать самому</button><button class="btn btn-primary" type="button" data-act="stimul-topic" data-topic="${esc(row.title)}">Попросить Стимула</button></div></div>` : ""}
      </article>`).join("") || `<p class="quiet">Таких тем пока нет.</p>`}
    </div>
    ${(report.priorities || []).length ? `<div><h2>Кому помочь</h2><ul class="plain">${report.priorities.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></div>` : ""}
    </div>
  </div>`;
}

function studentTone(student) {
  const topics = (student.topics || []).filter(inActiveSubject);
  if (topics.some((topic) => topic.status === "repeat")) return "coral";
  if (topics.some((topic) => topic.status === "needs_practice")) return "yellow";
  if (topics.some((topic) => topic.status === "mastered")) return "green";
  return "idle";
}

function matchesFilter(student) {
  const scoped = (student.topics || []).filter(inActiveSubject);
  if (store.filters.status === "all") return scoped.length ? true : !(student.topics || []).length;
  return scoped.some((topic) => {
    if (store.filters.topic !== "all" && topic.title !== store.filters.topic) return false;
    if (store.filters.status === "none") return !topic.status;
    return topic.status === store.filters.status;
  });
}

function rosterPeople(report) {
  const people = (report.students || []).filter(matchesFilter);
  if (!people.length) return `<p class="quiet">Таких учеников нет.</p>`;
  return people.map((student) => {
    const on = store.focusStudent === student.display_name;
    return `<button class="roster-person ${on ? "is-on" : ""}" type="button" role="listitem" data-act="focus-student" data-name="${esc(student.display_name)}" aria-pressed="${on}">
      <span class="roster-avatar roster-avatar--${studentTone(student)}">${esc(initials(student.display_name))}</span>
      <span>${esc(firstName(student.display_name) || student.display_name)}</span>
    </button>`;
  }).join("");
}

function studentSheet(report) {
  const person = (report.students || []).find((student) => student.display_name === store.focusStudent);
  if (!person) return `<p class="quiet">Нажмите на кружок ученика, чтобы увидеть темы и чем он занят.</p>`;
  const topics = (person.topics || []).filter(
    (topic) => inActiveSubject(topic) && (store.filters.topic === "all" || topic.title === store.filters.topic),
  );
  return `<article class="student-sheet">
    <h2>${esc(person.display_name)}</h2>
    <p>${esc(person.activity || "Пока нет занятий.")}</p>
    <div class="stack tight">${topics.map((topic) => `<div class="line"><span><b>${esc(topic.title)}</b><small>${topic.correct_percent != null ? `${topic.correct_percent}% верных` : "попыток ещё нет"}</small></span>${pill(topic.status)}</div>`).join("")}</div>
  </article>`;
}

function workDay(iso) {
  const date = new Date(iso || "");
  if (!iso || Number.isNaN(date.getTime())) return "";
  const opts = { day: "numeric", month: "short" };
  if (date.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return new Intl.DateTimeFormat("ru-RU", opts).format(date);
}

function workLine(item) {
  const published = item.status === "published";
  const handed = item.handed || [];
  const started = item.started || [];
  const finished = published && item.recipients && item.done >= item.recipients;
  let label = published ? "" : "черновик";
  if (published && finished) label = handed.length ? `сдали ${handed.join(", ")}` : "все сдали";
  else if (published && handed.length) label = `сдали ${handed.join(", ")} · ещё ${(item.recipients || 0) - (item.done || 0)}`;
  else if (published && started.length) label = `начали ${started.join(", ")}`;
  else if (published) label = `сдали 0 из ${item.recipients || 0}`;
  const when = workDay(item.published_at || item.created_at);
  const meta = [item.subject, when, label].filter(Boolean).join(" · ");
  const badge = published ? "" : `<span class="work-badge">Черновик</span>`;
  return `<button class="line" type="button" data-act="open-result" data-id="${item.id}"><span><b>${esc(item.title)}</b><small>${esc(meta)}</small></span>${badge}</button>`;
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
      <h2>Работ ещё не было</h2>
      <p>Напишите тему и вопросы сами или попросите Стимула собрать проверку.</p>
      <button class="primary-button" type="button" data-act="compose" data-mode="own">Новая тема ${icon("arrow")}</button>
    </article>
    <div class="tip-card">
      <div class="tip-card__icon">${icon("spark")}</div>
      <div><strong>Трёх вопросов обычно хватает</strong><p>Так видно, кто тему держит, и ученики не сидят над листом слишком долго.</p></div>
    </div>`;
  return `<div class="fig">
    ${topbar()}
    <div class="fig-page">
      <div class="page-heading page-heading--row">
        <div>
          <h1 id="page-title">Задания</h1>
        </div>
        <div class="task-actions">
          <button class="text-button" type="button" data-act="nav" data-screen="stimul">Попросить Стимула</button>
          <button class="round-add" type="button" data-act="compose" data-mode="own" aria-label="Новая тема">${icon("plus")}</button>
        </div>
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
    ${people.length ? `<section class="sheet-block">${people.map((person) => `<div class="line"><span><b>${esc(person.display_name)}</b><small>${person.status === "done" ? `сдано, верно ${person.correct} из ${person.answered}` : person.answered ? `ответил на ${person.answered}, работа ещё не закрыта` : "ещё не сдано"}</small></span></div>`).join("")}</section>` : `<p class="quiet">Получателей нет.</p>`}
    ${waiting.length ? `<p class="quiet">Ещё не сдали: ${esc(waiting.map((person) => person.display_name).join(", "))}.</p>` : `<p class="quiet">Все, кому работа назначена, её сдали.</p>`}
    ${!people.some((person) => person.status === "done" || person.answered) ? `<p class="quiet">Если ученик только разбирал тему у себя, это видно на карте класса. В эту работу ответ попадает, когда он сдаёт её в заданиях.</p>` : ""}
  </div>`;
}

function draftCardActions(message) {
  const payload = message.payload || {};
  if (payload.draft?.sent) return `<p class="chat-status">Работа отправлена ученикам.</p>`;
  return `<div class="chat-card__actions">
    <button class="btn btn-ghost" type="button" data-act="draft-review" data-mid="${message.id}">Проверить</button>
    <button class="btn btn-primary" type="button" data-act="draft-send" data-mid="${message.id}">Отправить</button>
  </div>`;
}

function chatRow(message) {
  if (message.role === "user") {
    return `<div class="chat-msg chat-msg--me"><div class="chat-msg__bubble">${nl(message.text)}</div></div>`;
  }
  const payload = message.payload || {};
  let body;
  if (message.kind === "draft" && payload.draft) {
    const draft = payload.draft;
    body = `<div class="chat-card"><strong>Черновик готов</strong>
      <p>${esc(draft.topic || "")} · ${esc(draft.count || "")} заданий · ${esc((draft.audience === "selected" ? (draft.students || []).join(", ") : "весь класс") || "")}</p>
      ${draftCardActions(message)}</div>`;
  } else {
    body = `<p>${nl(message.text || payload.text || "")}</p>`;
  }
  return `<div class="chat-msg"><span class="chat-msg__avatar">${mark()}</span><div class="chat-msg__body">${body}</div></div>`;
}

function chatPhotoChip() {
  if (!store.chatPhotoURL) return "";
  return `<div class="chat-photo-chip"><img alt="" src="${esc(store.chatPhotoURL)}"><span>Фото прикреплено</span><button class="text-btn" type="button" data-act="clear-chat-photo">Убрать</button></div>`;
}

function chatQuickActions() {
  if (!store.chatPhotoURL) return "";
  const items = [
    ["Создать тест", "Собери проверку по этому материалу"],
    ["Конспект", "Сделай конспект по этому материалу"],
    ["Объяснение", "Объясни этот материал простыми словами"],
  ];
  return `<div class="chat-quick">${items
    .map(([label, text]) => `<button type="button" data-act="chat-sample" data-text="${esc(text)}">${esc(label)}</button>`)
    .join("")}</div>`;
}

function chatEmpty() {
  const pick = `<button type="button" data-act="pick-chat-photo">Тест по фото</button>`;
  const samples = [
    ["Список тем", "Покажи темы класса и где больше всего ошибок"],
    ["Разбор ошибок класса", "Разбери ошибки класса по темам"],
  ];
  return `<div class="chat-empty">
    <div class="chat-empty__mark">${mark(true)}</div>
    <h2>С чем помочь?</h2>
    <p>Соберу проверку по теме или по материалу урока и покажу слабые места класса.</p>
    <div class="chat-suggest">${pick}${samples.map(([label, text]) => `<button type="button" data-act="chat-sample" data-text="${esc(text)}">${esc(label)}</button>`).join("")}</div>
  </div>`;
}

function chatThread() {
  const messages = store.chatMessages || [];
  const typing = store.chatBusy
    ? `<div class="chat-msg"><span class="chat-msg__avatar">${mark()}</span><div class="chat-typing" role="status" aria-label="Стимул пишет"><i></i><i></i><i></i></div></div>`
    : "";
  const rows = messages.length ? messages.map(chatRow).join("") + typing : typing || chatEmpty();
  return `<div class="chat-scroll"><div class="chat-thread">${rows}</div>
    ${store.stimulNote ? `<div class="assistant-notice" role="status">${icon("check")}<span>${esc(store.stimulNote)}</span></div>` : ""}
    ${materialsBlock()}
    <div class="chat-scroll-end"></div></div>
    <div class="chat-bottom">
      ${chatPhotoChip()}
      ${chatQuickActions()}
      ${store.chatRateNote ? `<p class="chat-status" role="status">${esc(store.chatRateNote)}</p>` : ""}
      ${store.chatError && store.chatError !== store.chatRateNote ? `<p class="chat-error" role="alert">${esc(store.chatError)}</p>` : ""}
      ${store.chatStatus ? `<p class="chat-status" role="status">${esc(store.chatStatus)}</p>` : ""}
      <form id="chat-form" class="chat-composer">
        <label class="chat-composer__attach" aria-label="Фото страницы">${icon("image")}<input id="chat-photo" type="file" accept="image/*"></label>
        <input id="chat-input" value="${esc(store.chatDraft)}" placeholder="Спросить Стимула" autocomplete="off" aria-label="Запрос помощнику" ${store.chatBusy ? "disabled" : ""}>
        <button class="chat-composer__send" type="submit" aria-label="Отправить" ${store.chatBusy ? "disabled" : ""}>${icon("send")}</button>
      </form>
      <p class="chat-note">Разговор хранится отдельно и виден только вам.</p>
    </div>`;
}

function chatList() {
  const items = store.chats?.items || [];
  return `${store.chatId ? `<button class="text-button back" type="button" data-act="assistant-back">${icon("chevron")} К разговору</button>` : ""}
    <div class="page-heading">
      <span class="eyebrow">Помощник</span>
      <h1 id="page-title">Разговоры</h1>
      <p>История запросов и ответов. Видна только вам.</p>
    </div>
    ${store.chatsError ? `<p class="field-error">${esc(store.chatsError)}</p>` : ""}
    <button class="btn btn-primary" type="button" data-act="assistant-new">Новый разговор</button>
    <div class="topic-preview" style="margin-top:14px">
      ${items.length ? items.map((item) => `<button class="study-row" type="button" data-act="assistant-open" data-id="${item.id}">
        <span class="topic-number topic-number--violet">✦</span>
        <span><strong>${esc(item.title || "Без названия")}</strong><small>${esc(new Date(item.updated_at).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }))}</small></span>
        <span class="topic-preview__arrow">${icon("arrow")}</span>
      </button>`).join("") : `<p class="quiet">Разговоров пока нет.</p>`}
    </div>`;
}

function materialsBlock() {
  const items = store.materials?.items || [];
  return `<section class="materials">
    <div class="materials__head">
      <div><strong>Материалы урока</strong><small>Учебник, параграф или фото страницы. По ним собираются задания.</small></div>
      <label class="btn btn-ghost file">Добавить<input id="material-file" type="file" accept=".pdf,.docx,.pptx,.txt,image/*" aria-label="Загрузить материал"></label>
    </div>
    ${store.materialsError ? `<p class="field-error">${esc(store.materialsError)}</p>` : ""}
    ${store.materials === null ? `<p class="quiet">Загружаю список…</p>` : items.length ? `<div class="stack tight">${items.map((item) => `<div class="line material-line">
      <span class="material-line__main"><b>${esc(item.title)}</b><small>${item.fragments} фрагм. · ${kindLabel(item.kind)}</small></span>
      <span class="material-state"><i></i>Активен</span>
      <button class="icon-button material-line__del" type="button" data-act="material-delete" data-id="${item.id}" aria-label="Убрать материал" title="Убрать">${icon("close")}</button>
    </div>`).join("")}</div>` : `<p class="quiet">Пока пусто. Добавьте PDF, DOCX, PPTX, TXT или фото страницы — задания «по материалу» собираются только по загруженному.</p>`}
  </section>`;
}

export function renderStimul() {
  if (store.chatView === "list") {
    return `<div class="fig">
      ${topbar()}
      <div class="fig-page assistant-page">${chatList()}</div>
    </div>`;
  }
  return `<div class="fig">
    ${topbar()}
    <div class="fig-page assistant-page chat-page">
      <div class="chat-head">
        <div class="chat-head__who">${mark()}<div><span class="eyebrow">Помощник</span><h1 id="page-title">${esc(chatTitle())}</h1></div></div>
        <div class="chat-head__actions">
          <button class="chat-tool" type="button" data-act="assistant-chats" aria-label="Разговоры" title="Разговоры">${icon("list")}</button>
          <button class="chat-tool" type="button" data-act="assistant-new" aria-label="Новый разговор" title="Новый разговор">${icon("plus")}</button>
        </div>
      </div>
      ${chatThread()}
    </div>
  </div>`;
}

function kindLabel(kind) {
  return { pdf: "PDF", docx: "DOCX", pptx: "PPTX", photo: "фото", text: "текст" }[kind] || kind;
}

export async function sendStimul(text) {
  const question = (text ?? store.chatDraft ?? store.stimulDraft ?? "").trim();
  const photo = store.chatPhotoFile || null;
  if (!question && !photo) return;
  await sendChat(question, {
    classId: store.classId || null,
    photo,
    onReply: (reply) => {
      if (reply && reply.kind === "draft" && reply.draft) {
        store.lastDraftReply = reply;
      }
      if (reply?.refresh_program) loadProgram();
    },
  });
  if (!store.chatError) clearChatPhoto();
}

function draftReplyById(mid) {
  const message = (store.chatMessages || []).find((item) => String(item.id) === String(mid));
  const payload = message?.payload;
  return payload && payload.draft ? payload : store.lastDraftReply;
}

export async function reviewDraft(mid) {
  const reply = draftReplyById(mid);
  if (!reply?.draft) return;
  openAssistantWizard(reply);
}

export async function sendDraftNow(mid) {
  const reply = draftReplyById(mid);
  const draft = reply?.draft;
  if (!draft || store.busy) return;
  const plan = reply.wizard || {};
  const audience = draft.audience === "selected" ? "selected" : "class";
  const names = audience === "selected" ? draft.students || [] : [];
  const ids = audience === "selected" ? plan.student_ids || [] : [];
  const items = (draft.items || [])
    .map((item) => ({ prompt: String(item.prompt || "").trim(), reference: String(item.reference || "").trim() }))
    .filter((item) => item.prompt && item.reference);
  if (!items.length) {
    store.chatError = "В черновике нет ни одного полного задания.";
    refresh();
    return;
  }
  const ok = await confirmDialog({
    title: "Отправить работу",
    text: `«${draft.topic || "Работа"}»: ${items.length} заданий, ${audience === "class" ? "весь класс" : names.join(", ") || "выбранные ученики"}. Вопросы не открывались в редакторе.`,
    confirm: "Отправить",
    cancel: "Отмена",
  });
  if (!ok) return;
  store.busy = true;
  store.chatError = "";
  refresh();
  try {
    const saved = await saveWork({
      topic: draft.topic || plan.topic || "",
      goal: draft.goal || plan.goal || "",
      count: items.length,
      difficulty: plan.difficulty || "normal",
      audience,
      students: names,
      student_ids: ids,
      prompts: items.map((item) => item.prompt),
      items,
      blurb: "",
      due_at: null,
      class_id: store.classId || null,
      work_id: null,
      subject_id: store.subjectId || null,
    });
    if (!saved?.persisted || !saved.id) {
      store.chatError = "Сервер не сохранил работу. Ученикам ничего не ушло.";
      return;
    }
    const published = await publishWork(saved.id);
    if (!published?.persisted) {
      store.chatError = "Черновик записан, публикация не подтверждена.";
      return;
    }
    draft.sent = true;
    store.lastDraftReply = null;
    toast(`Работа «${draft.topic || ""}» отправлена: ${published.recipients || ""} учеников.`);
    reloadQuiet();
  } catch (error) {
    store.chatError = error.message || "Не получилось отправить.";
  } finally {
    store.busy = false;
    refresh();
  }
}

function openAssistantWizard(reply) {
  const plan = reply.wizard || {};
  const students = reply.draft.audience === "selected"
    ? (plan.students || [])
    : [];
  store.wizardReturn = "stimul";
  store.wizard = {
    step: 1,
    mode: "stimul",
    subjectId: plan.subject_id || store.subjectId || null,
    topic: plan.topic || reply.draft.topic || "",
    goal: plan.goal || reply.draft.goal || "",
    blurb: "",
    count: plan.count || reply.draft.count || 3,
    difficulty: plan.difficulty || "normal",
    audience: reply.draft.audience === "selected" ? "selected" : "class",
    students,
    studentIds: plan.student_ids || [],
    studentQuery: "",
    own: [],
    useMaterial: Boolean(plan.use_material),
    dueAt: "",
    resources: [],
    autosave: "idle",
    draft: reply.draft,
    draftError: null,
    sendError: null,
    fieldError: "",
    triedKey: "",
    draftKey: "",
  };
  store.wizard.triedKey = store.wizard.draftKey = draftPayloadKey();
  const unknown = (reply.unknown_students || []).join(", ");
  if (unknown) {
    store.wizard.sendError = null;
    reply.draft.note = `${reply.draft.note ? `${reply.draft.note} ` : ""}Не нашёл в классе: ${unknown}.`;
  }
  store.stimulAnswer = null;
  store.stimulDraft = "";
  go("compose");
}

export async function loadMaterials() {
  if (store.preview || store.role !== "teacher") {
    store.materials = { items: [] };
    refresh();
    return;
  }
  store.materialsError = "";
  try {
    store.materials = await getMaterials(store.classId || undefined);
  } catch (error) {
    store.materials = { items: [] };
    store.materialsError = error.message;
  }
  refresh();
}

export async function addMaterial(file) {
  if (!file || store.stimulBusy) return;
  store.stimulBusy = true;
  store.materialsError = "";
  refresh();
  try {
    const saved = await uploadMaterial(file, "", store.classId || undefined);
    store.materials = { items: saved?.items || store.materials?.items || [] };
    store.stimulNote = `«${saved?.item?.title || file.name}» разобран на фрагменты. Теперь можно собирать задания по материалу.`;
  } catch (error) {
    store.materialsError = error.message;
  } finally {
    store.stimulBusy = false;
    refresh();
  }
}

export async function removeMaterial(id) {
  if (store.stimulBusy) return;
  store.stimulBusy = true;
  store.materialsError = "";
  refresh();
  try {
    await deleteMaterial(Number(id), store.classId || undefined);
    const items = (store.materials?.items || []).filter((item) => item.id !== Number(id));
    store.materials = { items };
  } catch (error) {
    store.materialsError = error.message;
  } finally {
    store.stimulBusy = false;
    refresh();
  }
}

function neededStudentIds(wizard) {
  const topic = String(wizard?.topic || "").trim();
  const subjectId = Number(wizard?.subjectId || store.subjectId) || null;
  if (!topic) return [];
  const ids = [];
  for (const student of store.report?.students || []) {
    const hit = (student.topics || []).some(
      (item) =>
        item.title === topic &&
        (!subjectId || item.subject_id == null || Number(item.subject_id) === subjectId) &&
        (item.status === "needs_practice" || item.status === "repeat"),
    );
    if (hit && student.user_id) ids.push(student.user_id);
  }
  return ids;
}

function neededNames(ids) {
  const roster = store.report?.students || [];
  return ids
    .map((id) => roster.find((student) => student.user_id === id)?.display_name || "")
    .filter(Boolean);
}

function resolvedAudience(wizard) {
  if (wizard.audience === "needed") {
    const ids = neededStudentIds(wizard);
    return { audience: "selected", students: neededNames(ids), student_ids: ids };
  }
  if (wizard.audience === "selected") {
    return { audience: "selected", students: wizard.students || [], student_ids: wizard.studentIds || [] };
  }
  return { audience: "class", students: [], student_ids: [] };
}

function audienceTiles(wizard, students) {
  const needed = neededStudentIds(wizard).length;
  const tile = (value, title, hint) => `<button class="audience-tile ${wizard.audience === value ? "is-on" : ""}" type="button" data-act="audience" data-value="${value}" aria-pressed="${wizard.audience === value}">
    <strong>${title}</strong><small>${hint}</small></button>`;
  return `<div class="audience-tiles">
    ${tile("class", "Весь класс", `${students.length} ${plural(students.length, "ученик", "ученика", "учеников")}`)}
    ${tile("selected", "Выбрать учеников", `${(wizard.studentIds || []).length} выбрано`)}
    ${tile("needed", "Кому нужна практика", needed ? `${needed} по теме` : "по этой теме")}
  </div>`;
}

export function studentRowsHTML() {
  const wizard = store.wizard;
  if (!wizard) return "";
  const students = store.report?.students || [];
  const query = String(wizard.studentQuery || "").trim().toLowerCase();
  const visible = students.filter(
    (student) => !query || String(student.display_name || "").toLowerCase().includes(query),
  );
  const ids = wizard.studentIds || [];
  if (!visible.length) return `<p class="quiet">Таких учеников нет.</p>`;
  return `<div class="student-list">${visible
    .map((student) => {
      const on = ids.includes(student.user_id);
      return `<label class="student-check ${on ? "is-on" : ""}">
        <input type="checkbox" data-student-id="${student.user_id}" data-name="${esc(student.display_name)}" ${on ? "checked" : ""}>
        <span>${esc(student.display_name)}</span></label>`;
    })
    .join("")}</div>`;
}

function neededPanel(wizard) {
  const ids = neededStudentIds(wizard);
  if (!String(wizard.topic || "").trim()) {
    return `<p class="hint">Сначала укажите тему на первом шаге.</p>`;
  }
  if (!ids.length) {
    return `<p class="hint">По теме «${esc(wizard.topic)}» пока никто не помечен «нужна практика» или «повторить». Выберите учеников вручную или отправьте всему классу.</p>`;
  }
  return `<div class="student-list">${neededNames(ids)
    .map((name) => `<div class="student-check is-on"><span>${esc(name)}</span></div>`)
    .join("")}</div>
    <p class="hint">Отметка берётся с карты класса: «нужна практика» и «повторить» по этой теме.</p>`;
}

function audienceCount(wizard, students) {
  const total = students.length;
  const get =
    wizard.audience === "class"
      ? total
      : wizard.audience === "needed"
        ? neededStudentIds(wizard).length
        : (wizard.studentIds || []).length;
  return `<p class="audience-count">Получат: ${get} из ${total}</p>`;
}

function cleanDraftNote(note) {
  return String(note || "")
    .replace(/[^.!?]*(?:не сош[а-яё]*|Проверьте (?:его|их|ответ))[^.!?]*[.!?]?/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function autosaveLine(wizard) {
  if (wizard.autosave === "saving") return `<p class="hint autosave-note">Сохраняю черновик…</p>`;
  if (wizard.autosave === "saved") return `<p class="hint autosave-note">Черновик сохранён автоматически.</p>`;
  if (wizard.autosave === "error") return `<p class="field-error">Автосохранение не удалось — нажмите «Черновик».</p>`;
  return "";
}

function wizardBody() {
  const wizard = store.wizard;
  const subjects = subjectOptions();
  if (!wizard) return "";
  if (!subjects.length) {
    return `<section class="panel">
      <div class="who"><b>Работу отправить нельзя</b><span>Нет предмета</span></div>
      <p>В этом классе нет назначения на предмет. Пока учителя предмета нет, заданий нет.</p>
      <button class="btn btn-primary" type="button" data-act="nav" data-screen="tasks">Закрыть</button>
    </section>`;
  }
  const activeSubject = Number(wizard.subjectId || store.subjectId || subjects[0]?.id) || null;
  const topics = (store.report?.topics || [])
    .filter((topic) => !activeSubject || topic.subject_id == null || Number(topic.subject_id) === activeSubject)
    .map((topic) => topic.title);
  const titles =
    wizard.mode === "stimul"
      ? ["Тема", "Задания", "Кому", "Просмотр и отправка"]
      : ["Тема", "Вопросы", "Кому", "Просмотр и отправка"];
  const students = store.report?.students || [];
  const subjectSelect = subjects.length > 1
    ? `<label class="field-label" for="wiz-subject">Предмет</label>
      <select id="wiz-subject" class="field">${subjects.map((item) => `<option value="${item.id}" ${activeSubject === item.id ? "selected" : ""}>${esc(item.title)}</option>`).join("")}</select>`
    : "";
  let body = "";
  if (wizard.step === 1) {
    body = `${subjectSelect}
      <label class="field-label" for="topic">Тема</label>
      <input id="topic" class="field" list="topic-list" value="${esc(wizard.topic)}" placeholder="Например: проценты" autocomplete="off">
      <datalist id="topic-list">${topics.map((title) => `<option value="${esc(title)}"></option>`).join("")}</datalist>
      <label class="field-label" for="goal">Что проверить <span class="hint-inline">необязательно</span></label>
      <textarea id="goal" class="area" placeholder="Например: найти процент от числа">${esc(wizard.goal)}</textarea>
      <label class="field-label" for="blurb">Коротко для учеников</label>
      <textarea id="blurb" class="area" placeholder="Два предложения перед заданиями. Можно оставить пустым.">${esc(wizard.blurb || "")}</textarea>
      <p class="hint">${wizard.mode === "stimul" ? "Стимул соберёт вопросы, если тема похожа на программу 8 класса. Если нет, напишите их сами." : "Название может быть любым. Вопросы и верные ответы вы напишете на следующем шаге."}</p>`;
  } else if (wizard.step === 2 && wizard.mode === "own") {
    const rows = Array.from({ length: wizard.count }, (_, index) => wizard.own?.[index] || { prompt: "", reference: "" });
    body = `<p class="field-label">Сколько заданий</p>
      <div class="chips">${[1, 2, 3, 4, 5, 6].map((count) => `<button class="chip ${wizard.count === count ? "is-on" : ""}" type="button" data-act="count" data-value="${count}">${count}</button>`).join("")}</div>
      ${rows.map((item, index) => `<label class="field-label" for="own-prompt-${index}">Задание ${index + 1}</label>
        <textarea id="own-prompt-${index}" class="area" data-own-prompt="${index}">${esc(item.prompt || "")}</textarea>
        <label class="field-label" for="own-answer-${index}">Верный ответ</label>
        <input id="own-answer-${index}" class="field" data-own-answer="${index}" value="${esc(item.reference || "")}" autocomplete="off">`).join("")}
      <p class="hint">Ученик увидит вопрос. Верный ответ останется у вас, по нему программа проверит сдачу.</p>`;
  } else if (wizard.step === 2) {
    body = `<p class="field-label">Сколько заданий</p>
      <div class="chips">${[1, 2, 3, 4, 5, 6].map((count) => `<button class="chip ${wizard.count === count ? "is-on" : ""}" type="button" data-act="count" data-value="${count}">${count}</button>`).join("")}</div>
      <p class="field-label">Сложность</p>
      <div class="chips">${DIFFICULTIES.map(([id, label]) => `<button class="chip ${wizard.difficulty === id ? "is-on" : ""}" type="button" data-act="difficulty" data-value="${id}">${label}</button>`).join("")}</div>
      <p class="hint">Стимул возьмёт вопросы из программы 8 класса и посчитает ответы. На просмотре их можно поправить.</p>
      ${(store.materials?.items || []).length ? `<label class="check"><input id="use-material" type="checkbox" ${wizard.useMaterial ? "checked" : ""}> Собрать по загруженным материалам</label>` : ""}
      <button class="text-btn" type="button" data-act="compose-own">Лучше напишите вопросы сами</button>`;
  } else if (wizard.step === 3) {
    body = `<p class="field-label">Кому отправить</p>
      ${audienceTiles(wizard, students)}
      ${wizard.audience === "selected" ? `<label class="field-label" for="student-q">Поиск по имени</label>
        <input id="student-q" class="field" placeholder="Начните вводить имя" value="${esc(wizard.studentQuery || "")}" autocomplete="off">
        <div id="student-list">${studentRowsHTML()}</div>
        <div class="student-list__foot">
          <button class="text-btn" type="button" data-act="select-all-students">Выбрать всех</button>
          ${(wizard.studentIds || []).length ? `<button class="text-btn" type="button" data-act="clear-students">Снять выбор</button>` : ""}
        </div>` : ""}
      ${wizard.audience === "needed" ? neededPanel(wizard) : ""}
      ${audienceCount(wizard, students)}`;
  } else {
    const draft = wizard.draft;
    const issues = (draft?.items || []).filter((item) => item.checked === false).length;
    const note = cleanDraftNote(draft?.note || "");
    const resolved = resolvedAudience(wizard);
    const audienceText =
      resolved.audience === "class"
        ? `Весь класс: ${students.length} ${plural(students.length, "ученик", "ученика", "учеников")}`
        : `Выбранные: ${resolved.students.join(", ") || "никто"}`;
    body = `${wizard.draftError ? `<div class="banner banner-bad"><p>${esc(wizard.draftError.message)}</p><button class="text-btn" type="button" data-act="compose-own">Написать вопросы самому</button></div>` : ""}
      ${store.busy ? `<p class="statusline" role="status">Собираю черновик…</p>` : ""}
      ${draft ? `<p class="hint">${draft.source === "own" ? "Это ваши вопросы." : "Проверьте вопросы перед отправкой."} Ученики увидят их только после «Опубликовать». Верный ответ виден только вам.</p>
        ${note ? `<div class="banner banner-warn"><p>${esc(note)}</p></div>` : ""}
        ${issues ? `<p class="issues-flag" role="status">⚠ ${issues} ${plural(issues, "проблема", "проблемы", "проблем")}</p>` : ""}
        <p><strong>${esc(draft.topic)}</strong></p>
        <p>${esc(draft.goal)}</p>
        <p class="hint">${esc(audienceText)}</p>
        <label class="field-label" for="due-at">Срок сдачи <span class="hint-inline">необязательно</span></label>
        <input id="due-at" class="field" type="datetime-local" value="${esc(wizard.dueAt || "")}">
        ${resourcesBlock(wizard)}
        <div class="stack tight">${(draft.items || []).map((item, index) => {
          const bad = item.checked === false;
          return `<article class="card card-flat draft-item ${bad ? "draft-item--issue" : ""}">
            <div class="draft-item__head"><h2>Задание ${item.number}</h2>${bad ? `<span class="issue-mark" title="Ответ не сошёлся при проверке" aria-label="Ответ не сошёлся">⚠</span>` : ""}</div>
            ${bad ? `<p class="issue-text">Ответ не сошёлся при проверке — перепроверьте его.</p>` : ""}
            <label class="field-label" for="prompt-${index}">Формулировка</label>
            <textarea id="prompt-${index}" class="area" data-prompt="${index}">${esc(item.prompt)}</textarea>
            <label class="field-label" for="reference-${index}">Верный ответ</label>
            <input id="reference-${index}" class="field" data-reference="${index}" value="${esc(item.reference || "")}" autocomplete="off">
            <div class="draft-item__actions">
              ${draft.source === "own" ? "" : `<button class="text-btn" type="button" data-act="regen-item" data-index="${index}" ${store.busy || wizard.autosave === "saving" ? "disabled" : ""}>Перегенерировать</button>`}
              <button class="text-btn draft-item__del" type="button" data-act="del-item" data-index="${index}" ${store.busy ? "disabled" : ""}>Удалить</button>
            </div>
          </article>`;
        }).join("")}</div>
        ${autosaveLine(wizard)}` : ""}
      ${wizard.sendError ? `<div class="banner banner-warn" role="status"><strong>Отправка не выполнена</strong><p>${esc(wizard.sendError)}</p></div>` : ""}
      ${wizard.mode === "own" ? "" : `<button class="text-btn" type="button" data-act="redraft" ${store.busy ? "disabled" : ""}>Собрать заново</button>`}`;
  }
  const actions = wizard.step < 4
    ? `${wizard.step > 1 ? `<button class="btn btn-ghost" type="button" data-act="wizard-back">Назад</button>` : `<button class="btn btn-ghost" type="button" data-act="wizard-exit">Закрыть</button>`}
        <button class="btn btn-primary" type="button" data-act="wizard-next">Дальше</button>`
    : `<button class="btn btn-ghost" type="button" data-act="save-draft" ${!wizard.draft || store.busy ? "disabled" : ""}>Черновик</button>
        <button class="btn btn-primary" type="button" data-act="send-assignment" ${!wizard.draft || store.busy ? "disabled" : ""}>Опубликовать</button>`;
  return `<div class="stack flow">
    <header class="flow-head">
      <div class="flow-head__top">
        <button class="flow-back" type="button" data-act="wizard-back" aria-label="Назад на шаг" title="Назад">${icon("chevron")}</button>
        <div class="who"><b>${titles[wizard.step - 1]}</b><span>Шаг ${wizard.step} из 4</span></div>
      </div>
      <ol class="steps" aria-label="Этапы">${titles.map((title, index) => {
        const n = index + 1;
        const cls = n < wizard.step ? "is-done" : n === wizard.step ? "is-now" : "";
        return `<li class="${cls}"><button type="button" class="steps__btn" data-act="wizard-step" data-step="${n}" ${n === wizard.step ? "disabled" : ""} aria-label="Шаг ${n}: ${esc(title)}"></button></li>`;
      }).join("")}</ol>
    </header>
    ${wizard.fieldError ? `<p class="field-error">${esc(wizard.fieldError)}</p>` : ""}
    ${body}
    <div class="flow-bar">${actions}</div>
  </div>`;
}

export function renderCompose() {
  if (!store.report) return errorBlock(store.reportError?.message, "retry");
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
        <button class="setting-row" type="button" ${claimsAct}><span>Кто проверяет работы</span><strong>${esc(reviewer || "Ответственный не назначен")}</strong>${icon("arrow")}</button>
      </div>
      <div class="settings-card" style="margin-top:14px">
        <div class="settings-card__heading">
          <span class="eyebrow">Конструктор</span>
          <h2>Предметы и темы</h2>
        </div>
        ${store.screen === "profile" ? programBlock() : ""}
      </div>
      <div class="settings-card" style="margin-top:14px">
        <div class="settings-card__heading">
          <span class="eyebrow">Оформление</span>
          <h2>Тема</h2>
        </div>
        <div class="setting-row"><span>Режим</span>${themeSwitch(themePref())}</div>
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

export function startCompose(topic = "", mode = "own") {
  if (store.screen !== "compose") store.wizardReturn = store.screen || "tasks";
  store.wizard = {
    step: 1,
    mode: mode === "stimul" ? "stimul" : "own",
    subjectId: store.subjectId || null,
    topic: topic || "",
    goal: "",
    blurb: "",
    count: 3,
    difficulty: "normal",
    audience: "class",
    students: [],
    studentIds: [],
    studentQuery: "",
    own: [],
    useMaterial: false,
    dueAt: "",
    resources: [],
    autosave: "idle",
    draft: null,
    draftError: null,
    sendError: null,
    fieldError: "",
    triedKey: "",
    draftKey: "",
  };
  if (!store.program && !store.preview) loadProgram();
  if (store.screen !== "compose") go("compose");
  else refresh();
}

export function wizardExit() {
  const back = store.wizardReturn && store.wizardReturn !== "compose" ? store.wizardReturn : "tasks";
  store.wizard = null;
  store.wizardReturn = "";
  go(back);
}

function readWizardFields() {
  const wizard = store.wizard;
  if (!wizard) return;
  const topic = document.querySelector("#topic");
  const goal = document.querySelector("#goal");
  const blurb = document.querySelector("#blurb");
  if (topic) wizard.topic = topic.value;
  if (goal) wizard.goal = goal.value;
  if (blurb) wizard.blurb = blurb.value;
  const due = document.querySelector("#due-at");
  if (due) wizard.dueAt = due.value;
  const own = [...(wizard.own || [])];
  document.querySelectorAll("[data-own-prompt]").forEach((node) => {
    const index = Number(node.dataset.ownPrompt);
    own[index] = { ...(own[index] || {}), prompt: node.value };
  });
  document.querySelectorAll("[data-own-answer]").forEach((node) => {
    const index = Number(node.dataset.ownAnswer);
    own[index] = { ...(own[index] || {}), reference: node.value };
  });
  if (document.querySelector("[data-own-prompt]")) wizard.own = own;
  document.querySelectorAll("[data-prompt]").forEach((node) => {
    const index = Number(node.dataset.prompt);
    if (wizard.draft?.items?.[index]) wizard.draft.items[index].prompt = node.value;
  });
  document.querySelectorAll("[data-reference]").forEach((node) => {
    const index = Number(node.dataset.reference);
    if (wizard.draft?.items?.[index]) wizard.draft.items[index].reference = node.value;
  });
}

function validateStep() {
  const wizard = store.wizard;
  wizard.fieldError = "";
  if (wizard.step === 1) {
    if (wizard.topic.trim().length < 2) {
      wizard.fieldError = "Напишите тему.";
      return false;
    }
  }
  if (wizard.step === 2 && wizard.mode === "own") {
    const missing = (wizard.own || []).slice(0, wizard.count).some((item) => !String(item?.prompt || "").trim() || !String(item?.reference || "").trim());
    const short = (wizard.own || []).length < wizard.count;
    if (missing || short) {
      wizard.fieldError = "У каждого задания нужны текст и верный ответ.";
      return false;
    }
  }
  if (wizard.step === 3) {
    if (!(store.report?.students || []).length) {
      wizard.fieldError = "В классе нет учеников, отправлять некому.";
      return false;
    }
    if (wizard.audience === "selected" && !(wizard.studentIds || []).length) {
      wizard.fieldError = "Отметьте хотя бы одного ученика.";
      return false;
    }
    if (wizard.audience === "needed" && !neededStudentIds(wizard).length) {
      wizard.fieldError = "По этой теме пока никому не нужна практика. Выберите учеников вручную или отправьте всему классу.";
      return false;
    }
  }
  return true;
}

export function wizardNext() {
  const wizard = store.wizard;
  if (!wizard) return;
  readWizardFields();
  if (!validateStep()) {
    refresh();
    return;
  }
  wizard.step += 1;
  if (wizard.step === 4 && wizard.mode === "own") sealOwnDraft();
  refresh();
  if (wizard.step === 4) maybeLoadDraft();
}

export function wizardGoto(step) {
  const wizard = store.wizard;
  const target = Math.max(1, Math.min(4, Number(step) || 1));
  if (!wizard || target === wizard.step) return;
  readWizardFields();
  if (target < wizard.step) {
    wizard.fieldError = "";
    wizard.step = target;
    refresh();
    if (target === 4) maybeLoadDraft();
    return;
  }
  while (wizard.step < target) {
    if (!validateStep()) {
      refresh();
      return;
    }
    wizard.step += 1;
    if (wizard.step === 4 && wizard.mode === "own") sealOwnDraft();
  }
  refresh();
  if (target === 4) maybeLoadDraft();
}

export function wizardBack() {
  const wizard = store.wizard;
  if (!wizard) return;
  readWizardFields();
  wizard.fieldError = "";
  wizard.sendError = null;
  if (wizard.step <= 1) {
    wizardExit();
    return;
  }
  wizard.step -= 1;
  refresh();
}

export function setCount(value) {
  if (!store.wizard) return;
  readWizardFields();
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
  store.wizard.audience = ["class", "selected", "needed"].includes(value) ? value : "class";
  refresh();
}

export function selectAllStudents() {
  const wizard = store.wizard;
  if (!wizard) return;
  const query = String(wizard.studentQuery || "").trim().toLowerCase();
  const ids = (store.report?.students || [])
    .filter((student) => !query || String(student.display_name || "").toLowerCase().includes(query))
    .map((student) => student.user_id)
    .filter(Boolean);
  wizard.studentIds = [...new Set([...(wizard.studentIds || []), ...ids])];
  const roster = store.report?.students || [];
  wizard.students = wizard.studentIds
    .map((item) => roster.find((student) => student.user_id === item)?.display_name || "")
    .filter(Boolean);
  refresh();
}

export function clearStudents() {
  const wizard = store.wizard;
  if (!wizard) return;
  wizard.studentIds = [];
  wizard.students = [];
  refresh();
}

export function regenItem(index) {
  const wizard = store.wizard;
  const item = wizard?.draft?.items?.[Number(index)];
  if (!item || wizard.mode === "own" || store.busy || wizard.autosave === "saving") return;
  readWizardFields();
  const resolved = resolvedAudience(wizard);
  store.busy = true;
  wizard.sendError = null;
  refresh();
  postDraft({
    topic: wizard.topic.trim(),
    goal: (wizard.goal || "").trim() || wizard.topic.trim(),
    count: 1,
    difficulty: wizard.difficulty,
    audience: resolved.audience,
    students: resolved.students,
    use_material: Boolean(wizard.useMaterial),
    class_id: store.classId || null,
  })
    .then((draft) => {
      const fresh = draft?.items?.[0];
      if (fresh) {
        item.prompt = fresh.prompt;
        item.reference = fresh.reference;
        item.choices = fresh.choices || [];
        item.checked = fresh.checked !== false;
        item.hint = fresh.hint || item.hint;
        wizard.autosave = "idle";
        scheduleAutosave();
      } else {
        wizard.sendError = "Новое задание не собралось. Попробуйте ещё раз.";
      }
    })
    .catch((error) => {
      wizard.sendError = error.message || "Не получилось перегенерировать задание.";
    })
    .finally(() => {
      store.busy = false;
      refresh();
    });
}

export function delItem(index) {
  const wizard = store.wizard;
  const items = wizard?.draft?.items;
  const at = Number(index);
  if (!items || !Number.isInteger(at) || at < 0 || at >= items.length || items.length <= 1) return;
  readWizardFields();
  items.splice(at, 1);
  items.forEach((item, position) => {
    item.number = position + 1;
  });
  wizard.autosave = "idle";
  scheduleAutosave();
  refresh();
}

let autosaveTimer = 0;

export function scheduleAutosave() {
  const wizard = store.wizard;
  if (!wizard || wizard.step !== 4 || !wizard.draft || store.preview) return;
  window.clearTimeout(autosaveTimer);
  autosaveTimer = window.setTimeout(() => autosaveDraft(), 1200);
}

export async function autosaveDraft() {
  const wizard = store.wizard;
  if (!wizard?.draft || wizard.step !== 4 || store.busy || store.preview) return;
  if (wizard.autosave === "saving") return;
  readWizardFields();
  const items = (wizard.draft.items || []).map((item) => ({
    prompt: String(item.prompt || "").trim(),
    reference: String(item.reference || "").trim(),
  }));
  if (!items.length || items.some((item) => !item.prompt || !item.reference)) return;
  wizard.autosave = "saving";
  refresh();
  try {
    const saved = await saveWork(workBody());
    if (saved?.persisted && saved.id) {
      wizard.workId = saved.id;
      wizard.draft.persisted = true;
      wizard.autosave = "saved";
      await uploadStagedResources(saved.id);
    } else {
      wizard.autosave = "error";
    }
  } catch {
    wizard.autosave = "error";
  }
  refresh();
}

export function toggleStudent(id, name) {
  const wizard = store.wizard;
  const key = Number(id);
  if (!wizard || !key) return;
  const ids = wizard.studentIds || [];
  wizard.studentIds = ids.includes(key) ? ids.filter((item) => item !== key) : [...ids, key];
  const roster = store.report?.students || [];
  wizard.students = wizard.studentIds
    .map((item) => roster.find((student) => student.user_id === item)?.display_name || (item === key ? name : ""))
    .filter(Boolean);
  refresh();
}

export function toggleMaterial(checked) {
  if (!store.wizard) return;
  store.wizard.useMaterial = Boolean(checked);
  refresh();
}

function draftPayload() {
  const wizard = store.wizard;
  const resolved = resolvedAudience(wizard);
  const goal = wizard.goal.trim() || wizard.topic.trim();
  return {
    topic: wizard.topic.trim(),
    goal,
    count: wizard.count,
    difficulty: wizard.difficulty,
    audience: resolved.audience,
    students: resolved.students,
    student_ids: resolved.student_ids,
    use_material: Boolean(wizard.useMaterial),
    subject_id: wizard.subjectId || store.subjectId || null,
    class_id: store.classId || null,
  };
}

function draftPayloadKey() {
  const wizard = store.wizard;
  if (!wizard) return "";
  return JSON.stringify(draftPayload());
}

function maybeLoadDraft() {
  const wizard = store.wizard;
  if (!wizard || wizard.step !== 4 || wizard.mode === "own" || store.busy || store.preview) return;
  const key = draftPayloadKey();
  if (wizard.draft && wizard.draftKey === key) return;
  if (wizard.triedKey === key) return;
  loadDraft();
}

async function uploadStagedResources(workId) {
  const wizard = store.wizard;
  const staged = wizard?.resources || [];
  if (!staged.length || !workId) return true;
  for (const item of staged) {
    if (item.sent || item.failed) continue;
    try {
      if (item.url) {
        const saved = await attachWorkResource(workId, { title: item.title, url: item.url });
        item.persistedId = { work: workId, id: saved?.id };
      } else if (item.file) {
        const saved = await attachWorkResource(workId, { title: item.title, file: item.file });
        item.persistedId = { work: workId, id: saved?.id };
      } else {
        continue;
      }
      item.sent = true;
    } catch (error) {
      item.failed = true;
      wizard.sendError = `Материал «${item.title}» не загрузился: ${error.message || "ошибка сети"}. Нажмите «Опубликовать» ещё раз.`;
      return false;
    }
  }
  return true;
}

function sealOwnDraft() {
  const wizard = store.wizard;
  if (!wizard) return;
  const items = (wizard.own || []).slice(0, wizard.count).map((item, index) => ({
    number: index + 1,
    prompt: String(item?.prompt || "").trim(),
    reference: String(item?.reference || "").trim(),
    choices: [],
  }));
  const names = resolvedAudience(wizard).students.length
    ? resolvedAudience(wizard).students
    : (store.report?.students || []).map((student) => student.display_name);
  const resolved = resolvedAudience(wizard);
  wizard.draft = {
    topic: wizard.topic.trim(),
    goal: wizard.goal.trim() || wizard.topic.trim(),
    audience: resolved.audience,
    students: names,
    source: "own",
    items,
    persisted: false,
    note: "",
  };
}

export async function loadDraft() {
  const wizard = store.wizard;
  if (!wizard || store.busy) return;
  readWizardFields();
  wizard.triedKey = draftPayloadKey();
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
    wizard.draftKey = wizard.triedKey;
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
  const items = (store.wizard.draft?.items || []).map((item) => ({
    prompt: String(item.prompt || "").trim(),
    reference: String(item.reference || "").trim(),
  }));
  const due = (store.wizard.dueAt || "").trim();
  return {
    ...payload,
    prompts: items.map((item) => item.prompt),
    items,
    blurb: (store.wizard.blurb || "").trim(),
    due_at: due ? new Date(due).toISOString() : null,
    work_id: store.wizard.workId || null,
    class_id: store.classId || null,
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
    wizard.autosave = "saved";
    wizard.sendError = null;
    if (!(await uploadStagedResources(saved.id))) return;
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
    const empty = !wizard.draft.items.length || wizard.draft.items.some((item) => !String(item.prompt || "").trim() || !String(item.reference || "").trim());
  if (empty) {
    wizard.sendError = "У каждого задания нужны текст и верный ответ.";
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
    wizard.workId = saved.id;
    if (!(await uploadStagedResources(saved.id))) return;
    const published = await publishWork(saved.id);
    if (!published?.persisted) {
      wizard.sendError = "Черновик записан, публикация не подтверждена. Ученикам ничего не ушло.";
      wizard.workId = saved.id;
      return;
    }
    wizard.workId = saved.id;
    await confirmDialog({
      title: "Работа опубликована",
      text: `Работа ушла ученикам: ${published.recipients}. Когда кто-то сдаст, имя появится в списке.`,
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
    text: `Сейчас открыт ${title}. Другой класс выбирается в списке, если он назначен.`,
    confirm: "Понятно",
  });
}

export async function reloadQuiet() {
  try {
    const report = await getClass(store.classId || undefined);
    store.report = report;
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
  refresh();
}

export function focusStudent(name) {
  store.focusStudent = store.focusStudent === name ? "" : name;
  refresh();
}

export function writeOwn() {
  if (!store.wizard) return;
  readWizardFields();
  store.wizard.mode = "own";
  store.wizard.step = 2;
  store.wizard.draft = null;
  store.wizard.draftError = null;
  refresh();
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

/* ===== Конструктор: предметы, темы, материалы работы ===== */

export async function loadProgram() {
  if (store.programLoading) return;
  store.programLoading = true;
  if (store.preview) {
    store.program = teacherPreviewProgram();
    store.programLoading = false;
    refresh();
    return;
  }
  store.programError = "";
  try {
    store.program = await getProgram(store.classId || undefined);
    if (!store.subjectId && store.program?.subjects?.length) {
      store.subjectId = store.program.subjects[0].id;
    }
    if (store.wizard && !store.wizard.subjectId && store.subjectId) {
      store.wizard.subjectId = store.subjectId;
    }
  } catch (error) {
    store.program = null;
    store.programError = error.message;
  } finally {
    store.programLoading = false;
  }
  refresh();
}

function teacherPreviewProgram() {
  return {
    subjects: [
      { id: 1, title: "Математика" },
      { id: 2, title: "История" },
    ],
    topics: [
      { id: 11, subject_id: 1, title: "Дроби", blurb: "", position: 1 },
      { id: 12, subject_id: 1, title: "Линейные уравнения", blurb: "", position: 2 },
      { id: 21, subject_id: 2, title: "Древний Рим", blurb: "Республика и империя.", position: 1 },
    ],
  };
}

function programTopics() {
  const topics = store.program?.topics || [];
  const subjects = store.program?.subjects || [];
  const active = store.subjectId || subjects[0]?.id;
  if (!active) return topics;
  return topics.filter((topic) => topic.subject_id === active);
}

function programBlock() {
  if (store.programError) {
    return `<p class="field-error">${esc(store.programError)}</p>
      <button class="text-btn" type="button" data-act="program-retry">Повторить</button>`;
  }
  if (!store.program) return `<p class="hint">Загружаю предметы…</p>`;
  const subjects = store.program.subjects || [];
  if (!subjects.length) {
    return `<p class="hint">В этом классе нет назначения на предмет. Сначала примите заявку или назначьте предмет.</p>`;
  }
  const active = store.subjectId || subjects[0].id;
  const topics = programTopics();
  const form = store.programForm === "subject"
    ? `<div class="program-form">
        <input id="new-subject-title" class="field" placeholder="Название предмета, например: Физика" value="${esc(store.newSubjectTitle)}" maxlength="200">
        <div class="program-form__actions">
          <button class="btn btn-primary" type="button" data-act="program-save-subject" ${!store.newSubjectTitle.trim() ? "disabled" : ""}>Добавить</button>
          <button class="btn btn-ghost" type="button" data-act="program-cancel">Отмена</button>
        </div></div>`
    : "";
  const topicForm = store.programForm === "topic"
    ? `<div class="program-form">
        <input id="new-topic-title" class="field" placeholder="Название темы" value="${esc(store.newTopicTitle)}" maxlength="200">
        <textarea id="new-topic-blurb" class="area" placeholder="Короткое пояснение для ученика (необязательно)">${esc(store.newTopicBlurb)}</textarea>
        <div class="program-form__actions">
          <button class="btn btn-primary" type="button" data-act="program-save-topic" ${!store.newTopicTitle.trim() || !active ? "disabled" : ""}>Добавить тему</button>
          <button class="btn btn-ghost" type="button" data-act="program-cancel">Отмена</button>
        </div></div>`
    : "";
  return `<div class="program">
    <div class="chips program__subjects">${subjects.map((item) => `<button class="chip ${item.id === active ? "is-on" : ""}" type="button" data-act="program-subject" data-id="${item.id}">${esc(item.title)}</button>`).join("")}
      <button class="chip" type="button" data-act="program-new-subject">+ Предмет</button></div>
    ${form}
    <div class="program__topics">
      ${topics.length ? topics.map((topic) => `<div class="program-topic"><strong>${esc(topic.title)}</strong>${topic.blurb ? `<small>${esc(topic.blurb)}</small>` : ""}</div>`).join("") : `<p class="hint">Тем пока нет — добавьте первую или напишите её в мастере работы.</p>`}
      ${topicForm}
      ${store.programForm !== "topic" ? `<button class="text-btn" type="button" data-act="program-new-topic" ${!active ? "disabled" : ""}>+ Тема</button>` : ""}
    </div>
  </div>`;
}

export async function programSubject(id) {
  store.subjectId = Number(id) || null;
  store.programForm = "";
  refresh();
}

export function programNewSubject() {
  store.programForm = "subject";
  store.newSubjectTitle = "";
  refresh();
}

export function programNewTopic() {
  store.programForm = "topic";
  store.newTopicTitle = "";
  store.newTopicBlurb = "";
  refresh();
}

export function programCancel() {
  store.programForm = "";
  refresh();
}

export async function programSaveSubject() {
  const title = (store.newSubjectTitle || "").trim();
  if (title.length < 2 || store.busy) return;
  store.busy = true;
  try {
    const saved = await createSubject({ title, class_id: store.classId || null });
    if (store.program) {
      if (!store.program.subjects.some((item) => item.id === saved.id)) {
        store.program.subjects.push({ id: saved.id, title: saved.title });
      }
      store.subjectId = saved.id;
    }
    store.newSubjectTitle = "";
    store.programForm = "";
    toast(`Предмет «${saved.title}» добавлен.`);
  } catch (error) {
    store.programError = error.message;
  } finally {
    store.busy = false;
    refresh();
  }
}

export async function programSaveTopic() {
  const title = (store.newTopicTitle || "").trim();
  const subjectId = store.subjectId || store.program?.subjects?.[0]?.id;
  if (title.length < 2 || !subjectId || store.busy) return;
  store.busy = true;
  try {
    const saved = await createTopic({
      subject_id: subjectId,
      title,
      blurb: store.newTopicBlurb || "",
      class_id: store.classId || null,
    });
    if (store.program) {
      const exists = store.program.topics.some(
        (item) => item.id === saved.id || (item.subject_id === saved.subject_id && item.title === saved.title),
      );
      if (!exists) store.program.topics.push(saved);
    }
    store.newTopicTitle = "";
    store.newTopicBlurb = "";
    store.programForm = "";
    toast(`Тема «${saved.title}» добавлена.`);
  } catch (error) {
    store.programError = error.message;
  } finally {
    store.busy = false;
    refresh();
  }
}

export function setWizardSubject(value) {
  const wizard = store.wizard;
  if (!wizard) return;
  const id = Number(value) || null;
  if (wizard.subjectId !== id) {
    wizard.subjectId = id;
    store.subjectId = id;
    refresh();
  }
}

function resourceKindHint(item) {
  if (item.url && !item.file) return "ссылка";
  const name = String(item.file?.name || item.title || "").toLowerCase();
  if (name.endsWith(".pdf")) return "PDF";
  if (/\.(png|jpe?g|webp|gif)$/.test(name)) return "изображение";
  if (/\.(docx?|pptx?|txt|md)$/.test(name)) return "документ";
  return "файл";
}

function resourcesBlock(wizard) {
  const staged = wizard.resources || [];
  const rows = staged.map((item, index) => `<div class="resource-row">
      <span class="resource-row__icon">${icon(item.url && !item.file ? "link" : "download")}</span>
      <span class="resource-row__text"><strong>${esc(item.title || item.file?.name || "Материал")}</strong><small>${esc(resourceKindHint(item))}${item.sent ? " · приложен" : item.failed ? " · не загрузился" : ""}</small></span>
      <button class="text-btn" type="button" data-act="resource-remove" data-index="${index}" ${store.busy ? "disabled" : ""}>Убрать</button>
    </div>`).join("");
  const linkForm = store.resourceLinkOpen
    ? `<div class="program-form">
        <input id="resource-link-url" class="field" placeholder="https://…" value="${esc(store.resourceLinkUrl)}" inputmode="url" autocomplete="off">
        <input id="resource-link-title" class="field" placeholder="Название, например: Конспект по теме" value="${esc(store.resourceLinkTitle)}" maxlength="200">
        <div class="program-form__actions">
          <button class="btn btn-primary" type="button" data-act="resource-link-add" ${!(store.resourceLinkUrl || "").trim() ? "disabled" : ""}>Добавить ссылку</button>
          <button class="btn btn-ghost" type="button" data-act="resource-link-cancel">Отмена</button>
        </div></div>`
    : "";
  return `<div class="resources">
    <p class="field-label">Материалы для ученика <span class="hint-inline">необязательно</span></p>
    ${rows}
    <div class="resources__add">
      <label class="btn btn-ghost file resources__file">${icon("download")} Файл<input id="resource-file" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.docx,.pptx"></label>
      <button class="btn btn-ghost" type="button" data-act="resource-link-toggle">${icon("link")} Ссылка</button>
    </div>
    ${linkForm}
    <p class="hint">PDF, изображение или ссылка. После публикации ученик увидит кнопки в работе.</p>
  </div>`;
}

export function resourceFilePicked(file) {
  const wizard = store.wizard;
  if (!wizard || !file || store.busy) return;
  wizard.resources = wizard.resources || [];
  wizard.resources.push({
    file,
    title: String(file.name || "").replace(/\.[^.]+$/, "").slice(0, 200) || "Материал",
    sent: false,
    failed: false,
  });
  wizard.sendError = null;
  refresh();
}

export function resourceLinkToggle() {
  store.resourceLinkOpen = !store.resourceLinkOpen;
  if (!store.resourceLinkOpen) {
    store.resourceLinkUrl = "";
    store.resourceLinkTitle = "";
  }
  refresh();
}

export function resourceLinkCancel() {
  store.resourceLinkOpen = false;
  store.resourceLinkUrl = "";
  store.resourceLinkTitle = "";
  refresh();
}

export function resourceLinkAdd() {
  const wizard = store.wizard;
  const url = (store.resourceLinkUrl || "").trim();
  if (!wizard || !url || store.busy) return;
  wizard.resources = wizard.resources || [];
  wizard.resources.push({
    url,
    title: (store.resourceLinkTitle || "").trim() || url.replace(/^https?:\/\//, "").slice(0, 200),
    sent: false,
    failed: false,
  });
  store.resourceLinkOpen = false;
  store.resourceLinkUrl = "";
  store.resourceLinkTitle = "";
  wizard.sendError = null;
  refresh();
}

export function resourceRemove(index) {
  const wizard = store.wizard;
  const at = Number(index);
  if (!wizard?.resources || !Number.isInteger(at) || at < 0 || at >= wizard.resources.length) return;
  const item = wizard.resources[at];
  if (item.persistedId?.id && !store.preview) {
    deleteWorkResource(item.persistedId.work, item.persistedId.id)
      .catch(() => toast("Не удалось убрать материал на сервере."));
  }
  wizard.resources.splice(at, 1);
  refresh();
}
