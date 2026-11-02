import { answerWork, getHistory, getProgress, getStudentWorks, practice, sendPhoto } from "./api.js";
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

function mast(name, klass) {
  const unread = Number(store.notices?.unread) || 0;
  return `<header class="mast">
    ${brand()}
    <span class="class-mark">${esc(klass || "без класса")}</span>
    <button class="bell" type="button" data-act="notices" aria-label="Уведомления">${icon("bell")}${unread ? `<i class="dot"></i>` : ""}</button>
  </header>
  <p class="quiet">${esc(name || "Ученик")}</p>`;
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

export function renderHome() {
  const progress = store.progress;
  if (store.loading && !progress) return skeleton();
  if (!progress) return errorBlock(store.progressError?.message, "retry");
  const stats = summarize(progress.topics);
  const name = progress.display_name || store.displayName || "Ученик";
  const klass = progress.class_title || "";
  const open = inProgress(store.openLesson) ? store.openLesson : null;
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
  const next = progress.next_topic
    ? `<button class="line" type="button" data-act="open-next"><span><b>${esc(progress.next_step || progress.next_topic)}</b><small>Следующий шаг</small></span>${icon("chevron")}</button>`
    : `<p class="quiet">Следующий шаг появится после первой проверки.</p>`;
  return `<div class="stack">
    ${mast(name, klass)}
    <section class="focus">
      <p class="quiet">${esc(klass ? `Математика, ${klass}` : "Математика")}</p>
      <h1 id="page-title" tabindex="-1">Что будем разбирать сегодня?</h1>
      <div class="pulse-line" aria-hidden="true"></div>
      <div class="focus-actions">
        <button class="btn btn-primary" type="button" data-act="toggle-ask">Задать вопрос</button>
        <label class="btn btn-lime file">Отправить фотографию<input id="photo" type="file" accept="image/*" aria-label="Отправить фотографию"></label>
      </div>
      ${composer}
    </section>
    ${open ? `<button class="line" type="button" data-act="resume"><span><b>${esc(open.topic)}</b><small>Продолжить занятие</small></span></button>` : ""}
    <section>
      ${stats.known
        ? `<p class="figure">${stats.known}</p><p class="figure-label">${plural(stats.known, "тема с попытками", "темы с попытками", "тем с попытками")}</p>`
        : `<p class="figure">0</p><p class="figure-label">Проверенных ответов пока нет. Начни с вопроса выше.</p>`}
    </section>
    <section class="sheet-block">${next}</section>
    <section class="sheet-block">${(progress.topics || []).map(topicLine).join("") || `<p class="quiet">Темы появятся, когда программа класса будет в базе.</p>`}</section>
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
    return `<section><h2 class="section-title">${title}</h2><div class="sheet-block">${items.map(topicLine).join("")}</div></section>`;
  }).join("");
  const fresh = (progress.topics || []).filter((topic) => !topic.status);
  const history = (store.history?.sessions || []).slice(0, 3);
  return `<div class="stack">
    ${mast(progress.display_name, progress.class_title)}
    <div>
      <h1 id="page-title" tabindex="-1">Карта знаний</h1>
      <p class="quiet">Усвоено ${stats.mastered}. Нужна практика ${stats.practice}. Повторить ${stats.repeat}. Статус считается по ответам.</p>
    </div>
    ${stats.known ? "" : `<p class="quiet">Пока нет проверенных ответов. Задай вопрос на главной, и тема получит статус.</p>`}
    ${blocks || ""}
    ${fresh.length ? `<section class="sheet-block">${fresh.map(topicLine).join("")}</section>` : ""}
    <section>
      <div class="row-between"><h2>История попыток</h2><button class="text-btn" type="button" data-act="nav" data-screen="history">Вся история</button></div>
      ${store.historyError ? `<p class="field-error">${esc(store.historyError.message)}</p>` : ""}
      ${history.length ? history.map(historyRow).join("") : `<p class="quiet">Проверенных занятий пока нет.</p>`}
    </section>
    ${progress.next_topic ? `<section class="card card-next">
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
  const done = Number(progress?.completed_tasks) || 0;
  return `<div class="stack">
    ${mast(name, progress?.class_title)}
    <section class="profile-card">
      <span class="avatar avatar-lg" aria-hidden="true">${esc(initials(name))}</span>
      <h1 id="page-title" tabindex="-1">${esc(name)}</h1>
      <p class="quiet">${esc(progress?.class_title ? `Класс ${progress.class_title}, математика` : "Математика")}</p>
      <p>Серия ${Number(progress?.streak_days) || 0} дн. Проверено ${done} ${plural(done, "задание", "задания", "заданий")}.</p>
      <p>Учитель видит статус темы, а не текст вопроса.</p>
      <button class="btn btn-primary" type="button" data-act="nav" data-screen="history">История занятий</button>
      <button class="btn btn-ghost" type="button" data-act="notices">Уведомления</button>
    </section>
  </div>`;
}

export function renderTasks() {
  if (store.openWork) return renderWork(store.openWork);
  if (store.worksError && !store.works) return errorBlock(store.worksError.message, "retry");
  const items = store.works?.items || [];
  if (store.preview && !items.length) {
    return `<div class="stack">${mast(store.displayName, "8Б")}<h1 id="page-title" tabindex="-1">Задания</h1>${emptyBlock("В демонстрации заданий нет", "Это не список с сервера. Открой кабинет из чата, чтобы увидеть свои работы.")}</div>`;
  }
  return `<div class="stack">
    ${mast(store.progress?.display_name || store.displayName, store.progress?.class_title)}
    <h1 id="page-title" tabindex="-1">Задания</h1>
    ${items.length ? `<section class="sheet-block">${items.map((item) => `<button class="line" type="button" data-act="open-work" data-id="${item.id}"><span><b>${esc(item.title)}</b><small>${esc(item.subject)} · ${esc(item.author)} · ${item.status === "done" ? "сделано" : "новое"}</small></span></button>`).join("")}</section>` : emptyBlock("Заданий пока нет", "Когда учитель опубликует работу, она появится здесь и в чате MAX.")}
  </div>`;
}

function renderWork(work) {
  return `<div class="stack">
    <button class="text-btn" type="button" data-act="close-work">К списку</button>
    <h1 id="page-title" tabindex="-1">${esc(work.title)}</h1>
    <p class="quiet">${esc(work.subject)} · назначил ${esc(work.author)}${work.due_at ? ` · срок ${esc(work.due_at)}` : ""}</p>
    <p>${esc(work.goal)}</p>
    ${(work.items || []).map((item) => `<section>
      <h2>Задание ${item.position}</h2>
      <p>${esc(item.prompt)}</p>
      ${item.answered ? `<p class="quiet">${item.correct ? "Верно" : "Пока не сошлось"}</p>` : `<label class="field-label" for="work-${item.id}">Ответ</label><input id="work-${item.id}" class="field" data-work-item="${item.id}" autocomplete="off">`}
    </section>`).join("")}
    ${store.fieldError ? `<p class="field-error">${esc(store.fieldError)}</p>` : ""}
    <button class="btn btn-primary" type="button" data-act="submit-work" ${disabled()}>Проверить ответы</button>
  </div>`;
}

export function renderStimul() {
  const samples = ["Как сложить дроби с разным знаменателем?", "Объясни дискриминант на коротком примере", "С чего начать геометрию?"];
  return `<div class="stack">
    ${mast(store.progress?.display_name || store.displayName, store.progress?.class_title)}
    <section class="focus">
      <h1 id="page-title" tabindex="-1">Стимул</h1>
      <div class="pulse-line" aria-hidden="true"></div>
      <p>ИИ-помощник готовится к запуску.</p>
      <p class="quiet">Сообщение сейчас никуда не отправляется и не притворяется ответом модели.</p>
    </section>
    <div class="chat">
      ${(store.stimulDraft ? `<div class="bubble me">${esc(store.stimulDraft)}</div>` : "")}
      ${store.stimulNote ? `<div class="bubble">${esc(store.stimulNote)}</div>` : ""}
    </div>
    <div class="chips">${samples.map((text) => `<button class="chip" type="button" data-act="stimul-sample" data-text="${esc(text)}">${esc(text)}</button>`).join("")}</div>
    <form id="stimul-form" class="composer">
      <input id="stimul-input" class="field" placeholder="Вопрос помощнику" value="${esc(store.stimulDraft)}" aria-label="Вопрос помощнику">
      <button class="btn btn-primary" type="submit">Отправить</button>
    </form>
  </div>`;
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
