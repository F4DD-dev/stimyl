import { approveJoin, deleteChat, getAttempts, getHistory, getLesson, getNotices, getProgress, getSession, getStudentWorks, joinClass, openSession, openTicket, pinChat, readNotice, renameMe, setCsrf } from "./api.js?v=8";
import { previewRole, studentPreview, teacherPreview } from "./preview.js?v=10";
import { applyTheme, setThemePref, themePref } from "./theme.js?v=1";
import {
  checkSubmission,
  clearPhoto,
  exitLesson,
  flush,
  loadMoreAttempts,
  openNext,
  openStudentChat,
  openSubmission,
  pickTopic,
  renderStudent,
  showStudentChats,
  startStudentChat,
  submitChat,
  submitWork,
  resume,
  retryLesson,
  runLessonAction,
  setMode,
  submitAnswer,
  submitQuestion,
  takePhoto,
} from "./student.js?v=17";
import { go, refresh, store, subscribe } from "./store.js?v=5";
import { clearChatPhoto, loadChats, newChat, openChat, takeChatPhoto } from "./chat.js?v=5";
import {
  addMaterial,
  autosaveDraft,
  clearStudents,
  copyInvite,
  delItem,
  focusStudent,
  focusTopic,
  loadDraft,
  loadMaterials,
  loadProgram,
  programCancel,
  programNewSubject,
  programNewTopic,
  programSaveSubject,
  programSaveTopic,
  programSubject,
  regenItem,
  reloadQuiet,
  reloadTeacher,
  removeMaterial,
  renderTeacher,
  openResult,
  resetNextTopic,
  resourceFilePicked,
  resourceLinkAdd,
  resourceLinkCancel,
  resourceLinkToggle,
  resourceRemove,
  reviewDraft,
  saveDraft,
  saveNextTopic,
  selectAllStudents,
  sendAssignment,
  sendDraftNow,
  sendStimul,
  setAudience,
  setCount,
  setDifficulty,
  setFilter,
  setWizardSubject,
  showClassInfo,
  startCompose,
  studentRowsHTML,
  scheduleAutosave,
  toggleGroupChat,
  toggleMaterial,
  toggleStudent,
  wizardBack,
  wizardExit,
  wizardGoto,
  wizardNext,
  writeOwn,
} from "./teacher.js?v=18";
import { acceptOne, appoint, changePerson, loadManage, rejectOne } from "./manage.js?v=13";
import { brand, confirmDialog, esc, icon, mark, skeleton, toast } from "./ui.js?v=5";

const TITLES = {
  home: "Главная",
  lesson: "Занятие",
  map: "Темы",
  history: "История",
  profile: "Профиль",
  overview: "Обзор",
  class: "Класс",
  tasks: "Задания",
  compose: "Проверка",
  results: "Результаты",
  stimul: "Стимул",
  manage: "Управление классом",
};

let bootId = 0;
let focused = "";
let backFn = null;
let fabMounted = false;

function mountSplash() {
  if (document.getElementById("splash") || document.getElementById("app")?.dataset.splashOff === "1") return;
  const el = document.createElement("div");
  el.id = "splash";
  el.setAttribute("aria-hidden", "true");
  el.innerHTML = `<div class="splash__stage">
    <div class="splash__logo">${mark(true)}</div>
    <div class="splash__word"><strong>Стимул</strong><span>помощник по учёбе</span></div>
  </div>`;
  document.body.appendChild(el);
  document.body.classList.add("boot-anim");
  window.setTimeout(() => el.classList.add("is-done"), 1150);
  window.setTimeout(() => {
    el.remove();
    window.setTimeout(() => document.body.classList.remove("boot-anim"), 900);
  }, 1650);
}

