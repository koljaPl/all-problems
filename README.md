# LeetCode Tracker

CLI-приложение для систематической подготовки к олимпиадам по программированию и техническим интервью.

Реализует систему интервальных повторений: напоминает о задачах через 5 дней после первого решения, открывает их в браузере без готового решения, отслеживает время и строит статистику.

---

## Содержание

- [Возможности](#возможности)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Команды](#команды)
- [Авторизация LeetCode](#авторизация-leetcode)
- [Схема базы данных](#схема-базы-данных)
- [Статистика и метрики](#статистика-и-метрики)
- [Экспорт данных](#экспорт-данных)
- [Тестирование](#тестирование)
- [Структура проекта](#структура-проекта)
- [План итераций](#план-итераций)

---

## Возможности

- **Система повторений**: напоминает о задачах через 5 дней (настраивается) — открывает задачу в браузере без готового решения
- **Трекер времени**: замер чистого времени на каждую задачу с поддержкой пауз, возобновления и ручной коррекции
- **Разделение по типу**: отдельная статистика для новых задач и повторений
- **Классификация**: группировка по сложности (Easy/Medium/Hard) и по тегам (two-pointers, dp, graph и т.д.)
- **Синхронизация с API**: опциональное получение данных из LeetCode GraphQL API через session cookie
- **Безопасность**: cookie хранится зашифрованным (Fernet AES-128), в логах не появляется
- **Экспорт**: JSON и CSV для внешнего анализа
- **Кросс-платформенность**: Linux, macOS, Windows

---

## Установка

### Требования

- Python 3.11+ 
- pip

### Из исходников

```bash
git clone https://github.com/yourname/leetcode-tracker.git
cd leetcode-tracker

# Создать виртуальное окружение (рекомендуется)
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows

# Установить
pip install -e .

# Проверить установку
lct --version
```

### Только зависимости (без установки пакета)

```bash
pip install -r requirements.txt
python -m leetcode_tracker.cli --version
```

---

## Быстрый старт

### 1. Добавить задачу

```bash
# С данными из LeetCode API (нужен cookie, см. раздел "Авторизация")
lct add two-sum

# Без API — вручную
lct add two-sum --title "Two Sum" --difficulty Easy --tags "array,hash-table" --no-api
```

### 2. Начать решать

```bash
lct start two-sum
# Таймер запущен. Открыть задачу в браузере:
lct open two-sum
```

### 3. Если отвлеклись — пауза

```bash
lct pause
# ... перерыв ...
lct resume
```

### 4. Закончили

```bash
lct stop
# или с заметкой:
lct stop --notes "Использовал HashMap, O(n)"
```

### 5. Посмотреть что нужно повторить

```bash
lct review
# Открыть все задачи для повторения в браузере:
lct review --open-browser
```

### 6. Статистика

```bash
lct stats
lct stats --days 7      # за последние 7 дней
lct stats --trend       # + график по дням
lct stats --slug two-sum  # по конкретной задаче
```

---

## Команды

### `lct add <slug>`

Добавить задачу в трекер.

```
lct add two-sum
lct add binary-search --title "Binary Search" --difficulty Easy --no-api
lct add longest-substring --tags "sliding-window,hash-table" --no-api
```

Опции:
- `--title, -t`      — название (если без API)
- `--difficulty, -d` — Easy / Medium / Hard
- `--tags, -g`       — теги через запятую
- `--no-api`         — не обращаться к LeetCode API

---

### `lct start <slug>`

Начать сессию решения задачи. Таймер запускается автоматически.

```bash
lct start two-sum            # новая задача
lct start two-sum --review   # повторение
```

Опции:
- `--review, -r` — пометить как повторение (иначе считается новой)

---

### `lct pause`

Поставить таймер на паузу.

```bash
lct pause
```

---

### `lct resume`

Продолжить после паузы.

```bash
lct resume
```

---

### `lct stop`

Завершить сессию. Чистое время фиксируется в БД.

```bash
lct stop
lct stop --notes "Решил через BFS, 25 мин"
```

Опции:
- `--notes, -n` — заметка к сессии

---

### `lct status`

Показать текущую активную сессию (если есть).

```bash
lct status
```

---

### `lct review`

Показать задачи для повторения сегодня.

```bash
lct review
lct review --open-browser     # открыть все в браузере
lct review --upcoming         # предстоящие в течение 7 дней
```

Опции:
- `--open-browser, -o` — открыть задачи в браузере
- `--upcoming, -u`     — показать предстоящие повторения (7 дней)

---

### `lct open <slug>`

Открыть задачу в браузере.

```bash
lct open two-sum
```

---

### `lct correct <session_id> <minutes>`

Скорректировать время завершённой сессии вручную.

```bash
lct correct 42 15.5   # установить 15 минут 30 секунд
```

---

### `lct list`

Показать все добавленные задачи.

```bash
lct list
lct list --difficulty Easy
lct list --tag dynamic-programming
lct list --search "two"
```

Опции:
- `--difficulty, -d` — фильтр по сложности
- `--tag, -t`        — фильтр по тегу
- `--search, -s`     — поиск по названию/slug

---

### `lct stats`

Показать статистику.

```bash
lct stats                        # за последние 30 дней
lct stats --days 7               # за 7 дней
lct stats --days 0               # за всё время
lct stats --slug two-sum         # по конкретной задаче
lct stats --trend                # + график активности по дням
```

Пример вывода:

```
╭──────────── Статистика за последние 30 дней ────────────╮
│ Сессий всего:      47 (32 новых, 15 повторений)         │
│ Уникальных задач:  38                                   │
│                                                         │
│ Суммарное время:   14ч 22м 18с                          │
│   Новые задачи:    10ч 05м 40с                          │
│   Повторения:      4ч 16м 38с                           │
│                                                         │
│ Среднее время:     18м 22с                              │
│   Новые задачи:    18м 55с                              │
│   Повторения:      17м 06с                              │
╰─────────────────────────────────────────────────────────╯
```

---

### `lct export <fmt>`

Экспорт данных в файл.

```bash
lct export json                          # всё в JSON
lct export csv                           # всё в CSV
lct export json --what problems          # только задачи
lct export csv --what sessions           # только сессии
lct export json --what reviews           # расписание повторений
```

Файлы сохраняются в каталог `~/.local/share/leetcode-tracker/exports/` (Linux/macOS) или `%APPDATA%/leetcode-tracker/exports/` (Windows).

---

### `lct sync <username>`

Синхронизировать решённые задачи с LeetCode API.

```bash
lct sync myusername
lct sync myusername --limit 100
```

Требует настроенного cookie (`lct auth set-cookie`).

---

### `lct auth`

Управление авторизацией.

```bash
lct auth set-cookie             # интерактивно запросить cookie
lct auth set-cookie --cookie eyJ...   # передать напрямую
lct auth status                 # проверить статус
lct auth clear                  # удалить сохранённый cookie
```

---

## Авторизация LeetCode

Для обращения к LeetCode API нужен session cookie. Пароль никогда не запрашивается и нигде не хранится.

### Как получить cookie

1. Откройте [leetcode.com](https://leetcode.com) и войдите в аккаунт
2. Откройте DevTools (F12)
3. Перейдите: **Application → Cookies → https://leetcode.com**
4. Скопируйте значение cookie с именем `LEETCODE_SESSION`

### Как сохранить

```bash
lct auth set-cookie
# введёт значение скрыто (как пароль)
```

или

```bash
lct auth set-cookie --cookie "eyJhbGci..."
```

### Безопасность хранения

Cookie шифруется алгоритмом Fernet (AES-128-CBC + HMAC-SHA256) перед сохранением на диск. Ключ шифрования хранится отдельно в файле с правами 600. В логах приложения чувствительные данные не появляются.

### Переменная окружения

Вместо хранения в файле можно передавать cookie через переменную окружения (не сохраняется):

```bash
export LEETCODE_SESSION="eyJhbGci..."
```

> Приложение проверяет файл и API работает только с файловым cookie. Через env-переменную прямая работа не поддерживается в текущей версии.

---

## Схема базы данных

### Таблица `problems`

| Колонка      | Тип     | Описание                                      |
|-------------|---------|-----------------------------------------------|
| id          | INTEGER | Первичный ключ                                |
| slug        | TEXT    | Уникальный идентификатор (two-sum)            |
| title       | TEXT    | Полное название                               |
| difficulty  | TEXT    | Easy / Medium / Hard                          |
| tags_json   | TEXT    | JSON-массив тегов: ["array","hash-table"]     |
| url         | TEXT    | Прямая ссылка                                 |
| frontend_id | INTEGER | Номер задачи на LeetCode (1, 42, 200...)      |
| added_at    | DATETIME| Дата добавления в трекер                      |

### Таблица `practice_sessions`

| Колонка           | Тип     | Описание                                         |
|------------------|---------|--------------------------------------------------|
| id               | INTEGER | Первичный ключ                                   |
| problem_id       | INTEGER | FK → problems.id                                 |
| session_type     | TEXT    | new / review                                     |
| status           | TEXT    | running / paused / finished                      |
| started_at       | DATETIME| Момент старта                                    |
| finished_at      | DATETIME| Момент завершения                                |
| last_paused_at   | DATETIME| Момент последней паузы                           |
| total_paused_secs| INTEGER | Суммарное время пауз (секунды)                   |
| net_duration_secs| INTEGER | Чистое время (gross − pauses)                    |
| is_corrected     | BOOLEAN | True если время скорректировано вручную          |
| notes            | TEXT    | Произвольные заметки                             |

### Таблица `review_schedule`

| Колонка       | Тип     | Описание                                      |
|--------------|---------|-----------------------------------------------|
| id           | INTEGER | Первичный ключ                                |
| problem_id   | INTEGER | FK → problems.id                              |
| session_id   | INTEGER | FK → practice_sessions.id (заполняется при выполнении) |
| scheduled_for| DATETIME| Дата запланированного повторения              |
| completed_at | DATETIME| Дата выполнения (NULL если не выполнено)      |

### Расположение файлов БД

| ОС      | Путь                                              |
|---------|---------------------------------------------------|
| Linux   | `~/.local/share/leetcode-tracker/tracker.db`     |
| macOS   | `~/.local/share/leetcode-tracker/tracker.db`     |
| Windows | `%APPDATA%\leetcode-tracker\tracker.db`           |

Переопределить: `export LCT_DATA_DIR=/path/to/dir`

---

## Статистика и метрики

Команда `lct stats` показывает:

- **Общее время**: суммарно, отдельно для новых задач и повторений
- **Среднее время**: по всем сессиям, по новым, по повторениям
- **По сложности**: количество сессий, суммарное и среднее время для Easy/Medium/Hard
- **По тегам**: топ-10 типов задач по суммарному времени (two-pointers, dp, graph и т.д.)
- **Прогресс**: для конкретной задачи — сравнение первого и последнего результата

Тренд (`--trend`) показывает ASCII-диаграмму активности по дням:

```
  2024-11-20  ████████  1ч 20м (3 сессии)
  2024-11-21  ████      40м (2 сессии)
  2024-11-22  ·         0с (0 сессий)
  2024-11-23  ██████████████  2ч 10м (5 сессий)
```

---

## Тестирование

```bash
# Установить dev-зависимости
pip install -r requirements-dev.txt

# Запустить все тесты
pytest

# С отчётом о покрытии
pytest --cov=leetcode_tracker --cov-report=html

# Конкретный модуль
pytest tests/test_repository.py -v

# С выводом логов
pytest -s -v
```

### Структура тестов

| Файл                   | Что тестирует                              | Тип          |
|------------------------|---------------------------------------------|--------------|
| `test_models.py`       | SQLAlchemy модели, вычисление времени        | Unit         |
| `test_repository.py`   | CRUD-операции, бизнес-логика репозиториев   | Unit         |
| `test_stats.py`        | Расчёт статистики, форматирование времени   | Unit         |
| `test_auth.py`         | Шифрование/дешифрование cookie              | Unit         |
| `test_api.py`          | GraphQL клиент (мокирование через respx)    | Integration  |
| `test_export.py`       | JSON/CSV экспорт                            | Unit         |
| `test_cli.py`          | CLI команды через Click test runner         | Integration  |

---

## Структура проекта

```
leetcode-tracker/
├── src/
│   └── leetcode_tracker/
│       ├── __init__.py         # версия, описание
│       ├── cli.py              # все CLI команды (Click)
│       ├── config.py           # пути, константы, env-переменные
│       ├── db/
│       │   ├── __init__.py
│       │   ├── models.py       # SQLAlchemy модели + миграции
│       │   └── repository.py   # слой доступа к данным
│       ├── api/
│       │   ├── __init__.py
│       │   ├── auth.py         # безопасное хранение cookie
│       │   └── leetcode.py     # GraphQL клиент
│       ├── tracker/
│       │   ├── __init__.py
│       │   └── stats.py        # расчёт статистики
│       └── export/
│           ├── __init__.py
│           └── exporters.py    # JSON/CSV экспорт
├── tests/
│   ├── conftest.py             # общие фикстуры
│   ├── test_models.py
│   ├── test_repository.py
│   ├── test_stats.py
│   ├── test_auth.py
│   ├── test_api.py
│   ├── test_export.py
│   └── test_cli.py
├── pyproject.toml              # метаданные, зависимости, entry points
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

---

## План итераций

### MVP (текущая версия v1.0)

- Добавление задач вручную или через API
- Трекер времени с паузами
- Система повторений (5 дней)
- Базовая статистика по сложности и тегам
- Экспорт JSON/CSV
- Безопасное хранение cookie
- 82% покрытие тестами

### v1.1 — Улучшения UX

- `lct dashboard` — интерактивный дашборд (Rich live view)
- Уведомления через системный трей (plyer)
- Автоматический запуск в фоне с напоминаниями
- Конфигурационный файл TOML (кастомный интервал повторений и т.д.)

### v1.2 — Расширенная аналитика

- Спейсд репетишн алгоритм SM-2 (вместо фиксированных 5 дней)
- Heatmap активности (Rich/ASCII)
- Метрика "consistency score"
- Прогноз времени до достижения цели

### v2.0 — Интеграции

- Синхронизация с Anki (карточки для алгоритмов)
- Экспорт в Notion/Obsidian markdown
- Telegram-бот для напоминаний
- GitHub Actions workflow для ежедневной статистики в README

---

## Настройка через переменные окружения

| Переменная          | По умолчанию | Описание                            |
|--------------------|--------------|--------------------------------------|
| `LCT_DATA_DIR`     | (платформенный) | Каталог данных приложения          |
| `LCT_REVIEW_DAYS`  | `5`          | Интервал повторений в днях           |

---

## Лицензия

MIT License — используйте свободно.