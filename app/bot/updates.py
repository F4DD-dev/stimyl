from dataclasses import dataclass


@dataclass(frozen=True)
class Incoming:
    kind: str
    dedup_key: str | None
    max_user_id: str
    chat_id: int | None
    name: str
    text: str | None = None
    callback_id: str | None = None
    payload: str | None = None
    photo_token: str | None = None
    photo_url: str | None = None
    start_payload: str | None = None
    contact_vcf: str | None = None
    contact_hash: str | None = None


def parse_update(update: dict) -> Incoming | None:
    kind = update.get("update_type")
    if kind == "bot_started":
        return _started(update)
    if kind == "message_callback":
        return _callback(update)
    if kind == "message_created":
        return _message(update)
    if kind in {"bot_added", "bot_removed"}:
        return _membership(update, kind)
    return None


def _membership(update: dict, kind: str) -> Incoming | None:
    chat_id = _chat_id(update.get("chat_id"))
    if chat_id is None or update.get("is_channel"):
        return None
    user = update.get("user") or {}
    return Incoming(
        kind=kind,
        dedup_key=f"{kind}:{chat_id}:{update.get('timestamp')}",
        max_user_id=str(user.get("user_id") or ""),
        chat_id=chat_id,
        name=_name(user) if user else "",
    )


def _started(update: dict) -> Incoming | None:
    user = update.get("user") or {}
    if user.get("is_bot") or user.get("user_id") is None:
        return None
    chat_id = _chat_id(update.get("chat_id"))
    return Incoming(
        kind="start",
        dedup_key=f"start:{chat_id}:{update.get('timestamp')}",
        max_user_id=str(user["user_id"]),
        chat_id=chat_id,
        name=_name(user),
        start_payload=_payload(update.get("payload")),
    )


def _callback(update: dict) -> Incoming | None:
    callback = update.get("callback") or {}
    user = callback.get("user") or {}
    if user.get("is_bot") or user.get("user_id") is None or not callback.get("callback_id"):
        return None
    message = update.get("message") or {}
    recipient = message.get("recipient") or {}
    return Incoming(
        kind="callback",
        dedup_key=str(callback["callback_id"]),
        max_user_id=str(user["user_id"]),
        chat_id=_chat_id(recipient.get("chat_id")),
        name=_name(user),
        callback_id=str(callback["callback_id"]),
        payload=str(callback.get("payload") or ""),
    )


def _message(update: dict) -> Incoming | None:
    message = update.get("message") or {}
    sender = message.get("sender") or {}
    if sender.get("is_bot") or sender.get("user_id") is None:
        return None
    body = message.get("body") or {}
    text = body.get("text") if isinstance(body.get("text"), str) else None
    attachments = body.get("attachments") or []
    photo_token, photo_url = _image(attachments)
    contact_vcf, contact_hash = _contact(attachments)
    recipient = message.get("recipient") or {}
    chat_type = recipient.get("chat_type")
    if chat_type == "channel":
        return None
    if chat_type not in {None, "dialog", "chat"}:
        return None
    stripped = text.strip() if text else ""
    folded = stripped.casefold()
    start_payload = None
    if chat_type == "chat":
        if not stripped:
            return None
        kind = "group_text"
    elif contact_vcf is not None or contact_hash is not None:
        kind = "contact"
    elif folded in {"/start", "start"}:
        kind = "start"
    elif folded.startswith("/start ") or folded.startswith("start "):
        kind = "start"
        start_payload = _payload(stripped.split(None, 1)[1])
    elif stripped:
        kind = "text"
    elif photo_token or photo_url:
        kind = "photo"
    else:
        return None
    mid = body.get("mid")
    return Incoming(
        kind=kind,
        dedup_key=str(mid) if mid else None,
        max_user_id=str(sender["user_id"]),
        chat_id=_chat_id(recipient.get("chat_id")),
        name=_name(sender),
        text=stripped or None,
        photo_token=photo_token,
        photo_url=photo_url,
        start_payload=start_payload,
        contact_vcf=contact_vcf,
        contact_hash=contact_hash,
    )


def _contact(attachments: list) -> tuple[str | None, str | None]:
    for attachment in attachments:
        if not isinstance(attachment, dict) or attachment.get("type") != "contact":
            continue
        payload = attachment.get("payload")
        source = payload if isinstance(payload, dict) else attachment
        vcf = source.get("vcf_info") if isinstance(source, dict) else None
        digest = source.get("hash") if isinstance(source, dict) else None
        return (
            vcf if isinstance(vcf, str) else "",
            digest if isinstance(digest, str) else "",
        )
    return None, None


def _image(attachments: list) -> tuple[str | None, str | None]:
    for attachment in attachments:
        if not isinstance(attachment, dict) or attachment.get("type") != "image":
            continue
        payload = attachment.get("payload") or {}
        if not isinstance(payload, dict):
            return None, None
        token = payload.get("token")
        url = payload.get("url")
        return (str(token) if token else None, str(url) if url else None)
    return None, None


def _payload(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()[:128]
    return cleaned or None


def _name(user: dict) -> str:
    parts = [user.get("first_name") or "", user.get("last_name") or ""]
    name = " ".join(part for part in parts if part).strip()
    return (name or "Ученик")[:200]


def _chat_id(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None