function ensureAssistant() {
  if (fabMounted || !store.role || store.gate || store.booting) return;
  fabMounted = true;
  const el = document.createElement("button");
  el.type = "button";
  el.className = "ai-fab";
  el.dataset.act = "nav";
  el.dataset.screen = "stimul";
  el.setAttribute("aria-label", "Открыть Стимула");
  const teacher = store.role === "teacher";
  const tip = teacher
    ? "Спросите Стимула — соберёт проверку или расскажет про класс"
    : "Задайте вопрос — объясню тему и дам практику";
  let seen = false;
  try {
    seen = sessionStorage.getItem("stimul_ai_tip") === "1";
  } catch { /* приватный режим — подсказка просто не запомнится */ }
  el.innerHTML = `${mark()}${seen ? "" : `<span class="ai-fab__tip">${esc(tip)}</span>`}`;
  if (!seen) {
    try {
      sessionStorage.setItem("stimul_ai_tip", "1");
    } catch { /* ignore */ }
    window.setTimeout(() => el.classList.remove("has-tip"), 8000);
    el.classList.add("has-tip");
  }
  document.body.appendChild(el);
}

function screenFromHash() {
  const raw = location.hash.startsWith("#/") ? location.hash.slice(2).split(/[?#]/)[0] : "";
  const student = ["home", "map", "stimul", "tasks", "profile", "lesson", "history"];
  const teacher = ["overview", "class", "tasks", "stimul", "profile", "compose", "results", "manage"];
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

function hashParams() {
  const raw = location.hash.startsWith("#") ? location.hash.slice(1) : "";
  if (!raw || raw.startsWith("/")) return new URLSearchParams();
  return new URLSearchParams(raw);
}

function readStartParam() {
  const unsafe = window.WebApp && window.WebApp.initDataUnsafe;
  if (unsafe && typeof unsafe === "object") {
    const value = unsafe.start_param || unsafe.startParam;
    if (typeof value === "string" && value) return value;
  }
  const data = readInitData();
  if (data) {
    const fromData = new URLSearchParams(data).get("start_param") || "";
    if (fromData) return fromData;
  }
  return hashParams().get("WebAppStartParam") || new URLSearchParams(location.search).get("WebAppStartParam") || "";
}

async function waitForBridge() {
  for (let step = 0; step < 40; step += 1) {
    if (readInitData()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
}

function readInitData() {
  const fromHash = hashParams().get("WebAppData") || "";
  if (fromHash) return fromHash;
  const fromApp = window.WebApp && typeof window.WebApp.initData === "string" ? window.WebApp.initData : "";
  if (fromApp) return fromApp;
  const search = new URLSearchParams(location.search);
  const fromSearch = search.get("WebAppData") || search.get("initData") || "";
  if (fromSearch) return fromSearch;
  try {
    return sessionStorage.getItem("WebAppData") || "";
  } catch {
    return "";
  }
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
  const [progress, history, lesson, works, notices, attempts] = await Promise.all([
    settle(getProgress),
    settle(getHistory),
    settle(getLesson),
    settle(getStudentWorks),
    settle(getNotices),
    settle(getAttempts),
  ]);
  store.progress = progress.value;
  store.progressError = progress.error;
  store.history = history.value;
  store.historyError = history.error;
  store.attempts = attempts.value;
  store.attemptsError = attempts.error;
  store.openLesson = lesson.value;
  store.works = works.value;
  store.worksError = works.error;
  store.notices = notices.value || { unread: 0, items: [] };
}

function enterPreview(role) {
  store.preview = true;
  store.role = role;
  store.booting = false;
  store.gate = null;
  store.loading = false;
  store.notices = { unread: 0, items: [] };
  store.works = { items: [] };
  store.canManage = false;
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
  if (store.screen === "manage") loadManage();
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
      const opened = await openSession(initData, readStartParam());
      setCsrf(opened.csrf);
      stripInit();
    }
    if (id !== bootId) return;
    const me = await getSession();
    setCsrf(me.csrf);
    if (id !== bootId) return;
    store.role = me.role;
    store.displayName = me.display_name || "";
    store.nameChanged = Boolean(me.name_changed);
    store.canManage = Boolean(me.can_manage_school);
    store.classTitle = me.class_title || "";
    store.schoolTitle = me.school_title || "";
    store.applicationStatus = me.application_status || "";
    store.classHasTeacher = Boolean(me.class_has_teacher);
    store.preview = false;
    if (me.status === "pending") {
      store.booting = false;
      store.gate = "waiting";
      refresh();
      return;
    }
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
      if (
        !store.preview &&
        store.progress &&
        !store.progress.class_title &&
        me.status === "active"
      ) {
        store.gate = "invite";
        refresh();
      }
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
        ["class", "Класс", "map"],
        ["stimul", "Стимул", "core"],
        ["tasks", "Задания", "list"],
        ["profile", "Профиль", "user"],
      ]
    : [
        ["home", "Обзор", "grid"],
        ["map", "Темы", "map"],
        ["stimul", "Стимул", "core"],
        ["tasks", "Задания", "list"],
        ["profile", "Профиль", "user"],
      ];
  const current = store.screen === "lesson" ? "home" : store.screen === "compose" || store.screen === "results" ? "tasks" : store.screen === "manage" || store.screen === "history" ? "profile" : store.screen;
  return `<nav class="tabbar" aria-label="Основная навигация">${items.map(([id, label, glyph]) => {
    const active = current === id;
    const glyphHtml = glyph === "core" ? mark() : icon(glyph);
    return `<button type="button" class="tab${active ? " is-active" : ""}" data-act="nav" data-screen="${id}" ${active ? 'aria-current="page"' : ""}><span class="nav-glyph">${glyphHtml}</span><span>${label}</span></button>`;
  }).join("")}</nav>`;
}

function sidenav() {
  const teacher = store.role === "teacher";
  const items = teacher
    ? [
        ["overview", "Обзор", "grid"],
        ["class", "Класс", "map"],
        ["stimul", "Стимул", "core"],
        ["tasks", "Задания", "list"],
        ["profile", "Профиль", "user"],
      ]
    : [
        ["home", "Обзор", "grid"],
        ["map", "Темы", "map"],
        ["stimul", "Стимул", "core"],
        ["tasks", "Задания", "list"],
        ["profile", "Профиль", "user"],
      ];
  const current = store.screen === "lesson" ? "home" : store.screen === "compose" || store.screen === "results" ? "tasks" : store.screen === "manage" || store.screen === "history" ? "profile" : store.screen;
  return `<aside class="sidenav">
    <div class="side-brand">${brand({ home: true })}</div>
    <p class="side-note">${teacher ? "Кабинет учителя" : "Кабинет ученика"}</p>
    ${items.map(([id, label, glyph]) => {
      const active = current === id;
      const badge = glyph === "core" ? mark() : icon(glyph);
      return `<button type="button" class="side-link${active ? " is-active" : ""}" data-act="nav" data-screen="${id}" ${active ? 'aria-current="page"' : ""}>${badge}<span>${label}</span></button>`;
    }).join("")}
  </aside>`;
}

function askName(current) {
  const dialog = document.querySelector("#dialog");
  if (!dialog) return Promise.resolve("");
  dialog.innerHTML = `<h2>Новое имя</h2><p>Сменить можно один раз. Так имя сохранится в кабинете и в классе.</p><label class="field-label" for="rename-input">Имя</label><input id="rename-input" class="field" maxlength="80" value="${esc(current)}" autocomplete="name"><div class="dialog-actions"><button type="button" class="btn btn-ghost" data-cancel>Отмена</button><button type="button" class="btn btn-primary" data-ok>Сохранить</button></div>`;
  if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
  const input = dialog.querySelector("#rename-input");
  input?.focus();
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      if (dialog.open && typeof dialog.close === "function") dialog.close();
      resolve(value);
    };
    dialog.querySelector("[data-ok]")?.addEventListener("click", () => finish(input?.value.trim() || ""));
    dialog.querySelector("[data-cancel]")?.addEventListener("click", () => finish(""));
    dialog.addEventListener("close", () => finish(""), { once: true });
    input?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        finish(input.value.trim());
      }
    });
  });
}

