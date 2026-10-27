import hashlib
import hmac
import time

COOKIE_NAME = "stimul_session"
MAX_AGE_SECONDS = 12 * 60 * 60


def write_cookie(secret: str, role: str, max_user_id: str, now: int | None = None) -> str:
    issued = int(time.time()) if now is None else now
    exp = issued + MAX_AGE_SECONDS
    payload = f"{role}:{max_user_id}:{exp}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_cookie(secret: str, value: str, now: int | None = None) -> tuple[str, str] | None:
    payload, separator, signature = value.rpartition(".")
    if not separator:
        return None
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    role, rest = payload.split(":", 1)
    max_user_id, exp_raw = rest.rsplit(":", 1)
    try:
        exp = int(exp_raw)
    except ValueError:
        return None
    current = int(time.time()) if now is None else now
    if exp < current:
        return None
    if role not in {"student", "teacher"} or not max_user_id:
        return None
    return role, max_user_id
