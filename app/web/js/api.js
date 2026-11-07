const JSON_HEADERS = { "Content-Type": "application/json" };
const TOKEN_KEY = "stimul_session";
let csrfToken = "";
let sessionToken = "";

try {
  sessionToken = sessionStorage.getItem(TOKEN_KEY) || "";
} catch {
  sessionToken = "";
}

export function setCsrf(value) {
  csrfToken = value || "";
}

export function setSession(value) {
  sessionToken = value || "";
  try {
    if (sessionToken) sessionStorage.setItem(TOKEN_KEY, sessionToken);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* окно MAX может закрыть хранилище, токен останется в памяти вкладки */
  }
}

function remember(payload) {
  if (payload && payload.csrf) setCsrf(payload.csrf);
  if (payload && payload.token) setSession(payload.token);
  return payload;
}

export class ApiError extends Error {
  constructor(message, extra) {
    super(message);
    this.name = "ApiError";
    this.status = extra.status;
    this.code = extra.code || "";
    this.network = Boolean(extra.network);
  }
}

function messageFor(status, detail) {
  if (detail && detail !== "error") return detail;
  if (status === 401) return "Открой приложение кнопкой из чата с ботом.";
  if (status === 403) return "Этот раздел сейчас закрыт.";
  if (status === 409) return "Открой приложение кнопкой из чата с ботом.";
  if (status === 422) return "Проверьте поля и отправьте ещё раз.";
  if (status >= 500) return "Сервер не ответил. Попробуйте ещё раз.";
  return "Не получилось выполнить запрос.";
}

async function once(path, options) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeout || 15000);
  try {
    const headers = { ...(options.headers || {}) };
    const method = (options.method || "GET").toUpperCase();
    if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;
    if (method !== "GET" && method !== "HEAD" && csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }
    const response = await fetch(path, {
      method: options.method || "GET",
      headers,
      body: options.body,
      credentials: "same-origin",
      signal: controller.signal,
    });
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = null;
      }
    }
    if (!response.ok) {
      const detail = payload && typeof payload.detail === "string" ? payload.detail : "";
      throw new ApiError(messageFor(response.status, detail), {
        status: response.status,
        code: payload?.code || "",
      });
    }
    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const timeout = error && error.name === "AbortError";
    throw new ApiError(
      timeout
        ? "Сервер отвечает слишком долго. Попробуйте ещё раз."
        : "Нет соединения. Проверьте сеть и повторите.",
      { status: 0, code: "", network: true },
    );
  } finally {
    clearTimeout(timer);
  }
}

export async function request(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  try {
    return await once(path, options);
  } catch (error) {
    const retry = method === "GET" && (error.network || [502, 503, 504].includes(error.status));
    if (!retry) throw error;
    return once(path, options);
  }
}

export const getSession = () => request("/api/session");
export const getAssistantStatus = () => request("/api/assistant/status");

export const renameMe = (displayName) =>
  request("/api/profile/name", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ display_name: displayName }),
  });

export const openSession = (initData, startParam) =>
  request("/api/session", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ init_data: initData, start_param: startParam || "" }),
  }).then(remember);

export const webLogin = (publicId, code) =>
  request("/api/web-login", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ public_id: publicId, code }),
  }).then(remember);

export const openTicket = (ticket) =>
  request("/api/web-login/ticket", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ ticket }),
  }).then(remember);

export const approveJoin = (studentId) =>
  request(`/api/teacher/joins/${studentId}/approve`, { method: "POST" });

export const getProgress = () => request("/api/student/progress");
export const getHistory = () => request("/api/student/history");
export const getLesson = () => request("/api/student/lesson");

const LLM_WAIT = 80000;

export const practice = (body) =>
  request("/api/student/practice", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
    timeout: LLM_WAIT,
  });

export function sendPhoto(file, text) {
  const body = new FormData();
  body.append("photo", file);
  body.append("text", text || "");
  body.append("mode", "training");
  return request("/api/student/practice/photo", { method: "POST", body, timeout: LLM_WAIT });
}

export const getClass = (classId) =>
  request(classId ? `/api/teacher/class?class_id=${encodeURIComponent(classId)}` : "/api/teacher/class");
