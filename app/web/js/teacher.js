import { askAssistant, deleteMaterial, getAssignments, getClass, getMaterials, getNotices, getWorkResult, postDraft, publishWork, saveWork, uploadMaterial } from "./api.js?v=3";
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
            <small>${checks ? "уже проводились" : "пока не проводились"}</small>
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
  return `<div class="fig">
    ${topbar()}
    <div class="fig-page">
    <div class="page-heading">
      <h1 id="page-title">Карта класса</h1>
      <p>${report.frequent_mistakes ? esc(report.frequent_mistakes) : "Нажмите на кружок. Зелёный: усвоено. Жёлтый: нужна практика. Красный: повторить."}</p>
    </div>
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
        ${store.filters.topic === row.title ? `<div class="reveal-body"><p>${weakNames.length ? `Нужна работа: ${esc(weakNames.join(", "))}.` : "По этой теме нет учеников со статусом «повторить» или «нужна практика»."}</p><div class="flow-bar"><button class="btn btn-ghost" type="button" data-act="compose" data-mode="own" data-topic="${esc(row.title)}">Написать самому</button><button class="btn btn-primary" type="button" data-act="compose" data-mode="stimul" data-topic="${esc(row.title)}">Попросить Стимула</button></div></div>` : ""}
      </article>`).join("") || `<p class="quiet">Таких тем пока нет.</p>`}
    </div>
    ${(report.priorities || []).length ? `<div><h2>Кому помочь</h2><ul class="plain">${report.priorities.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></div>` : ""}
    </div>
  </div>`;
}

function studentTone(student) {
  const topics = student.topics || [];
  if (topics.some((topic) => topic.status === "repeat")) return "coral";
  if (topics.some((topic) => topic.status === "needs_practice")) return "yellow";
  if (topics.some((topic) => topic.status === "mastered")) return "green";
  return "idle";
}

function matchesFilter(student) {
  if (store.filters.status === "all") return true;
  return (student.topics || []).some((topic) => {
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
  const topics = (person.topics || []).filter((topic) => store.filters.topic === "all" || topic.title === store.filters.topic);
  return `<article class="student-sheet">
    <h2>${esc(person.display_name)}</h2>
    <p>${esc(person.activity || "Пока нет занятий.")}</p>
    <div class="stack tight">${topics.map((topic) => `<div class="line"><span><b>${esc(topic.title)}</b><small>${topic.correct_percent != null ? `${topic.correct_percent}% верных` : "попыток ещё нет"}</small></span>${pill(topic.status)}</div>`).join("")}</div>
  </article>`;
}

function workLine(item) {
  const published = item.status === "published";
  const handed = item.handed || [];
  const started = item.started || [];
  const finished = published && item.recipients && item.done >= item.recipients;
  let label = "черновик";
  if (published && finished) label = handed.length ? `сдали ${handed.join(", ")}` : "все сдали";
  else if (published && handed.length) label = `сдали ${handed.join(", ")} · ещё ${(item.recipients || 0) - (item.done || 0)}`;
  else if (published && started.length) label = `начали ${started.join(", ")}`;
  else if (published) label = `сдали 0 из ${item.recipients || 0}`;
  return `<button class="line" type="button" data-act="open-result" data-id="${item.id}"><span><b>${esc(item.title)}</b><small>${esc(item.subject || "")} · ${esc(label)}</small></span></button>`;
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
          <button class="text-button" type="button" data-act="compose" data-mode="stimul">Попросить Стимула</button>
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

export function renderStimul() {
  const samples = ["Собери короткую проверку по дробям", "Какие темы класса сейчас слабее?", "Тест по загруженному материалу, 3 задания"];
  const answer = store.stimulAnswer;
  const items = store.materials?.items || [];
  return `<div class="fig">
    ${topbar()}
    <div class="fig-page assistant-page">
      <div class="assistant-intro">
        <div class="assistant-intro__icon">${icon("spark")}</div>
        <div>
          <h1 id="page-title">Чем помочь?</h1>
          <p>Соберу проверку по теме или по материалу урока и покажу слабые места класса.</p>
        </div>
      </div>
      <div class="prompt-grid">
        ${samples.map((text, index) => `<button type="button" data-act="stimul-sample" data-text="${esc(text)}"><span>${String(index + 1).padStart(2, "0")}</span><strong>${esc(text)}</strong>${icon("arrow")}</button>`).join("")}
      </div>
      ${store.stimulBusy ? `<p class="statusline" role="status">Собираю ответ…</p>` : ""}
      ${answer ? `<article class="card card-flat assistant-answer"><h2>${esc(answer.title)}</h2><p>${esc(answer.text)}</p></article>` : ""}
      ${store.stimulNote ? `<div class="assistant-notice" role="status">${icon("check")}<span>${esc(store.stimulNote)}</span></div>` : ""}
      <form id="stimul-form" class="composer composer--text">
        <input id="stimul-input" value="${esc(store.stimulDraft)}" placeholder="Например: проверка по дробям для Ани" aria-label="Запрос помощнику" ${store.stimulBusy ? "disabled" : ""}>
        <button class="composer__send" type="submit" aria-label="Отправить" ${store.stimulBusy ? "disabled" : ""}>${icon("arrow")}</button>
      </form>
      <section class="materials">
        <div class="materials__head">
          <div><strong>Материалы урока</strong><small>Учебник, параграф или фото страницы. По ним собираются задания.</small></div>
          <label class="btn btn-ghost file">Загрузить<input id="material-file" type="file" accept=".pdf,.docx,.pptx,.txt,image/*" aria-label="Загрузить материал"></label>
        </div>
        ${store.materialsError ? `<p class="field-error">${esc(store.materialsError)}</p>` : ""}
        ${store.materials === null ? `<p class="quiet">Загружаю список…</p>` : items.length ? `<div class="stack tight">${items.map((item) => `<div class="line"><span><b>${esc(item.title)}</b><small>${item.fragments} фрагм. · ${kindLabel(item.kind)}</small></span><button class="text-btn" type="button" data-act="material-delete" data-id="${item.id}">Убрать</button></div>`).join("")}</div>` : `<p class="quiet">Пока пусто. Добавьте PDF, DOCX, PPTX, TXT или фото страницы — задания «по материалу» собираются только по загруженному.</p>`}
      </section>
    </div>
  </div>`;
}

function kindLabel(kind) {
  return { pdf: "PDF", docx: "DOCX", pptx: "PPTX", photo: "фото", text: "текст" }[kind] || kind;
}

export async function sendStimul(text) {
  const question = (text ?? store.stimulDraft ?? "").trim();
  if (store.stimulBusy) return;
  if (question.length < 2) {
    store.stimulNote = "Напишите, что нужно: тему, сколько заданий и кому.";
    refresh();
    return;
  }
  if (store.preview) {
    store.stimulNote = "В демонстрации помощник к серверу не ходит.";
    refresh();
    return;
  }
  store.stimulBusy = true;
  store.stimulNote = "";
  refresh();
  try {
    const reply = await askAssistant(question, store.classId);
    if (!reply || !reply.kind) {
      store.stimulNote = "Ответ пустой. Попробуйте сформулировать иначе.";
      return;
    }
    if (reply.kind === "draft" && reply.draft) {
      openAssistantWizard(reply);
      return;
    }
    store.stimulAnswer = {
      title: reply.kind === "summary" ? "Как у класса" : "Подсказка",
      text: reply.text || "",
    };
    store.stimulDraft = "";
  } catch (error) {
    store.stimulNote = error.message;
  } finally {
    store.stimulBusy = false;
    refresh();
  }
}

function openAssistantWizard(reply) {
  const plan = reply.wizard || {};
  const students = reply.draft.audience === "selected"
    ? (plan.students || [])
    : [];
  store.wizard = {
    step: 4,
    mode: "stimul",
    topic: plan.topic || reply.draft.topic || "",
    goal: plan.goal || reply.draft.goal || "",
    blurb: "",
    count: plan.count || reply.draft.count || 3,
    difficulty: plan.difficulty || "normal",
    audience: reply.draft.audience === "selected" ? "selected" : "class",
    students,
    studentIds: plan.student_ids || [],
    own: [],
    useMaterial: Boolean(plan.use_material),
    draft: reply.draft,
    draftError: null,
    sendError: null,
    fieldError: "",
  };
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

function wizardBody() {
  const wizard = store.wizard;
  const topics = (store.report?.topics || []).map((topic) => topic.title);
  if (!wizard) return "";
  if (!(store.report?.subjects || []).length) {
    return `<section class="panel">
      <div class="who"><b>Работу отправить нельзя</b><span>Нет предмета</span></div>
      <p>В этом классе нет назначения на предмет. Пока учителя предмета нет, заданий нет.</p>
      <button class="btn btn-primary" type="button" data-act="nav" data-screen="tasks">Закрыть</button>
    </section>`;
  }
  const titles = wizard.mode === "stimul"
    ? ["Тема", "Сколько заданий", "Кому отправить", "Просмотр"]
    : ["Тема", "Вопросы", "Кому отправить", "Просмотр"];
  const students = store.report?.students || [];
  let body = "";
  if (wizard.step === 1) {
    body = `<label class="field-label" for="topic">Тема</label>
      <input id="topic" class="field" list="topic-list" value="${esc(wizard.topic)}" placeholder="Например: проценты" autocomplete="off">
      <datalist id="topic-list">${topics.map((title) => `<option value="${esc(title)}"></option>`).join("")}</datalist>
      <label class="field-label" for="goal">Что проверить</label>
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
    body = `<div class="segment">
        <button type="button" class="${wizard.audience === "class" ? "is-on" : ""}" data-act="audience" data-value="class">Весь класс</button>
        <button type="button" class="${wizard.audience === "selected" ? "is-on" : ""}" data-act="audience" data-value="selected">Выбранные</button>
      </div>
      ${wizard.audience === "selected" ? `<p class="hint">Отдельных групп на сервере нет. Отметьте учеников ${esc(classTitle())}.</p>
        <div class="stack tight">${students.map((student) => {
          const on = (wizard.studentIds || []).includes(student.user_id);
          return `<button class="choice ${on ? "is-on" : ""}" type="button" data-act="toggle-student" data-id="${student.user_id}" data-name="${esc(student.display_name)}" aria-pressed="${on}">${esc(student.display_name)}</button>`;
        }).join("")}</div>` : `<p class="hint">Работа уйдёт ученикам ${esc(classTitle())}.</p>`}`;
  } else {
    const draft = wizard.draft;
    body = `${wizard.draftError ? `<div class="banner banner-bad"><p>${esc(wizard.draftError.message)}</p><button class="text-btn" type="button" data-act="compose-own">Написать вопросы самому</button></div>` : ""}
      ${store.busy ? `<p class="statusline" role="status">Собираю черновик…</p>` : ""}
      ${draft ? `<p class="hint">${draft.source === "own" ? "Это ваши вопросы." : "Проверьте вопросы перед отправкой."} Ученики увидят их только после «Опубликовать». Верный ответ виден только вам.</p>
        ${draft.note ? `<div class="banner banner-warn"><p>${esc(draft.note)}</p></div>` : ""}
        <p><strong>${esc(draft.topic)}</strong></p>
        <p>${esc(draft.goal)}</p>
        <p class="hint">${draft.audience === "class" ? "Весь класс" : "Выбранные"}: ${esc((draft.students || []).join(", ") || "никто")}</p>
        <div class="stack tight">${(draft.items || []).map((item, index) => `<article class="card card-flat">
          <h2>Задание ${item.number}</h2>
          <label class="field-label" for="prompt-${index}">Формулировка</label>
          <textarea id="prompt-${index}" class="area" data-prompt="${index}">${esc(item.prompt)}</textarea>
          <label class="field-label" for="reference-${index}">Верный ответ</label>
          <input id="reference-${index}" class="field" data-reference="${index}" value="${esc(item.reference || "")}" autocomplete="off">
        </article>`).join("")}</div>
        <p class="hint">Пока вы не нажали кнопку, правки остаются на этом экране.</p>` : ""}
      ${wizard.sendError ? `<div class="banner banner-warn" role="status"><strong>Отправка не выполнена</strong><p>${esc(wizard.sendError)}</p></div>` : ""}
      ${wizard.mode === "own" ? "" : `<button class="text-btn" type="button" data-act="redraft" ${store.busy ? "disabled" : ""}>Собрать заново</button>`}`;
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
  store.wizard = {
    step: 1,
    mode: mode === "stimul" ? "stimul" : "own",
    topic: topic || "",
    goal: "",
    blurb: "",
    count: 3,
    difficulty: "normal",
    audience: "class",
    students: [],
    studentIds: [],
    own: [],
    useMaterial: false,
    draft: null,
    draftError: null,
    sendError: null,
    fieldError: "",
  };
  if (store.screen !== "compose") go("compose");
  else refresh();
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

export function wizardNext() {
  const wizard = store.wizard;
  if (!wizard) return;
  readWizardFields();
  wizard.fieldError = "";
  if (wizard.step === 1) {
    if (wizard.topic.trim().length < 2) {
      wizard.fieldError = "Напишите тему.";
      refresh();
      return;
    }
    if (wizard.goal.trim().length < 3) {
      wizard.fieldError = "Напишите цель проверки.";
      refresh();
      return;
    }
  }
  if (wizard.step === 2 && wizard.mode === "own") {
    const missing = (wizard.own || []).slice(0, wizard.count).some((item) => !String(item?.prompt || "").trim() || !String(item?.reference || "").trim());
    const short = (wizard.own || []).length < wizard.count;
    if (missing || short) {
      wizard.fieldError = "У каждого задания нужны текст и верный ответ.";
      refresh();
      return;
    }
  }
  if (wizard.step === 3 && !(store.report?.students || []).length) {
    wizard.fieldError = "В классе нет учеников, отправлять некому.";
    refresh();
    return;
  }
  if (wizard.step === 3 && wizard.audience === "selected" && !(wizard.studentIds || []).length) {
    wizard.fieldError = "Отметьте хотя бы одного ученика.";
    refresh();
    return;
  }
  wizard.step += 1;
  if (wizard.step === 4 && wizard.mode === "own") sealOwnDraft();
  refresh();
  if (wizard.step === 4 && wizard.mode !== "own") loadDraft();
}

export function wizardBack() {
  const wizard = store.wizard;
  if (!wizard) return;
  readWizardFields();
  wizard.fieldError = "";
  wizard.sendError = null;
  wizard.step = Math.max(1, wizard.step - 1);
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
  store.wizard.audience = value === "selected" ? "selected" : "class";
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
  return {
    topic: wizard.topic.trim(),
    goal: wizard.goal.trim(),
    count: wizard.count,
    difficulty: wizard.difficulty,
    audience: wizard.audience,
    students: wizard.audience === "selected" ? wizard.students : [],
    student_ids: wizard.audience === "selected" ? wizard.studentIds || [] : [],
    use_material: Boolean(wizard.useMaterial),
    class_id: store.classId || null,
  };
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
  const names = wizard.audience === "selected"
    ? wizard.students
    : (store.report?.students || []).map((student) => student.display_name);
  wizard.draft = {
    topic: wizard.topic.trim(),
    goal: wizard.goal.trim(),
    audience: wizard.audience,
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
  const items = (store.wizard.draft?.items || []).map((item) => ({
    prompt: String(item.prompt || "").trim(),
    reference: String(item.reference || "").trim(),
  }));
  return {
    ...payload,
    prompts: items.map((item) => item.prompt),
    items,
    blurb: (store.wizard.blurb || "").trim(),
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
    const empty = wizard.draft.items.some((item) => !String(item.prompt || "").trim() || !String(item.reference || "").trim());
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
