"""
Экспорт данных в JSON и CSV форматы.

Поддерживаются:
- Экспорт всех задач
- Экспорт всех сессий практики
- Экспорт статистики
- Экспорт расписания повторений
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from config import EXPORT_DIR
from db.models import (
    PracticeSession,
    Problem,
    ReviewSchedule,
    SessionStatus,
)
from tracker.stats import OverallStats, format_duration

logger = logging.getLogger(__name__)


def _timestamp_filename(prefix: str, ext: str) -> Path:
    """Сгенерировать имя файла с временной меткой."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return EXPORT_DIR / f"{prefix}_{ts}.{ext}"


# ---------------------------------------------------------------------------
# JSON экспорт
# ---------------------------------------------------------------------------

class JsonExporter:
    """Экспорт данных в JSON."""

    @staticmethod
    def export_problems(problems: list[Problem], output_path: Path | None = None) -> Path:
        """Экспортировать все задачи."""
        path = output_path or _timestamp_filename("problems", "json")
        data = [
            {
                "id":          p.id,
                "slug":        p.slug,
                "title":       p.title,
                "difficulty":  p.difficulty.value,
                "tags":        p.tags,
                "url":         p.url,
                "frontend_id": p.frontend_id,
                "added_at":    p.added_at.isoformat(),
            }
            for p in problems
        ]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Задачи экспортированы в %s", path)
        return path

    @staticmethod
    def export_sessions(sessions: list[PracticeSession], output_path: Path | None = None) -> Path:
        """Экспортировать сессии практики."""
        path = output_path or _timestamp_filename("sessions", "json")
        data = []
        for s in sessions:
            if s.status != SessionStatus.FINISHED:
                continue
            data.append({
                "id":                s.id,
                "problem_slug":      s.problem.slug if s.problem else None,
                "problem_title":     s.problem.title if s.problem else None,
                "difficulty":        s.problem.difficulty.value if s.problem else None,
                "tags":              s.problem.tags if s.problem else [],
                "session_type":      s.session_type.value,
                "started_at":        s.started_at.isoformat(),
                "finished_at":       s.finished_at.isoformat() if s.finished_at else None,
                "net_duration_secs": s.net_duration_secs,
                "net_duration_fmt":  format_duration(s.net_duration_secs or 0),
                "total_paused_secs": s.total_paused_secs,
                "is_corrected":      s.is_corrected,
                "notes":             s.notes,
            })
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Сессии экспортированы в %s", path)
        return path

    @staticmethod
    def export_stats(stats: OverallStats, output_path: Path | None = None) -> Path:
        """Экспортировать статистику."""
        path = output_path or _timestamp_filename("stats", "json")
        path.write_text(
            json.dumps(stats.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Статистика экспортирована в %s", path)
        return path

    @staticmethod
    def export_review_schedule(reviews: list[ReviewSchedule], output_path: Path | None = None) -> Path:
        """Экспортировать расписание повторений."""
        path = output_path or _timestamp_filename("reviews", "json")
        data = [
            {
                "id":            r.id,
                "problem_slug":  r.problem.slug if r.problem else None,
                "problem_title": r.problem.title if r.problem else None,
                "difficulty":    r.problem.difficulty.value if r.problem else None,
                "scheduled_for": r.scheduled_for.isoformat(),
                "completed_at":  r.completed_at.isoformat() if r.completed_at else None,
                "is_due":        r.is_due,
            }
            for r in reviews
        ]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# CSV экспорт
# ---------------------------------------------------------------------------

class CsvExporter:
    """Экспорт данных в CSV."""

    @staticmethod
    def export_problems(problems: list[Problem], output_path: Path | None = None) -> Path:
        """Экспортировать задачи в CSV."""
        path = output_path or _timestamp_filename("problems", "csv")
        fieldnames = ["id", "slug", "title", "difficulty", "tags", "url", "frontend_id", "added_at"]

        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for p in problems:
                writer.writerow({
                    "id":          p.id,
                    "slug":        p.slug,
                    "title":       p.title,
                    "difficulty":  p.difficulty.value,
                    "tags":        "|".join(p.tags),  # теги через |
                    "url":         p.url,
                    "frontend_id": p.frontend_id or "",
                    "added_at":    p.added_at.isoformat(),
                })
        logger.info("Задачи экспортированы в CSV: %s", path)
        return path

    @staticmethod
    def export_sessions(sessions: list[PracticeSession], output_path: Path | None = None) -> Path:
        """Экспортировать сессии практики в CSV."""
        path = output_path or _timestamp_filename("sessions", "csv")
        fieldnames = [
            "id", "problem_slug", "problem_title", "difficulty", "tags",
            "session_type", "started_at", "finished_at",
            "net_duration_secs", "net_duration_fmt", "total_paused_secs",
            "is_corrected", "notes",
        ]

        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for s in sessions:
                if s.status != SessionStatus.FINISHED:
                    continue
                writer.writerow({
                    "id":                s.id,
                    "problem_slug":      s.problem.slug if s.problem else "",
                    "problem_title":     s.problem.title if s.problem else "",
                    "difficulty":        s.problem.difficulty.value if s.problem else "",
                    "tags":              "|".join(s.problem.tags) if s.problem else "",
                    "session_type":      s.session_type.value,
                    "started_at":        s.started_at.isoformat(),
                    "finished_at":       s.finished_at.isoformat() if s.finished_at else "",
                    "net_duration_secs": s.net_duration_secs or "",
                    "net_duration_fmt":  format_duration(s.net_duration_secs or 0),
                    "total_paused_secs": s.total_paused_secs,
                    "is_corrected":      s.is_corrected,
                    "notes":             s.notes or "",
                })
        logger.info("Сессии экспортированы в CSV: %s", path)
        return path