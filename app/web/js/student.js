import { getHistory, getProgress, practice, sendPhoto } from "./api.js";
import { sampleLesson } from "./preview.js";
import { go, refresh, store } from "./store.js";
import {
  brand,
  confirmDialog,
  emptyBlock,
  errorBlock,
  esc,
  icon,
  initials,
  nl,
  pill,
  plural,
  ring,
  track,
} from "./ui.js";

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

function hello(name) {
  const clean = String(name || "").trim();
  if (!clean) return "Привет";
  return `Привет, <strong>${esc(clean)}</strong>`;
}

function topbar(name) {
  return `<div class="top">
    <div>
      ${brand()}
      <p class="hello">${hello(name)}</p>
    </div>
    <button class="avatar" type="button" data-act="nav" data-screen="profile" aria-label="Профиль">${esc(initials(name))}</button>
  </div>`;
}

function topicButton(topic) {
  const percent = topic.correct_percent == null ? "" : `${topic.correct_percent}%`;
  return `<button class="topic-row" type="button" data-act="pick" data-topic="${esc(topic.title)}" ${disabled()}>
    <span>
      <strong>${esc(topic.title)}</strong>
      ${percent ? `<span class="hint">${esc(percent)}</span>` : ""}
    </span>
    ${pill(topic.status)}
  </button>`;
}

