import { answerWork, getAttempts, getHistory, getProgress, getStudentWorks, practice, sendPhoto } from "./api.js?v=8";
import { chatTitle, clearChatPhoto, loadChats, newChat, openChat, sendChat, showChatList } from "./chat.js?v=5";
import { sampleLesson } from "./preview.js";
import { go, refresh, store } from "./store.js?v=5";
import { themePref } from "./theme.js?v=1";
import {
  classbar,
  confirmDialog,
  emptyBlock,
  errorBlock,
  esc,
  firstName,
  icon,
  initials,
  mark,
  nl,
  pill,
  themeSwitch,
} from "./ui.js?v=5";

let photoFile = null;

function disabled() {
  return store.busy ? "disabled" : "";
}

function summarize(topics) {
  const known = (topics || []).filter((topic) => topic.status);
  const avg = known.length
    ? Math.round(known.reduce((sum, topic) => sum + (Number(topic.correct_percent) || 0), 0) / known.length)
    : null;
  return {
    avg,
    known: known.length,
    mastered: known.filter((topic) => topic.status === "mastered").length,
    practice: known.filter((topic) => topic.status === "needs_practice").length,
    repeat: known.filter((topic) => topic.status === "repeat").length,
  };
}

function inProgress(lesson) {
  return Boolean(lesson && lesson.topic && (lesson.step === "explain" || lesson.step === "check"));
}

function recentTopics() {
  const progress = store.progress;
  if (!progress) return { items: [], fromHistory: false };
  const byTitle = new Map((progress.topics || []).map((topic) => [topic.title, topic]));
  const items = [];
  for (const session of store.history?.sessions || []) {
    if (!session.topic || items.some((item) => item.title === session.topic)) continue;
    const topic = byTitle.get(session.topic);
    items.push({
      title: session.topic,
      status: topic?.status || null,
      correct_percent: topic?.correct_percent ?? null,
    });
    if (items.length === 3) return { items, fromHistory: true };
  }
  if (items.length) return { items, fromHistory: true };
  return {
    items: (progress.topics || []).filter((topic) => topic.status).slice(0, 3),
    fromHistory: false,
  };
}

function topicButton(topic) {
  const percent = topic.correct_percent == null ? "" : `${topic.correct_percent}%`;
  return `<button class="line" type="button" data-act="pick" data-topic="${esc(topic.title)}" ${disabled()}>
    <span>
      <strong>${esc(topic.title)}</strong>
      ${percent ? `<span class="hint">${esc(percent)}</span>` : ""}
    </span>
    ${pill(topic.status)}
  </button>`;
}

function mast(name, klass) {
  const unread = Number(store.notices?.unread) || 0;
  return classbar({
    title: klass || "Класс",
    subject: store.progress?.subject_title || "",
    letter: initials(name),
    unread,
    who: name || "",
  });
}

function topicLine(topic) {
  const width = topic.correct_percent == null ? 0 : Math.max(0, Math.min(100, Number(topic.correct_percent)));
  const label = topic.status ? pill(topic.status) : `<em>нет попыток</em>`;
  return `<button class="topic-line" type="button" data-act="pick" data-topic="${esc(topic.title)}">
    <span>${esc(topic.title)}</span>
    <span class="bar" data-status="${esc(topic.status || "none")}"><i style="width:${width}%"></i></span>
    ${label}
  </button>`;
}

function tone(status) {
  if (status === "mastered") return "green";
  if (status === "needs_practice") return "yellow";
  if (status === "repeat") return "coral";
  return "violet";
}

function statusLabel(status) {
  if (status === "mastered") return "Уже получается";
  if (status === "needs_practice") return "Нужна практика";
  if (status === "repeat") return "Повторить";
  return "Ещё без попыток";
}

function workBucket(item) {
  if (item.status === "done") return "done";
  const started = (item.items || []).some((question) => question.answered);
  return started ? "active" : "fresh";
}

function formatDue(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(date);
}

function workMeta(item) {
  const bits = [item.status === "done" ? "сдано" : "", item.subject, item.topic && item.topic !== item.title ? item.topic : "", item.author ? `назначил ${item.author}` : ""];
  const due = formatDue(item.due_at);
  if (due) bits.push(`срок ${due}`);
  return bits.filter(Boolean).join(" · ");
}

function studyRow(topic, index = 0) {
  return `<button class="study-row" type="button" data-act="pick" data-topic="${esc(topic.title)}" ${disabled()}>
    <span class="topic-number topic-number--${tone(topic.status)}">${String(index + 1).padStart(2, "0")}</span>
    <span><strong>${esc(topic.title)}</strong><small>${esc(statusLabel(topic.status))}${topic.correct_percent != null ? ` · ${esc(topic.correct_percent)}%` : ""}</small></span>
    <span class="topic-preview__arrow">${icon("arrow")}</span>
  </button>`;
}

function askBlock() {
  const photo = store.photoURL
    ? `<div class="attach"><img class="thumb" alt="" src="${esc(store.photoURL)}"><span>Фото прикреплено</span><button class="text-btn" type="button" data-act="clear-photo">Убрать</button></div>`
    : "";
  const composer = store.composer || store.question || store.photoURL
    ? `<textarea id="question" class="area" placeholder="Например: не понимаю, как сложить дроби" aria-label="Вопрос" ${disabled()}>${esc(store.question)}</textarea>
      ${photo}
      ${store.fieldError ? `<p class="field-error">${esc(store.fieldError)}</p>` : ""}
      <div class="ask-actions">
        <button class="btn btn-primary" type="button" data-act="send-question" ${disabled()}>Отправить вопрос</button>
      </div>
      <p class="quiet">Тренировка остаётся у тебя. Учителю уходит только статус темы.</p>`
    : "";
  return `<section class="ask-card">
    <div class="ask-card__row">
      <div>
        <span class="eyebrow">Вопрос по теме</span>
        <strong>Не получается шаг</strong>
      </div>
      <div class="ask-actions">
        <button class="btn btn-primary" type="button" data-act="toggle-ask">Задать вопрос</button>
        <label class="btn btn-ghost file">Фото страницы<input id="photo" type="file" accept="image/*" aria-label="Отправить фотографию"></label>
      </div>
    </div>
    ${composer}
  </section>`;
}

