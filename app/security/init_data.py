import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 3600) -> str | None:
    """Вернуть user.id из подписанного initData.

    Это поле из документации мини-приложения. Его нельзя подставлять
    в user_id бота, пока живая сверка не подтвердит, что числа равны.
    """
    fields = read_init_data(init_data, bot_token, max_age_seconds)
    if fields is None:
        return None
    return fields["user_id"]


def read_init_data(init_data: str, bot_token: str, max_age_seconds: int = 3600) -> dict | None:
    """Проверить подпись и вернуть user_id и start_param. start_param есть в Bridge."""
    pairs = parse_qsl(init_data, keep_blank_values=True)
    hash_values = [value for key, value in pairs if key == "hash"]
    if len(hash_values) != 1:
        return None
    items = [(key, value) for key, value in pairs if key != "hash"]
    fields = dict(items)
    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError):
        return None
    if time.time() - auth_date > max_age_seconds:
        return None
    check = "\n".join(sorted(f"{key}={value}" for key, value in items))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, hash_values[0]):
        return None
    try:
        user = json.loads(fields["user"])
        user_id = str(user["id"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
    return {"user_id": user_id, "start_param": fields.get("start_param") or ""}
