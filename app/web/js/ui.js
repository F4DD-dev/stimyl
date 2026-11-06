const PATHS = {
  home: '<path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z"/>',
  map: '<path d="M3 5l6-2 6 2 6-2v16l-6 2-6-2-6 2V5z"/><path d="M9 3v16M15 5v16"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v5l3 2"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/>',
  send: '<path d="M5 12h14M14 7l5 5-5 5"/>',
  arrow: '<path d="M5 12h14M14 7l5 5-5 5"/>',
  image:
    '<path d="M4 7h4l2-3h4l2 3h4v12H4V7z"/><circle cx="12" cy="13" r="3.5"/>',
  camera:
    '<path d="M4 7h4l2-3h4l2 3h4v12H4V7z"/><circle cx="12" cy="13" r="3.5"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  close: '<path d="M5 5l14 14M19 5 5 19"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  list: '<path d="M9 6h12M9 12h12M9 18h12"/><path d="M4 6h.01M4 12h.01M4 18h.01" stroke-width="3"/>',
  check: '<path d="M5 12l4 4L19 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  spark: '<path d="M12 2l1.4 4.6L18 8l-4.6 1.4L12 14l-1.4-4.6L6 8l4.6-1.4L12 2z"/><path d="M19 15l.7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7L19 15z"/>',
  bell: '<path d="M18 9a6 6 0 0 0-12 0c0 7-3 6-3 8h18c0-2-3-1-3-8z"/><path d="M10 21h4"/>',
  link: '<path d="M10 14a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 10a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
  download: '<path d="M12 4v11m0 0 4.5-4.5M12 15 7.5 10.5"/><path d="M4 19h16"/>',
  book: '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.7a3.5 3.5 0 0 1 0 6.6M18.5 14.5a6.5 6.5 0 0 1 3 5.5"/>',
};

export function icon(name) {
  return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${PATHS[name] || ""}</svg>`;
}

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

export function nl(value) {
  return esc(value).replaceAll("\n", "<br>");
}

export function plural(n, one, few, many) {
  const value = Math.abs(Number(n) || 0);
  const mod10 = value % 10;
  const mod100 = value % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

export function initials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean).slice(0, 2);
  if (!parts.length) return "•";
  return parts.map((part) => part[0]).join("").toUpperCase();
}

export function firstName(name) {
  return String(name || "").trim().split(/\s+/).filter(Boolean)[0] || "";
}

export function mark(large = false) {
  return `<span class="logo${large ? " logo--large" : ""}" aria-hidden="true"><span class="logo__dot logo__dot--green"></span><span class="logo__dot logo__dot--coral"></span><span class="logo__dot logo__dot--yellow"></span></span>`;
}

export function brand({ home = false } = {}) {
  const inner = `${mark()}<span class="logo-lock"><span class="brand__name">Стимул</span><span class="brand__line" aria-hidden="true"></span></span>`;
  if (!home) return `<span class="brand">${inner}</span>`;
  return `<button class="brand" type="button" data-act="nav" data-screen="stimul" aria-label="Стимул">${inner}</button>`;
}

export function classbar({ title, letter, unread, pickClass = false }) {
  const klass = pickClass
    ? `<button class="classbar__class" type="button" data-act="class-sheet"><strong>${esc(title || "Класс")}</strong></button>`
    : `<div class="classbar__class"><strong>${esc(title || "Класс")}</strong></div>`;
  return `<header class="classbar">
    ${brand({ home: true })}
    ${klass}
    <div class="classbar__actions">
      <button class="icon-button" type="button" data-act="notices" aria-label="Уведомления">${icon("bell")}${unread ? `<span class="notification-dot"></span>` : ""}</button>
      <button class="avatar-button" type="button" data-act="nav" data-screen="profile" aria-label="Профиль">${esc(letter || "•")}</button>
    </div>
  </header>`;
}

export function themeSwitch(pref) {
  const items = [
    ["auto", "Авто"],
    ["light", "Светлая"],
    ["dark", "Тёмная"],
  ];
  return `<div class="segment theme-segment" role="tablist" aria-label="Тема оформления">${items
    .map(
      ([id, label]) =>
        `<button type="button" role="tab" data-act="theme" data-value="${id}" aria-selected="${(pref || "auto") === id}" class="${(pref || "auto") === id ? "is-on" : ""}">${label}</button>`,
    )
    .join("")}</div>`;
}

export function pill(status) {
  const labels = {
    mastered: "усвоено",
    needs_practice: "нужна практика",
    repeat: "повторить",
  };
  if (!labels[status]) return `<span class="pill" data-status="none">нет попыток</span>`;
  return `<span class="pill" data-status="${esc(status)}">${labels[status]}</span>`;
}

export function track(percent, status) {
  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  const known = percent != null && percent !== "";
  return `<div class="track" data-status="${esc(status || "none")}"><span style="width:${known ? value : 0}%"></span></div>`;
}

export function ring(percent) {
  const known = percent != null && !Number.isNaN(Number(percent));
  const value = known ? Math.max(0, Math.min(100, Math.round(Number(percent)))) : 0;
  const arc = value > 0
    ? `<circle class="ring-fg" cx="18" cy="18" r="15" pathLength="100" stroke-dasharray="${value} 100"></circle>`
    : "";
  return `<div class="ring-wrap" aria-hidden="true">
    <svg viewBox="0 0 36 36" class="ring">
      <circle class="ring-bg" cx="18" cy="18" r="15" pathLength="100"></circle>
      ${arc}
    </svg>
    <strong>${known ? `${value}%` : "—"}</strong>
  </div>`;
}

export function skeleton() {
  return `<div class="skeleton" aria-busy="true" aria-label="Загрузка">
    <span style="width:46%"></span>
    <span style="width:100%;height:108px"></span>
    <span style="width:72%"></span>
  </div>`;
}

export function errorBlock(message, act = "retry") {
  return `<section class="card empty">
    <h2>Не получилось загрузить</h2>
    <p>${esc(message || "Попробуйте ещё раз.")}</p>
    <button class="btn btn-primary" type="button" data-act="${esc(act)}">Повторить</button>
  </section>`;
}

export function emptyBlock(title, text) {
  return `<section class="card empty"><h2>${esc(title)}</h2><p>${esc(text)}</p></section>`;
}

let toastTimer = 0;

export function toast(message) {
  const node = document.querySelector("#toast");
  if (!node) return;
  node.textContent = message;
  node.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    node.hidden = true;
  }, 3400);
}

export function confirmDialog({ title, text, confirm, cancel }) {
  const dialog = document.querySelector("#dialog");
  if (!dialog) return Promise.resolve(false);
  dialog.innerHTML = `<h2>${esc(title)}</h2><p>${esc(text)}</p><div class="dialog-actions">
    ${cancel ? `<button type="button" class="btn btn-ghost" data-cancel>${esc(cancel)}</button>` : ""}
    <button type="button" class="btn btn-primary" data-ok>${esc(confirm || "Понятно")}</button>
  </div>`;
  if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
  else dialog.setAttribute("open", "");
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      if (dialog.open && typeof dialog.close === "function") dialog.close();
      resolve(value);
    };
    dialog.querySelector("[data-ok]")?.addEventListener("click", () => finish(true));
    dialog.querySelector("[data-cancel]")?.addEventListener("click", () => finish(false));
    dialog.addEventListener("close", () => finish(false), { once: true });
  });
}