async function renameProfile() {
  if (store.preview) {
    await confirmDialog({
      title: "Демонстрация",
      text: "В просмотре имя не записывается.",
      confirm: "Понятно",
    });
    return;
  }
  if (store.nameChanged) {
    await confirmDialog({
      title: "Имя уже изменено",
      text: "Сменить имя можно только один раз.",
      confirm: "Понятно",
    });
    return;
  }
  const next = await askName(store.displayName || "");
  if (!next) return;
  store.busy = true;
  try {
    const saved = await renameMe(next);
    store.displayName = saved.display_name || next;
    store.nameChanged = true;
    if (store.progress) store.progress = { ...store.progress, display_name: store.displayName };
    toast("Имя сохранено.");
    refresh();
  } catch (error) {
    toast(error.message || "Не получилось сохранить имя.");
  } finally {
    store.busy = false;
  }
}

function closeSheet() {
  const dialog = document.querySelector("#dialog");
  if (dialog?.open && typeof dialog.close === "function") dialog.close();
}

function openSheet(html) {
  const dialog = document.querySelector("#dialog");
  if (!dialog) return;
  dialog.innerHTML = `<div class="sheet-top"><div class="grab"></div><button type="button" class="sheet-close" data-act="close-sheet">Закрыть</button></div>${html}`;
  if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
}

