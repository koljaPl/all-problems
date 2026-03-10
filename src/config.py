"""
Конфигурация приложения: пути к файлам, константы, переменные окружения.

Все пути определяются относительно платформо-специфичного каталога данных
пользователя, чтобы приложение работало одинаково на Linux, macOS и Windows.
"""

import os
import platform
from pathlib import Path

# ---------------------------------------------------------------------------
# Определение каталога данных приложения (кросс-платформенно)
# ---------------------------------------------------------------------------

def get_app_data_dir() -> Path:
    """
    Возвращает каталог для хранения данных приложения.

    - Linux/macOS: ~/.local/share/leetcode-tracker
    - Windows:     %APPDATA%/leetcode-tracker
    - Переопределяется через env-переменную LCT_DATA_DIR.
    """
    if env_path := os.environ.get("LCT_DATA_DIR"):
        return Path(env_path).expanduser().resolve()

    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    return base / "leetcode-tracker"


# ---------------------------------------------------------------------------
# Публичные константы
# ---------------------------------------------------------------------------

APP_DIR: Path = get_app_data_dir()
APP_DIR.mkdir(parents=True, exist_ok=True)

# Путь к SQLite базе данных
DB_PATH: Path = APP_DIR / "tracker.db"

# Файл с зашифрованным LeetCode session cookie
COOKIE_FILE: Path = APP_DIR / ".cookie.enc"

# Файл с ключом шифрования cookie (Fernet key)
KEY_FILE: Path = APP_DIR / ".key"

# Каталог для экспортируемых файлов (JSON/CSV)
EXPORT_DIR: Path = APP_DIR / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Настройки бизнес-логики
# ---------------------------------------------------------------------------

# Через сколько дней задача считается "требующей повторения"
REVIEW_INTERVAL_DAYS: int = int(os.environ.get("LCT_REVIEW_DAYS", "5"))

# URL LeetCode GraphQL API
LEETCODE_GRAPHQL_URL: str = "https://leetcode.com/graphql"

# Базовый URL для открытия задач в браузере
LEETCODE_PROBLEM_URL: str = "https://leetcode.com/problems/{slug}/"

# Таймаут HTTP-запросов в секундах
HTTP_TIMEOUT: int = 30

# Максимальное время одной сессии (защита от "забытого" таймера), секунды
MAX_SESSION_DURATION_SECONDS: int = 8 * 3600  # 8 часов

# ---------------------------------------------------------------------------
# Настройки отображения
# ---------------------------------------------------------------------------

DIFFICULTY_COLORS: dict[str, str] = {
    "Easy": "green",
    "Medium": "yellow",
    "Hard": "red",
}