"""Проверка контакта MAX. Полный номер не пишем в лог и не отдаём в кабинет."""

import hmac
import re
from hashlib import sha256


def verify_contact_hash(vcf_info: str, digest: str, bot_token: str) -> bool:
    """HMAC-SHA256(token, vcf_info). Это не подпись initData и не хеш телефона из мини-приложения."""
    if not vcf_info or not digest or not bot_token:
        return False
    computed = hmac.new(bot_token.encode(), vcf_info.encode(), sha256).hexdigest()
    if len(computed) != len(digest):
        return False
    return hmac.compare_digest(computed, digest)


def phone_from_vcard(vcf_info: str) -> str | None:
    for raw in vcf_info.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        head, sep, value = raw.partition(":")
        if not sep:
            continue
        if head.split(";", 1)[0].strip().upper() == "TEL" and value.strip():
            return value.strip()
    return None


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if not 11 <= len(digits) <= 15:
        return None
    return digits


def mask_phone(digits: str) -> str:
    tail = digits[-4:]
    return f"+{digits[0]} ··· ·· {tail[:2]}-{tail[2:]}"


def hash_phone(secret: str, digits: str) -> str:
    return hmac.new(secret.encode(), f"phone:{digits}".encode(), sha256).hexdigest()