function classSheet() {
  const classes = store.report?.classes || [];
  const only = classes.length <= 1;
  const rows = classes.map((item) => {
    const subject = (item.subjects || []).map((row) => row.title).join(", ");
    const note = only ? "основной тестовый класс" : subject;
    return `<button class="line" type="button" data-act="pick-class" data-id="${item.id}"><span><b>${esc(item.title)}</b><small>${esc(note)}</small></span></button>`;
  }).join("");
  openSheet(`<h2>Класс</h2>${only ? `<p class="quiet">Пока доступен один класс.</p>` : ""}<section class="sheet-block">${rows || `<p class="quiet">Класс ещё не назначен.</p>`}</section>`);
}

async function noticesSheet() {
  const items = store.notices?.items || [];
  const rows = items.length
    ? items
        .map(
          (item) => `<button class="line notice-line${item.read ? "" : " is-unread"}" type="button" data-act="notice-open" data-id="${item.id}" data-kind="${esc(item.kind || "")}" data-ref="${item.ref_id || ""}">
            <span class="notice-dot${item.read ? " is-read" : ""}" aria-hidden="true"></span>
            <span><b>${esc(item.title)}</b><small>${esc(item.body)}</small></span>
            ${icon("chevron")}
          </button>`,
        )
        .join("")
    : `<p class="quiet">Уведомлений нет.</p>`;
  openSheet(`<h2>Уведомления</h2><div class="notices-scroll"><section class="sheet-block">${rows}</section></div>`);
}

async function submitJoinClass() {
  const input = document.querySelector("#join-code");
  const code = (input?.value || "").trim();
  if (!code) {
    store.gateMessage = "Введите код класса.";
    refresh();
    return;
  }
  store.busy = true;
  store.gateMessage = "";
  refresh();
  try {
    const saved = await joinClass(code);
    store.gate = null;
    store.classTitle = saved.class_title || store.classTitle;
    toast(`Ты в классе ${saved.class_title || ""}.`);
    await loadStudent();
    store.loading = false;
    refresh();
  } catch (error) {
    store.gateMessage = error.message || "Код не подошёл.";
    refresh();
  } finally {
    store.busy = false;
  }
}

async function openNotice(button) {
  const id = Number(button.dataset.id);
  const kind = button.dataset.kind || "";
  const ref = button.dataset.ref || "";
  const item = (store.notices?.items || []).find((row) => Number(row.id) === id);
  if (item && !item.read) {
    item.read = true;
    try {
      await readNotice(id);
      const unread = (store.notices?.items || []).filter((row) => !row.read).length;
      store.notices = { ...store.notices, unread, items: [...(store.notices?.items || [])] };
      refresh();
    } catch { /* остаётся непрочитанным, если сервер не ответил */ }
  }
  closeSheet();
  if (kind === "work" && ref) {
    if (store.role === "teacher") {
      go("tasks");
      await reloadQuiet();
      return;
    }
    go("tasks");
    try {
      const fresh = await getStudentWorks();
      store.works = fresh;
      const work = (fresh?.items || []).find((row) => String(row.id) === String(ref));
      store.openWork = work || null;
      refresh();
    } catch { /* список работ уже был загружен при входе */ }
  } else if (kind === "join_request") {
    go("manage");
    await loadManage();
  }
}