export function renderHome() {
  const progress = store.progress;
  if (store.loading && !progress) return skeleton();
  if (!progress) return errorBlock(store.progressError?.message, "retry");
  const stats = summarize(progress.topics);
  const name = firstName(progress.display_name || store.displayName || "");
  const open = inProgress(store.openLesson) ? store.openLesson : null;
  const waiting = (store.works?.items || []).filter((item) => workBucket(item) !== "done").slice(0, 2);
  const attention = (progress.topics || [])
    .filter((topic) => topic.status === "repeat" || topic.status === "needs_practice")
    .sort((a, b) => (a.status === "repeat" ? -1 : 1) - (b.status === "repeat" ? -1 : 1))
    .slice(0, 3);
  const fresh = !stats.known && !waiting.length && !open;
  const lead = fresh
    ? "Занятий ещё не было. Можно начать с вопроса по теме из урока."
    : (progress.next_step || "Дальше разберём то, что уже просится в практику.");
  const heroTitle = fresh ? "С чего начать" : (progress.next_topic || "Следующий шаг");
  return `<div class="fig">
    ${mast(progress.display_name || store.displayName, progress.class_title)}
    <div class="fig-page">
      <div class="welcome">
        <span class="eyebrow">Мой день</span>
        <h1 id="page-title">${name ? `Привет, ${esc(name)}` : "Привет"}</h1>
        <p>${esc(lead)}</p>
      </div>
      <article class="learn-card">
        <span class="eyebrow">${fresh ? "Пока пусто" : "Следующий шаг"}</span>
        <h2>${esc(heroTitle)}</h2>
        <p>${fresh ? "После первой проверки здесь появятся темы, которые уже получаются, и те, что стоит повторить." : esc(progress.next_step || "Открой тему и пройди короткое объяснение с практикой.")}</p>
        ${progress.next_topic
    ? `<button class="primary-button primary-button--light" type="button" data-act="open-next">Разобрать шаг<span>${icon("arrow")}</span></button>`
    : `<button class="primary-button primary-button--light" type="button" data-act="toggle-ask">Задать вопрос<span>${icon("arrow")}</span></button>`}
      </article>
      ${open ? `<button class="study-row study-row--solo" type="button" data-act="resume"><span class="topic-number topic-number--violet">▶</span><span><strong>${esc(open.topic)}</strong><small>Занятие уже открыто</small></span><span class="topic-preview__arrow">${icon("arrow")}</span></button>` : ""}
      <section class="study-group">
        <div class="section-heading">
          <div><span class="eyebrow">Сейчас</span><h2>Что сделать</h2></div>
          <button class="text-button" type="button" data-act="nav" data-screen="tasks">Все задания ${icon("arrow")}</button>
        </div>
        ${waiting.length ? `<div class="topic-preview">${waiting.map((item) => `<button class="study-row" type="button" data-act="open-work" data-id="${item.id}"><span class="topic-number topic-number--${workBucket(item) === "active" ? "yellow" : "coral"}">${workBucket(item) === "active" ? "…" : "!"}</span><span><strong>${esc(item.title)}</strong><small>${esc(workMeta(item) || "Назначенная работа")}</small></span><span class="topic-preview__arrow">${icon("arrow")}</span></button>`).join("")}</div>` : `<p class="quiet">Назначенных работ нет. Когда учитель опубликует проверку, она появится здесь.</p>`}
      </section>
      <section class="study-group">
        <div class="section-heading">
          <div><span class="eyebrow">Темы</span><h2>${attention.length ? "Стоит вернуться" : "Программа"}</h2></div>
          <button class="text-button" type="button" data-act="nav" data-screen="map">Карта знаний ${icon("arrow")}</button>
        </div>
        ${attention.length ? `<div class="topic-preview">${attention.map((topic, index) => studyRow(topic, index)).join("")}</div>` : `<p class="quiet">${stats.known ? "Слабых тем сейчас нет. Новую можно открыть на карте." : "Статусов ещё нет: тема получит его после проверенного ответа."}</p>`}
        ${stats.known ? `<p class="quiet">Уже получается ${stats.mastered}. Нужна практика ${stats.practice}. Повторить ${stats.repeat}.</p>` : ""}
      </section>
      ${askBlock()}
    </div>
  </div>`;
}

function modeChip(mode) {
  if (mode === "submission") {
    return `<p class="mode mode-submission">Сдача. Учителю уходит результат работы, не личный вопрос.</p>`;
  }
  return `<p class="mode mode-training">Тренировка. Вопрос остаётся у тебя, учителю не уходит.</p>`;
}

function stages(lesson) {
  let current = 0;
  if (lesson?.feedback) current = 3;
  else if (lesson?.awaiting_answer || lesson?.step === "check") current = 2;
  else if (lesson?.explanation) current = 1;
  if (!current) return "";
  return `<ol class="stages">${["Объяснение", "Практика", "Проверка"].map((label, index) => {
    const step = index + 1;
    const state = current > step ? "is-done" : current === step ? "is-current" : "";
    return `<li class="${state}">${label}</li>`;
  }).join("")}</ol>`;
}

function lessonBanner(error) {
  if (!error) return "";
  const calm = error.code === "submission_unavailable" || error.code === "preview" || error.status === 501;
  return `<div class="banner ${calm ? "banner-info" : "banner-bad"}" role="status">
    <strong>${calm ? "Сдачу принять не могу" : "Не получилось"}</strong>
    <p>${esc(error.message)}</p>
    ${calm ? "" : `<button class="btn btn-ghost" type="button" data-act="retry-lesson">Повторить</button>`}
  </div>`;
}

function actionButtons(actions) {
  const items = (actions || []).filter((item) => item.action !== "pick");
  if (!items.length) return "";
  return `<div class="actions">${items.map((item) => {
    const primary = item.action === "to_practice" || item.action === "again" || item.action === "review";
    const version = store.lesson && store.lesson.version != null ? String(store.lesson.version) : "";
    return `<button class="btn ${primary ? "btn-primary" : "btn-ghost"}" type="button" data-act="lesson-action" data-action="${esc(item.action)}" data-topic="${esc(item.topic || "")}" data-version="${esc(version)}" ${disabled()}>${esc(item.label)}</button>`;
  }).join("")}</div>`;
}

