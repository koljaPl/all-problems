"""
Модели базы данных (SQLAlchemy 2.0 Declarative API).

Схема БД:
  problems         — задачи LeetCode (slug, title, difficulty, tags, url)
  practice_sessions — сессии практики с трекингом времени
  review_schedule  — расписание повторений

Миграции выполняются через migrate() при каждом запуске (idempotent).
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedColumn,
    mapped_column,
    relationship,
    sessionmaker,
)

from config import DB_PATH


# ---------------------------------------------------------------------------
# Перечисления
# ---------------------------------------------------------------------------

class Difficulty(str, PyEnum):
    """Уровень сложности задачи на LeetCode."""
    EASY   = "Easy"
    MEDIUM = "Medium"
    HARD   = "Hard"


class SessionType(str, PyEnum):
    """Тип сессии: новая задача или повторение."""
    NEW    = "new"
    REVIEW = "review"


class SessionStatus(str, PyEnum):
    """Текущий статус сессии практики."""
    RUNNING  = "running"   # таймер запущен
    PAUSED   = "paused"    # таймер на паузе
    FINISHED = "finished"  # сессия завершена


# ---------------------------------------------------------------------------
# Базовый класс
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Общий базовый класс для всех моделей."""
    pass


# ---------------------------------------------------------------------------
# Таблица: задачи
# ---------------------------------------------------------------------------

