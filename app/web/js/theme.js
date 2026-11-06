const KEY = "stimul_theme";
const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

export function themePref() {
  try {
    return localStorage.getItem(KEY) || "auto";
  } catch {
    return "auto";
  }
}

export function setThemePref(value) {
  try {
    if (value === "auto") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, value);
  } catch {
    /* приватный режим — выбор живёт до закрытия вкладки */
  }
}

export function applyTheme(pref = themePref()) {
  const effective = pref === "dark" || (pref !== "light" && mq && mq.matches) ? "dark" : "light";
  document.documentElement.dataset.theme = effective;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = effective === "dark" ? "#14141C" : "#f8f6fc";
  return effective;
}

if (mq && typeof mq.addEventListener === "function") {
  mq.addEventListener("change", () => applyTheme());
}

applyTheme();