function pickChips(actions) {
  const picks = (actions || []).filter((item) => item.action === "pick");
  if (!picks.length) return "";
  const version = store.lesson && store.lesson.version != null ? String(store.lesson.version) : "";
  return `<div class="chips">${picks.map((item) => `<button class="chip" type="button" data-act="lesson-action" data-action="${esc(item.action)}" data-topic="${esc(item.topic || "")}" data-version="${esc(version)}" ${disabled()}>${esc(item.label || item.topic)}</button>`).join("")}</div>`;
}

export function renderLesson() {
  const lesson = store.lesson;
  const mode = lesson?.mode === "submission" ? "submission" : store.lessonMode;
  const started = Boolean(lesson && (lesson.explanation || lesson.task || lesson.feedback || lesson.notice));
  const switcher = started
    ? ""
    : `<div class="segment" role="tablist" aria-label="Режим">
        <button type="button" role="tab" data-act="mode" data-mode="training" aria-selected="${mode !== "submission"}" class="${mode !== "submission" ? "is-on" : ""}">Тренировка</button>
        <button type="button" role="tab" data-act="mode" data-mode="submission" aria-selected="${mode === "submission"}" class="${mode === "submission" ? "is-on" : ""}">Сдача</button>
      </div>`;
  const submission = mode === "submission" && !lesson?.task
    ? `<section class="card">
        <h2>Жду работу от учителя</h2>
        <p>Здесь я принимаю ответы на выданную работу и не разбираю новую страницу. Личный вопрос учителю не уходит.</p>
        <button class="btn btn-primary" type="button" data-act="check-submission" ${disabled()}>Проверить, есть ли работа</button>
      </section>`
    : "";
  const idleHelp = !started && mode !== "submission" && !store.busy
    ? `<section class="card">
        <h2>С чего начать</h2>
        <p>Вопрос пишется на главной. Здесь можно открыть тему из программы.</p>
        <div class="chips">${(store.progress?.topics || []).map((topic) => `<button class="chip" type="button" data-act="pick" data-topic="${esc(topic.title)}" ${disabled()}>${esc(topic.title)}</button>`).join("")}</div>
      </section>`
    : "";
  const note = lesson?.notice
    ? `<div class="banner banner-info" role="status"><p>${esc(lesson.notice)}</p></div>`
    : lesson?.photo_note && !lesson.explanation
      ? `<div class="banner banner-info" role="status"><p>${esc(lesson.photo_note)}</p></div>`
      : "";
  const photoNote = lesson?.photo_received && lesson?.explanation
    ? `<p class="hint">${esc(lesson.photo_note || "Фото получили. Страницу не решаем.")}</p>`
    : "";
  const answerForm = lesson?.awaiting_answer
    ? `<form id="answer-form" class="stack tight">
        <label class="field-label" for="answer">Твой ответ</label>
        <input id="answer" class="field" value="${esc(store.answer)}" autocomplete="off" autocorrect="off" spellcheck="false" enterkeyhint="send" ${disabled()}>
        ${store.fieldError ? `<p class="field-error">${esc(store.fieldError)}</p>` : ""}
        <button class="btn btn-primary" type="submit" ${disabled()}>Проверить</button>
      </form>`
    : "";
  const klass = store.progress?.class_title || "";
  const subject = store.progress?.subject_title || "";
  return `<div class="fig">
    <div class="fig-page lesson-page">
      <button class="text-button back" type="button" data-act="exit-lesson">${icon("chevron")} К прогрессу</button>
    ${modeChip(mode)}
    ${stages(lesson)}
    <h1 id="page-title" tabindex="-1">${esc(lesson?.topic || "Занятие")}</h1>
    <p class="hint">${esc([subject, klass].filter(Boolean).join(" · ") || "Твоё занятие")}</p>
    ${store.busy ? `<p class="statusline" role="status">${esc(store.busyLabel || "Секунду…")}</p>` : ""}
    ${lessonBanner(store.lessonError)}
    ${switcher}
    ${submission}
    ${note}
    ${photoNote}
    ${lesson?.explanation ? `<section class="card"><h2>Простыми словами</h2><p>${nl(lesson.explanation)}</p></section>` : ""}
    ${lesson?.example ? `<section class="card card-flat"><h2>Пример</h2><p>${nl(lesson.example)}</p></section>` : ""}
    ${lesson?.task ? `<section class="card task-card"><h2>Задание</h2><p>${nl(lesson.task)}</p>${answerForm}</section>` : ""}
    ${lesson?.hint ? `<section class="card card-flat hint-card" role="status"><h2>Подсказка</h2><p>${nl(lesson.hint)}</p></section>` : ""}
    ${lesson?.feedback ? `<section class="card feedback ${lesson.correct ? "is-ok" : "is-bad"}" role="status">
      <h2>${lesson.correct ? "Верно" : "Есть ошибка"}</h2>
      <p>${nl(lesson.feedback)}</p>
      ${lesson.given ? `<p class="hint">Твой ответ: ${esc(lesson.given)}</p>` : ""}
      ${lesson.status_line ? `<p>${nl(lesson.status_line)}</p>` : ""}
    </section>` : ""}
    ${actionButtons(lesson?.actions)}
    ${pickChips(lesson?.actions)}
    ${lesson?.notice && !lesson.task && !(lesson.actions || []).some((item) => item.action === "pick") ? `<div class="chips">${(store.progress?.topics || []).map((topic) => `<button class="chip" type="button" data-act="pick" data-topic="${esc(topic.title)}" ${disabled()}>${esc(topic.title)}</button>`).join("")}</div>` : ""}
    ${idleHelp}
    ${lesson?.topic && !lesson.feedback && !(lesson.actions || []).some((item) => item.action === "more_example") ? `<button class="btn btn-ghost" type="button" data-act="lesson-action" data-action="more_example" ${disabled()}>Объясни иначе</button>` : ""}
    <button class="btn btn-ghost" type="button" data-act="exit-lesson">К моему прогрессу</button>
    </div>
  </div>`;
}

