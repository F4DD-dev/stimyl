"""Материал урока: текст из файла и фрагменты. Задания по материалу берутся только отсюда."""

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

MAX_TEXT = 300_000
MAX_CHUNKS = 400
CHUNK_SIZE = 1200
_ZIP_LIMIT = 60 * 1024 * 1024
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

NO_TEXT = "В файле нет текста. Если это скан, загрузите фото страниц."
UNSUPPORTED = "Подойдёт PDF, DOCX, PPTX, TXT или фото страницы."


@dataclass(frozen=True)
class Extracted:
    text: str
    error: str | None = None


def file_kind(filename: str, blob: bytes) -> str | None:
    name = (filename or "").casefold()
    if blob.startswith(b"%PDF"):
        return "pdf"
    if blob.startswith(b"PK"):
        if name.endswith(".docx"):
            return "docx"
        if name.endswith(".pptx"):
            return "pptx"
        return None
    if name.endswith((".txt", ".md")):
        return "txt"
    return None


def extract_text(filename: str, blob: bytes) -> Extracted:
    kind = file_kind(filename, blob)
    try:
        if kind == "pdf":
            text = _pdf(blob)
        elif kind == "docx":
            text = _docx(blob)
        elif kind == "pptx":
            text = _pptx(blob)
        elif kind == "txt":
            text = _txt(blob)
        else:
            return Extracted("", UNSUPPORTED)
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, ValueError):
        return Extracted("", "Файл не открылся. Проверьте, что он не повреждён.")
    except Exception:
        return Extracted("", "Файл не открылся. Проверьте, что он не повреждён.")
    text = normalize(text)
    if len(text) < 40:
        return Extracted("", NO_TEXT)
    return Extracted(text[:MAX_TEXT])


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\x00", "")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"-\n(?=[а-яёa-z])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Фрагменты по абзацам. Длинный абзац режется по предложениям."""
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= size:
            pieces.append(paragraph)
            continue
        current = ""
        for sentence in re.split(r"(?<=[.!?…])\s+", paragraph):
            if current and len(current) + len(sentence) + 1 > size:
                pieces.append(current)
                current = ""
            while len(sentence) > size:
                pieces.append(sentence[:size])
                sentence = sentence[size:]
            current = f"{current} {sentence}".strip()
        if current:
            pieces.append(current)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 2 > size:
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{piece}".strip()
    if current:
        chunks.append(current)
    return chunks[:MAX_CHUNKS]


def _guard_zip(archive: zipfile.ZipFile) -> None:
    if sum(item.file_size for item in archive.infolist()) > _ZIP_LIMIT:
        raise ValueError("archive too large")


def _docx(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        _guard_zip(archive)
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    lines = []
    for paragraph in root.iter(f"{_W}p"):
        line = "".join(node.text or "" for node in paragraph.iter(f"{_W}t"))
        lines.append(line)
    return "\n\n".join(line for line in lines if line.strip())


def _pptx(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        _guard_zip(archive)
        names = [
            name
            for name in archive.namelist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        ]
        names.sort(key=lambda name: int(re.search(r"(\d+)", name).group(1)))
        slides = []
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            lines = [
                "".join(node.text or "" for node in paragraph.iter(f"{_A}t"))
                for paragraph in root.iter(f"{_A}p")
            ]
            slide = "\n".join(line for line in lines if line.strip())
            if slide:
                slides.append(slide)
    return "\n\n".join(slides)


def _pdf(blob: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(blob))
    pages = []
    for page in reader.pages[:400]:
        pages.append(page.extract_text() or "")
        if sum(len(item) for item in pages) > MAX_TEXT:
            break
    return "\n\n".join(pages)


def _txt(blob: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return blob.decode(encoding)
        except UnicodeDecodeError:
            continue
    return blob.decode("utf-8", errors="ignore")