function frame(inner) {
  return `<div class="frame">
    ${sidenav()}
    <div class="content">
      ${store.preview ? `<div class="demo-banner">Демонстрационный просмотр. Имена и цифры из локального макета, не из базы и не из API.</div>` : ""}
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
  if (store.gate === "waiting") {
    const school = store.schoolTitle ? `${store.schoolTitle}, ` : "";
    const room = store.classTitle ? `класс ${store.classTitle}` : "класс ещё не выбран";
    const rejected = store.applicationStatus === "rejected";
    const quiet = !store.classHasTeacher
      ? "Учителя в классе нет, поэтому заданий нет. Они появятся, когда учителя назначат и заявку примут."
      : "Заданий пока нет. Они появятся после того, как заявку примут.";
    return `<div class="gate">${brand()}
      <h1>${rejected ? "Заявку отклонили" : "Заявка на рассмотрении"}</h1>
      <p>${rejected ? "Вернись в чат и выбери школу и класс снова." : `${esc(school)}${esc(room)}. Кабинет открыт, решение ещё не пришло.`}</p>
      ${rejected ? "" : `<p>${quiet}</p>`}
      <button class="btn btn-primary" type="button" data-act="retry-auth">Проверить заявку</button>
    </div>`;
  }
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
  if (store.gate === "invite") {
    return `<div class="gate">${brand()}
      <h1>Код класса</h1>
      <p>Введите код класса для входа. Его выдаёт учитель в своём кабинете.</p>
      ${store.gateMessage ? `<p class="gate-error">${esc(store.gateMessage)}</p>` : ""}
      <form id="join-form" class="gate-form">
        <input id="join-code" class="field" maxlength="16" placeholder="Например, 8BDEMO" autocomplete="off" autocapitalize="characters">
        <button class="btn btn-primary" type="submit" ${store.busy ? "disabled" : ""}>Войти в класс</button>
      </form>
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
  focused = store.screen;
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
    else if (store.screen === "compose" && store.wizard) wizardExit();
    else if (store.screen === "lesson") exitLesson();
    else go(store.role === "teacher" ? "overview" : "home");
  };
  if (nested) {
    back.show();
    if (typeof back.onClick === "function") back.onClick(backFn);
  } else if (typeof back.hide === "function") back.hide();
}

function syncFormButtons() {
  const subjectBtn = document.querySelector('[data-act="program-save-subject"]');
  if (subjectBtn) subjectBtn.disabled = !(store.newSubjectTitle || "").trim() || Boolean(store.busy);
  const topicBtn = document.querySelector('[data-act="program-save-topic"]');
  if (topicBtn) {
    const active = store.subjectId || store.program?.subjects?.[0]?.id;
    topicBtn.disabled = !(store.newTopicTitle || "").trim() || !active || Boolean(store.busy);
  }
  const linkBtn = document.querySelector('[data-act="resource-link-add"]');
  if (linkBtn) linkBtn.disabled = !(store.resourceLinkUrl || "").trim() || Boolean(store.busy);
}

function syncChatInset() {
  const bottom = document.querySelector(".chat-bottom");
  if (!bottom) {
    document.documentElement.style.removeProperty("--chat-bottom-h");
    return;
  }
  document.documentElement.style.setProperty("--chat-bottom-h", `${Math.ceil(bottom.offsetHeight)}px`);
}

function paint() {
  store.themePref = themePref();
  document.body.classList.toggle("role-teacher", store.role === "teacher");
  document.body.classList.toggle("role-student", store.role === "student");
  document.body.classList.toggle("is-flow", store.screen === "compose" || store.screen === "lesson");
  document.body.classList.toggle("is-chat", store.screen === "stimul" && store.chatView === "thread");
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
  ensureAssistant();
  if (
    store.role === "teacher" &&
    store.screen === "profile" &&
    store.program === null &&
    !store.programLoading &&
    !store.programError &&
    !store.loading
  ) {
    loadProgram();
  }
  if (store.screen === "stimul" && store.chatView === "thread") {
    document.querySelector(".chat-scroll-end")?.scrollIntoView({ block: "end" });
  }
  syncChatInset();
  syncBack();
  focusTitle();
  document.title = `Стимул — ${TITLES[store.screen] || "Стимул"}`;
}