class Problem(Base):
    """
    Задача LeetCode.

    Поля:
      slug        — уникальный идентификатор задачи (используется в URL)
      title       — полное название задачи
      difficulty  — уровень сложности (Easy/Medium/Hard)
      tags        — JSON-массив строк с тегами/топиками задачи
      url         — прямая ссылка на задачу
      added_at    — дата добавления в трекер
      frontend_id — номер задачи на LeetCode (например, 1, 42, 200)
    """
    __tablename__ = "problems"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug:        Mapped[str]           = mapped_column(String(200), unique=True, nullable=False, index=True)
    title:       Mapped[str]           = mapped_column(String(500), nullable=False)
    difficulty:  Mapped[Difficulty]    = mapped_column(Enum(Difficulty), nullable=False)
    tags_json:   Mapped[str]           = mapped_column(Text, default="[]", nullable=False)
    url:         Mapped[str]           = mapped_column(String(500), nullable=False)
    added_at:    Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    frontend_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Связи
    sessions:        Mapped[list["PracticeSession"]] = relationship("PracticeSession", back_populates="problem", cascade="all, delete-orphan")
    review_schedule: Mapped[list["ReviewSchedule"]]  = relationship("ReviewSchedule", back_populates="problem", cascade="all, delete-orphan")

    # ---------------------------------------------------------------------------
    # Вспомогательные свойства
    # ---------------------------------------------------------------------------

    @property
    def tags(self) -> list[str]:
        """Теги задачи как список Python-строк."""
        try:
            return json.loads(self.tags_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self.tags_json = json.dumps(value, ensure_ascii=False)

    def __repr__(self) -> str:
        return f"<Problem id={self.id} slug={self.slug!r} difficulty={self.difficulty.value}>"


# ---------------------------------------------------------------------------
# Таблица: сессии практики
# ---------------------------------------------------------------------------

class PracticeSession(Base):
    """
    Одна сессия решения задачи.

    Трекер времени:
      started_at         — момент старта
      finished_at        — момент завершения (NULL если не завершена)
      total_paused_secs  — суммарное время на паузе (секунды)
      last_paused_at     — момент последней паузы (для расчёта длительности паузы)
      net_duration_secs  — итоговое чистое время (секунды); может быть скорректировано вручную
      is_corrected       — True если время было скорректировано вручную
      status             — текущий статус (running/paused/finished)
      session_type       — новая задача или повторение
      notes              — произвольные заметки по сессии
    """
    __tablename__ = "practice_sessions"

    id:                 Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    problem_id:         Mapped[int]            = mapped_column(Integer, ForeignKey("problems.id"), nullable=False, index=True)
    session_type:       Mapped[SessionType]    = mapped_column(Enum(SessionType), nullable=False)
    status:             Mapped[SessionStatus]  = mapped_column(Enum(SessionStatus), default=SessionStatus.RUNNING, nullable=False)

    started_at:         Mapped[datetime]       = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at:        Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_paused_at:     Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    total_paused_secs:  Mapped[int]            = mapped_column(Integer, default=0, nullable=False)
    net_duration_secs:  Mapped[Optional[int]]  = mapped_column(Integer, nullable=True)
    is_corrected:       Mapped[bool]           = mapped_column(Boolean, default=False, nullable=False)

    notes:              Mapped[Optional[str]]  = mapped_column(Text, nullable=True)

    # Связи
    problem:           Mapped["Problem"]          = relationship("Problem", back_populates="sessions")
    review_entry:      Mapped[Optional["ReviewSchedule"]] = relationship("ReviewSchedule", back_populates="session", uselist=False)

    # ---------------------------------------------------------------------------
    # Вспомогательные методы
    # ---------------------------------------------------------------------------

    def compute_net_seconds(self, now: Optional[datetime] = None) -> int:
        """
        Вычисляет чистое время (без пауз) в секундах.

        Если сессия ещё идёт — считает до текущего момента.
        Если время было скорректировано вручную — возвращает скорректированное.
        """
        if self.is_corrected and self.net_duration_secs is not None:
            return self.net_duration_secs

        end = self.finished_at or now or datetime.utcnow()
        gross = (end - self.started_at).total_seconds()

        paused = self.total_paused_secs
        # Если сейчас на паузе — добавляем текущую длительность паузы
        if self.status == SessionStatus.PAUSED and self.last_paused_at:
            paused += (end - self.last_paused_at).total_seconds()

        return max(0, int(gross - paused))

    def __repr__(self) -> str:
        return (
            f"<PracticeSession id={self.id} problem_id={self.problem_id} "
            f"type={self.session_type.value} status={self.status.value}>"
        )


# ---------------------------------------------------------------------------
# Таблица: расписание повторений
# ---------------------------------------------------------------------------

class ReviewSchedule(Base):
    """
    Запись о запланированном повторении задачи.

    Когда пользователь решает задачу первый раз (session_type=new),
    создаётся запись с scheduled_for = started_at + REVIEW_INTERVAL_DAYS.
    При выполнении повторения — заполняется completed_at.
    """
    __tablename__ = "review_schedule"

    id:           Mapped[int]              = mapped_column(Integer, primary_key=True, autoincrement=True)
    problem_id:   Mapped[int]              = mapped_column(Integer, ForeignKey("problems.id"), nullable=False, index=True)
    session_id:   Mapped[Optional[int]]    = mapped_column(Integer, ForeignKey("practice_sessions.id"), nullable=True)
    scheduled_for: Mapped[datetime]        = mapped_column(DateTime, nullable=False, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Связи
    problem: Mapped["Problem"]                   = relationship("Problem", back_populates="review_schedule")
    session: Mapped[Optional["PracticeSession"]] = relationship("PracticeSession", back_populates="review_entry")

    @property
    def is_due(self) -> bool:
        """True если повторение уже наступило и ещё не выполнено."""
        return self.completed_at is None and self.scheduled_for <= datetime.utcnow()

    def __repr__(self) -> str:
        return (
            f"<ReviewSchedule id={self.id} problem_id={self.problem_id} "
            f"scheduled_for={self.scheduled_for.date()} completed={self.completed_at is not None}>"
        )


# ---------------------------------------------------------------------------
# Движок и фабрика сессий
# ---------------------------------------------------------------------------

def create_db_engine(db_path: str | None = None):
    """
    Создаёт движок SQLAlchemy для SQLite.

    Args:
        db_path: путь к файлу БД; если None — берётся из конфига.
    """
    path = db_path or str(DB_PATH)
    # check_same_thread=False нужен для SQLite при многопоточности
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        echo=False,  # установи True для отладки SQL-запросов
    )
    return engine


def get_session_factory(engine=None):
    """Возвращает фабрику ORM-сессий."""
    if engine is None:
        engine = create_db_engine()
    return sessionmaker(bind=engine, autoflush=True, autocommit=False)


# ---------------------------------------------------------------------------
# Миграции (idempotent)
# ---------------------------------------------------------------------------

def run_migrations(engine) -> None:
    """
    Применяет миграции схемы БД.

    Стратегия: CREATE TABLE IF NOT EXISTS + ALTER TABLE ADD COLUMN IF NOT EXISTS.
    Это позволяет безопасно добавлять новые поля в существующую БД без потери данных.
    Порядок миграций зафиксирован и не меняется.
    """
    # Создаём все таблицы, которых ещё нет
    Base.metadata.create_all(engine)

    # Дополнительные ALTER миграции для совместимости с будущими версиями
    _migrations = [
        # Миграция 001: добавить frontend_id если его нет (для апгрейда с v0.x)
        "ALTER TABLE problems ADD COLUMN frontend_id INTEGER",
        # Миграция 002: добавить notes в practice_sessions
        "ALTER TABLE practice_sessions ADD COLUMN notes TEXT",
    ]

    with engine.connect() as conn:
        for stmt in _migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                # SQLite бросает исключение если колонка уже существует — игнорируем
                conn.rollback()


def init_db(db_path: str | None = None):
    """
    Инициализирует БД: создаёт движок, применяет миграции.

    Returns:
        (engine, SessionFactory)
    """
    engine = create_db_engine(db_path)
    run_migrations(engine)
    factory = get_session_factory(engine)
    return engine, factory