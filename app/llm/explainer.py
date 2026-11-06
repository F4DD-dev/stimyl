"""Помощник на модели. Модель объясняет, читает фото и предлагает задания.
Принять ли эталон и засчитать ли ответ, решает код (app.domain.assist, app.domain.answers)."""

import base64
import logging
from typing import Protocol

from app.core.config import Settings
from app.domain.assist import LessonDraft, TaskDraft, TeacherAsk, plain, task_confirmed
from app.llm import prompts
from app.llm.client import ChatClient, loads_object
from app.llm.gigachat import GigaChatClient

logger = logging.getLogger(__name__)


class Explainer(Protocol):
    enabled: bool

    async def explain_topic(self, topic_title: str) -> str | None: ...

    async def explain_mistake(
        self, topic_title: str, hint: str, *, prompt: str = "", answer: str = ""
    ) -> str | None: ...

    async def read_photo(self, image: bytes, mime: str) -> str | None: ...

    async def analyze(
        self,
        question: str,
        topics: list[str],
        fragments: list[str],
        history: list[tuple[str, str]],
        image: tuple[bytes, str] | None = None,
    ) -> LessonDraft | None: ...

    async def confirm(self, task: TaskDraft | None) -> bool: ...

    async def make_task(self, topic: str, level: str, fragments: list[str]) -> TaskDraft | None: ...

    async def draft_work(
        self, topic: str, goal: str, count: int, difficulty: str, fragments: list[str]
    ) -> list[tuple[TaskDraft, bool]] | None: ...

    async def read_teacher(self, text: str, topics: list[str]) -> TeacherAsk | None: ...

    async def teacher_reply(self, text: str) -> str | None: ...

    async def topic_from_fragments(self, fragments: list[str]) -> str | None: ...


class NullExplainer:
    enabled = False
    last_error = ""

    async def explain_topic(self, topic_title: str) -> str | None:
        return None

    async def explain_mistake(
        self, topic_title: str, hint: str, *, prompt: str = "", answer: str = ""
    ) -> str | None:
        return None

    async def read_photo(self, image: bytes, mime: str) -> str | None:
        return None

    async def analyze(self, question, topics, fragments, history, image=None) -> LessonDraft | None:
        return None

    async def confirm(self, task: TaskDraft | None) -> bool:
        return False

    async def make_task(self, topic: str, level: str, fragments: list[str]) -> TaskDraft | None:
        return None

    async def draft_work(self, topic, goal, count, difficulty, fragments):
        return None

    async def read_teacher(self, text: str, topics: list[str]) -> TeacherAsk | None:
        return None

    async def teacher_reply(self, text: str) -> str | None:
        return None

    async def topic_from_fragments(self, fragments: list[str]) -> str | None:
        return None


def topic_prompt(topic_title: str) -> str:
    return (
        f"Объясни тему школьной математики 8 класса «{topic_title}» "
        "в двух коротких предложениях. Не решай задачу ученика и не называй числовой ответ."
    )


def mistake_prompt(topic_title: str, hint: str) -> str:
    return (
        f"Тема «{topic_title}». Ученик ошибся в похожем задании. "
        f"Объясни способ в одном предложении, без числового ответа. Опора: {hint}"
    )


def _task(raw: object) -> TaskDraft | None:
    if not isinstance(raw, dict):
        return None
    prompt = plain(str(raw.get("prompt") or ""), 500)
    answer = str(raw.get("answer") or "").strip()[:64]
    if not prompt or not answer:
        return None
    return TaskDraft(
        prompt=prompt,
        answer=answer,
        hint=plain(str(raw.get("hint") or ""), 300),
        first_step=plain(str(raw.get("first_step") or ""), 300),
    )


