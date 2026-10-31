const JSON_HEADERS = { "Content-Type": "application/json" };
let csrfToken = "";

export function setCsrf(value) {
  csrfToken = value || "";
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
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const headers = { ...(options.headers || {}) };
    const method = (options.method || "GET").toUpperCase();
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

export const openSession = (initData) =>
  request("/api/session", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ init_data: initData }),
  });

export const webLogin = (publicId, code) =>
  request("/api/web-login", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ public_id: publicId, code }),
  });

export const openTicket = (ticket) =>
  request("/api/web-login/ticket", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ ticket }),
  });

export const approveJoin = (studentId) =>
  request(`/api/teacher/joins/${studentId}/approve`, { method: "POST" });

export const getProgress = () => request("/api/student/progress");
export const getHistory = () => request("/api/student/history");
export const getLesson = () => request("/api/student/lesson");

export const practice = (body) =>
  request("/api/student/practice", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });

export function sendPhoto(file, text) {
  const body = new FormData();
  body.append("photo", file);
  body.append("text", text || "");
  body.append("mode", "training");
  return request("/api/student/practice/photo", { method: "POST", body });
}

export const getClass = () => request("/api/teacher/class");
export const getAssignments = () => request("/api/teacher/assignments");

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
