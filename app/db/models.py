from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('student', 'teacher')", name="ck_users_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    max_user_id: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(200))


class SchoolClass(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(64), unique=True)


class ClassTeacher(Base):
    __tablename__ = "class_teachers"

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)


class Enrollment(Base):
    __tablename__ = "enrollments"

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), unique=True)


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("subject_id", "position", name="uq_topics_subject_position"),
        UniqueConstraint("subject_id", "title", name="uq_topics_subject_title"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    title: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer)


class LearningSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("mode IN ('training', 'submission')", name="ck_sessions_mode"),
        CheckConstraint(
            "step IN ('explain', 'practice', 'check', 'done')",
            name="ck_sessions_step",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    step: Mapped[str] = mapped_column(String(16))
    example_index: Mapped[int] = mapped_column(Integer, default=0)
    task_index: Mapped[int] = mapped_column(Integer, default=0)
    pending_answer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_hint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pending_prompt: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    photo_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    topic: Mapped[Topic | None] = relationship()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('student', 'bot')", name="ck_messages_role"),
        CheckConstraint(
            "visibility IN ('private', 'submission')",
            name="ck_messages_visibility",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(String(4000))
    visibility: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint("mode IN ('training', 'submission')", name="ck_attempts_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    mode: Mapped[str] = mapped_column(String(16))
    prompt: Mapped[str] = mapped_column(String(500))
    expected: Mapped[str] = mapped_column(String(64))
    answer: Mapped[str] = mapped_column(String(200))
    correct: Mapped[bool] = mapped_column(Boolean)
    feedback: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TopicState(Base):
    __tablename__ = "topic_states"
    __table_args__ = (
        UniqueConstraint("user_id", "topic_id", name="uq_topic_states_user_topic"),
        CheckConstraint(
            "status IN ('mastered', 'needs_practice', 'repeat')",
            name="ck_topic_states_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    status: Mapped[str] = mapped_column(String(32))
    correct_ratio: Mapped[float] = mapped_column(Float)
    attempts_count: Mapped[int] = mapped_column(Integer)
    has_recheck: Mapped[bool] = mapped_column(Boolean)
    last_attempt_on: Mapped[date] = mapped_column(Date)


class InboundEvent(Base):
    __tablename__ = "inbound_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(200), unique=True)


class RuntimeFlag(Base):
    __tablename__ = "runtime_flags"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))
