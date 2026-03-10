"""
Расчёт статистики по сессиям практики.

Метрики:
- Общее время (all/new/review)
- Среднее время по сложности (Easy/Medium/Hard)
- Распределение времени по тегам
- Количество сессий и задач
- Прогресс по времени (тренд)
- Процент "повторений вовремя"
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from db.models import (
    Difficulty,
    PracticeSession,
    Problem,
    SessionType,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def format_duration(seconds: int) -> str:
    """
    Форматировать секунды в читаемую строку.

    Примеры:
        45      -> "45с"
        90      -> "1м 30с"
        3661    -> "1ч 01м 01с"
    """
    if seconds < 0:
        seconds = 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}ч {m:02d}м {s:02d}с"
    if m:
        return f"{m}м {s:02d}с"
    return f"{s}с"


def _safe_avg(values: list[int]) -> float:
    """Среднее значение или 0 если список пуст."""
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# Dataclass для агрегированных метрик
# ---------------------------------------------------------------------------

@dataclass
class DifficultyStats:
    """Статистика по одному уровню сложности."""
    difficulty:     str
    count:          int   = 0  # кол-во сессий
    total_seconds:  int   = 0  # суммарное время
    avg_seconds:    float = 0.0

    def to_dict(self) -> dict:
        return {
            "difficulty":    self.difficulty,
            "count":         self.count,
            "total_seconds": self.total_seconds,
            "avg_seconds":   round(self.avg_seconds, 1),
            "total_fmt":     format_duration(self.total_seconds),
            "avg_fmt":       format_duration(int(self.avg_seconds)),
        }


@dataclass
class TagStats:
    """Статистика по одному тегу/типу задачи."""
    tag:            str
    count:          int   = 0
    total_seconds:  int   = 0
    avg_seconds:    float = 0.0

    def to_dict(self) -> dict:
        return {
            "tag":           self.tag,
            "count":         self.count,
            "total_seconds": self.total_seconds,
            "avg_seconds":   round(self.avg_seconds, 1),
            "total_fmt":     format_duration(self.total_seconds),
            "avg_fmt":       format_duration(int(self.avg_seconds)),
        }


@dataclass
class OverallStats:
    """Общая сводная статистика."""
    total_sessions:         int   = 0
    new_sessions:           int   = 0
    review_sessions:        int   = 0
    unique_problems:        int   = 0

    total_seconds:          int   = 0
    new_total_seconds:      int   = 0
    review_total_seconds:   int   = 0

    avg_seconds_all:        float = 0.0
    avg_seconds_new:        float = 0.0
    avg_seconds_review:     float = 0.0

    by_difficulty:          dict[str, DifficultyStats] = field(default_factory=dict)
    by_tag:                 dict[str, TagStats]         = field(default_factory=dict)

    # Топ-5 самых долгих задач
    slowest_problems:       list[dict] = field(default_factory=list)
    # Топ-5 самых быстрых задач (для оценки прогресса)
    fastest_problems:       list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_sessions":       self.total_sessions,
            "new_sessions":         self.new_sessions,
            "review_sessions":      self.review_sessions,
            "unique_problems":      self.unique_problems,
            "total_seconds":        self.total_seconds,
            "total_fmt":            format_duration(self.total_seconds),
            "new_total_fmt":        format_duration(self.new_total_seconds),
            "review_total_fmt":     format_duration(self.review_total_seconds),
            "avg_all_fmt":          format_duration(int(self.avg_seconds_all)),
            "avg_new_fmt":          format_duration(int(self.avg_seconds_new)),
            "avg_review_fmt":       format_duration(int(self.avg_seconds_review)),
            "by_difficulty":        {k: v.to_dict() for k, v in self.by_difficulty.items()},
            "by_tag":               {k: v.to_dict() for k, v in self.by_tag.items()},
        }


# ---------------------------------------------------------------------------
# Главный класс расчёта статистики
# ---------------------------------------------------------------------------

class StatsCalculator:
    """
    Вычисляет агрегированную статистику из списка сессий практики.

    Использование:
        calc = StatsCalculator(sessions)
        stats = calc.compute()
        print(stats.to_dict())
    """

    def __init__(self, sessions: list[PracticeSession]) -> None:
        """
        Args:
            sessions: список завершённых сессий (status=FINISHED).
        """
        # Фильтруем только завершённые сессии с ненулевым временем
        self._sessions = [
            s for s in sessions
            if s.net_duration_secs is not None and s.net_duration_secs > 0
        ]

    def compute(self) -> OverallStats:
        """Вычислить всю статистику и вернуть объект OverallStats."""
        stats = OverallStats()

        if not self._sessions:
            return stats

        # --- Базовые счётчики ---
        new_secs:    list[int] = []
        review_secs: list[int] = []
        all_secs:    list[int] = []

        # difficulty -> [seconds]
        diff_map: dict[str, list[int]] = defaultdict(list)
        # tag -> [seconds]
        tag_map:  dict[str, list[int]] = defaultdict(list)

        unique_problems: set[int] = set()

        # problem_id -> avg_seconds (для топ списков)
        problem_agg: dict[int, dict] = {}

        for s in self._sessions:
            secs = s.net_duration_secs  # type: ignore[assignment]
            unique_problems.add(s.problem_id)
            all_secs.append(secs)

            if s.session_type == SessionType.NEW:
                new_secs.append(secs)
                stats.new_sessions += 1
            else:
                review_secs.append(secs)
                stats.review_sessions += 1

            # По сложности
            if s.problem:
                diff_key = s.problem.difficulty.value
                diff_map[diff_key].append(secs)

                # По тегам
                for tag in s.problem.tags:
                    tag_map[tag].append(secs)

                # Для топ-задач: агрегируем среднее время по problem_id
                pid = s.problem_id
                if pid not in problem_agg:
                    problem_agg[pid] = {
                        "slug":       s.problem.slug,
                        "title":      s.problem.title,
                        "difficulty": s.problem.difficulty.value,
                        "secs":       [],
                    }
                problem_agg[pid]["secs"].append(secs)

        # --- Заполняем сводные поля ---
        stats.total_sessions     = len(self._sessions)
        stats.unique_problems    = len(unique_problems)
        stats.total_seconds      = sum(all_secs)
        stats.new_total_seconds  = sum(new_secs)
        stats.review_total_seconds = sum(review_secs)
        stats.avg_seconds_all    = _safe_avg(all_secs)
        stats.avg_seconds_new    = _safe_avg(new_secs)
        stats.avg_seconds_review = _safe_avg(review_secs)

        # --- По сложности ---
        for diff_name, secs_list in diff_map.items():
            stats.by_difficulty[diff_name] = DifficultyStats(
                difficulty=diff_name,
                count=len(secs_list),
                total_seconds=sum(secs_list),
                avg_seconds=_safe_avg(secs_list),
            )

        # --- По тегам (топ-20 по суммарному времени) ---
        sorted_tags = sorted(tag_map.items(), key=lambda x: sum(x[1]), reverse=True)
        for tag, secs_list in sorted_tags[:20]:
            stats.by_tag[tag] = TagStats(
                tag=tag,
                count=len(secs_list),
                total_seconds=sum(secs_list),
                avg_seconds=_safe_avg(secs_list),
            )

        # --- Топ задач по среднему времени ---
        problem_avg_list = [
            {
                "slug":       v["slug"],
                "title":      v["title"],
                "difficulty": v["difficulty"],
                "avg_secs":   int(_safe_avg(v["secs"])),
                "attempts":   len(v["secs"]),
            }
            for v in problem_agg.values()
        ]

        stats.slowest_problems = sorted(
            problem_avg_list, key=lambda x: x["avg_secs"], reverse=True
        )[:5]
        stats.fastest_problems = sorted(
            problem_avg_list, key=lambda x: x["avg_secs"]
        )[:5]

        return stats

    def compute_daily_trend(self, days: int = 30) -> list[dict]:
        """
        Прогресс по дням: суммарное время практики за каждый день.

        Args:
            days: за сколько последних дней строить тренд.

        Returns:
            Список словарей {date: str, total_seconds: int, session_count: int}.
        """
        now = datetime.utcnow().date()
        buckets: dict[str, dict] = {}

        # Инициализируем все дни нулями
        for i in range(days):
            day = (now - timedelta(days=days - 1 - i)).isoformat()
            buckets[day] = {"date": day, "total_seconds": 0, "session_count": 0}

        for s in self._sessions:
            if not s.finished_at or s.net_duration_secs is None:
                continue
            day = s.finished_at.date().isoformat()
            if day in buckets:
                buckets[day]["total_seconds"] += s.net_duration_secs
                buckets[day]["session_count"] += 1

        return list(buckets.values())

    def compute_improvement_rate(self, problem_id: int) -> Optional[dict]:
        """
        Вычислить динамику улучшения для конкретной задачи.

        Сравнивает первое решение (new) с последним (review).

        Returns:
            Словарь с метриками или None если мало данных.
        """
        problem_sessions = [s for s in self._sessions if s.problem_id == problem_id]
        if len(problem_sessions) < 2:
            return None

        problem_sessions.sort(key=lambda s: s.started_at)
        first = problem_sessions[0]
        last  = problem_sessions[-1]

        first_secs = first.net_duration_secs or 0
        last_secs  = last.net_duration_secs  or 0

        if first_secs == 0:
            return None

        improvement_pct = (first_secs - last_secs) / first_secs * 100

        return {
            "problem_id":      problem_id,
            "attempts":        len(problem_sessions),
            "first_secs":      first_secs,
            "last_secs":       last_secs,
            "improvement_pct": round(improvement_pct, 1),
            "first_fmt":       format_duration(first_secs),
            "last_fmt":        format_duration(last_secs),
        }