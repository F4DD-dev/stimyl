export const store = {
  booting: true,
  loading: false,
  preview: false,
  role: null,
  displayName: "",
  screen: "home",
  gate: null,
  gateMessage: "",
  fromMax: false,
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
  canManage: false,
  classTitle: "",
  composer: false,
  notices: null,
  works: null,
  worksError: null,
  openWork: null,
  peopleQuery: "",
  peopleRole: "",
  claims: null,
  people: null,
  catalog: null,
  manageError: null,
  stimulDraft: "",
  stimulNote: "",
  stimulBusy: false,
  stimulAnswer: null,
  chats: null,
  chatsError: "",
  chatId: null,
  chatMessages: null,
  chatView: "thread",
  chatDraft: "",
  chatBusy: false,
  chatError: "",
  chatPhotoURL: "",
  chatRateNote: "",
  materials: null,
  materialsError: "",
  focusStudent: "",
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
