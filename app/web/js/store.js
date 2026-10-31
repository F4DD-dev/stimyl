export const store = {
  booting: true,
  loading: false,
  preview: false,
  role: null,
  displayName: "",
  screen: "home",
  gate: null,
  gateMessage: "",
  ticket: "",
  progress: null,
  progressError: null,
  history: null,
  historyError: null,
  openLesson: null,
  report: null,
  reportError: null,
  assignments: null,
  assignmentsError: null,
  lesson: null,
  lessonError: null,
  lessonMode: "training",
  question: "",
  answer: "",
  photoURL: "",
  fieldError: "",
  busy: false,
  busyLabel: "",
  pending: null,
  lastJob: null,
  wizard: null,
  filters: { status: "all", topic: "all" },
};

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
}

export function refresh() {
  for (const fn of listeners) fn();
}

export function go(screen) {
  store.fieldError = "";
  const dialog = document.querySelector("#dialog");
  if (dialog?.open) dialog.close();
  const next = `#/${screen}`;
  if (location.hash === next) refresh();
  else location.hash = next;
}
