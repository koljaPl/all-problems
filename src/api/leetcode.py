"""
Клиент LeetCode GraphQL API.

Поддерживает:
- Получение списка решённых задач пользователя
- Получение деталей задачи (difficulty, tags)
- Авторизацию через session cookie (без пароля)

GraphQL endpoint: https://leetcode.com/graphql
Документация API неофициальная; запросы могут измениться при обновлении LeetCode.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from api.auth import load_cookie
from config import HTTP_TIMEOUT, LEETCODE_GRAPHQL_URL, LEETCODE_PROBLEM_URL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Структуры данных
# ---------------------------------------------------------------------------

@dataclass
class LeetCodeProblem:
    """Данные задачи, полученные из API."""
    slug:        str
    title:       str
    difficulty:  str        # "Easy" | "Medium" | "Hard"
    tags:        list[str]  # топики: ["Array", "Two Pointers", ...]
    frontend_id: int
    url:         str

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "LeetCodeProblem":
        """Создать объект из raw-данных GraphQL ответа."""
        slug = data.get("titleSlug", "")
        tags = [t["slug"] for t in data.get("topicTags", [])]
        return cls(
            slug=slug,
            title=data.get("title", ""),
            difficulty=data.get("difficulty", "Unknown"),
            tags=tags,
            frontend_id=int(data.get("questionFrontendId", 0)),
            url=LEETCODE_PROBLEM_URL.format(slug=slug),
        )


# ---------------------------------------------------------------------------
# GraphQL-запросы
# ---------------------------------------------------------------------------

# Запрос: список всех задач, которые пользователь решил
QUERY_RECENT_SUBMISSIONS = """
query recentAcSubmissions($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    titleSlug
    timestamp
  }
}
"""

# Запрос: детали конкретной задачи (difficulty, tags)
QUERY_PROBLEM_DETAIL = """
query problemDetail($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionFrontendId
    title
    titleSlug
    difficulty
    topicTags {
      slug
      name
    }
  }
}
"""

# Запрос: профиль пользователя и статистика
QUERY_USER_PROFILE = """
query userProfile($username: String!) {
  matchedUser(username: $username) {
    username
    submitStats: submitStatsGlobal {
      acSubmissionNum {
        difficulty
        count
      }
    }
  }
}
"""

# Запрос: история всех решённых задач (через userQuestionStatus)
QUERY_SOLVED_PROBLEMS = """
query allSolvedProblems($username: String!, $limit: Int!, $skip: Int!) {
  problemsetQuestionList: problemsetQuestionList(
    categorySlug: ""
    limit: $limit
    skip: $skip
    filters: { status: AC }
    username: $username
  ) {
    total: totalNum
    questions: data {
      questionFrontendId
      title
      titleSlug
      difficulty
      topicTags {
        slug
        name
      }
    }
  }
}
"""


# ---------------------------------------------------------------------------
# API-клиент
# ---------------------------------------------------------------------------

class LeetCodeClient:
    """
    Клиент для взаимодействия с LeetCode GraphQL API.

    Использует session cookie для авторизации.
    Все HTTP-запросы выполняются синхронно через httpx.
    """

    def __init__(
        self,
        cookie: Optional[str] = None,
        timeout: int = HTTP_TIMEOUT,
    ) -> None:
        """
        Args:
            cookie:  значение LEETCODE_SESSION cookie (если None — загружается из хранилища).
            timeout: таймаут HTTP-запросов в секундах.
        """
        self._cookie = cookie or load_cookie()
        self._timeout = timeout
        self._client = self._build_client()

    def _build_client(self) -> httpx.Client:
        """Создать httpx-клиент с нужными заголовками и cookie."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "leetcode-tracker/1.0 (github.com/yourname/leetcode-tracker)",
            "Referer": "https://leetcode.com/",
            "Origin": "https://leetcode.com",
        }

        cookies: dict[str, str] = {}
        if self._cookie:
            cookies["LEETCODE_SESSION"] = self._cookie
            # csrftoken нужен для POST-запросов к LeetCode
            # Получаем его из cookie или устанавливаем пустой
            headers["x-csrftoken"] = "dummy"

        return httpx.Client(
            base_url=LEETCODE_GRAPHQL_URL,
            headers=headers,
            cookies=cookies,
            timeout=self._timeout,
            follow_redirects=True,
        )

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """
        Выполнить GraphQL POST-запрос.

        Args:
            query:     GraphQL query string.
            variables: переменные запроса.

        Returns:
            Содержимое поля data из ответа.

        Raises:
            httpx.HTTPStatusError: при HTTP-ошибке.
            ValueError: при ошибке в GraphQL ответе.
        """
        payload = {"query": query, "variables": variables}

        try:
            response = self._client.post("", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Не логируем тело ответа — оно может содержать чувствительные данные
            logger.error(
                "HTTP ошибка при запросе к LeetCode API: %s %s",
                e.response.status_code,
                e.response.reason_phrase,
            )
            raise

        data = response.json()

        if "errors" in data:
            errors = data["errors"]
            logger.error("GraphQL ошибки: %s", errors)
            raise ValueError(f"LeetCode API вернул ошибки: {errors}")

        return data.get("data", {})

    def get_problem_detail(self, slug: str) -> Optional[LeetCodeProblem]:
        """
        Получить детали задачи по slug.

        Args:
            slug: идентификатор задачи (например, "two-sum").

        Returns:
            LeetCodeProblem или None если задача не найдена.
        """
        try:
            data = self._post(QUERY_PROBLEM_DETAIL, {"titleSlug": slug})
            question = data.get("question")
            if not question:
                logger.warning("Задача '%s' не найдена в API.", slug)
                return None
            return LeetCodeProblem.from_api_response(question)
        except Exception as e:
            logger.error("Не удалось получить данные задачи '%s': %s", slug, e)
            return None

    def get_recent_accepted(self, username: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        Получить последние accepted сабмиты пользователя.

        Args:
            username: имя пользователя на LeetCode.
            limit:    максимальное количество записей.

        Returns:
            Список словарей {titleSlug, timestamp}.
        """
        try:
            data = self._post(
                QUERY_RECENT_SUBMISSIONS,
                {"username": username, "limit": limit},
            )
            return data.get("recentAcSubmissionList", [])
        except Exception as e:
            logger.error("Не удалось получить сабмиты пользователя '%s': %s", username, e)
            return []

    def get_solved_problems(self, username: str, limit: int = 50, skip: int = 0) -> dict[str, Any]:
        """
        Получить список решённых задач со статусом AC.

        Args:
            username: имя пользователя.
            limit:    количество задач на страницу.
            skip:     смещение для пагинации.

        Returns:
            Словарь {total: int, questions: list[dict]}.
        """
        try:
            data = self._post(
                QUERY_SOLVED_PROBLEMS,
                {"username": username, "limit": limit, "skip": skip},
            )
            return data.get("problemsetQuestionList", {"total": 0, "questions": []})
        except Exception as e:
            logger.error("Не удалось получить список задач пользователя '%s': %s", username, e)
            return {"total": 0, "questions": []}

    def fetch_all_solved_problems(self, username: str) -> list[LeetCodeProblem]:
        """
        Загрузить ВСЕ решённые задачи пользователя (с пагинацией).

        Args:
            username: имя пользователя на LeetCode.

        Returns:
            Список LeetCodeProblem объектов.
        """
        problems: list[LeetCodeProblem] = []
        skip = 0
        page_size = 50

        while True:
            result = self.get_solved_problems(username, limit=page_size, skip=skip)
            questions = result.get("questions", [])
            total = result.get("total", 0)

            for q in questions:
                try:
                    problems.append(LeetCodeProblem.from_api_response(q))
                except Exception as e:
                    logger.warning("Не удалось обработать задачу: %s", e)

            skip += len(questions)
            logger.debug("Загружено %d / %d задач", skip, total)

            if skip >= total or not questions:
                break

        return problems

    def close(self) -> None:
        """Закрыть HTTP-клиент."""
        self._client.close()

    def __enter__(self) -> "LeetCodeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()