"""Проверка и очистка снимка до отправки модели: без EXIF и геометки."""

import struct


def image_kind(blob: bytes) -> str | None:
    if blob.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(blob) >= 12 and blob.startswith(b"RIFF") and blob[8:12] == b"WEBP":
        return "webp"
    if blob.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return None


MIME = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}


def strip_metadata(blob: bytes) -> bytes:
    kind = image_kind(blob)
    try:
        if kind == "jpeg":
            return _jpeg(blob)
        if kind == "png":
            return _png(blob)
    except (IndexError, struct.error):
        return blob
    return blob


def _jpeg(blob: bytes) -> bytes:
    out = bytearray(blob[:2])
    index = 2
    while index + 4 <= len(blob):
        if blob[index] != 0xFF:
            return blob
        marker = blob[index + 1]
        if marker == 0xDA:
            out += blob[index:]
            return bytes(out)
        length = struct.unpack(">H", blob[index + 2 : index + 4])[0]
        segment = blob[index : index + 2 + length]
        if not (0xE1 <= marker <= 0xEF or marker == 0xFE):
            out += segment
        index += 2 + length
    return blob


_PNG_DROP = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}


def _png(blob: bytes) -> bytes:
    out = bytearray(blob[:8])
    index = 8
    while index + 12 <= len(blob):
        length = struct.unpack(">I", blob[index : index + 4])[0]
        kind = blob[index + 4 : index + 8]
        chunk = blob[index : index + 12 + length]
        if kind not in _PNG_DROP:
            out += chunk
        index += 12 + length
        if kind == b"IEND":
            break
    return bytes(out)