export function renderHome() {
  const progress = store.progress;
  if (store.loading && !progress) return `${topbar(store.displayName)}<div class="stack" id="page-title" tabindex="-1"></div>`;
  if (!progress) return errorBlock(store.progressError?.message, "retry");
  const stats = summarize(progress.topics);
  const recent = recentTopics();
  const open = inProgress(store.openLesson) ? store.openLesson : null;
  const photo = store.photoURL
    ? `<div class="attach"><img class="thumb" alt="" src="${esc(store.photoURL)}"><span>Фото прикреплено</span><button class="text-btn" type="button" data-act="clear-photo">Убрать</button></div>`
    : "";
  return `<div class="stack">
    ${topbar(progress.display_name || store.displayName)}
    <section class="card card-ask">
      <h1 id="page-title" tabindex="-1">Что разберём сегодня?</h1>
      <textarea id="question" class="area" placeholder="Например: не понимаю, как сложить дроби" aria-label="Вопрос" ${disabled()}>${esc(store.question)}</textarea>
      ${photo}
      ${store.fieldError ? `<p class="field-error">${esc(store.fieldError)}</p>` : ""}
      <div class="ask-actions">
        <label class="btn btn-icon file">
          ${icon("image")}
          <span class="sr">Прикрепить фото</span>
          <input id="photo" type="file" accept="image/*" aria-label="Прикрепить фото">
        </label>
        <button class="btn btn-primary" type="button" data-act="send-question" ${disabled()}>${icon("send")}<span>Отправить</span></button>
      </div>
      <p class="hint">Напиши вопрос своими словами. Если есть фото, подпиши тему.</p>
      <p class="hint">Это тренировка: текст вопроса учителю не уходит.</p>
      <button class="text-btn" type="button" data-act="open-submission">Сдать работу учителя</button>
    </section>
    <div class="pair">
      <section class="card stat">
        <p class="kicker">Прогресс</p>
        <div class="stat-line">
          ${ring(stats.avg)}
          <div>
            <strong>${stats.known ? "Доля верных" : "Пока пусто"}</strong>
            <p class="hint">${stats.known ? "По темам, где уже есть попытки." : "Статус появится после проверки."}</p>
          </div>
        </div>
      </section>
      <section class="card stat">
        <p class="kicker">Сделано</p>
        <p class="stat-num">${Number(progress.completed_tasks) || 0}</p>
        <p class="hint">${plural(progress.completed_tasks, "задание", "задания", "заданий")} · серия ${Number(progress.streak_days) || 0} дн.</p>
      </section>
    </div>
    ${open ? `<button class="card card-link" type="button" data-act="resume">
      <span><span class="kicker">Продолжить обучение</span><strong>${esc(open.topic)}</strong></span>
      ${icon("chevron")}
    </button>` : ""}
    ${recent.items.length ? `<section class="stack tight">
      <h2 class="section-title">${recent.fromHistory ? "Недавние темы" : "Темы с попытками"}</h2>
      ${recent.items.map(topicButton).join("")}
    </section>` : ""}
    ${progress.next_topic ? `<section class="card card-next">
      <p class="kicker">Твой следующий шаг</p>
      <h2>${esc(progress.next_step || progress.next_topic)}</h2>
      <button class="btn btn-dark" type="button" data-act="open-next" ${disabled()}>Разобрать</button>
    </section>` : ""}
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
        <p>В сдаче принимаю ответы на выданные задания и не разбираю новую страницу. Личный вопрос сам не отправляю.</p>
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
  const answerForm = lesson?.awaiting_answer && !lesson.feedback
    ? `<form id="answer-form" class="stack tight">
        <label class="field-label" for="answer">Твой ответ</label>
        <input id="answer" class="field" value="${esc(store.answer)}" autocomplete="off" autocorrect="off" spellcheck="false" enterkeyhint="send" ${disabled()}>
        ${store.fieldError ? `<p class="field-error">${esc(store.fieldError)}</p>` : ""}
        <button class="btn btn-primary" type="submit" ${disabled()}>Проверить</button>
      </form>`
    : "";
  return `<div class="stack">
    <div class="top compact">
      <button class="text-btn back" type="button" data-act="exit-lesson">${icon("chevron")}<span>К прогрессу</span></button>
    </div>
    ${modeChip(mode)}
    ${stages(lesson)}
    <h1 id="page-title" tabindex="-1">${esc(lesson?.topic || "Занятие")}</h1>
    <p class="hint">${esc(store.progress?.class_title ? `Математика · ${store.progress.class_title}` : "Математика · 8 класс")}</p>
    ${store.busy ? `<p class="statusline" role="status">${esc(store.busyLabel || "Секунду…")}</p>` : ""}
    ${lessonBanner(store.lessonError)}
    ${switcher}
    ${submission}
    ${note}
    ${photoNote}
    ${lesson?.explanation ? `<section class="card"><h2>Простыми словами</h2><p>${nl(lesson.explanation)}</p></section>` : ""}
    ${lesson?.example ? `<section class="card card-flat"><h2>Пример</h2><p>${nl(lesson.example)}</p></section>` : ""}
    ${lesson?.task ? `<section class="card"><h2>Задание</h2><p>${nl(lesson.task)}</p>${answerForm}</section>` : ""}
    ${lesson?.feedback ? `<section class="card feedback ${lesson.correct ? "is-ok" : "is-bad"}" role="status">
      <h2>${lesson.correct ? "Верно" : "Есть ошибка"}</h2>
      <p>${nl(lesson.feedback)}</p>
      ${lesson.given ? `<p class="hint">Твой ответ: ${esc(lesson.given)}</p>` : ""}
      ${lesson.status_line ? `<p>${nl(lesson.status_line)}</p>` : ""}
    </section>` : ""}
    ${actionButtons(lesson?.actions)}
    ${pickChips(lesson?.actions)}
    ${lesson?.notice && !(lesson.actions || []).some((item) => item.action === "pick") ? `<div class="chips">${(store.progress?.topics || []).map((topic) => `<button class="chip" type="button" data-act="pick" data-topic="${esc(topic.title)}" ${disabled()}>${esc(topic.title)}</button>`).join("")}</div>` : ""}
    ${idleHelp}
    ${lesson?.topic && !lesson.feedback && !(lesson.actions || []).some((item) => item.action === "more_example") ? `<button class="btn btn-ghost" type="button" data-act="lesson-action" data-action="more_example" ${disabled()}>Объясни иначе</button>` : ""}
    <button class="btn btn-ghost" type="button" data-act="exit-lesson">К моему прогрессу</button>
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
  const blocks = groups.map(([status, title]) => {
    const items = (progress.topics || []).filter((topic) => topic.status === status);
    if (!items.length) return "";
    return `<section class="stack tight"><h2 class="section-title">${title}</h2>${items.map((topic) => `<article class="card topic-card">
      <div class="row-between"><strong>${esc(topic.title)}</strong>${pill(topic.status)}</div>
      ${track(topic.correct_percent, topic.status)}
      <p class="hint">${topic.correct_percent == null ? "Нет доли верных" : `${topic.correct_percent}% верных ответов`}</p>
      <button class="btn btn-ghost" type="button" data-act="pick" data-topic="${esc(topic.title)}">Разобрать</button>
    </article>`).join("")}</section>`;
  }).join("");
  const fresh = (progress.topics || []).filter((topic) => !topic.status);
  const history = (store.history?.sessions || []).slice(0, 3);
  return `<div class="stack">
    ${topbar(progress.display_name)}
    <h1 id="page-title" tabindex="-1">Моя карта</h1>
    <section class="card">
      <div class="stat-line">
        ${ring(stats.avg)}
        <div>
          <strong>${stats.known ? `${stats.known} ${plural(stats.known, "тема с попытками", "темы с попытками", "тем с попытками")}` : "Попыток ещё нет"}</strong>
          <p class="hint">Усвоено ${stats.mastered} · практика ${stats.practice} · повтор ${stats.repeat}. Статус считается по ответам, не по времени в приложении.</p>
        </div>
      </div>
    </section>
    ${blocks || emptyBlock("Тем с попытками нет", "Задай вопрос на главной — после проверки тема появится здесь.")}
    ${fresh.length ? `<section class="stack tight"><h2 class="section-title">Ещё не пробовал</h2><div class="chips">${fresh.map((topic) => `<button class="chip" type="button" data-act="pick" data-topic="${esc(topic.title)}">${esc(topic.title)}</button>`).join("")}</div></section>` : ""}
    <section class="stack tight">
      <div class="row-between"><h2 class="section-title">История</h2><button class="text-btn" type="button" data-act="nav" data-screen="history">Вся история</button></div>
      ${store.historyError ? `<p class="field-error">${esc(store.historyError.message)}</p>` : ""}
      ${history.length ? history.map(historyRow).join("") : `<p class="hint">Проверенных занятий пока нет.</p>`}
    </section>
    ${progress.next_topic ? `<section class="card card-next">
      <p class="kicker">Следующий шаг</p>
      <h2>${esc(progress.next_step || progress.next_topic)}</h2>
      <button class="btn btn-dark" type="button" data-act="open-next">Разобрать</button>
    </section>` : ""}
  </div>`;
}

