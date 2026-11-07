import { createChat, getAssistantStatus, getChat, getChats, sendChatMessage, sendChatPhoto } from "./api.js?v=8";
import { refresh, store } from "./store.js?v=5";

export function takeChatPhoto(file) {
  if (!file) return;
  if (file.size > 8 * 1024 * 1024) {
    store.chatError = "Фото больше 8 МБ. Выбери снимок поменьше.";
    refresh();
    return;
  }
  if (file.type && !file.type.startsWith("image/")) {
    store.chatError = "Нужен файл изображения.";
    refresh();
    return;
  }
  if (store.chatPhotoURL) URL.revokeObjectURL(store.chatPhotoURL);
  store.chatPhotoFile = file;
  store.chatPhotoURL = URL.createObjectURL(file);
  store.chatError = "";
  refresh();
}

export function clearChatPhoto() {
  if (store.chatPhotoURL) URL.revokeObjectURL(store.chatPhotoURL);
  store.chatPhotoFile = null;
  store.chatPhotoURL = "";
  refresh();
}

export function chatKind() {
  return store.role === "teacher" ? "teacher" : "student";
}

export async function loadChats() {
  if (store.preview) {
    store.chats = { items: [] };
    refresh();
    return;
  }
  store.chatsError = "";
  try {
    store.chats = await getChats(chatKind());
  } catch (error) {
    store.chats = { items: [] };
    store.chatsError = error.message;
  }
  refresh();
}

export async function openChat(id) {
  const kind = chatKind();
  store.chatId = Number(id);
  store.chatView = "thread";
  store.chatMessages = null;
  store.chatError = "";
  refresh();
  if (store.preview) {
    store.chatMessages = [];
    refresh();
    return;
  }
  try {
    const view = await getChat(kind, store.chatId);
    store.chatMessages = view.messages || [];
    const found = (store.chats?.items || []).find((item) => item.id === store.chatId);
    if (found && view.title) found.title = view.title;
  } catch (error) {
    store.chatError = error.message;
    store.chatMessages = [];
  }
  refresh();
}

export async function newChat() {
  if (store.preview) {
    store.chatView = "thread";
    store.chatId = null;
    store.chatMessages = [];
    refresh();
    return;
  }
  try {
    const created = await createChat(chatKind(), "");
    await openChat(created.id);
  } catch (error) {
    store.chatError = error.message;
    refresh();
  }
}

export function showChatList() {
  store.chatView = "list";
  refresh();
}

export async function loadAssistantStatus() {
  if (store.preview) return;
  try {
    const status = await getAssistantStatus();
    if (!status.enabled) {
      store.chatStatus = "Помощник на сервере выключен: проверьте LLM_BASE_URL и LLM_API_KEY.";
    } else if (status.last_error) {
      store.chatStatus = `Причина последнего сбоя: ${status.provider} — ${status.last_error}`;
    } else {
      store.chatStatus = "";
    }
  } catch {
    store.chatStatus = "";
  }
  refresh();
}

function shortChatTitle(text) {
  const first = String(text || "").split("\n")[0].trim();
  const sentence = first.split(/[.!?…]/)[0].trim() || first;
  const words = sentence.split(/\s+/).filter(Boolean).slice(0, 6).join(" ");
  if (words.length <= 48) return words;
  return `${words.slice(0, 48).replace(/\s+\S*$/, "")}…`;
}

async function ensureChat(text) {
  if (store.chatId) return store.chatId;
  const created = await createChat(chatKind(), shortChatTitle(text));
  store.chatId = created.id;
  store.chatMessages = [];
  store.chats = { items: [{ id: created.id, title: created.title, updated_at: new Date().toISOString() }, ...(store.chats?.items || [])] };
  return created.id;
}

export async function sendChat(text, { classId = null, photo = null, onReply = null } = {}) {
  const kind = chatKind();
  const trimmed = (text || "").trim();
  if (store.chatBusy) return;
  if (!trimmed && !photo) {
    store.chatError = "Напишите вопрос или прикрепите фото.";
    refresh();
    return;
  }
  if (store.preview) {
    store.chatError = "В демонстрации помощник к серверу не ходит.";
    refresh();
    return;
  }
  store.chatBusy = true;
  store.chatError = "";
  store.chatRateNote = "";
  store.chatStatus = "";
  refresh();
  try {
    const id = await ensureChat(trimmed);
    const result = photo
      ? await sendChatPhoto(kind, id, photo, trimmed, kind === "teacher" ? classId : null)
      : await sendChatMessage(kind, id, trimmed, kind === "teacher" ? classId : null);
    store.chatId = result.chat_id || id;
    store.chatMessages = result.messages || store.chatMessages;
    store.chatDraft = "";
    if (result.reply && onReply) onReply(result.reply);
    const item = { id: store.chatId, title: "", updated_at: new Date().toISOString() };
    store.chats = { items: [item, ...(store.chats?.items || []).filter((row) => row.id !== store.chatId)] };
  } catch (error) {
    store.chatError = error.message;
    if (error.code === "rate_limited") store.chatRateNote = error.message;
    if (!error.status || error.status >= 500) loadAssistantStatus();
  } finally {
    store.chatBusy = false;
    refresh();
  }
}

export function chatTitle() {
  const found = (store.chats?.items || []).find((item) => item.id === store.chatId);
  return found?.title || "Новый разговор";
}
