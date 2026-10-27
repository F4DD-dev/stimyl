import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 3600) -> str | None:
    """Return the MAX user id when initData is valid. Never trust initDataUnsafe."""
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
        return str(user["id"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