export function renderMap() {
  const progress = store.progress;
  if (store.loading && !progress) return "";
  if (!progress) return errorBlock(store.progressError?.message, "retry");
  const stats = summarize(progress.topics);
  const groups = [
    ["mastered", "Уже получается"],
    ["needs_practice", "Нужна практика"],
    ["repeat", "Повторить"],
  ];
  const fresh = (progress.topics || []).filter((topic) => !topic.status);
  const history = (store.history?.sessions || []).slice(0, 3);
  const block = (status, title) => {
    const items = (progress.topics || []).filter((topic) => topic.status === status);
    if (!items.length) return "";
    return `<section class="study-group"><h2 class="study-label">${title}</h2><div class="topic-preview">${items.map((topic, index) => studyRow(topic, index)).join("")}</div></section>`;
  };
  return `<div class="fig">
    ${mast(progress.display_name, progress.class_title)}
    <div class="fig-page">
      <div class="page-heading">
        <span class="eyebrow">Личный прогресс</span>
        <h1 id="page-title">Карта знаний</h1>
        <p>${stats.known ? `Усвоено ${stats.mastered}. Нужна практика ${stats.practice}. Повторить ${stats.repeat}. Статус считается по твоим ответам.` : "Пока нет проверенных ответов. Открой тему на обзоре или сдай работу из заданий."}</p>
      </div>
      ${progress.next_topic ? `<article class="learn-card learn-card--compact"><span class="eyebrow">Дальше</span><h2>${esc(progress.next_step || progress.next_topic)}</h2><button class="primary-button primary-button--light" type="button" data-act="open-next">Разобрать<span>${icon("arrow")}</span></button></article>` : ""}
      ${groups.map(([status, title]) => block(status, title)).join("")}
      ${fresh.length ? `<section class="study-group"><h2 class="study-label">Ещё без попыток</h2><div class="topic-preview">${fresh.map((topic, index) => studyRow(topic, index)).join("")}</div></section>` : ""}
      <section class="study-group">
        <div class="section-heading">
          <div><span class="eyebrow">Попытки</span><h2>Недавние</h2></div>
          <button class="text-button" type="button" data-act="nav" data-screen="history">Вся история ${icon("arrow")}</button>
        </div>
        ${store.historyError ? `<p class="field-error">${esc(store.historyError.message)}</p>` : ""}
        ${history.length ? `<div class="topic-list">${history.map(historyRow).join("")}</div>` : `<p class="quiet">Проверенных занятий пока нет.</p>`}
      </section>
      ${attemptsSection()}
    </div>
  </div>`;
}

function historyRow(item) {
  const when = formatWhen(item.created_at);
  const mode = item.mode === "submission" ? "сдача" : "тренировка";
  const result = item.answered ? `${item.correct_count} из ${item.answered} верно` : "без проверки";
  return `<article class="history-row">
    <strong>${esc(item.topic || "Тема не выбрана")}</strong>
    <span>${esc(when)} · ${esc(mode)} · ${esc(result)}</span>
  </article>`;
}

function attemptRow(item) {
  const meta = [item.topic, formatWhen(item.created_at), item.hinted ? "с подсказкой" : "", item.mode === "submission" ? "сдача" : ""]
    .filter(Boolean)
    .join(" · ");
  return `<article class="attempt-row ${item.correct ? "is-ok" : "is-bad"}">
    <span class="attempt-row__mark ${item.correct ? "bubble-ok" : "bubble-bad"}" aria-label="${item.correct ? "Верно" : "Ошибка"}">${item.correct ? "✓" : "✗"}</span>
    <div>
      <strong>${nl(item.prompt)}</strong>
      <span>Твой ответ: <b class="${item.correct ? "bubble-ok" : "bubble-bad"}">${esc(item.answer || "—")}</b></span>
      ${meta ? `<small>${esc(meta)}</small>` : ""}
    </div>
  </article>`;
}

function attemptsSection() {
  const items = store.attempts?.items || [];
  const misses = items.filter((item) => !item.correct).length;
  return `<section class="study-group attempts">
    <div class="section-heading">
      <div><span class="eyebrow">Только мои ответы</span><h2>История решённых примеров</h2></div>
    </div>
    ${items.length && misses ? `<p class="quiet">Ошибок в списке: ${misses}. Их стоит разобрать ещё раз.</p>` : ""}
    ${store.attemptsError ? `<p class="field-error">${esc(store.attemptsError.message)}</p>` : ""}
    ${items.length
    ? `<div class="topic-list">${items.map(attemptRow).join("")}</div>`
    : `<p class="quiet">Пока пусто. Реши первое задание, и оно появится здесь.</p>`}
    ${store.attempts?.more ? `<button class="btn btn-ghost" type="button" data-act="attempts-more" ${store.attemptsBusy ? "disabled" : ""}>Показать ещё</button>` : ""}
  </section>`;
}

function formatWhen(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" }).format(date);
}

export function renderHistory() {
  if (store.loading && !store.history && !store.historyError) return "";
  if (store.historyError && !store.history) return errorBlock(store.historyError.message, "retry");
  const sessions = store.history?.sessions || [];
  return `<div class="fig">
    ${mast(store.progress?.display_name || store.displayName, store.progress?.class_title)}
    <div class="fig-page">
      <div class="page-heading">
        <span class="eyebrow">Только мои попытки</span>
        <h1 id="page-title">История</h1>
        <p>Занятия и проверки. Текст личного вопроса здесь не показываю.</p>
      </div>
      ${sessions.length ? `<div class="topic-list">${sessions.map(historyRow).join("")}</div>` : emptyBlock("Пока пусто", "Когда проверишь первое задание, занятие появится в этом списке.")}
    </div>
  </div>`;
}