class LlmTutor:
    enabled = True

    def __init__(
        self, settings: Settings, client: ChatClient | GigaChatClient | None = None
    ) -> None:
        self._chat = client or ChatClient(settings)
        self._reasoning = settings.llm_reasoning
        self._verify = settings.llm_verify
        self._topics = settings.llm_explain_topics
        self._mistakes = settings.llm_explain_mistakes

    @property
    def last_error(self) -> str:
        return getattr(self._chat, "last_error", "") or ""

    async def explain_topic(self, topic_title: str) -> str | None:
        if not self._topics:
            return None
        text = await self._chat.chat(
            [
                {"role": "system", "content": prompts.EXPLAIN_SYSTEM},
                {"role": "user", "content": topic_prompt(topic_title)},
            ],
            max_tokens=300,
            purpose="explain",
        )
        return plain(text, 800) or None

    async def explain_mistake(
        self, topic_title: str, hint: str, *, prompt: str = "", answer: str = ""
    ) -> str | None:
        if not self._mistakes:
            return None
        parts = [f"Тема «{topic_title}»."]
        if prompt:
            parts.append(f"Задание: {prompt}")
        if answer:
            parts.append(f"Ответ ученика: {answer}")
        if hint:
            parts.append(f"Подсказка учителя к заданию: {hint}")
        text = await self._chat.chat(
            [
                {"role": "system", "content": prompts.MISTAKE_SYSTEM},
                {"role": "user", "content": "\n".join(parts)},
            ],
            max_tokens=250,
            purpose="mistake",
        )
        return plain(text, 500) or None

    async def read_photo(self, image: bytes, mime: str) -> str | None:
        encoded = base64.b64encode(image).decode("ascii")
        text = await self._chat.chat(
            [
                {"role": "system", "content": prompts.OCR_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Перепиши задание с этого снимка."},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                    ],
                },
            ],
            model=self._chat.vision_model,
            max_tokens=900,
            temperature=0,
            purpose="ocr",
        )
        return plain(text, 3000) or None

    async def analyze(
        self,
        question: str,
        topics: list[str],
        fragments: list[str],
        history: list[tuple[str, str]],
        image: tuple[bytes, str] | None = None,
    ) -> LessonDraft | None:
        """Один запрос на вопрос: снимок читается тут же, без отдельного OCR."""
        context = [prompts.topics_block(topics)]
        if fragments:
            context.append(prompts.fragments_block(fragments))
        if history:
            lines = [f"{'Ученик' if role == 'student' else 'Стимул'}: {text[:400]}" for role, text in history]
            context.append("Недавняя переписка:\n" + "\n".join(lines))
        if image is not None:
            context.append(prompts.PHOTO_NOTE)
        context.append(f"Вопрос ученика:\n{question[:3000] or '(только фото)'}")
        context.append(prompts.ANALYZE_FORMAT)
        content: str | list = "\n\n".join(context)
        if image is not None:
            blob, mime = image
            encoded = base64.b64encode(blob).decode("ascii")
            content = [
                {"type": "text", "text": content},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ]
        raw = await self._chat.chat(
            [
                {"role": "system", "content": prompts.TUTOR_SYSTEM},
                {"role": "user", "content": content},
            ],
            model=self._chat.vision_model if image is not None else None,
            json_mode=True,
            max_tokens=1200,
            purpose="analyze",
        )
        data = loads_object(raw)
        if data is None:
            return None
        topic = data.get("topic")
        return LessonDraft(
            topic=str(topic).strip() if isinstance(topic, str) else None,
            explanation=plain(str(data.get("explanation") or ""), 900),
            example=plain(str(data.get("example") or ""), 700),
            task=_task(data.get("task")),
            original_answer=str(data.get("original_answer") or "").strip()[:64],
            off_topic=bool(data.get("off_topic")),
            unreadable=bool(data.get("unreadable")),
        )

    async def solve_many(self, tasks: list[str]) -> list[str | None]:
        """Независимое решение пачкой: один запрос на всю работу."""
        if not tasks:
            return []
        numbered = "\n".join(f"{index}. {text[:600]}" for index, text in enumerate(tasks, start=1))
        raw = await self._chat.chat(
            [
                {"role": "system", "content": prompts.SOLVE_SYSTEM},
                {"role": "user", "content": numbered},
            ],
            json_mode=True,
            reasoning=self._reasoning,
            max_tokens=120 + 60 * len(tasks),
            temperature=0,
            purpose="solve",
        )
        data = loads_object(raw)
        answers = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(answers, list):
            return [None] * len(tasks)
        cleaned = [str(item).strip()[:64] if item is not None else None for item in answers]
        return (cleaned + [None] * len(tasks))[: len(tasks)]

    async def confirm(self, task: TaskDraft | None) -> bool:
        if task is None:
            return False
        if not self._verify:
            return task_confirmed(task, task.answer)
        return task_confirmed(task, (await self.solve_many([task.prompt]))[0])

    async def make_task(self, topic: str, level: str, fragments: list[str]) -> TaskDraft | None:
        items = await self._draft(
            topic,
            "одно задание для самостоятельной тренировки",
            1,
            "hard" if level == "hard" else "easy",
            fragments,
        )
        for task in items or []:
            if await self.confirm(task):
                return task
        return None

    async def draft_work(
        self, topic: str, goal: str, count: int, difficulty: str, fragments: list[str]
    ) -> list[tuple[TaskDraft, bool]] | None:
        items = await self._draft(topic, goal, count, difficulty, fragments)
        if not items:
            return None
        items = items[:count]
        if not self._verify:
            return [(task, task_confirmed(task, task.answer)) for task in items]
        solved = await self.solve_many([task.prompt for task in items])
        return [(task, task_confirmed(task, answer)) for task, answer in zip(items, solved, strict=True)]

    async def _draft(
        self, topic: str, goal: str, count: int, difficulty: str, fragments: list[str]
    ) -> list[TaskDraft] | None:
        level = {"easy": "проще среднего", "hard": "сложнее среднего"}.get(difficulty, "средней сложности")
        context = [
            f"Тема: {topic[:200]}",
            f"Что проверить: {goal[:300]}",
            f"Сколько заданий: {count}. Сложность: {level}.",
        ]
        if fragments:
            context.append(prompts.fragments_block(fragments))
        context.append(prompts.DRAFT_FORMAT)
        raw = await self._chat.chat(
            [
                {"role": "system", "content": prompts.DRAFT_SYSTEM},
                {"role": "user", "content": "\n\n".join(context)},
            ],
            json_mode=True,
            reasoning=self._reasoning,
            max_tokens=400 + 220 * count,
            temperature=0.6,
            purpose="draft",
        )
        data = loads_object(raw)
        rows = data.get("items") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return None
        items = [task for task in (_task(row) for row in rows) if task is not None]
        return items or None

    async def read_teacher(self, text: str, topics: list[str]) -> TeacherAsk | None:
        raw = await self._chat.chat(
            [
                {"role": "system", "content": prompts.TEACHER_SYSTEM},
                {
                    "role": "user",
                    "content": f"{prompts.topics_block(topics)}\n\nПросьба учителя:\n{text[:1500]}\n\n"
                    f"{prompts.TEACHER_FORMAT}",
                },
            ],
            json_mode=True,
            max_tokens=300,
            temperature=0,
            purpose="teacher",
        )
        data = loads_object(raw)
        if data is None:
            return None
        intent = str(data.get("intent") or "other").strip()
        try:
            count = int(data.get("count") or 3)
        except (TypeError, ValueError):
            count = 3
        difficulty = str(data.get("difficulty") or "normal")
        students = data.get("students") if isinstance(data.get("students"), list) else []
        return TeacherAsk(
            intent=intent if intent in {"work", "summary", "chat", "other"} else "other",
            topic=plain(str(data.get("topic") or ""), 200),
            goal=plain(str(data.get("goal") or ""), 300),
            count=max(1, min(6, count)),
            difficulty=difficulty if difficulty in {"easy", "normal", "hard"} else "normal",
            students=tuple(str(item)[:200] for item in students if str(item).strip())[:40],
            use_material=bool(data.get("use_material")),
            reply=plain(str(data.get("reply") or ""), 600),
        )

    async def teacher_reply(self, text: str) -> str | None:
        raw = await self._chat.chat(
            [
                {"role": "system", "content": prompts.TEACHER_CHAT_SYSTEM},
                {"role": "user", "content": text[:1000]},
            ],
            max_tokens=300,
            temperature=0.5,
            purpose="teacher_chat",
        )
        return plain(raw, 600) or None

    async def topic_from_fragments(self, fragments: list[str]) -> str | None:
        if not fragments:
            return None
        joined = "\n---\n".join(fragment[:1200] for fragment in fragments[:6])
        raw = await self._chat.chat(
            [
                {"role": "system", "content": prompts.MATERIAL_TOPIC_SYSTEM},
                {"role": "user", "content": joined},
            ],
            max_tokens=60,
            temperature=0,
            purpose="topic",
        )
        return plain(raw, 120) or None


def build_explainer(settings: Settings) -> Explainer:
    if not settings.feature_llm or not settings.llm_base_url:
        return NullExplainer()
    base = settings.llm_base_url
    if "giga.chat" in base or "sberbank" in base:
        if not settings.llm_api_key:
            logger.warning("gigachat is set without LLM_API_KEY, assistant is off")
            return NullExplainer()
        return LlmTutor(settings, client=GigaChatClient(settings))
    if "openrouter.ai" in base and not settings.llm_api_key:
        logger.warning("openrouter is set without LLM_API_KEY, assistant is off")
        return NullExplainer()
    return LlmTutor(settings)