export const getAssignments = () => request("/api/teacher/assignments");
export const getStudentWorks = () => request("/api/student/works");
export const answerWork = (id, answers) =>
  request(`/api/student/works/${id}/answers`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ answers }),
  });
export const getNotices = () => request("/api/notices");
export const readNotice = (id) => request(`/api/notices/${id}/read`, { method: "POST" });
export const saveWork = (body) =>
  request("/api/teacher/works", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
export const publishWork = (id) => request(`/api/teacher/works/${id}/publish`, { method: "POST" });
export const getWorkResult = (id) => request(`/api/teacher/works/${id}`);
export const getClaims = () => request("/api/manage/claims");
export const acceptClaim = (id) => request(`/api/manage/claims/${id}/accept`, { method: "POST" });
export const rejectClaim = (id) => request(`/api/manage/claims/${id}/reject`, { method: "POST" });
export const getPeople = (q, role) =>
  request(`/api/manage/people?q=${encodeURIComponent(q || "")}&role=${encodeURIComponent(role || "")}`);
export const savePerson = (id, body) =>
  request(`/api/manage/people/${id}`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
export const getCatalog = () => request("/api/manage/catalog");
export const appointTeacher = (body) =>
  request("/api/manage/appointments", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });

export const postDraft = (body) =>
  request("/api/teacher/drafts", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });

export const postAssignment = (body) =>
  request("/api/teacher/assignments", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });

export const askAssistant = (text, classId) =>
  request("/api/teacher/assistant", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ text, class_id: classId || null }),
    timeout: LLM_WAIT,
  });

const chatBase = (kind) => `/api/${kind}/chats`;

export const getChats = (kind) => request(chatBase(kind));
export const pinChat = (kind, id) =>
  request(`${chatBase(kind)}/${id}/pin`, { method: "POST" });
export const deleteChat = (kind, id) =>
  request(`${chatBase(kind)}/${id}`, { method: "DELETE" });
export const getChat = (kind, id) => request(`${chatBase(kind)}/${id}`);
export const createChat = (kind, title) =>
  request(chatBase(kind), {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ title: title || "" }),
  });
export const sendChatMessage = (kind, id, text, classId) =>
  request(`${chatBase(kind)}/${id}/messages`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ text, class_id: classId || null }),
    timeout: LLM_WAIT,
  });

export function sendChatPhoto(kind, id, file, text, classId) {
  const body = new FormData();
  body.append("photo", file);
  body.append("text", text || "");
  if (classId) body.append("class_id", String(classId));
  return request(`${chatBase(kind)}/${id}/messages/photo`, {
    method: "POST",
    body,
    timeout: LLM_WAIT,
  });
}

export const getMaterials = (classId) =>
  request(
    classId
      ? `/api/teacher/materials?class_id=${encodeURIComponent(classId)}`
      : "/api/teacher/materials",
  );

export function uploadMaterial(file, title, classId) {
  const body = new FormData();
  body.append("file", file);
  body.append("title", title || "");
  if (classId) body.append("class_id", String(classId));
  return request("/api/teacher/materials", { method: "POST", body, timeout: LLM_WAIT });
}

export const deleteMaterial = (id, classId) =>
  request(`/api/teacher/materials/${id}${classId ? `?class_id=${classId}` : ""}`, {
    method: "DELETE",
  });

export const getProgram = (classId) =>
  request(
    classId
      ? `/api/teacher/program?class_id=${encodeURIComponent(classId)}`
      : "/api/teacher/program",
  );

export const createSubject = (body) =>
  request("/api/teacher/subjects", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });

export const createTopic = (body) =>
  request("/api/teacher/topics", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });

export function attachWorkResource(workId, { title, url, file }) {
  const body = new FormData();
  body.append("title", title || "");
  if (url) body.append("url", url);
  if (file) body.append("file", file);
  return request(`/api/teacher/works/${workId}/resources`, {
    method: "POST",
    body,
    timeout: LLM_WAIT,
  });
}

export const deleteWorkResource = (workId, resourceId) =>
  request(`/api/teacher/works/${workId}/resources/${resourceId}`, {
    method: "DELETE",
  });
