import { approveJoin, getHistory, getLesson, getProgress, getSession, openSession, openTicket, setCsrf } from "./api.js";
import { previewRole, studentPreview, teacherPreview } from "./preview.js";
import {
  checkSubmission,
  clearPhoto,
  exitLesson,
  flush,
  openNext,
  openSubmission,
  pickTopic,
  renderStudent,
  resume,
  retryLesson,
  runLessonAction,
  setMode,
  submitAnswer,
  submitQuestion,
  takePhoto,
} from "./student.js";
import { go, refresh, store, subscribe } from "./store.js";
import {
  focusTopic,
  loadDraft,
  reloadTeacher,
  renderTeacher,
  sendAssignment,
  setAudience,
  setCount,
  setDifficulty,
  setFilter,
  showClassInfo,
  startCompose,
  toggleMaterial,
  toggleStudent,
  wizardBack,
  wizardNext,
} from "./teacher.js";
import { brand, esc, icon, skeleton } from "./ui.js";

const TITLES = {
  home: "Главная",
  lesson: "Занятие",
  map: "Моя карта",
  history: "История",
  profile: "Профиль",
  overview: "Обзор",
  class: "Карта класса",
  tasks: "Задания",
  compose: "Проверка",
  results: "Результаты",
};

let bootId = 0;
let focused = "";
let backFn = null;

