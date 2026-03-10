"""
Тесты слоя доступа к данным (репозитории).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from db.models import (
    Difficulty,
    SessionStatus,
    SessionType,
)


class TestProblemRepository:
    """Тесты ProblemRepository."""

    def test_create_new_problem(self, prob_repo, db_session):
        """Создание новой задачи."""
        p = prob_repo.create(
            slug="two-sum",
            title="Two Sum",
            difficulty=Difficulty.EASY,
            tags=["array"],
            url="https://leetcode.com/problems/two-sum/",
            frontend_id=1,
        )
        db_session.commit()
        assert p.id is not None
        assert p.slug == "two-sum"
        assert p.difficulty == Difficulty.EASY

    def test_create_duplicate_updates(self, prob_repo, db_session):
        """Повторное создание с тем же slug обновляет поля."""
        prob_repo.create(
            slug="two-sum",
            title="Two Sum (old)",
            difficulty=Difficulty.EASY,
            tags=[],
            url="https://leetcode.com/problems/two-sum/",
        )
        db_session.commit()

        updated = prob_repo.create(
            slug="two-sum",
            title="Two Sum",
            difficulty=Difficulty.EASY,
            tags=["array", "hash-table"],
            url="https://leetcode.com/problems/two-sum/",
        )
        db_session.commit()

        # Должна быть одна запись с обновлённым названием
        all_problems = prob_repo.list_all()
        assert len(all_problems) == 1
        assert updated.title == "Two Sum"
        assert "array" in updated.tags

    def test_get_by_slug(self, make_problem, prob_repo):
        """Поиск по slug."""
        make_problem(slug="longest-substring", title="Longest Substring")
        found = prob_repo.get_by_slug("longest-substring")
        assert found is not None
        assert found.title == "Longest Substring"

    def test_get_by_slug_not_found(self, prob_repo):
        """Несуществующий slug возвращает None."""
        assert prob_repo.get_by_slug("nonexistent-slug") is None

    def test_list_all(self, make_problem, prob_repo):
        """Список всех задач."""
        make_problem(slug="problem-1", title="A")
        make_problem(slug="problem-2", title="B")
        problems = prob_repo.list_all()
        assert len(problems) == 2

    def test_search(self, make_problem, prob_repo):
        """Поиск по подстроке."""
        make_problem(slug="two-sum", title="Two Sum")
        make_problem(slug="three-sum", title="Three Sum")
        make_problem(slug="binary-search", title="Binary Search")

        results = prob_repo.search("sum")
        assert len(results) == 2
        slugs = {p.slug for p in results}
        assert "two-sum" in slugs
        assert "three-sum" in slugs


class TestSessionRepository:
    """Тесты SessionRepository."""

    def test_start_session(self, sess_repo, sample_problem, db_session):
        """Запуск новой сессии."""
        session = sess_repo.start(sample_problem, SessionType.NEW)
        db_session.commit()
        assert session.id is not None
        assert session.status == SessionStatus.RUNNING
        assert session.session_type == SessionType.NEW

    def test_start_fails_if_active(self, sess_repo, sample_problem, db_session):
        """Нельзя начать вторую сессию пока идёт первая."""
        sess_repo.start(sample_problem, SessionType.NEW)
        db_session.commit()

        with pytest.raises(RuntimeError, match="активная сессия"):
            sess_repo.start(sample_problem, SessionType.NEW)

    def test_pause_and_resume(self, sess_repo, sample_problem, db_session):
        """Пауза и возобновление корректно учитывают время."""
        session = sess_repo.start(sample_problem, SessionType.NEW)
        db_session.commit()

        sess_repo.pause(session)
        db_session.commit()
        assert session.status == SessionStatus.PAUSED
        assert session.last_paused_at is not None

        sess_repo.resume(session)
        db_session.commit()
        assert session.status == SessionStatus.RUNNING
        assert session.last_paused_at is None
        # Паузы накоплены
        assert session.total_paused_secs >= 0

    def test_pause_already_paused_raises(self, sess_repo, sample_problem, db_session):
        """Пауза уже приостановленной сессии — ошибка."""
        session = sess_repo.start(sample_problem, SessionType.NEW)
        db_session.commit()
        sess_repo.pause(session)
        db_session.commit()

        with pytest.raises(RuntimeError):
            sess_repo.pause(session)

    def test_finish_session(self, sess_repo, sample_problem, db_session):
        """Завершение сессии фиксирует время."""
        session = sess_repo.start(sample_problem, SessionType.NEW)
        db_session.commit()

        finished = sess_repo.finish(session)
        db_session.commit()

        assert finished.status == SessionStatus.FINISHED
        assert finished.finished_at is not None
        assert finished.net_duration_secs is not None
        assert finished.net_duration_secs >= 0

    def test_finish_paused_session(self, sess_repo, sample_problem, db_session):
        """Завершение сессии на паузе корректно считает время."""
        session = sess_repo.start(sample_problem, SessionType.NEW)
        db_session.commit()
        sess_repo.pause(session)
        db_session.commit()

        # Завершаем со статуса PAUSED
        finished = sess_repo.finish(session)
        db_session.commit()
        assert finished.status == SessionStatus.FINISHED

    def test_finish_already_finished_raises(self, sess_repo, sample_problem, db_session):
        """Повторное завершение — ошибка."""
        session = sess_repo.start(sample_problem, SessionType.NEW)
        sess_repo.finish(session)
        db_session.commit()

        with pytest.raises(RuntimeError):
            sess_repo.finish(session)

    def test_correct_time(self, make_finished_session, sess_repo, sample_problem, db_session):
        """Ручная коррекция времени."""
        session = make_finished_session(sample_problem, duration_secs=600)

        sess_repo.correct_time(session, new_seconds=300)
        db_session.commit()

        assert session.net_duration_secs == 300
        assert session.is_corrected is True

    def test_correct_time_negative_raises(self, make_finished_session, sess_repo, sample_problem):
        """Отрицательное время — ValueError."""
        session = make_finished_session(sample_problem, duration_secs=600)
        with pytest.raises(ValueError):
            sess_repo.correct_time(session, new_seconds=-1)

    def test_get_active(self, sess_repo, sample_problem, db_session):
        """get_active возвращает запущенную сессию."""
        sess_repo.start(sample_problem, SessionType.NEW)
        db_session.commit()
        active = sess_repo.get_active()
        assert active is not None
        assert active.status == SessionStatus.RUNNING

    def test_get_active_none_after_finish(self, sess_repo, sample_problem, db_session):
        """После завершения активных сессий нет."""
        session = sess_repo.start(sample_problem, SessionType.NEW)
        sess_repo.finish(session)
        db_session.commit()
        assert sess_repo.get_active() is None

    def test_list_for_problem(self, make_finished_session, sess_repo, make_problem):
        """Список завершённых сессий по задаче."""
        p = make_problem(slug="problem-a")
        make_finished_session(p, duration_secs=300)
        make_finished_session(p, session_type="review", duration_secs=200)

        sessions = sess_repo.list_for_problem(p.id)
        assert len(sessions) == 2


class TestReviewRepository:
    """Тесты ReviewRepository."""

    def test_schedule_review(self, review_repo, sample_problem, db_session):
        """Повторение планируется через N дней."""
        from leetcode_tracker.config import REVIEW_INTERVAL_DAYS
        now = datetime.utcnow()
        entry = review_repo.schedule(sample_problem, reference_date=now)
        db_session.commit()

        expected = now + timedelta(days=REVIEW_INTERVAL_DAYS)
        diff = abs((entry.scheduled_for - expected).total_seconds())
        assert diff < 5  # не более 5 секунд расхождения

    def test_get_due(self, review_repo, make_problem, db_session):
        """get_due возвращает просроченные повторения."""
        p = make_problem(slug="overdue-problem")
        past = datetime.utcnow() - timedelta(days=1)
        review_repo.schedule(p, reference_date=past, interval_days=0)
        db_session.commit()

        due = review_repo.get_due()
        assert len(due) >= 1
        assert any(r.problem_id == p.id for r in due)

    def test_get_due_excludes_future(self, review_repo, sample_problem, db_session):
        """Будущие повторения не попадают в due."""
        review_repo.schedule(sample_problem)  # через 5 дней по умолчанию
        db_session.commit()

        due = review_repo.get_due()
        assert not any(r.problem_id == sample_problem.id for r in due)

    def test_mark_completed(self, review_repo, sample_problem, db_session):
        """Отмечаем повторение как выполненное."""
        past = datetime.utcnow() - timedelta(days=1)
        entry = review_repo.schedule(sample_problem, reference_date=past, interval_days=0)
        db_session.commit()

        review_repo.mark_completed(entry)
        db_session.commit()

        assert entry.completed_at is not None
        # После выполнения не должна попадать в due
        due = review_repo.get_due()
        assert not any(r.id == entry.id for r in due)

    def test_get_upcoming(self, review_repo, make_problem, db_session):
        """Предстоящие повторения."""
        p = make_problem(slug="upcoming-problem")
        # Планируем на 3 дня вперёд (входит в 7-дневное окно)
        review_repo.schedule(p, interval_days=3)
        db_session.commit()

        upcoming = review_repo.get_upcoming(days=7)
        assert any(r.problem_id == p.id for r in upcoming)

    def test_get_problems_solved_n_days_ago(
        self, review_repo, make_finished_session, make_problem, db_session
    ):
        """Задачи решённые N дней назад."""
        p = make_problem(slug="old-problem")
        make_finished_session(p, started_offset_days=5)

        problems = review_repo.get_problems_solved_n_days_ago(days=5)
        assert any(pr.id == p.id for pr in problems)