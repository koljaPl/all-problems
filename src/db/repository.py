"""
Слой доступа к данным (Repository pattern).

Все операции с БД изолированы здесь, CLI и бизнес-логика
не работают с ORM-сессиями напрямую.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session as OrmSession

from config import REVIEW_INTERVAL_DAYS
from db.models import (
    Difficulty,
    Problem,
    PracticeSession,
    ReviewSchedule,
    SessionStatus,
    SessionType,
)


# ---------------------------------------------------------------------------
# Репозиторий задач
# ---------------------------------------------------------------------------

class ProblemRepository:
    """CRUD-операции над таблицей problems."""

    def __init__(self, db: OrmSession) -> None:
        self.db = db

    def get_by_slug(self, slug: str) -> Optional[Problem]:
        """Найти задачу по slug."""
        return self.db.query(Problem).filter(Problem.slug == slug).first()

    def get_by_id(self, problem_id: int) -> Optional[Problem]:
        """Найти задачу по первичному ключу."""
        return self.db.get(Problem, problem_id)

    def list_all(self) -> list[Problem]:
        """Все задачи, отсортированные по дате добавления."""
        return self.db.query(Problem).order_by(Problem.added_at).all()

    def create(
        self,
        slug: str,
        title: str,
        difficulty: Difficulty,
        tags: list[str],
        url: str,
        frontend_id: Optional[int] = None,
    ) -> Problem:
        """Создать новую задачу. Если slug уже существует — обновить поля."""
        existing = self.get_by_slug(slug)
        if existing:
            # Обновляем актуальные данные (название/теги могли измениться)
            existing.title = title
            existing.difficulty = difficulty
            existing.tags = tags
            existing.url = url
            if frontend_id is not None:
                existing.frontend_id = frontend_id
            self.db.flush()
            return existing

        problem = Problem(
            slug=slug,
            title=title,
            difficulty=difficulty,
            tags_json="[]",
            url=url,
            frontend_id=frontend_id,
            added_at=datetime.utcnow(),
        )
        problem.tags = tags
        self.db.add(problem)
        self.db.flush()
        return problem

    def search(self, query: str) -> list[Problem]:
        """Поиск задач по подстроке в названии или slug."""
        q = f"%{query.lower()}%"
        return (
            self.db.query(Problem)
            .filter(
                Problem.slug.ilike(q) | Problem.title.ilike(q)
            )
            .all()
        )


# ---------------------------------------------------------------------------
# Репозиторий сессий практики
# ---------------------------------------------------------------------------

class SessionRepository:
    """CRUD и бизнес-операции над practice_sessions."""

    def __init__(self, db: OrmSession) -> None:
        self.db = db

    def get_by_id(self, session_id: int) -> Optional[PracticeSession]:
        return self.db.get(PracticeSession, session_id)

    def get_active(self) -> Optional[PracticeSession]:
        """
        Возвращает текущую активную сессию (running или paused).
        В любой момент должна быть не более одной.
        """
        return (
            self.db.query(PracticeSession)
            .filter(PracticeSession.status.in_([SessionStatus.RUNNING, SessionStatus.PAUSED]))
            .order_by(PracticeSession.started_at.desc())
            .first()
        )

    def start(self, problem: Problem, session_type: SessionType) -> PracticeSession:
        """
        Создать и стартовать новую сессию.

        Raises:
            RuntimeError: если уже есть активная сессия.
        """
        active = self.get_active()
        if active:
            raise RuntimeError(
                f"Уже есть активная сессия #{active.id} "
                f"(задача: {active.problem.slug}). "
                "Сначала завершите или остановите её командой 'lct stop'."
            )

        session = PracticeSession(
            problem_id=problem.id,
            session_type=session_type,
            status=SessionStatus.RUNNING,
            started_at=datetime.utcnow(),
            total_paused_secs=0,
        )
        self.db.add(session)
        self.db.flush()
        return session

    def pause(self, session: PracticeSession) -> PracticeSession:
        """Поставить сессию на паузу."""
        if session.status != SessionStatus.RUNNING:
            raise RuntimeError(f"Сессия #{session.id} не запущена (статус: {session.status.value}).")
        session.status = SessionStatus.PAUSED
        session.last_paused_at = datetime.utcnow()
        self.db.flush()
        return session

    def resume(self, session: PracticeSession) -> PracticeSession:
        """Возобновить сессию после паузы."""
        if session.status != SessionStatus.PAUSED:
            raise RuntimeError(f"Сессия #{session.id} не на паузе (статус: {session.status.value}).")

        # Считаем длительность паузы и добавляем к суммарному времени пауз
        if session.last_paused_at:
            pause_duration = (datetime.utcnow() - session.last_paused_at).total_seconds()
            session.total_paused_secs += int(pause_duration)

        session.status = SessionStatus.RUNNING
        session.last_paused_at = None
        self.db.flush()
        return session

    def finish(self, session: PracticeSession) -> PracticeSession:
        """
        Завершить сессию: зафиксировать финальное время.
        Если была на паузе — добавить последнюю паузу.
        """
        if session.status == SessionStatus.FINISHED:
            raise RuntimeError(f"Сессия #{session.id} уже завершена.")

        now = datetime.utcnow()

        # Если была на паузе в момент завершения — посчитать последнюю паузу
        if session.status == SessionStatus.PAUSED and session.last_paused_at:
            pause_duration = (now - session.last_paused_at).total_seconds()
            session.total_paused_secs += int(pause_duration)
            session.last_paused_at = None

        session.finished_at = now
        session.status = SessionStatus.FINISHED
        session.net_duration_secs = session.compute_net_seconds(now)
        self.db.flush()
        return session

    def correct_time(self, session: PracticeSession, new_seconds: int) -> PracticeSession:
        """
        Ручная коррекция времени сессии.

        Args:
            session:     сессия для коррекции (должна быть завершена).
            new_seconds: скорректированное чистое время в секундах.
        """
        if session.status != SessionStatus.FINISHED:
            raise RuntimeError("Корректировать время можно только завершённых сессий.")
        if new_seconds < 0:
            raise ValueError("Время не может быть отрицательным.")

        session.net_duration_secs = new_seconds
        session.is_corrected = True
        self.db.flush()
        return session

    def list_for_problem(self, problem_id: int) -> list[PracticeSession]:
        """Все завершённые сессии для конкретной задачи, по дате."""
        return (
            self.db.query(PracticeSession)
            .filter(
                PracticeSession.problem_id == problem_id,
                PracticeSession.status == SessionStatus.FINISHED,
            )
            .order_by(PracticeSession.started_at)
            .all()
        )

    def list_finished_in_range(
        self,
        date_from: datetime,
        date_to: datetime,
    ) -> list[PracticeSession]:
        """Завершённые сессии в заданном временном диапазоне."""
        return (
            self.db.query(PracticeSession)
            .filter(
                PracticeSession.status == SessionStatus.FINISHED,
                PracticeSession.finished_at >= date_from,
                PracticeSession.finished_at <= date_to,
            )
            .order_by(PracticeSession.finished_at)
            .all()
        )


# ---------------------------------------------------------------------------
# Репозиторий расписания повторений
# ---------------------------------------------------------------------------

class ReviewRepository:
    """CRUD-операции над таблицей review_schedule."""

    def __init__(self, db: OrmSession) -> None:
        self.db = db

    def schedule(
        self,
        problem: Problem,
        reference_date: Optional[datetime] = None,
        interval_days: int = REVIEW_INTERVAL_DAYS,
    ) -> ReviewSchedule:
        """
        Создать запись о повторении через interval_days дней.

        Args:
            problem:        задача для повторения.
            reference_date: дата от которой считать интервал (default: сейчас).
            interval_days:  через сколько дней напомнить.
        """
        base = reference_date or datetime.utcnow()
        scheduled_for = base + timedelta(days=interval_days)

        entry = ReviewSchedule(
            problem_id=problem.id,
            scheduled_for=scheduled_for,
        )
        self.db.add(entry)
        self.db.flush()
        return entry

    def get_due(self, as_of: Optional[datetime] = None) -> list[ReviewSchedule]:
        """
        Получить все повторения, которые уже наступили и не выполнены.

        Args:
            as_of: точка отсчёта (default: сейчас).
        """
        now = as_of or datetime.utcnow()
        return (
            self.db.query(ReviewSchedule)
            .filter(
                ReviewSchedule.completed_at.is_(None),
                ReviewSchedule.scheduled_for <= now,
            )
            .order_by(ReviewSchedule.scheduled_for)
            .all()
        )

    def get_upcoming(self, days: int = 7, as_of: Optional[datetime] = None) -> list[ReviewSchedule]:
        """Предстоящие повторения в течение следующих `days` дней."""
        now = as_of or datetime.utcnow()
        until = now + timedelta(days=days)
        return (
            self.db.query(ReviewSchedule)
            .filter(
                ReviewSchedule.completed_at.is_(None),
                ReviewSchedule.scheduled_for > now,
                ReviewSchedule.scheduled_for <= until,
            )
            .order_by(ReviewSchedule.scheduled_for)
            .all()
        )

    def mark_completed(
        self,
        review: ReviewSchedule,
        session: Optional[PracticeSession] = None,
    ) -> ReviewSchedule:
        """Отметить повторение как выполненное."""
        review.completed_at = datetime.utcnow()
        if session:
            review.session_id = session.id
        self.db.flush()
        return review

    def get_for_problem(self, problem_id: int) -> list[ReviewSchedule]:
        """История всех повторений конкретной задачи."""
        return (
            self.db.query(ReviewSchedule)
            .filter(ReviewSchedule.problem_id == problem_id)
            .order_by(ReviewSchedule.scheduled_for)
            .all()
        )

    def get_problems_solved_n_days_ago(
        self,
        days: int = REVIEW_INTERVAL_DAYS,
        as_of: Optional[datetime] = None,
    ) -> list[Problem]:
        """
        Задачи, которые были решены впервые ровно `days` дней назад
        (используется как фоллбэк если нет расписания в БД).
        """
        now = as_of or datetime.utcnow()
        target_date_start = now - timedelta(days=days + 1)
        target_date_end   = now - timedelta(days=days - 1)

        sessions = (
            self.db.query(PracticeSession)
            .filter(
                PracticeSession.session_type == SessionType.NEW,
                PracticeSession.status == SessionStatus.FINISHED,
                PracticeSession.started_at >= target_date_start,
                PracticeSession.started_at <= target_date_end,
            )
            .all()
        )
        # Убираем дубликаты (задача могла быть решена несколько раз)
        seen: set[int] = set()
        problems: list[Problem] = []
        for s in sessions:
            if s.problem_id not in seen:
                seen.add(s.problem_id)
                problems.append(s.problem)
        return problems