function screenFromHash() {
  const raw = location.hash.startsWith("#/") ? location.hash.slice(2).split(/[?#]/)[0] : "";
  const student = ["home", "map", "history", "profile", "lesson"];
  const teacher = ["overview", "class", "tasks", "compose", "results", "profile"];
  const allowed = store.role === "teacher" ? teacher : student;
  if (allowed.includes(raw)) return raw;
  return store.role === "teacher" ? "overview" : "home";
}

function ensureHash() {
  store.screen = screenFromHash();
  const next = `#/${store.screen}`;
  if (location.hash !== next) {
    history.replaceState(null, "", `${location.pathname}${location.search}${next}`);
  }
}

async function waitForBridge() {
  if (readInitData()) return;
  for (let step = 0; step < 16; step += 1) {
    if (readInitData()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
}

function readInitData() {
  const fromApp = window.WebApp && typeof window.WebApp.initData === "string" ? window.WebApp.initData : "";
  if (fromApp) return fromApp;
  const search = new URLSearchParams(location.search).get("initData");
  if (search) return search;
  if (!location.hash || location.hash.startsWith("#/")) return "";
  return new URLSearchParams(location.hash.slice(1)).get("initData") || "";
}

function stripInit() {
  const url = new URL(location.href);
  url.searchParams.delete("initData");
  const search = url.searchParams.toString();
  history.replaceState(null, "", url.pathname + (search ? `?${search}` : ""));
}

async function settle(fn) {
  try {
    return { value: await fn(), error: null };
  } catch (error) {
    return { value: null, error };
  }
}

async function loadStudent() {
  const [progress, history, lesson] = await Promise.all([
    settle(getProgress),
    settle(getHistory),
    settle(getLesson),
  ]);
  store.progress = progress.value;
  store.progressError = progress.error;
  store.history = history.value;
  store.historyError = history.error;
  store.openLesson = lesson.value;
}

function enterPreview(role) {
  store.preview = true;
  store.role = role;
  store.booting = false;
  store.gate = null;
  store.loading = false;
  if (role === "teacher") {
    const data = teacherPreview();
    store.displayName = data.displayName;
    store.report = data.report;
    store.assignments = data.assignments;
  } else {
    const data = studentPreview();
    store.displayName = data.displayName;
    store.progress = data.progress;
    store.history = data.history;
    store.openLesson = data.openLesson;
  }
  ensureHash();
  refresh();
}

async function boot() {
  const id = ++bootId;
  store.booting = true;
  store.gate = null;
  refresh();
  const entry = document.body.dataset.entry || "auto";
  const preview = previewRole(new URLSearchParams(location.search).get("preview"), entry);
  if (preview) {
    enterPreview(preview);
    return;
  }
  try {
    await waitForBridge();
    const ticket = new URLSearchParams(location.search).get("ticket");
    if (ticket) {
      store.ticket = ticket;
      store.booting = false;
      store.gate = "ticket";
      refresh();
      return;
    }
    const initData = readInitData();
    store.fromMax = Boolean(initData);
    if (initData) {
      const opened = await openSession(initData);
      setCsrf(opened.csrf);
      stripInit();
    }
    if (id !== bootId) return;
    const me = await getSession();
    setCsrf(me.csrf);
    if (id !== bootId) return;
    store.role = me.role;
    store.displayName = me.display_name || "";
    store.preview = false;
    if (!store.fromMax && entry !== "auto" && entry !== me.role) {
      store.booting = false;
      store.gate = "mismatch";
      refresh();
      return;
    }
    store.booting = false;
    store.loading = true;
    ensureHash();
    refresh();
    if (me.role === "teacher") await reloadTeacher();
    else {
      await loadStudent();
      store.loading = false;
      refresh();
    }
    if (id !== bootId) return;
  } catch (error) {
    if (id !== bootId) return;
    store.booting = false;
    store.loading = false;
    store.gateMessage = error.message || "";
    if (error.status === 409 || (store.fromMax && error.status === 401)) {
      store.gate = "unlinked";
    } else if (error.status === 403) {
      store.gate = "forbidden";
    } else if (error.status === 401 && isTeacherEntry()) {
      store.gate = "browser";
    } else if (error.status === 401) {
      store.gate = "unlinked";
    } else {
      store.gate = "network";
    }
    refresh();
  }
}

function tabs() {
  const teacher = store.role === "teacher";
  const items = teacher
    ? [
        ["overview", "Обзор", "grid"],
        ["class", "Карта", "map"],
        ["tasks", "Задания", "list"],
        ["results", "Результаты", "check"],
        ["profile", "Профиль", "user"],
      ]
    : [
        ["home", "Главная", "home"],
        ["map", "Моя карта", "map"],
        ["history", "История", "clock"],
        ["profile", "Профиль", "user"],
      ];
  const current = store.screen === "lesson" ? "home" : store.screen === "compose" ? "tasks" : store.screen;
  return `<nav class="tabbar" aria-label="Разделы">${items.map(([id, label, glyph]) => {
    const active = current === id;
    return `<button type="button" class="tab${active ? " is-active" : ""}" data-act="nav" data-screen="${id}" ${active ? 'aria-current="page"' : ""}>${icon(glyph)}<span>${label}</span></button>`;
  }).join("")}</nav>`;
}

function sidenav() {
  if (store.role !== "teacher") return "";
  const items = [
    ["overview", "Обзор", "grid"],
    ["class", "Карта класса", "map"],
    ["tasks", "Задания", "list"],
    ["results", "Результаты", "check"],
    ["profile", "Профиль", "user"],
  ];
  const current = store.screen === "compose" ? "tasks" : store.screen;
  return `<aside class="sidenav">
    <div class="side-brand">${brand()}</div>
    <p class="side-note">Кабинет учителя</p>
    ${items.map(([id, label, glyph]) => {
      const active = current === id;
      return `<button type="button" class="side-link${active ? " is-active" : ""}" data-act="nav" data-screen="${id}" ${active ? 'aria-current="page"' : ""}>${icon(glyph)}<span>${label}</span></button>`;
    }).join("")}
  </aside>`;
}

function frame(inner) {
  return `<div class="frame">
    ${sidenav()}
    <div class="content">
      ${store.preview ? `<div class="demo-banner">Демонстрационный просмотр. Это не результаты учеников и не ответ сервера.</div>` : ""}
      <main class="page"><div class="page-inner">${inner}</div></main>
    </div>
  </div>${tabs()}`;
}

function isTeacherEntry() {
  const entry = document.body.dataset.entry || "auto";
  return entry === "teacher" || location.pathname.endsWith("/cabinet");
}

function returnToChat() {
  const name = (document.body.dataset.bot || "").trim();
  const app = window.WebApp;
  if (!name || !app || typeof app.openMaxLink !== "function") return;
  app.openMaxLink(`https://max.ru/${name}`);
}

function renderGate() {
  if (store.gate === "ticket") {
    return `<div class="gate">${brand()}
      <h1>Кабинет</h1>
      <p>Ссылка ещё действует. Нажми кнопку, чтобы войти.</p>
      <button class="btn btn-primary" type="button" data-act="use-ticket">Войти</button>
    </div>`;
  }
  if (store.gate === "mismatch") {
    const teacher = store.role === "teacher";
    return `<div class="gate">${brand()}
      <h1>${teacher ? "Это экран ученика" : "Это кабинет учителя"}</h1>
      <p>${teacher ? "Вы вошли как учитель." : "Ты вошёл как ученик. Свой прогресс — на своём экране."}</p>
      <a class="btn btn-primary" href="${teacher ? "/cabinet" : "/student"}">${teacher ? "Открыть кабинет" : "Открыть свой прогресс"}</a>
    </div>`;
  }
  if (store.gate === "unlinked") {
    return `<div class="gate">${brand()}
      <h1>Стимул</h1>
      <p>Открой приложение кнопкой из чата с ботом.</p>
      <button class="btn btn-primary" type="button" data-act="return-chat">Вернуться в чат</button>
    </div>`;
  }
  if (store.gate === "forbidden") {
    return `<div class="gate">${brand()}
      <h1>Сюда не попасть</h1>
      <p>${esc(store.gateMessage || "Этот раздел сейчас закрыт.")}</p>
      <button class="btn btn-primary" type="button" data-act="return-chat">Вернуться в чат</button>
    </div>`;
  }
  if (store.gate === "browser") {
    return `<div class="gate">${brand()}
      <h1>Кабинет</h1>
      <p>Открой кабинет кнопкой из чата с ботом.</p>
      <button class="btn btn-primary" type="button" data-act="return-chat">Вернуться в чат</button>
    </div>`;
  }
  return `<div class="gate">${brand()}
    <h1>Стимул</h1>
    <p>${esc(store.gateMessage)}</p>
    <button class="btn btn-primary" type="button" data-act="retry-auth">Повторить</button>
  </div>`;
}

function pageInner() {
  if (store.role === "teacher") {
    if (store.loading && !store.report) return skeleton();
    return renderTeacher();
  }
  if (store.loading && !store.progress && store.screen !== "lesson") return skeleton();
  return renderStudent();
}

function focusTitle() {
  if (focused !== store.screen) {
    focused = store.screen;
    if (!store.fieldError) document.querySelector("#page-title")?.focus({ preventScroll: true });
  }
  if (store.fieldError) document.querySelector("#question, #answer, #goal")?.focus();
}

function syncCloseConfirm(dirty) {
  const app = window.WebApp;
  if (!app) return;
  try {
    if (dirty && typeof app.enableClosingConfirmation === "function") app.enableClosingConfirmation();
    else if (typeof app.disableClosingConfirmation === "function") app.disableClosingConfirmation();
  } catch {
    // The bridge method is absent outside MAX.
  }
}

function syncBack() {
  const back = window.WebApp && window.WebApp.BackButton;
  if (!back || typeof back.show !== "function") return;
  if (backFn && typeof back.offClick === "function") back.offClick(backFn);
  const nested = store.screen === "lesson" || store.screen === "compose";
  backFn = () => {
    if (store.screen === "compose" && store.wizard && store.wizard.step > 1) wizardBack();
    else if (store.screen === "lesson") exitLesson();
    else go(store.role === "teacher" ? "overview" : "home");
  };
  if (nested) {
    back.show();
    if (typeof back.onClick === "function") back.onClick(backFn);
  } else if (typeof back.hide === "function") back.hide();
}

function paint() {
  document.body.classList.toggle("role-teacher", store.role === "teacher");
  document.body.classList.toggle("role-student", store.role === "student");
  const app = document.querySelector("#app");
  if (!app) return;
  if (store.booting) {
    app.innerHTML = `<div class="gate">${brand()}<p class="hello">Открываю Стимул…</p>${skeleton()}</div>`;
    return;
  }
  if (store.gate) {
    app.innerHTML = renderGate();
    document.title = "Стимул";
    return;
  }
  app.innerHTML = frame(pageInner());
  syncBack();
  focusTitle();
  document.title = `Стимул — ${TITLES[store.screen] || "Стимул"}`;
}

async function onAction(act, button) {
  if (act === "nav") {
    go(button.dataset.screen);
    return;
  }
  if (act === "approve-join") {
    await approveJoin(button.dataset.id);
    if (store.role === "teacher") await reloadTeacher();
    return;
  }
  if (act === "use-ticket") {
    const ticket = store.ticket;
    if (!ticket) return;
    try {
      const opened = await openTicket(ticket);
      setCsrf(opened.csrf);
      store.ticket = "";
      location.replace(location.pathname);
    } catch (error) {
      store.gate = "auth";
      store.gateMessage = error.message;
      refresh();
    }
    return;
  }
  if (act === "retry-auth") {
    await boot();
    return;
  }
  if (act === "return-chat") {
    returnToChat();
    return;
  }
  if (act === "retry") {
    if (store.role === "teacher") await reloadTeacher();
    else {
      store.loading = true;
      refresh();
      await loadStudent();
      store.loading = false;
      refresh();
    }
    return;
  }
  if (store.busy && !["exit-lesson", "wizard-back"].includes(act)) return;
  if (act === "send-question") submitQuestion();
  else if (act === "clear-photo") clearPhoto();
  else if (act === "open-submission") openSubmission();
  else if (act === "resume") resume();
  else if (act === "open-next") openNext();
  else if (act === "pick") pickTopic(button.dataset.topic);
  else if (act === "lesson-action") {
    runLessonAction(button.dataset.action, button.dataset.topic, button.dataset.version);
  }
  else if (act === "mode") setMode(button.dataset.mode);
  else if (act === "check-submission") await checkSubmission();
  else if (act === "retry-lesson") retryLesson();
  else if (act === "exit-lesson") await exitLesson();
  else if (act === "class-info") await showClassInfo();
  else if (act === "compose") startCompose(button.dataset.topic || "");
  else if (act === "focus-topic") focusTopic(button.dataset.topic);
  else if (act === "filter-status") setFilter(button.dataset.status);
  else if (act === "wizard-next") wizardNext();
  else if (act === "wizard-back") wizardBack();
  else if (act === "count") setCount(button.dataset.value);
  else if (act === "difficulty") setDifficulty(button.dataset.value);
  else if (act === "audience") setAudience(button.dataset.value);
  else if (act === "toggle-student") toggleStudent(button.dataset.name);
  else if (act === "redraft") await loadDraft();
  else if (act === "send-assignment") await sendAssignment();
}

function bind() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-act]");
    if (!button || button.disabled) return;
    onAction(button.dataset.act, button);
  });
  document.addEventListener("submit", (event) => {
    event.preventDefault();
    if (event.target.id === "answer-form") submitAnswer();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && event.target.id === "question") {
      event.preventDefault();
      submitQuestion();
    }
  });
  document.addEventListener("input", (event) => {
    const target = event.target;
    if (target.id === "question") store.question = target.value;
    if (target.id === "answer") {
      store.answer = target.value;
      syncCloseConfirm(Boolean(target.value.trim()));
    }
    if (target.id === "goal" && store.wizard) store.wizard.goal = target.value;
    if (target.dataset.prompt != null && store.wizard?.draft?.items) {
      const item = store.wizard.draft.items[Number(target.dataset.prompt)];
      if (item) item.prompt = target.value;
    }
  });
  document.addEventListener("change", (event) => {
    const target = event.target;
    if (target.id === "question") store.question = target.value;
    if (target.id === "answer") store.answer = target.value;
    if (target.id === "photo") {
      takePhoto(target.files && target.files[0]);
      target.value = "";
    }
    if (target.id === "topic-filter") {
      store.filters = { ...store.filters, topic: target.value };
      refresh();
    }
    if (target.id === "topic" && store.wizard) store.wizard.topic = target.value;
    if (target.id === "material") toggleMaterial(target.checked);
  });
  window.addEventListener("hashchange", () => {
    if (store.booting || store.gate) return;
    store.screen = screenFromHash();
    store.fieldError = "";
    const next = `#/${store.screen}`;
    if (location.hash !== next) {
      history.replaceState(null, "", `${location.pathname}${location.search}${next}`);
    }
    refresh();
  });
}

subscribe(() => {
  paint();
  queueMicrotask(() => {
    if (store.pending && !store.busy) flush();
  });
});

bind();
boot();
