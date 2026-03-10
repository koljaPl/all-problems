"""
Тесты модуля статистики.
"""

from __future__ import annotations

import pytest

from tracker.stats import StatsCalculator, format_duration


class TestFormatDuration:
    """Тесты функции форматирования времени."""

    def test_seconds_only(self):
        assert format_duration(45) == "45с"

    def test_minutes_and_seconds(self):
        assert format_duration(90) == "1м 30с"

    def test_hours(self):
        assert format_duration(3661) == "1ч 01м 01с"

    def test_zero(self):
        assert format_duration(0) == "0с"

    def test_negative_treated_as_zero(self):
        assert format_duration(-10) == "0с"

    def test_exactly_one_hour(self):
        assert format_duration(3600) == "1ч 00м 00с"

    def test_exactly_one_minute(self):
        assert format_duration(60) == "1м 00с"


class TestStatsCalculator:
    """Тесты StatsCalculator."""

    def test_empty_sessions(self):
        """Пустой список сессий — нулевая статистика."""
        calc  = StatsCalculator([])
        stats = calc.compute()
        assert stats.total_sessions == 0
        assert stats.total_seconds == 0
        assert stats.unique_problems == 0

    def test_basic_counts(self, make_finished_session, make_problem):
        """Базовые счётчики сессий."""
        p1 = make_problem(slug="p1")
        p2 = make_problem(slug="p2")
        s1 = make_finished_session(p1, session_type="new",    duration_secs=300)
        s2 = make_finished_session(p2, session_type="review", duration_secs=150)

        calc  = StatsCalculator([s1, s2])
        stats = calc.compute()

        assert stats.total_sessions   == 2
        assert stats.new_sessions     == 1
        assert stats.review_sessions  == 1
        assert stats.unique_problems  == 2
        assert stats.total_seconds    == 450
        assert stats.new_total_seconds    == 300
        assert stats.review_total_seconds == 150

    def test_average_times(self, make_finished_session, make_problem):
        """Среднее время считается корректно."""
        p = make_problem(slug="avg-test")
        s1 = make_finished_session(p, session_type="new", duration_secs=100)
        s2 = make_finished_session(p, session_type="new", duration_secs=200)

        calc  = StatsCalculator([s1, s2])
        stats = calc.compute()
        assert stats.avg_seconds_new == 150.0

    def test_difficulty_stats(self, make_finished_session, make_problem):
        """Статистика по сложности."""
        easy   = make_problem(slug="easy",   difficulty="Easy")
        medium = make_problem(slug="medium", difficulty="Medium")

        se = make_finished_session(easy,   duration_secs=120)
        sm = make_finished_session(medium, duration_secs=360)

        calc  = StatsCalculator([se, sm])
        stats = calc.compute()

        assert "Easy"   in stats.by_difficulty
        assert "Medium" in stats.by_difficulty
        assert stats.by_difficulty["Easy"].total_seconds   == 120
        assert stats.by_difficulty["Medium"].total_seconds == 360

    def test_tag_stats(self, make_finished_session, make_problem):
        """Статистика по тегам."""
        p = make_problem(slug="tagged", tags=["dynamic-programming", "array"])
        s = make_finished_session(p, duration_secs=500)

        calc  = StatsCalculator([s])
        stats = calc.compute()

        assert "dynamic-programming" in stats.by_tag
        assert "array"               in stats.by_tag
        assert stats.by_tag["dynamic-programming"].total_seconds == 500

    def test_skips_zero_duration_sessions(self, make_finished_session, make_problem):
        """Сессии с нулевым временем не учитываются."""
        p = make_problem(slug="zero-test")
        s = make_finished_session(p, duration_secs=0)

        calc  = StatsCalculator([s])
        stats = calc.compute()
        assert stats.total_sessions == 0

    def test_compute_improvement_rate(self, make_finished_session, make_problem):
        """Динамика улучшения: первое > последнее = прогресс."""
        p = make_problem(slug="improve-test")
        s1 = make_finished_session(p, session_type="new",    duration_secs=600)
        s2 = make_finished_session(p, session_type="review", duration_secs=300)

        calc = StatsCalculator([s1, s2])
        result = calc.compute_improvement_rate(p.id)

        assert result is not None
        assert result["first_secs"]      == 600
        assert result["last_secs"]       == 300
        assert result["improvement_pct"] == 50.0  # улучшение на 50%

    def test_improvement_requires_2_sessions(self, make_finished_session, make_problem):
        """Для расчёта прогресса нужно минимум 2 сессии."""
        p = make_problem(slug="single-session")
        s = make_finished_session(p, duration_secs=300)

        calc = StatsCalculator([s])
        assert calc.compute_improvement_rate(p.id) is None

    def test_daily_trend(self, make_finished_session, make_problem):
        """Тренд по дням содержит все дни."""
        p = make_problem(slug="trend-test")
        make_finished_session(p, duration_secs=300, started_offset_days=0)
        make_finished_session(p, duration_secs=200, started_offset_days=1)

        calc  = StatsCalculator([])  # пустой для проверки структуры
        trend = calc.compute_daily_trend(days=7)
        assert len(trend) == 7
        for day in trend:
            assert "date"          in day
            assert "total_seconds" in day
            assert "session_count" in day

    def test_to_dict(self, make_finished_session, make_problem):
        """to_dict возвращает сериализуемый словарь."""
        import json
        p = make_problem(slug="dict-test")
        s = make_finished_session(p, duration_secs=300)

        calc  = StatsCalculator([s])
        stats = calc.compute()
        d     = stats.to_dict()

        # Проверяем JSON-сериализуемость
        json_str = json.dumps(d)
        assert len(json_str) > 0
        assert d["total_sessions"] == 1