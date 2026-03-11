"""
Безопасное хранение LeetCode session cookie.

Cookie шифруется симметричным алгоритмом Fernet (AES-128-CBC + HMAC-SHA256)
и хранится в файле на диске. Ключ шифрования также хранится в отдельном файле.

ВАЖНО: этот модуль НЕ хранит пароли пользователя. Только session cookie,
который пользователь сам копирует из браузера.

Безопасность:
- В логах секреты не появляются
- Файлы ключа и cookie имеют права 600 (только владелец)
- При потере ключа cookie нельзя расшифровать (намеренно)
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from config import COOKIE_FILE, KEY_FILE

logger = logging.getLogger(__name__)


def _set_private_permissions(path: Path) -> None:
    """
    Устанавливает права доступа 600 на файл (только для Unix-систем).
    На Windows это игнорируется — там безопасность обеспечивается NTFS ACL.
    """
    if os.name != "nt":
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as e:
            logger.warning("Не удалось установить права на файл %s: %s", path, e)


def _get_or_create_key() -> bytes:
    """
    Загружает существующий ключ шифрования или генерирует новый.

    Returns:
        Fernet-совместимый ключ в байтах.
    """
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes().strip()

    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    _set_private_permissions(KEY_FILE)
    logger.debug("Сгенерирован новый ключ шифрования: %s", KEY_FILE)
    return key


def save_cookie(cookie_value: str) -> None:
    """
    Зашифровать и сохранить session cookie на диск.

    Args:
        cookie_value: значение cookie LEETCODE_SESSION из браузера.
    """
    key = _get_or_create_key()
    fernet = Fernet(key)
    encrypted = fernet.encrypt(cookie_value.encode())
    COOKIE_FILE.write_bytes(encrypted)
    _set_private_permissions(COOKIE_FILE)
    # Не логируем само значение — только факт сохранения
    logger.info("Cookie сохранён в %s", COOKIE_FILE)


def load_cookie() -> str | None:
    """
    Загрузить и расшифровать session cookie.

    Returns:
        Значение cookie или None если cookie не настроен / ключ утерян.
    """
    if not COOKIE_FILE.exists() or not KEY_FILE.exists():
        return None

    try:
        key = KEY_FILE.read_bytes().strip()
        fernet = Fernet(key)
        encrypted = COOKIE_FILE.read_bytes()
        value = fernet.decrypt(encrypted).decode()
        return value
    except InvalidToken:
        logger.error(
            "Не удалось расшифровать cookie — возможно, ключ был изменён. "
            "Выполните 'lct auth set-cookie' заново."
        )
        return None
    except Exception as e:
        logger.error("Ошибка загрузки cookie: %s", e)
        return None


def delete_cookie() -> None:
    """Удалить сохранённый cookie (выход из аккаунта)."""
    for path in (COOKIE_FILE, KEY_FILE):
        if path.exists():
            path.unlink()
            logger.info("Удалён файл: %s", path)


def is_cookie_configured() -> bool:
    """Проверить, настроен ли cookie."""
    return COOKIE_FILE.exists() and KEY_FILE.exists()