export function renderProfile() {
  const progress = store.progress;
  if (!progress && store.progressError) return errorBlock(store.progressError.message, "retry");
  const name = progress?.display_name || store.displayName || "";
  const topics = progress?.topics || [];
  const stats = summarize(topics);
  const works = (store.works?.items || []).length;
  const score = stats.avg == null ? 0 : stats.avg;
  const headline = stats.known ? (progress?.next_step || "Есть темы для повторения") : "Начни с первой темы";
  const subject = progress?.subject_title || "";
  return `<div class="fig">
    ${mast(name, progress?.class_title)}
    <div class="fig-page">
      <div class="profile-card profile-card--student">
        <div class="profile-card__avatar profile-card__avatar--student">${esc(initials(name))}</div>
        <div>
          <span class="eyebrow">Ученик</span>
          <h1 id="page-title">${esc(firstName(name) || name || "Имя не пришло")}</h1>
          <p>${esc(progress?.class_title || "класс не указан")}${subject ? ` · ${esc(subject)}` : ""}</p>
        </div>
        ${store.nameChanged ? "" : `<button class="profile-card__edit" type="button" data-act="profile-note">Изменить имя</button>`}
      </div>
      <div class="student-stats">
        <article><span>Работы</span><strong>${works}</strong><small>${works ? "назначены" : "ещё не было"}</small></article>
        <article><span>Темы</span><strong>${topics.length}</strong><small>в этом году</small></article>
      </div>
      <div class="student-focus">
        <div class="student-focus__heading">
          <div>
            <span class="eyebrow">Мой прогресс</span>
            <h2>${esc(headline)}</h2>
          </div>
          <div class="student-focus__score">${score}%</div>
        </div>
        <div class="student-progress"><span style="width:${score || 3}%"></span></div>
        <p>${stats.known ? `Усвоено ${stats.mastered}. Нужна практика ${stats.practice}. Повторить ${stats.repeat}.` : "После первой работы здесь появятся темы, которые уже получаются, и подсказки для повторения."}</p>
        <button class="student-focus__action" type="button" data-act="nav" data-screen="map">Открыть карту знаний ${icon("arrow")}</button>
      </div>
      <button class="student-tip" type="button" data-act="nav" data-screen="history">
        <div class="student-tip__icon">${icon("spark")}</div>
        <div>
          <strong>Личный помощник</strong>
          <p>Можно задать вопрос по теме — учитель не увидит личный диалог. История занятий — внутри.</p>
        </div>
        ${icon("chevron")}
      </button>
      ${attemptsSection()}
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

export function renderTasks() {
  if (store.openWork) return renderWork(store.openWork);
  if (store.worksError && !store.works) return errorBlock(store.worksError.message, "retry");
  const items = store.works?.items || [];
  const groups = [
    ["fresh", "Новые", "coral"],
    ["active", "В работе", "yellow"],
    ["done", "Сданные", "green"],
  ];
  const row = (item, marker) => `<button class="study-row" type="button" data-act="open-work" data-id="${item.id}">
      <span class="topic-number topic-number--${marker}">${item.status === "done" ? "✓" : "!"}</span>
      <span><strong>${esc(item.title)}</strong><small>${esc(workMeta(item) || "Работа без описания")}</small></span>
      <span class="topic-preview__arrow">${icon("arrow")}</span>
    </button>`;
  const filled = groups
    .map(([id, title, marker]) => {
      const list = items.filter((item) => workBucket(item) === id);
      if (!list.length) return "";
      return `<section class="study-group"><h2 class="study-label">${title}</h2><div class="topic-preview">${list.map((item) => row(item, marker)).join("")}</div></section>`;
    })
    .join("");
  return `<div class="fig">
    ${mast(store.progress?.display_name || store.displayName, store.progress?.class_title)}
    <div class="fig-page">
      <div class="page-heading">
        <span class="eyebrow">Назначил учитель</span>
        <h1 id="page-title">Задания</h1>
        <p>Здесь только работы, которые отправили тебе. Личный вопрос в этот список не попадает.</p>
      </div>
      ${store.worksError ? `<p class="field-error">${esc(store.worksError.message)}</p>` : ""}
      ${items.length ? filled : `<article class="empty-task-card">
        <div class="empty-task-card__art" aria-hidden="true"><div class="task-sheet task-sheet--back"></div><div class="task-sheet task-sheet--front"><i></i><i></i><i></i></div><span class="art-dot art-dot--one"></span><span class="art-dot art-dot--two"></span></div>
        <span class="eyebrow">Пока тихо</span><h2>Заданий пока нет</h2><p>${store.preview ? "В демонстрации список с сервера не подставляется." : store.works?.reason === "no_teacher" ? "В классе нет учителя, поэтому заданий нет." : "Когда учитель опубликует работу, она появится здесь и в чате."}</p>
      </article>`}
    </div>
  </div>`;
}

function resourceKindHint(item) {
  if (item.kind === "link") return "ссылка";
  const name = String(item.title || "").toLowerCase();
  const mime = String(item.mime || "").toLowerCase();
  if (mime.includes("pdf") || name.endsWith(".pdf")) return "PDF · скачать";
  if (mime.startsWith("image/") || /\.(png|jpe?g|webp|gif)$/.test(name)) return "изображение · скачать";
  return "файл · скачать";
}

function renderWork(work) {
  const due = formatDue(work.due_at);
  const items = work.items || [];
  const allAnswered = items.length > 0 && items.every((item) => item.answered);
  return `<div class="fig">
    ${mast(store.progress?.display_name || store.displayName, store.progress?.class_title)}
    <div class="fig-page">
      <button class="text-button" type="button" data-act="close-work">${icon("chevron")} К списку</button>
      <div class="page-heading">
        <span class="eyebrow">${esc(work.subject || "Работа")}</span>
        <h1 id="page-title">${esc(work.title)}</h1>
        <p>${esc(work.topic && work.topic !== work.title ? work.topic : work.goal || "")}${work.author ? ` Назначил ${esc(work.author)}.` : ""}${due ? ` Срок ${esc(due)}.` : ""}</p>
        ${work.study ? `<p>${esc(work.study)}</p>` : ""}
      </div>
      ${(work.resources || []).length ? `<div class="resource-list">
        <p class="field-label">Материалы</p>
        ${work.resources.map((item) => `<a class="resource-card" href="${esc(item.url)}" ${item.kind === "link" ? 'target="_blank" rel="noopener noreferrer"' : ""}>
          <span class="resource-card__icon">${icon(item.kind === "link" ? "link" : "download")}</span>
          <span class="resource-card__text"><strong>${esc(item.title)}</strong><small>${esc(resourceKindHint(item))}</small></span>
          <span class="resource-card__go">${icon("arrow")}</span>
        </a>`).join("")}
      </div>` : ""}
      <div class="work-sheet">
        ${(work.items || []).map((item) => `<section>
          <h2>Задание ${item.position}</h2>
          <p>${esc(item.prompt)}</p>
          ${item.answered ? `<p class="quiet">${item.correct ? "Верно" : "Пока не сошлось"}</p>` : `<label class="field-label" for="work-${item.id}">Ответ</label><input id="work-${item.id}" class="field" data-work-item="${item.id}" autocomplete="off">`}
        </section>`).join("")}
      </div>
      ${store.fieldError ? `<p class="field-error">${esc(store.fieldError)}</p>` : ""}
      ${allAnswered
        ? `<button class="primary-button" type="button" data-act="close-work">К списку</button>`
        : `<button class="primary-button" type="button" data-act="submit-work" ${disabled()}>Проверить ответы</button>`}
    </div>
  </div>`;
}

function lessonBubble(payload) {
  if (!payload) return "";
  const parts = [];
  if (payload.topic) parts.push(`<strong>${esc(payload.topic)}</strong>`);
  if (payload.explanation) parts.push(`<p>${nl(payload.explanation)}</p>`);
  if (payload.example) parts.push(`<p class="hint">Пример: ${nl(payload.example)}</p>`);
  if (payload.task) parts.push(`<p><b>Задание:</b> ${nl(payload.task)}</p>`);
  if (payload.hint) parts.push(`<p class="hint"><b>Подсказка:</b> ${nl(payload.hint)}</p>`);
  if (payload.feedback) {
    parts.push(`<p class="${payload.correct ? "bubble-ok" : "bubble-bad"}"><b>${payload.correct ? "Верно" : "Есть ошибка"}:</b> ${nl(payload.feedback)}</p>`);
  }
  if (payload.given) parts.push(`<p class="hint">Твой ответ: ${esc(payload.given)}</p>`);
  if (payload.status_line) parts.push(`<p class="hint">${nl(payload.status_line)}</p>`);
  if (payload.notice && !payload.explanation) parts.push(`<p>${nl(payload.notice)}</p>`);
  if (payload.photo_note) parts.push(`<p class="hint">${esc(payload.photo_note)}</p>`);
  return parts.join("");
}

function chatMessageRow(message) {
  if (message.role === "user") {
    return `<div class="chat-msg chat-msg--me"><div class="chat-msg__bubble">${nl(message.text)}</div></div>`;
  }
  const body = message.kind === "lesson" ? lessonBubble(message.payload) : nl(message.text);
  return `<div class="chat-msg"><span class="chat-msg__avatar">${mark()}</span><div class="chat-msg__body">${body || nl(message.text)}</div></div>`;
}

function chatEmpty() {
  const samples = [
    ["Объясни тему", "Объясни простыми словами тему из моей программы"],
    ["Дай пример", "Приведи пример и похожее задание по теме"],
    ["Что повторить", "Что мне сейчас стоит повторить?"],
  ];
  return `<div class="chat-empty">
    <div class="chat-empty__mark">${mark(true)}</div>
    <h2>С чем помочь?</h2>
    <p>Объясню способ и дам похожее задание. Готовый ответ для списывания не выдаю.</p>
    <div class="chat-suggest">${samples.map(([label, text]) => `<button type="button" data-act="chat-sample" data-text="${esc(text)}">${esc(label)}</button>`).join("")}</div>
  </div>`;
}

function chatQuickActions() {
  if (!store.chatPhotoURL) return "";
  const items = [
    ["Объясни это", "Объясни, что на фото, и дай похожее задание"],
    ["Пример", "Приведи пример по материалу с фото"],
    ["Проверь решение", "Проверь моё решение по материалу с фото"],
  ];
  return `<div class="chat-quick">${items
    .map(([label, text]) => `<button type="button" data-act="chat-sample" data-text="${esc(text)}">${esc(label)}</button>`)
    .join("")}</div>`;
}

function chatThread() {
  const messages = store.chatMessages || [];
  const typing = store.chatBusy
    ? `<div class="chat-msg"><span class="chat-msg__avatar">${mark()}</span><div class="chat-typing" role="status" aria-label="Стимул пишет"><i></i><i></i><i></i></div></div>`
    : "";
  const rows = messages.length ? messages.map(chatMessageRow).join("") + typing : typing || chatEmpty();
  const photo = store.chatPhotoURL
    ? `<div class="chat-photo-chip"><img alt="" src="${esc(store.chatPhotoURL)}"><span>Фото прикреплено</span><button class="text-btn" type="button" data-act="clear-chat-photo">Убрать</button></div>`
    : "";
  return `<div class="chat-scroll"><div class="chat-thread">${rows}</div><div class="chat-scroll-end"></div></div>
    <div class="chat-bottom">
      ${photo}
      ${chatQuickActions()}
      ${store.chatRateNote ? `<p class="chat-status" role="status">${esc(store.chatRateNote)}</p>` : ""}
      ${store.chatError && store.chatError !== store.chatRateNote ? `<p class="chat-error" role="alert">${esc(store.chatError)}</p>` : ""}
      ${store.chatStatus ? `<p class="chat-status" role="status">${esc(store.chatStatus)}</p>` : ""}
      <form id="chat-form" class="chat-composer">
        <label class="chat-composer__attach" aria-label="Фото страницы">${icon("image")}<input id="chat-photo" type="file" accept="image/*"></label>
        <input id="chat-input" value="${esc(store.chatDraft)}" placeholder="Спросить Стимула" autocomplete="off" aria-label="Вопрос помощнику" ${store.chatBusy ? "disabled" : ""}>
        <button class="chat-composer__send" type="submit" aria-label="Отправить" ${store.chatBusy ? "disabled" : ""}>${icon("send")}</button>
      </form>
      <p class="chat-note">Разговор виден только тебе. Учителю уходит статус темы, не текст.</p>
    </div>`;
}

function chatList() {
  const items = store.chats?.items || [];
  return `${store.chatId ? `<button class="text-button back" type="button" data-act="assistant-back">${icon("chevron")} К разговору</button>` : ""}
    <div class="page-heading">
      <span class="eyebrow">Личный помощник</span>
      <h1 id="page-title">Разговоры</h1>
      <p>История вопросов и разборов. Каждый разговор виден только тебе.</p>
    </div>
    ${store.chatsError ? `<p class="field-error">${esc(store.chatsError)}</p>` : ""}
    <button class="btn btn-primary" type="button" data-act="assistant-new">Новый разговор</button>
    <div class="topic-preview" style="margin-top:14px">
      ${items.length ? items.map((item) => `<div class="chat-row">
        <button class="study-row chat-row__main" type="button" data-act="assistant-open" data-id="${item.id}">
          <span class="topic-number topic-number--violet">${item.pinned ? "📌" : "✦"}</span>
          <span><strong>${esc(item.title || "Без названия")}</strong><small>${esc(new Date(item.updated_at).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }))}</small></span>
          <span class="topic-preview__arrow">${icon("arrow")}</span>
        </button>
        <button class="icon-button chat-row__pin ${item.pinned ? "is-on" : ""}" type="button" data-act="assistant-pin" data-id="${item.id}" aria-label="Закрепить" title="${item.pinned ? "Открепить" : "Закрепить"}">📌</button>
        <button class="icon-button chat-row__del" type="button" data-act="assistant-delete" data-id="${item.id}" aria-label="Удалить" title="Удалить">${icon("close")}</button>
      </div>`).join("") : `<p class="quiet">Разговоров пока нет.</p>`}
    </div>`;
}

export function renderStimul() {
  const klass = store.progress?.class_title || "";
  if (store.chatView === "list") {
    return `<div class="fig">
      ${mast(store.progress?.display_name || store.displayName, klass)}
      <div class="fig-page assistant-page">${chatList()}</div>
    </div>`;
  }
  return `<div class="fig">
    ${mast(store.progress?.display_name || store.displayName, klass)}
    <div class="fig-page assistant-page chat-page">
      <div class="chat-head">
        <div class="chat-head__who">${mark()}<div><span class="eyebrow">Личный помощник</span><h1 id="page-title">${esc(chatTitle())}</h1></div></div>
        <div class="chat-head__actions">
          <button class="chat-tool" type="button" data-act="assistant-chats" aria-label="Разговоры" title="Разговоры">${icon("list")}</button>
          <button class="chat-tool" type="button" data-act="assistant-new" aria-label="Новый разговор" title="Новый разговор">${icon("plus")}</button>
        </div>
      </div>
      ${chatThread()}
    </div>
  </div>`;
}

export async function openStudentChat(id) {
  await openChat(id);
}

export async function startStudentChat() {
  await newChat();
}

export function showStudentChats() {
  showChatList();
  loadChats();
}

export async function submitChat() {
  const text = (store.chatDraft || "").trim();
  const photo = store.chatPhotoFile || null;
  await sendChat(text, {
    photo,
    onReply: (reply) => {
      if (reply && reply.ok !== false) {
        store.lesson = keepTask(reply);
        store.openLesson = reply;
        rememberProgress();
      }
    },
  });
  if (!store.chatError) clearChatPhoto();
}

export async function submitWork() {
  const work = store.openWork;
  if (!work || store.busy) return;
  if (store.preview) {
    store.fieldError = "В демонстрации ответ не сохраняется.";
    refresh();
    return;
  }
  const answers = [...document.querySelectorAll("[data-work-item]")].map((input) => ({
    item_id: Number(input.dataset.workItem),
    answer: input.value.trim(),
  })).filter((item) => item.answer);
  if (!answers.length) {
    const items = work.items || [];
    if (items.length && items.every((item) => item.answered)) {
      store.openWork = null;
      refresh();
      return;
    }
    store.fieldError = "Введите ответ.";
    refresh();
    return;
  }
  store.busy = true;
  store.fieldError = "";
  refresh();
  try {
    const result = await answerWork(work.id, answers);
    if (!result?.persisted) {
      store.fieldError = "Сервер не сохранил ответ.";
      return;
    }
    store.works = await getStudentWorks();
    store.openWork = (store.works.items || []).find((item) => item.id === work.id) || work;
    store.progress = await getProgress();
  } catch (error) {
    store.fieldError = error.message;
  } finally {
    store.busy = false;
    refresh();
  }
}

export function renderStudent() {
  if (store.screen === "lesson") return renderLesson();
  if (store.screen === "map") return renderMap();
  if (store.screen === "history") return renderHistory();
  if (store.screen === "profile") return renderProfile();
  if (store.screen === "tasks") return renderTasks();
  if (store.screen === "stimul") return renderStimul();
  return renderHome();
}

function queue(job) {
  if (store.busy || store.pending) return;
  store.lessonMode = "training";
  store.lessonError = null;
  store.pending = job;
  store.lastJob = job;
  if (location.hash !== "#/lesson") location.hash = "#/lesson";
  else refresh();
}

export function takePhoto(file) {
  if (!file) return;
  if (file.size > 8 * 1024 * 1024) {
    store.fieldError = "Фото больше 8 МБ. Выбери снимок поменьше.";
    refresh();
    return;
  }
  if (file.type && !file.type.startsWith("image/")) {
    store.fieldError = "Нужен файл изображения.";
    refresh();
    return;
  }
  if (store.photoURL) URL.revokeObjectURL(store.photoURL);
  photoFile = file;
  store.photoURL = URL.createObjectURL(file);
  store.fieldError = "";
  refresh();
}

function dropPhoto() {
  if (store.photoURL) URL.revokeObjectURL(store.photoURL);
  photoFile = null;
  store.photoURL = "";
}

export function clearPhoto() {
  dropPhoto();
  refresh();
}

export function submitQuestion() {
  const text = (store.question || "").trim();
  if (!text && !photoFile) {
    store.fieldError = "Напишите вопрос или прикрепите фото страницы.";
    refresh();
    return;
  }
  store.fieldError = "";
  store.lesson = null;
  queue({ type: "ask", text, photo: photoFile });
}

export function submitAnswer() {
  const text = (store.answer || "").trim();
  if (!text) {
    store.fieldError = "Введите ответ.";
    refresh();
    return;
  }
  store.fieldError = "";
  store.busyLabel = "Проверяю ответ…";
  queue({ type: "answer", text });
}

export function runLessonAction(action, topic, version) {
  if (!action) return;
  store.busyLabel = "Собираю шаг…";
  const parsed = version === "" || version == null ? null : Number(version);
  queue({
    type: "action",
    action,
    topic: topic || null,
    version: Number.isInteger(parsed) ? parsed : null,
  });
}

export function pickTopic(title) {
  if (!title) return;
  const pending = (store.works?.items || []).find((item) => item.status !== "done" && (item.title === title || item.topic === title));
  if (pending) {
    store.openWork = pending;
    go("tasks");
    return;
  }
  store.lesson = null;
  store.busyLabel = "Открываю тему…";
  queue({ type: "action", action: "pick", topic: title });
}

export function openNext() {
  const title = store.progress?.next_topic;
  if (!title) return;
  pickTopic(title);
}

export function resume() {
  store.lessonMode = "training";
  store.lesson = keepTask(store.openLesson);
  store.lessonError = null;
  go("lesson");
}

export function openSubmission() {
  store.lessonMode = "submission";
  store.lesson = null;
  store.lessonError = null;
  store.pending = null;
  go("lesson");
}

export function setMode(mode) {
  if (store.lesson && (store.lesson.explanation || store.lesson.task || store.lesson.feedback)) return;
  store.lessonMode = mode === "submission" ? "submission" : "training";
  store.lessonError = null;
  refresh();
}

export async function exitLesson() {
  if ((store.answer || "").trim()) {
    const leave = await confirmDialog({
      title: "Выйти к прогрессу?",
      text: "Ответ ещё не проверен.",
      confirm: "Выйти",
      cancel: "Остаться",
    });
    if (!leave) return;
  }
  store.answer = "";
  go("map");
}

export async function checkSubmission() {
  if (store.busy) return;
  store.busy = true;
  store.busyLabel = "Смотрю, есть ли работа…";
  store.lessonError = null;
  refresh();
  try {
    if (store.preview) {
      store.lessonError = {
        message: "В демонстрационном просмотре сдача не отправляется.",
        code: "preview",
        status: 0,
      };
      return;
    }
    const result = await practice({ mode: "submission" });
    if (result?.ok && (result.task || result.explanation)) store.lesson = result;
    else {
      store.lessonError = {
        message: result?.notice || "Сервер не подтвердил сдачу.",
        code: "submission_unavailable",
        status: 409,
      };
    }
  } catch (error) {
    store.lessonError = error;
  } finally {
    store.busy = false;
    refresh();
  }
}

export function retryLesson() {
  if (!store.lastJob || store.busy || store.pending) return;
  store.lessonError = null;
  store.pending = store.lastJob;
  if (location.hash !== "#/lesson") location.hash = "#/lesson";
  else refresh();
}

// Пока задание открыто, его текст не пропадает, даже если ответ сервера пришёл без него.
function keepTask(lesson) {
  if (!lesson) return lesson;
  if (lesson.task) store.lastTask = { topic: lesson.topic || null, task: lesson.task };
  else if (lesson.awaiting_answer && store.lastTask && store.lastTask.topic === (lesson.topic || null)) {
    lesson.task = store.lastTask.task;
  } else if (!lesson.awaiting_answer) store.lastTask = null;
  return lesson;
}

async function rememberProgress() {
  try {
    store.progress = await getProgress();
    store.progressError = null;
    store.history = await getHistory();
    store.historyError = null;
    store.attempts = await getAttempts();
    store.attemptsError = null;
  } catch {
    // The lesson result stays on screen even if the refresh fails.
  }
}

export async function loadMoreAttempts() {
  const items = store.attempts?.items || [];
  if (!items.length || !store.attempts?.more || store.attemptsBusy) return;
  store.attemptsBusy = true;
  refresh();
  try {
    const next = await getAttempts(items[items.length - 1].id);
    store.attempts = { items: [...items, ...(next.items || [])], more: Boolean(next.more) };
    store.attemptsError = null;
  } catch (error) {
    store.attemptsError = error;
  } finally {
    store.attemptsBusy = false;
    refresh();
  }
}

export async function flush() {
  if (!store.pending || store.busy) return;
  const job = store.pending;
  store.pending = null;
  store.busy = true;
  store.lessonError = null;
  if (!store.busyLabel) store.busyLabel = "Собираю разбор…";
  refresh();
  try {
    if (store.preview) {
      const sample = sampleLesson();
      sample.notice = "Демонстрационный разбор. Сервер не вызывался, ответ не проверяется.";
      store.lesson = sample;
      store.answer = "";
      return;
    }
    const previous = store.lesson;
    let lesson;
    if (job.type === "ask" && job.photo) {
      store.busyLabel = "Отправляю фото…";
      refresh();
      lesson = await sendPhoto(job.photo, job.text || "");
    } else if (job.type === "action") {
      lesson = await practice({
        mode: "training",
        action: job.action,
        topic: job.topic,
        version: job.version,
      });
    } else {
      lesson = await practice({ mode: "training", text: job.text });
    }
    if (previous && lesson && lesson.topic && lesson.topic === previous.topic) {
      lesson.explanation = lesson.explanation || previous.explanation;
      lesson.example = lesson.example || previous.example;
    }
    keepTask(lesson);
    store.lesson = lesson;
    store.openLesson = lesson;
    store.answer = "";
    store.fieldError = "";
    if (job.type === "ask") {
      store.question = "";
      dropPhoto();
    }
    await rememberProgress();
  } catch (error) {
    store.lessonError = error;
  } finally {
    store.busy = false;
    store.busyLabel = "";
    refresh();
  }
}
