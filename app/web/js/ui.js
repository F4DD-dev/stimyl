const PATHS = {
  home: '<path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z"/>',
  map: '<path d="M8 5 4 6.5v13L8 18l8 2 4-1.5v-13L16 7 8 5z"/><path d="M8 5v13M16 7v13"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v5l3 2"/>',
  user: '<circle cx="12" cy="9" r="3"/><path d="M6.5 19c1.1-2.4 2.8-3.5 5.5-3.5s4.4 1.1 5.5 3.5"/>',
  send: '<path d="m5 12 15-7-6 16-2.2-6.2L5 12z"/>',
  image:
    '<rect x="4" y="5" width="16" height="14" rx="2"/><circle cx="9" cy="10" r="1.3"/><path d="m5 16 4-3 3 2 3-2.5L19 16"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  close: '<path d="M7 7l10 10M17 7 7 17"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1.6"/><rect x="13" y="4" width="7" height="7" rx="1.6"/><rect x="4" y="13" width="7" height="7" rx="1.6"/><rect x="13" y="13" width="7" height="7" rx="1.6"/>',
  list: '<path d="M9 7h11M9 12h11M9 17h11"/><path d="M5 7h.01M5 12h.01M5 17h.01"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
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

export function brand() {
  return `<span class="brand"><span class="mark" aria-hidden="true"></span><span class="logo">стимул</span></span>`;
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
