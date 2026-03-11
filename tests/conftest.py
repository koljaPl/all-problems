"""
Общие pytest-фикстуры для всех тестов.

Используем in-memory SQLite для изоляции тестов.
"""

from __future__ import annotations

import os
import pytest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Устанавливаем переменную окружения ДО импорта конфига
os.environ.setdefault("LCT_DATA_DIR", "/tmp/lct_test")

from src.db.models import (
    Base,
    Difficulty,
    Problem,
    PracticeSession,
    ReviewSchedule,
    SessionStatus,
    SessionType,
    run_migrations,
)
from src.db.repository import (
    ProblemRepository,
    ReviewRepository,
    SessionRepository,
)


@pytest.fixture
def engine():
    """Движок SQLite в памяти — каждый тест получает чистую БД."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    run_migrations(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine):
    """ORM-сессия, привязанная к in-memory БД."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def prob_repo(db_session):
    return ProblemRepository(db_session)


@pytest.fixture
def sess_repo(db_session):
    return SessionRepository(db_session)


@pytest.fixture
def review_repo(db_session):
    return ReviewRepository(db_session)


# ---------------------------------------------------------------------------
# Фабричные фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def make_problem(prob_repo, db_session):
    """Фабрика задач для тестов."""
    def _factory(
        slug: str = "two-sum",
        title: str = "Two Sum",
        difficulty: str = "Easy",
        tags: list[str] | None = None,
        frontend_id: int = 1,
    ) -> Problem:
        p = prob_repo.create(
            slug=slug,
            title=title,
            difficulty=Difficulty(difficulty),
            tags=tags or ["array", "hash-table"],
            url=f"https://leetcode.com/problems/{slug}/",
            frontend_id=frontend_id,
        )
        db_session.commit()
        return p

    return _factory


@pytest.fixture
def sample_problem(make_problem) -> Problem:
    """Стандартная тестовая задача."""
    return make_problem()


@pytest.fixture
def make_finished_session(sess_repo, db_session):
    """Фабрика завершённых сессий."""
    def _factory(
        problem: Problem,
        session_type: str = "new",
        duration_secs: int = 600,
        started_offset_days: int = 0,
    ) -> PracticeSession:
        now = datetime.utcnow() - timedelta(days=started_offset_days)
        session = PracticeSession(
            problem_id=problem.id,
            session_type=SessionType(session_type),
            status=SessionStatus.RUNNING,
            started_at=now,
            total_paused_secs=0,
        )
        db_session.add(session)
        db_session.flush()

        # Завершаем
        session.finished_at = now + timedelta(seconds=duration_secs)
        session.status = SessionStatus.FINISHED
        session.net_duration_secs = duration_secs
        db_session.commit()
        return session

    return _factory