function historyRow(item) {
  const when = formatWhen(item.created_at);
  const mode = item.mode === "submission" ? "сдача" : "тренировка";
  const result = item.answered ? `${item.correct_count} из ${item.answered} верно` : "без проверки";
  return `<article class="card card-flat">
    <div class="row-between"><strong>${esc(item.topic || "Тема не выбрана")}</strong><span class="hint">${esc(when)}</span></div>
    <p class="hint">${esc(mode)} · ${esc(result)}</p>
  </article>`;
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
  return `<div class="stack">
    ${topbar(store.progress?.display_name || store.displayName)}
    <h1 id="page-title" tabindex="-1">История</h1>
    <p class="hint">Занятия и проверки. Текст личного вопроса здесь не показываю.</p>
    ${sessions.length ? sessions.map(historyRow).join("") : emptyBlock("Пока пусто", "Когда проверишь первое задание, занятие появится в этом списке.")}
  </div>`;
}

export function renderProfile() {
  const progress = store.progress;
  if (!progress && store.progressError) return errorBlock(store.progressError.message, "retry");
  const name = progress?.display_name || store.displayName || "Ученик";
  return `<div class="stack">
    ${topbar(name)}
    <section class="card profile-card">
      <span class="avatar avatar-lg" aria-hidden="true">${esc(initials(name))}</span>
      <h1 id="page-title" tabindex="-1">${esc(name)}</h1>
      <p class="hint">${esc(progress?.class_title ? `Класс ${progress.class_title} · математика` : "Математика")}</p>
      <p>Серия ${Number(progress?.streak_days) || 0} дн. · ${Number(progress?.completed_tasks) || 0} ${plural(progress?.completed_tasks, "задание", "задания", "заданий")}.</p>
      <p>Тренировка остаётся у тебя. Учитель видит статус темы, а не текст вопроса.</p>
      <button class="btn btn-primary" type="button" data-act="nav" data-screen="map">Открыть карту</button>
    </section>
  </div>`;
}

export function renderStudent() {
  if (store.screen === "lesson") return renderLesson();
  if (store.screen === "map") return renderMap();
  if (store.screen === "history") return renderHistory();
  if (store.screen === "profile") return renderProfile();
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
  store.lesson = store.openLesson;
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

async function rememberProgress() {
  try {
    store.progress = await getProgress();
    store.progressError = null;
    store.history = await getHistory();
    store.historyError = null;
  } catch {
    // The lesson result stays on screen even if the refresh fails.
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