async function onAction(act, button) {
  if (act === "nav") {
    const screen = button.dataset.screen;
    go(screen);
    if (screen === "manage") await loadManage();
    if (screen === "profile" && store.role === "teacher" && !store.program && !store.programError) loadProgram();
    if (screen === "stimul") {
      if (store.role === "teacher" && store.materials === null) loadMaterials();
      if (store.chats === null) loadChats();
    }
    if (store.role === "teacher" && ["tasks", "class", "overview"].includes(screen)) await reloadQuiet();
    return;
  }
  if (act === "assistant-chats") {
    if (store.role === "teacher") {
      store.chatView = "list";
      refresh();
      loadChats();
    } else {
      showStudentChats();
    }
    return;
  }
  if (act === "assistant-new") {
    if (store.role === "teacher") await newChat();
    else await startStudentChat();
    return;
  }
  if (act === "assistant-open") {
    const id = Number(button.dataset.id);
    if (store.role === "teacher") await openChat(id);
    else await openStudentChat(id);
    return;
  }
  if (act === "assistant-pin") {
    const kind = store.role === "teacher" ? "teacher" : "student";
    try {
      await pinChat(kind, button.dataset.id);
      await loadChats();
    } catch { /* ignore */ }
    return;
  }
  if (act === "assistant-delete") {
    const ok = await confirmDialog({
      title: "Удалить разговор?",
      text: "Вся история этого чата будет стёрта.",
      confirm: "Удалить",
      cancel: "Отмена",
    });
    if (!ok) return;
    const kind = store.role === "teacher" ? "teacher" : "student";
    try {
      await deleteChat(kind, button.dataset.id);
      if (Number(store.chatId) === Number(button.dataset.id)) {
        store.chatId = null;
        store.chatMessages = [];
      }
      await loadChats();
    } catch { /* ignore */ }
    return;
  }
  if (act === "assistant-back") {
    store.chatView = "thread";
    refresh();
    return;
  }
  if (act === "chat-sample") {
    const text = button.dataset.text || "";
    store.chatDraft = text;
    if (store.role === "teacher") await sendStimul(text);
    else await submitChat();
    return;
  }
  if (act === "pick-chat-photo") {
    document.querySelector("#chat-photo")?.click();
    return;
  }
  if (act === "draft-review") {
    await reviewDraft(button.dataset.mid);
    return;
  }
  if (act === "draft-send") {
    await sendDraftNow(button.dataset.mid);
    return;
  }
  if (act === "theme") {
    const value = button.dataset.value || "auto";
    store.themePref = value;
    setThemePref(value);
    applyTheme(value);
    refresh();
    return;
  }
  if (act === "wizard-step") {
    wizardGoto(button.dataset.step);
    return;
  }
  if (act === "wizard-exit") {
    wizardExit();
    return;
  }
  if (act === "program-subject") {
    programSubject(button.dataset.id);
    return;
  }
  if (act === "program-new-subject") {
    programNewSubject();
    return;
  }
  if (act === "program-new-topic") {
    programNewTopic();
    return;
  }
  if (act === "program-cancel") {
    programCancel();
    return;
  }
  if (act === "program-save-subject") {
    await programSaveSubject();
    return;
  }
  if (act === "program-save-topic") {
    await programSaveTopic();
    return;
  }
  if (act === "program-retry") {
    await loadProgram();
    return;
  }
  if (act === "resource-link-toggle") {
    resourceLinkToggle();
    return;
  }
  if (act === "resource-link-cancel") {
    resourceLinkCancel();
    return;
  }
  if (act === "resource-link-add") {
    resourceLinkAdd();
    return;
  }
  if (act === "resource-remove") {
    resourceRemove(button.dataset.index);
    return;
  }
  if (act === "class-subject") {
    store.subjectId = Number(button.dataset.id) || null;
    refresh();
    return;
  }
  if (act === "stimul-topic") {
    const topic = String(button.dataset.topic || "").trim();
    if (topic) store.chatDraft = `Собери проверку по теме «${topic}»`;
    go("stimul");
    if (store.role === "teacher" && store.materials === null) loadMaterials();
    if (store.chats === null) loadChats();
    return;
  }
  if (act === "select-all-students") {
    selectAllStudents();
    return;
  }
  if (act === "clear-students") {
    clearStudents();
    return;
  }
  if (act === "regen-item") {
    regenItem(button.dataset.index);
    return;
  }
  if (act === "del-item") {
    delItem(button.dataset.index);
    refresh();
    return;
  }
  if (act === "clear-chat-photo") {
    clearChatPhoto();
    return;
  }
  if (act === "toggle-ask") {
    store.composer = !store.composer;
    refresh();
    return;
  }
  if (act === "close-sheet") {
    closeSheet();
    return;
  }
  if (act === "notices") {
    await noticesSheet();
    return;
  }
  if (act === "notice-open") {
    await openNotice(button);
    return;
  }
  if (act === "join-class") {
    await submitJoinClass();
    return;
  }
  if (act === "copy-invite") {
    await copyInvite();
    return;
  }
  if (act === "next-topic-save") {
    await saveNextTopic();
    return;
  }
  if (act === "next-topic-reset") {
    await resetNextTopic();
    return;
  }
  if (act === "group-chat-toggle") {
    await toggleGroupChat();
    return;
  }
  if (act === "class-sheet") {
    classSheet();
    return;
  }
  if (act === "pick-class") {
    store.classId = Number(button.dataset.id);
    store.materials = null;
    store.program = null;
    store.subjectId = null;
    document.querySelector("#dialog")?.close();
    await reloadTeacher();
    return;
  }
  if (act === "open-work") {
    const work = (store.works?.items || []).find((item) => String(item.id) === button.dataset.id);
    store.openWork = work || null;
    go("tasks");
    return;
  }
  if (act === "close-work") {
    store.openWork = null;
    refresh();
    return;
  }
  if (act === "submit-work") {
    await submitWork();
    return;
  }
  if (act === "stimul-sample") {
    store.stimulDraft = button.dataset.text || "";
    await sendStimul(store.stimulDraft);
    return;
  }
  if (act === "material-delete") {
    await removeMaterial(button.dataset.id);
    return;
  }
  if (act === "save-draft") {
    await saveDraft();
    return;
  }
  if (act === "open-result") {
    await openResult(button.dataset.id);
    return;
  }
  if (act === "close-result") {
    store.resultView = null;
    refresh();
    return;
  }
  if (act === "accept-claim") {
    await acceptOne(button.dataset.id);
    if (store.role === "teacher") await reloadTeacher();
    return;
  }
  if (act === "reject-claim") {
    await rejectOne(button.dataset.id);
    return;
  }
  if (act === "people-role") {
    store.peopleRole = button.dataset.role || "";
    await loadManage();
    return;
  }
  if (act === "make-teacher") {
    await changePerson(button.dataset.id, { role: "teacher", status: "active" });
    return;
  }
  if (act === "block-person") {
    await changePerson(button.dataset.id, { status: "blocked" });
    return;
  }
  if (act === "unblock-person") {
    await changePerson(button.dataset.id, { status: "active" });
    return;
  }
  if (act === "appoint") {
    await appoint();
    return;
  }
  if (act === "reload-manage") {
    await loadManage();
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
  if (act === "attempts-more") {
    await loadMoreAttempts();
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
  else if (act === "profile-note") await renameProfile();
  else if (act === "class-info") await showClassInfo();
  else if (act === "compose") startCompose(button.dataset.topic || "", button.dataset.mode || "own");
  else if (act === "compose-own") writeOwn();
  else if (act === "focus-student") focusStudent(button.dataset.name || "");
  else if (act === "focus-topic") focusTopic(button.dataset.topic);
  else if (act === "filter-status") setFilter(button.dataset.status);
  else if (act === "wizard-next") wizardNext();
  else if (act === "wizard-back") wizardBack();
  else if (act === "count") setCount(button.dataset.value);
  else if (act === "difficulty") setDifficulty(button.dataset.value);
  else if (act === "audience") setAudience(button.dataset.value);
  else if (act === "toggle-student") toggleStudent(button.dataset.id, button.dataset.name);
  else if (act === "redraft") await loadDraft();
  else if (act === "send-assignment") await sendAssignment();
}

function bind() {
  const dialog = document.querySelector("#dialog");
  dialog?.addEventListener("click", (event) => {
    if (event.target === dialog) closeSheet();
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-act]");
    if (!button || button.disabled) return;
    onAction(button.dataset.act, button);
  });
  document.addEventListener("submit", (event) => {
    event.preventDefault();
    if (event.target.id === "answer-form") submitAnswer();
    if (event.target.id === "join-form") {
      event.preventDefault();
      submitJoinClass();
    }
    if (event.target.id === "chat-form") {
      const value = document.querySelector("#chat-input")?.value.trim() || "";
      store.chatDraft = value;
      if (store.role === "teacher") sendStimul(value);
      else submitChat();
    }
    if (event.target.id === "stimul-form") {
      const value = document.querySelector("#stimul-input")?.value.trim() || "";
      store.stimulDraft = value;
      sendStimul(value);
    }
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
    if (target.id === "stimul-input") store.stimulDraft = target.value;
    if (target.id === "chat-input") store.chatDraft = target.value;
    if (target.id === "people-q") store.peopleQuery = target.value;
    if (target.id === "student-q" && store.wizard) {
      store.wizard.studentQuery = target.value;
      const list = document.querySelector("#student-list");
      if (list) list.innerHTML = studentRowsHTML();
      return;
    }
    if (target.id === "due-at" && store.wizard) {
      store.wizard.dueAt = target.value;
      scheduleAutosave();
      return;
    }
    if (target.dataset.prompt != null && store.wizard?.draft?.items) {
      const item = store.wizard.draft.items[Number(target.dataset.prompt)];
      if (item) item.prompt = target.value;
      scheduleAutosave();
    }
    if (target.dataset.reference != null && store.wizard?.draft?.items) {
      const item = store.wizard.draft.items[Number(target.dataset.reference)];
      if (item) item.reference = target.value;
      scheduleAutosave();
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
    if (target.id === "chat-photo") {
      takeChatPhoto(target.files && target.files[0]);
      target.value = "";
    }
    if (target.id === "material-file") {
      addMaterial(target.files && target.files[0]);
      target.value = "";
    }
    if (target.id === "resource-file") {
      resourceFilePicked(target.files && target.files[0]);
      target.value = "";
    }
    if (target.id === "use-material") {
      toggleMaterial(target.checked);
    }
    if (target.id === "topic-filter") {
      store.filters = { ...store.filters, topic: target.value };
      refresh();
    }
    if (target.id === "topic" && store.wizard) store.wizard.topic = target.value;
    if (target.id === "new-subject-title") { store.newSubjectTitle = target.value; syncFormButtons(); }
    if (target.id === "new-topic-title") { store.newTopicTitle = target.value; syncFormButtons(); }
    if (target.id === "new-topic-blurb") store.newTopicBlurb = target.value;
    if (target.id === "resource-link-url") { store.resourceLinkUrl = target.value; syncFormButtons(); }
    if (target.id === "resource-link-title") store.resourceLinkTitle = target.value;
    if (target.id === "material") toggleMaterial(target.checked);
    if (target.id === "wiz-subject") setWizardSubject(target.value);
    if (target.dataset.studentId != null) {
      toggleStudent(target.dataset.studentId, target.dataset.name || "");
    }
    if (target.id === "people-q") {
      store.peopleQuery = target.value;
      loadManage();
    }
  });
  window.addEventListener("hashchange", () => {
    if (store.booting || store.gate) return;
    store.screen = screenFromHash();
    if (store.screen === "manage" && store.role === "teacher") loadManage();
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
window.addEventListener("resize", syncChatInset);
mountSplash();
boot();
