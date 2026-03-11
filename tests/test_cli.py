"""
Тесты CLI через Click test runner.

Используем Click's CliRunner для изоляции — реальный терминал не нужен.
База данных также изолирована через in-memory SQLite.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cli import main


@pytest.fixture
def runner():
    """Click test runner с изоляцией окружения."""
    return CliRunner()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """
    Подменяем init_db чтобы использовать изолированную тестовую БД.
    """
    db_path = str(tmp_path / "test.db")
    os.environ["LCT_DATA_DIR"] = str(tmp_path)

    # Используем реальную SQLite но в tmp_path
    from leetcode_tracker.db.models import init_db as real_init_db

    def patched_init_db(path=None):
        return real_init_db(db_path)

    monkeypatch.setattr("leetcode_tracker.cli.init_db", patched_init_db)
    yield db_path


class TestAddCommand:
    """Тесты команды 'lct add'."""

    def test_add_manual_no_api(self, runner, isolated_db):
        """Добавление задачи вручную (без API)."""
        result = runner.invoke(main, [
            "add", "two-sum",
            "--title", "Two Sum",
            "--difficulty", "Easy",
            "--tags", "array,hash-table",
            "--no-api",
        ])
        assert result.exit_code == 0, result.output
        assert "two-sum" in result.output.lower() or "добавлена" in result.output.lower()

    def test_add_prompts_for_title_if_missing(self, runner, isolated_db):
        """Если --title не указан — запрашивается интерактивно."""
        result = runner.invoke(main, [
            "add", "merge-intervals",
            "--no-api",
        ], input="Merge Intervals\nMedium\n")
        assert result.exit_code == 0, result.output


class TestStartStopCommands:
    """Тесты команд start/stop/pause/resume."""

    def _add_problem(self, runner, isolated_db, slug="two-sum"):
        runner.invoke(main, [
            "add", slug,
            "--title", "Two Sum",
            "--difficulty", "Easy",
            "--no-api",
        ])

    def test_start_creates_session(self, runner, isolated_db):
        """start создаёт активную сессию."""
        self._add_problem(runner, isolated_db)
        result = runner.invoke(main, ["start", "two-sum"])
        assert result.exit_code == 0, result.output
        assert "запущен" in result.output.lower() or "таймер" in result.output.lower()

    def test_start_nonexistent_slug_fails(self, runner, isolated_db):
        """start с несуществующим slug завершается с ошибкой."""
        result = runner.invoke(main, ["start", "nonexistent-problem-slug"])
        assert result.exit_code != 0

    def test_start_twice_fails(self, runner, isolated_db):
        """Нельзя стартовать вторую сессию пока активна первая."""
        self._add_problem(runner, isolated_db)
        runner.invoke(main, ["start", "two-sum"])
        result = runner.invoke(main, ["start", "two-sum"])
        assert result.exit_code != 0

    def test_pause_and_resume(self, runner, isolated_db):
        """Пауза и возобновление работают."""
        self._add_problem(runner, isolated_db)
        runner.invoke(main, ["start", "two-sum"])

        result = runner.invoke(main, ["pause"])
        assert result.exit_code == 0

        result = runner.invoke(main, ["resume"])
        assert result.exit_code == 0

    def test_stop_finishes_session(self, runner, isolated_db):
        """stop завершает активную сессию."""
        self._add_problem(runner, isolated_db)
        runner.invoke(main, ["start", "two-sum"])
        result = runner.invoke(main, ["stop"])
        assert result.exit_code == 0
        assert "завершена" in result.output.lower()

    def test_stop_without_active_fails(self, runner, isolated_db):
        """stop без активной сессии завершается с ошибкой."""
        result = runner.invoke(main, ["stop"])
        assert result.exit_code != 0

    def test_status_no_active_session(self, runner, isolated_db):
        """status при отсутствии активной сессии выводит сообщение."""
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "нет" in result.output.lower()


class TestListCommand:
    """Тесты команды 'lct list'."""

    def test_list_empty(self, runner, isolated_db):
        """Пустой список задач."""
        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "не найдены" in result.output.lower()

    def test_list_shows_problems(self, runner, isolated_db):
        """Список отображает добавленные задачи."""
        runner.invoke(main, ["add", "two-sum", "--title", "Two Sum",
                              "--difficulty", "Easy", "--no-api"])
        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "two-sum" in result.output

    def test_list_filter_by_difficulty(self, runner, isolated_db):
        """Фильтр по сложности работает."""
        runner.invoke(main, ["add", "easy-problem", "--title", "Easy",
                              "--difficulty", "Easy", "--no-api"])
        runner.invoke(main, ["add", "hard-problem", "--title", "Hard",
                              "--difficulty", "Hard", "--no-api"])

        result = runner.invoke(main, ["list", "--difficulty", "Easy"])
        assert result.exit_code == 0
        assert "easy-problem" in result.output
        assert "hard-problem" not in result.output


class TestReviewCommand:
    """Тесты команды 'lct review'."""

    def test_review_no_due(self, runner, isolated_db):
        """Нет задач для повторения."""
        result = runner.invoke(main, ["review"])
        assert result.exit_code == 0
        assert "нет" in result.output.lower()

    def test_review_upcoming(self, runner, isolated_db):
        """Предстоящие повторения."""
        result = runner.invoke(main, ["review", "--upcoming"])
        assert result.exit_code == 0


class TestStatsCommand:
    """Тесты команды 'lct stats'."""

    def test_stats_empty(self, runner, isolated_db):
        """Статистика при отсутствии данных."""
        result = runner.invoke(main, ["stats"])
        assert result.exit_code == 0

    def test_stats_with_data(self, runner, isolated_db):
        """Статистика отображается после завершённых сессий."""
        runner.invoke(main, ["add", "two-sum", "--title", "Two Sum",
                              "--difficulty", "Easy", "--no-api"])
        runner.invoke(main, ["start", "two-sum"])
        runner.invoke(main, ["stop"])

        result = runner.invoke(main, ["stats"])
        assert result.exit_code == 0

    def test_stats_unknown_slug(self, runner, isolated_db):
        """stats --slug с несуществующей задачей — ошибка."""
        result = runner.invoke(main, ["stats", "--slug", "nonexistent"])
        assert result.exit_code != 0


class TestCorrectCommand:
    """Тесты команды 'lct correct'."""

    def test_correct_time(self, runner, isolated_db):
        """Ручная коррекция времени сессии."""
        runner.invoke(main, ["add", "two-sum", "--title", "Two Sum",
                              "--difficulty", "Easy", "--no-api"])
        runner.invoke(main, ["start", "two-sum"])
        runner.invoke(main, ["stop"])

        # ID сессии = 1 (первая в чистой БД)
        result = runner.invoke(main, ["correct", "1", "5.0"])  # 5 минут
        assert result.exit_code == 0
        assert "300" in result.output or "5м" in result.output

    def test_correct_nonexistent_session(self, runner, isolated_db):
        """Коррекция несуществующей сессии — ошибка."""
        result = runner.invoke(main, ["correct", "9999", "10"])
        assert result.exit_code != 0


class TestAuthCommands:
    """Тесты команд авторизации."""

    def test_auth_status_not_configured(self, runner, isolated_db):
        """Статус авторизации когда cookie не настроен."""
        with patch("leetcode_tracker.cli.is_cookie_configured", return_value=False):
            result = runner.invoke(main, ["auth", "status"])
        assert result.exit_code == 0
        assert "не настроен" in result.output.lower()

    def test_auth_status_configured(self, runner, isolated_db):
        """Статус авторизации когда cookie настроен."""
        with patch("leetcode_tracker.cli.is_cookie_configured", return_value=True):
            result = runner.invoke(main, ["auth", "status"])
        assert result.exit_code == 0
        assert "настроен" in result.output.lower()

    def test_auth_set_cookie_interactive(self, runner, isolated_db, tmp_path):
        """Интерактивная установка cookie."""
        with patch("leetcode_tracker.cli.save_cookie") as mock_save:
            result = runner.invoke(
                main,
                ["auth", "set-cookie"],
                input="fake_session_cookie_value\n",
            )
        assert result.exit_code == 0
        mock_save.assert_called_once_with("fake_session_cookie_value")

    def test_auth_set_cookie_via_option(self, runner, isolated_db):
        """Установка cookie через опцию --cookie."""
        with patch("leetcode_tracker.cli.save_cookie") as mock_save:
            result = runner.invoke(
                main,
                ["auth", "set-cookie", "--cookie", "my_cookie_12345"],
            )
        assert result.exit_code == 0
        mock_save.assert_called_once_with("my_cookie_12345")


class TestOpenCommand:
    """Тест команды 'lct open'."""

    def test_open_problem(self, runner, isolated_db):
        """open вызывает webbrowser.open."""
        from unittest.mock import patch
        with patch("webbrowser.open") as mock_open:
            result = runner.invoke(main, ["open", "two-sum"])
        assert result.exit_code == 0
        mock_open.assert_called_once()
        assert "two-sum" in mock_open.call_args[0][0]


class TestExportCommand:
    """Тест команды 'lct export'."""

    def test_export_json_problems(self, runner, isolated_db, tmp_path):
        """Экспорт задач в JSON."""
        runner.invoke(main, ["add", "export-test", "--title", "Export Test",
                              "--difficulty", "Easy", "--no-api"])
        result = runner.invoke(main, ["export", "json", "--what", "problems"])
        assert result.exit_code == 0

    def test_export_csv_sessions(self, runner, isolated_db):
        """Экспорт сессий в CSV."""
        runner.invoke(main, ["add", "csv-test", "--title", "CSV Test",
                              "--difficulty", "Easy", "--no-api"])
        runner.invoke(main, ["start", "csv-test"])
        runner.invoke(main, ["stop"])
        result = runner.invoke(main, ["export", "csv", "--what", "sessions"])
        assert result.exit_code == 0