"""
Тесты клиента LeetCode GraphQL API.

API мокается через respx (httpx-совместимый mock).
Реальных HTTP-запросов нет — тесты изолированы от сети.
"""

from __future__ import annotations

import json
import pytest
import httpx

try:
    import respx
    HAS_RESPX = True
except ImportError:
    HAS_RESPX = False

from api.leetcode import LeetCodeClient, LeetCodeProblem
from config import LEETCODE_GRAPHQL_URL

# httpx добавляет trailing slash к base_url при POST на ""
_MOCK_URL = LEETCODE_GRAPHQL_URL.rstrip("/") + "/"


# Пропускаем тесты если respx не установлен
pytestmark = pytest.mark.skipif(not HAS_RESPX, reason="respx не установлен")


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

MOCK_PROBLEM_RESPONSE = {
    "data": {
        "question": {
            "questionFrontendId": "1",
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "difficulty": "Easy",
            "topicTags": [
                {"slug": "array",      "name": "Array"},
                {"slug": "hash-table", "name": "Hash Table"},
            ],
        }
    }
}

MOCK_SUBMISSIONS_RESPONSE = {
    "data": {
        "recentAcSubmissionList": [
            {"titleSlug": "two-sum",      "timestamp": "1700000000"},
            {"titleSlug": "longest-substring-without-repeating-characters", "timestamp": "1699900000"},
        ]
    }
}

MOCK_SOLVED_PROBLEMS_RESPONSE = {
    "data": {
        "problemsetQuestionList": {
            "total": 2,
            "questions": [
                {
                    "questionFrontendId": "1",
                    "title": "Two Sum",
                    "titleSlug": "two-sum",
                    "difficulty": "Easy",
                    "topicTags": [{"slug": "array", "name": "Array"}],
                },
                {
                    "questionFrontendId": "200",
                    "title": "Number of Islands",
                    "titleSlug": "number-of-islands",
                    "difficulty": "Medium",
                    "topicTags": [{"slug": "bfs", "name": "BFS"}],
                },
            ],
        }
    }
}


# ---------------------------------------------------------------------------
# Тесты LeetCodeProblem.from_api_response
# ---------------------------------------------------------------------------

class TestLeetCodeProblemParsing:
    """Тесты парсинга ответа API."""

    def test_from_api_response(self):
        """Корректный парсинг полного ответа."""
        raw = MOCK_PROBLEM_RESPONSE["data"]["question"]
        problem = LeetCodeProblem.from_api_response(raw)

        assert problem.slug        == "two-sum"
        assert problem.title       == "Two Sum"
        assert problem.difficulty  == "Easy"
        assert problem.frontend_id == 1
        assert "array"      in problem.tags
        assert "hash-table" in problem.tags
        assert "two-sum" in problem.url

    def test_from_api_response_no_tags(self):
        """Задача без тегов — пустой список."""
        raw = {
            "questionFrontendId": "999",
            "title": "No Tags Problem",
            "titleSlug": "no-tags-problem",
            "difficulty": "Hard",
            "topicTags": [],
        }
        problem = LeetCodeProblem.from_api_response(raw)
        assert problem.tags == []
        assert problem.difficulty == "Hard"

    def test_from_api_response_missing_fields(self):
        """Отсутствующие поля не вызывают исключений."""
        raw = {"titleSlug": "minimal-problem"}
        problem = LeetCodeProblem.from_api_response(raw)
        assert problem.slug  == "minimal-problem"
        assert problem.title == ""
        assert problem.tags  == []


# ---------------------------------------------------------------------------
# Интеграционный тест с моком HTTP
# ---------------------------------------------------------------------------

class TestLeetCodeClientMocked:
    """Тесты клиента с замоканными HTTP-запросами."""

    @respx.mock
    def test_get_problem_detail(self):
        """get_problem_detail возвращает задачу при успешном ответе."""
        respx.post(_MOCK_URL).mock(
            return_value=httpx.Response(200, json=MOCK_PROBLEM_RESPONSE)
        )

        client = LeetCodeClient(cookie="fake_cookie")
        problem = client.get_problem_detail("two-sum")

        assert problem is not None
        assert problem.slug  == "two-sum"
        assert problem.title == "Two Sum"
        client.close()

    @respx.mock
    def test_get_problem_detail_not_found(self):
        """get_problem_detail возвращает None если задача не найдена."""
        respx.post(_MOCK_URL).mock(
            return_value=httpx.Response(200, json={"data": {"question": None}})
        )

        client = LeetCodeClient(cookie="fake_cookie")
        result = client.get_problem_detail("nonexistent-slug")
        assert result is None
        client.close()

    @respx.mock
    def test_get_recent_accepted(self):
        """get_recent_accepted возвращает список сабмитов."""
        respx.post(_MOCK_URL).mock(
            return_value=httpx.Response(200, json=MOCK_SUBMISSIONS_RESPONSE)
        )

        client = LeetCodeClient(cookie="fake_cookie")
        submissions = client.get_recent_accepted("testuser", limit=10)

        assert len(submissions) == 2
        assert submissions[0]["titleSlug"] == "two-sum"
        client.close()

    @respx.mock
    def test_http_error_returns_empty(self):
        """При HTTP 401 — возвращается пустой результат, не исключение в вызывающий код."""
        respx.post(_MOCK_URL).mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )

        client = LeetCodeClient(cookie="invalid_cookie")
        submissions = client.get_recent_accepted("testuser")
        assert submissions == []
        client.close()

    @respx.mock
    def test_graphql_errors_handled(self):
        """GraphQL ошибки в ответе обрабатываются корректно."""
        error_response = {
            "errors": [{"message": "User not found"}],
            "data": None,
        }
        respx.post(_MOCK_URL).mock(
            return_value=httpx.Response(200, json=error_response)
        )

        client = LeetCodeClient(cookie="fake_cookie")
        result = client.get_problem_detail("some-slug")
        assert result is None
        client.close()

    @respx.mock
    def test_context_manager(self):
        """Клиент корректно работает как context manager."""
        respx.post(_MOCK_URL).mock(
            return_value=httpx.Response(200, json=MOCK_PROBLEM_RESPONSE)
        )

        with LeetCodeClient(cookie="fake_cookie") as client:
            problem = client.get_problem_detail("two-sum")
        assert problem is not None

    @respx.mock
    def test_fetch_all_solved_with_pagination(self):
        """fetch_all_solved_problems обрабатывает пагинацию."""
        # Первая страница — 2 задачи, total=2 (одна страница)
        respx.post(_MOCK_URL).mock(
            return_value=httpx.Response(200, json=MOCK_SOLVED_PROBLEMS_RESPONSE)
        )

        client = LeetCodeClient(cookie="fake_cookie")
        problems = client.fetch_all_solved_problems("testuser")

        assert len(problems) == 2
        slugs = {p.slug for p in problems}
        assert "two-sum"           in slugs
        assert "number-of-islands" in slugs
        client.close()