"""
Точка входа CLI-приложения.

Команды:
  lct add       <slug>          — добавить задачу (из API или вручную)
  lct start     <slug>          — начать сессию решения
  lct pause                     — поставить активную сессию на паузу
  lct resume                    — продолжить после паузы
  lct stop                      — завершить сессию
  lct status                    — показать текущую активную сессию
  lct review                    — показать задачи для повторения сегодня
  lct open      <slug>          — открыть задачу в браузере
  lct correct   <session_id>    — скорректировать время сессии вручную
  lct list                      — список всех задач
  lct stats                     — показать статистику
  lct export    json|csv        — экспортировать данные
  lct auth      set-cookie      — сохранить LeetCode session cookie
  lct auth      status          — проверить статус авторизации
  lct auth      clear           — удалить сохранённый cookie
"""

from __future__ import annotations

import logging
import sys
import webbrowser
from contextlib import contextmanager
from typing import Generator

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from api.auth import (
    delete_cookie,
    is_cookie_configured,
    save_cookie,
)
from api.leetcode import LeetCodeClient
from config import (
    DIFFICULTY_COLORS,
    LEETCODE_PROBLEM_URL,
    REVIEW_INTERVAL_DAYS,
)
from db.models import (
    Difficulty,
    SessionType,
    init_db,
)
from db.repository import (
    ProblemRepository,
    ReviewRepository,
    SessionRepository,
)
from export.exporters import CsvExporter, JsonExporter
from tracker.stats import StatsCalculator, format_duration

# ---------------------------------------------------------------------------
# Инициализация
# ---------------------------------------------------------------------------

console = Console()
err_console = Console(stderr=True, style="bold red")

# Настройка логирования: только предупреждения и выше в stderr
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
)


# ---------------------------------------------------------------------------
# Вспомогательный контекст-менеджер для сессии БД
# ---------------------------------------------------------------------------

@contextmanager
def db_session() -> Generator:
    """
    Контекст-менеджер, открывающий сессию БД.
    При успехе — commit; при исключении — rollback.
    """
    _, SessionFactory = init_db()
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Утилиты отображения
# ---------------------------------------------------------------------------

def _difficulty_color(difficulty: str) -> str:
    return DIFFICULTY_COLORS.get(difficulty, "white")


def _print_problem_table(problems: list) -> None:
    """Вывести список задач в виде таблицы."""
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=6)
    table.add_column("Slug", style="cyan")
    table.add_column("Название")
    table.add_column("Сложность", width=10)
    table.add_column("Теги")

    for p in problems:
        color = _difficulty_color(p.difficulty.value)
        table.add_row(
            str(p.frontend_id or "—"),
            p.slug,
            p.title,
            f"[{color}]{p.difficulty.value}[/{color}]",
            ", ".join(p.tags[:4]) + ("..." if len(p.tags) > 4 else ""),
        )

    console.print(table)


def _print_session_info(session, label: str = "Активная сессия") -> None:
    """Вывести информацию об активной сессии."""
    from datetime import datetime
    elapsed = session.compute_net_seconds()
    problem = session.problem

    console.print(
        Panel(
            f"[bold]{label}[/bold] #{session.id}\n"
            f"Задача:   [{_difficulty_color(problem.difficulty.value)}]{problem.title}[/{_difficulty_color(problem.difficulty.value)}] "
            f"([dim]{problem.slug}[/dim])\n"
            f"Тип:      {'Новая' if session.session_type.value == 'new' else 'Повторение'}\n"
            f"Статус:   {session.status.value}\n"
            f"Время:    [bold green]{format_duration(elapsed)}[/bold green]",
            title="[bold blue]LeetCode Tracker[/bold blue]",
            border_style="blue",
        )
    )


# ---------------------------------------------------------------------------
# Корневая группа команд
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(version="1.0.0", prog_name="lct")
def main() -> None:
    """LeetCode Tracker — система интервальных повторений для подготовки к олимпиадам."""
    pass


# ---------------------------------------------------------------------------
# lct add <slug>
# ---------------------------------------------------------------------------

@main.command()
@click.argument("slug")
@click.option("--title",      "-t", default=None, help="Название задачи (если без API)")
@click.option("--difficulty", "-d", default=None,
              type=click.Choice(["Easy", "Medium", "Hard"]), help="Сложность")
@click.option("--tags",       "-g", default="", help="Теги через запятую")
@click.option("--no-api",     is_flag=True, help="Не обращаться к LeetCode API")
def add(slug: str, title: str | None, difficulty: str | None, tags: str, no_api: bool) -> None:
    """Добавить задачу в трекер.

    SLUG — идентификатор задачи из URL, например: two-sum, longest-substring-without-repeating-characters
    """
    url = LEETCODE_PROBLEM_URL.format(slug=slug)

    # Пытаемся получить данные из API
    api_problem = None
    if not no_api:
        if is_cookie_configured():
            console.print("[dim]Запрашиваем данные задачи из LeetCode API...[/dim]")
            try:
                with LeetCodeClient() as client:
                    api_problem = client.get_problem_detail(slug)
            except Exception as e:
                console.print(f"[yellow]API недоступен: {e}. Используем ручной ввод.[/yellow]")
        else:
            console.print(
                "[yellow]Cookie не настроен. Используйте 'lct auth set-cookie' для авторизации.[/yellow]"
            )

    # Определяем финальные поля
    if api_problem:
        final_title      = api_problem.title
        final_difficulty = api_problem.difficulty
        final_tags       = api_problem.tags
        final_id         = api_problem.frontend_id
        url              = api_problem.url
    else:
        # Ручной ввод
        if not title:
            title = click.prompt("Название задачи")
        if not difficulty:
            difficulty = click.prompt(
                "Сложность",
                type=click.Choice(["Easy", "Medium", "Hard"]),
                default="Medium",
            )
        final_title      = title
        final_difficulty = difficulty
        final_tags       = [t.strip() for t in tags.split(",") if t.strip()]
        final_id         = None

    # Сохраняем в БД
    with db_session() as db:
        repo = ProblemRepository(db)
        problem = repo.create(
            slug=slug,
            title=final_title,
            difficulty=Difficulty(final_difficulty),
            tags=final_tags,
            url=url,
            frontend_id=final_id,
        )

    color = _difficulty_color(final_difficulty)
    console.print(
        f"[green]Задача добавлена:[/green] [{color}]{final_title}[/{color}] "
        f"([dim]{slug}[/dim])"
    )


# ---------------------------------------------------------------------------
# lct start <slug>
# ---------------------------------------------------------------------------

@main.command()
@click.argument("slug")
@click.option("--review", "-r", is_flag=True, help="Отметить как повторение (не новая задача)")
def start(slug: str, review: bool) -> None:
    """Начать сессию решения задачи и запустить таймер.

    SLUG — идентификатор задачи (должна быть добавлена командой 'lct add').
    """
    with db_session() as db:
        prob_repo    = ProblemRepository(db)
        sess_repo    = SessionRepository(db)
        review_repo  = ReviewRepository(db)

        problem = prob_repo.get_by_slug(slug)
        if not problem:
            err_console.print(
                f"Задача '{slug}' не найдена. Сначала добавьте её: lct add {slug}"
            )
            sys.exit(1)

        session_type = SessionType.REVIEW if review else SessionType.NEW
        try:
            session = sess_repo.start(problem, session_type)
        except RuntimeError as e:
            err_console.print(str(e))
            sys.exit(1)

        # Если это первое решение (new) — запланировать повторение
        if session_type == SessionType.NEW:
            review_repo.schedule(problem)
            console.print(
                f"[dim]Повторение запланировано через {REVIEW_INTERVAL_DAYS} дней.[/dim]"
            )

        # Сохраняем данные задачи ДО закрытия сессии БД
        problem_title      = problem.title
        problem_difficulty = problem.difficulty.value

    type_label = "Повторение" if review else "Новая задача"
    color = _difficulty_color(problem_difficulty)
    console.print(
        f"[green]Таймер запущен[/green] — {type_label}: "
        f"[{color}]{problem_title}[/{color}]"
    )
    console.print("[dim]Остановить: lct stop  |  Пауза: lct pause[/dim]")


# ---------------------------------------------------------------------------
# lct pause
# ---------------------------------------------------------------------------

@main.command()
def pause() -> None:
    """Поставить активную сессию на паузу."""
    with db_session() as db:
        sess_repo = SessionRepository(db)
        session = sess_repo.get_active()

        if not session:
            err_console.print("Нет активной сессии. Начните с 'lct start <slug>'.")
            sys.exit(1)

        try:
            sess_repo.pause(session)
        except RuntimeError as e:
            err_console.print(str(e))
            sys.exit(1)

        elapsed = session.compute_net_seconds()
        console.print(
            f"[yellow]Пауза.[/yellow] Прошло: [bold]{format_duration(elapsed)}[/bold]. "
            "Продолжить: [dim]lct resume[/dim]"
        )


# ---------------------------------------------------------------------------
# lct resume
# ---------------------------------------------------------------------------

@main.command()
def resume() -> None:
    """Продолжить сессию после паузы."""
    with db_session() as db:
        sess_repo = SessionRepository(db)
        session = sess_repo.get_active()

        if not session:
            err_console.print("Нет активной сессии.")
            sys.exit(1)

        try:
            sess_repo.resume(session)
        except RuntimeError as e:
            err_console.print(str(e))
            sys.exit(1)

        console.print("[green]Таймер возобновлён.[/green] Продолжайте решать!")


# ---------------------------------------------------------------------------
# lct stop
# ---------------------------------------------------------------------------

@main.command()
@click.option("--notes", "-n", default=None, help="Заметки по сессии")
def stop(notes: str | None) -> None:
    """Завершить активную сессию и зафиксировать время."""
    with db_session() as db:
        sess_repo   = SessionRepository(db)
        review_repo = ReviewRepository(db)
        session     = sess_repo.get_active()

        if not session:
            err_console.print("Нет активной сессии.")
            sys.exit(1)

        if notes:
            session.notes = notes

        sess_repo.finish(session)

        # Если это повторение — отмечаем review как выполненное
        if session.session_type == SessionType.REVIEW:
            due_reviews = review_repo.get_due()
            for r in due_reviews:
                if r.problem_id == session.problem_id:
                    review_repo.mark_completed(r, session)
                    break

        elapsed = session.net_duration_secs or 0
        color = _difficulty_color(session.problem.difficulty.value)

        console.print(
            f"[green]Сессия завершена.[/green] "
            f"[{color}]{session.problem.title}[/{color}] — "
            f"[bold]{format_duration(elapsed)}[/bold]"
        )


# ---------------------------------------------------------------------------
# lct status
# ---------------------------------------------------------------------------

@main.command()
def status() -> None:
    """Показать текущую активную сессию."""
    with db_session() as db:
        sess_repo = SessionRepository(db)
        session   = sess_repo.get_active()

        if not session:
            console.print("[dim]Нет активных сессий.[/dim]")
            return

        _print_session_info(session)


# ---------------------------------------------------------------------------
# lct review
# ---------------------------------------------------------------------------

@main.command()
@click.option("--open-browser", "-o", is_flag=True, help="Открыть все задачи в браузере")
@click.option("--upcoming",     "-u", is_flag=True, help="Показать предстоящие повторения (7 дней)")
def review(open_browser: bool, upcoming: bool) -> None:
    """Показать задачи для повторения сегодня."""
    with db_session() as db:
        review_repo = ReviewRepository(db)

        if upcoming:
            items = review_repo.get_upcoming(days=7)
            title = "Предстоящие повторения (7 дней)"
        else:
            items = review_repo.get_due()
            title = "Задачи для повторения сегодня"

        if not items:
            console.print(f"[green]Нет задач для {title.lower()}.[/green]")
            return

        table = Table(
            title=title,
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Slug", style="cyan")
        table.add_column("Название")
        table.add_column("Сложность", width=10)
        table.add_column("Запланировано", width=15)
        table.add_column("Теги")

        for r in items:
            p = r.problem
            color = _difficulty_color(p.difficulty.value)
            table.add_row(
                p.slug,
                p.title,
                f"[{color}]{p.difficulty.value}[/{color}]",
                r.scheduled_for.strftime("%d.%m.%Y"),
                ", ".join(p.tags[:3]) + ("..." if len(p.tags) > 3 else ""),
            )

        console.print(table)
        console.print(
            f"\n[dim]Начать повторение: lct start <slug> --review[/dim]"
        )

        if open_browser:
            for r in items:
                url = r.problem.url
                console.print(f"[dim]Открываю: {url}[/dim]")
                webbrowser.open(url)


# ---------------------------------------------------------------------------
# lct open <slug>
# ---------------------------------------------------------------------------

@main.command(name="open")
@click.argument("slug")
def open_problem(slug: str) -> None:
    """Открыть задачу в браузере (без готового решения).

    SLUG — идентификатор задачи.
    """
    url = LEETCODE_PROBLEM_URL.format(slug=slug)
    console.print(f"[dim]Открываю: {url}[/dim]")
    webbrowser.open(url)


# ---------------------------------------------------------------------------
# lct correct <session_id> <minutes>
# ---------------------------------------------------------------------------

@main.command()
@click.argument("session_id", type=int)
@click.argument("minutes",    type=float)
def correct(session_id: int, minutes: float) -> None:
    """Скорректировать время завершённой сессии вручную.

    SESSION_ID — номер сессии (из 'lct list' или 'lct stats').
    MINUTES    — новое чистое время в минутах.
    """
    new_seconds = int(minutes * 60)

    with db_session() as db:
        sess_repo = SessionRepository(db)
        session   = sess_repo.get_by_id(session_id)

        if not session:
            err_console.print(f"Сессия #{session_id} не найдена.")
            sys.exit(1)

        try:
            sess_repo.correct_time(session, new_seconds)
        except (RuntimeError, ValueError) as e:
            err_console.print(str(e))
            sys.exit(1)

        console.print(
            f"[green]Время сессии #{session_id} скорректировано:[/green] "
            f"[bold]{format_duration(new_seconds)}[/bold]"
        )


# ---------------------------------------------------------------------------
# lct list
# ---------------------------------------------------------------------------

@main.command(name="list")
@click.option("--difficulty", "-d",
              type=click.Choice(["Easy", "Medium", "Hard"]),
              default=None, help="Фильтр по сложности")
@click.option("--tag", "-t", default=None, help="Фильтр по тегу")
@click.option("--search", "-s", default=None, help="Поиск по названию/slug")
def list_problems(difficulty: str | None, tag: str | None, search: str | None) -> None:
    """Показать все добавленные задачи."""
    with db_session() as db:
        repo = ProblemRepository(db)

        if search:
            problems = repo.search(search)
        else:
            problems = repo.list_all()

        # Фильтры
        if difficulty:
            problems = [p for p in problems if p.difficulty.value == difficulty]
        if tag:
            problems = [p for p in problems if tag.lower() in [t.lower() for t in p.tags]]

        if not problems:
            console.print("[dim]Задачи не найдены.[/dim]")
            return

        _print_problem_table(problems)
        console.print(f"\n[dim]Всего: {len(problems)} задач[/dim]")


# ---------------------------------------------------------------------------
# lct stats
# ---------------------------------------------------------------------------

@main.command()
@click.option("--days",  "-d", default=30, help="Статистика за последние N дней (0 = за всё время)")
@click.option("--slug",  "-s", default=None, help="Статистика по конкретной задаче")
@click.option("--trend", "-t", is_flag=True, help="Показать тренд по дням")
def stats(days: int, slug: str | None, trend: bool) -> None:
    """Показать статистику практики."""
    from datetime import datetime, timedelta

    with db_session() as db:
        sess_repo = SessionRepository(db)
        prob_repo = ProblemRepository(db)

        if slug:
            # Статистика по конкретной задаче
            problem = prob_repo.get_by_slug(slug)
            if not problem:
                err_console.print(f"Задача '{slug}' не найдена.")
                sys.exit(1)

            sessions = sess_repo.list_for_problem(problem.id)
            calc     = StatsCalculator(sessions)
            overall  = calc.compute()

            console.print(
                Panel(
                    f"[bold]{problem.title}[/bold]\n"
                    f"Сложность: [{_difficulty_color(problem.difficulty.value)}]{problem.difficulty.value}[/{_difficulty_color(problem.difficulty.value)}]\n"
                    f"Теги: {', '.join(problem.tags)}\n\n"
                    f"Попыток:           {overall.total_sessions}\n"
                    f"Суммарное время:   {format_duration(overall.total_seconds)}\n"
                    f"Среднее время:     {format_duration(int(overall.avg_seconds_all))}",
                    title=f"Задача: {slug}",
                    border_style="blue",
                )
            )

            # Прогресс (улучшение со временем)
            improvement = calc.compute_improvement_rate(problem.id)
            if improvement:
                sign = "-" if improvement["improvement_pct"] >= 0 else "+"
                console.print(
                    f"Первое решение:  [bold]{improvement['first_fmt']}[/bold]  →  "
                    f"Последнее: [bold]{improvement['last_fmt']}[/bold]  "
                    f"([{'green' if improvement['improvement_pct'] >= 0 else 'red'}]"
                    f"{sign}{abs(improvement['improvement_pct']):.1f}%[/])"
                )
            return

        # Общая статистика
        if days > 0:
            date_from = datetime.utcnow() - timedelta(days=days)
            date_to   = datetime.utcnow()
            sessions  = sess_repo.list_finished_in_range(date_from, date_to)
            period_label = f"за последние {days} дней"
        else:
            # За всё время — загружаем все сессии через list_finished_in_range с широким диапазоном
            from datetime import datetime as dt
            sessions = sess_repo.list_finished_in_range(
                dt(2000, 1, 1), dt(2100, 1, 1)
            )
            period_label = "за всё время"

        calc    = StatsCalculator(sessions)
        overall = calc.compute()

        # --- Сводная панель ---
        console.print(
            Panel(
                f"Сессий всего:      [bold]{overall.total_sessions}[/bold] "
                f"([green]{overall.new_sessions}[/green] новых, "
                f"[cyan]{overall.review_sessions}[/cyan] повторений)\n"
                f"Уникальных задач:  [bold]{overall.unique_problems}[/bold]\n\n"
                f"Суммарное время:   [bold green]{format_duration(overall.total_seconds)}[/bold green]\n"
                f"  Новые задачи:    {format_duration(overall.new_total_seconds)}\n"
                f"  Повторения:      {format_duration(overall.review_total_seconds)}\n\n"
                f"Среднее время:     [bold]{format_duration(int(overall.avg_seconds_all))}[/bold]\n"
                f"  Новые задачи:    {format_duration(int(overall.avg_seconds_new))}\n"
                f"  Повторения:      {format_duration(int(overall.avg_seconds_review))}",
                title=f"[bold blue]Статистика {period_label}[/bold blue]",
                border_style="blue",
            )
        )

        # --- По сложности ---
        if overall.by_difficulty:
            diff_table = Table(title="По сложности", box=box.SIMPLE)
            diff_table.add_column("Сложность")
            diff_table.add_column("Сессий", justify="right")
            diff_table.add_column("Суммарно", justify="right")
            diff_table.add_column("Среднее", justify="right")

            for diff_name in ("Easy", "Medium", "Hard"):
                if diff_name in overall.by_difficulty:
                    d = overall.by_difficulty[diff_name]
                    color = _difficulty_color(diff_name)
                    diff_table.add_row(
                        f"[{color}]{diff_name}[/{color}]",
                        str(d.count),
                        format_duration(d.total_seconds),
                        format_duration(int(d.avg_seconds)),
                    )
            console.print(diff_table)

        # --- Топ тегов ---
        if overall.by_tag:
            tag_table = Table(title="Топ типов задач (по времени)", box=box.SIMPLE)
            tag_table.add_column("Тег/Тип")
            tag_table.add_column("Сессий", justify="right")
            tag_table.add_column("Суммарно", justify="right")
            tag_table.add_column("Среднее", justify="right")

            for tag_stats in list(overall.by_tag.values())[:10]:
                tag_table.add_row(
                    tag_stats.tag,
                    str(tag_stats.count),
                    format_duration(tag_stats.total_seconds),
                    format_duration(int(tag_stats.avg_seconds)),
                )
            console.print(tag_table)

        # --- Тренд по дням ---
        if trend:
            daily = calc.compute_daily_trend(days=min(days, 30) if days > 0 else 30)
            console.print("\n[bold]Тренд (последние 30 дней):[/bold]")
            for day in daily:
                if day["session_count"] > 0:
                    bar = "█" * min(40, day["total_seconds"] // 300)
                    console.print(
                        f"  {day['date']}  {bar or '·'}  "
                        f"[dim]{format_duration(day['total_seconds'])} "
                        f"({day['session_count']} сессий)[/dim]"
                    )


# ---------------------------------------------------------------------------
# lct export
# ---------------------------------------------------------------------------

@main.command(name="export")
@click.argument("fmt", type=click.Choice(["json", "csv"]))
@click.option("--what", "-w",
              type=click.Choice(["problems", "sessions", "reviews", "all"]),
              default="all", help="Что экспортировать")
def export_data(fmt: str, what: str) -> None:
    """Экспортировать данные в файл.

    FMT — формат: json или csv
    """
    from datetime import datetime

    with db_session() as db:
        prob_repo   = ProblemRepository(db)
        sess_repo   = SessionRepository(db)
        review_repo = ReviewRepository(db)

        problems = prob_repo.list_all()
        sessions = sess_repo.list_finished_in_range(
            datetime(2000, 1, 1), datetime(2100, 1, 1)
        )
        reviews = review_repo.get_for_problem

        exported: list[str] = []

        if what in ("problems", "all"):
            if fmt == "json":
                path = JsonExporter.export_problems(problems)
            else:
                path = CsvExporter.export_problems(problems)
            exported.append(str(path))

        if what in ("sessions", "all"):
            if fmt == "json":
                path = JsonExporter.export_sessions(sessions)
            else:
                path = CsvExporter.export_sessions(sessions)
            exported.append(str(path))

        if what in ("reviews", "all") and fmt == "json":
            all_reviews = (
                db.query(__import__(
                    "leetcode_tracker.db.models", fromlist=["ReviewSchedule"]
                ).ReviewSchedule).all()
            )
            path = JsonExporter.export_review_schedule(all_reviews)
            exported.append(str(path))

    for p in exported:
        console.print(f"[green]Экспортировано:[/green] {p}")


# ---------------------------------------------------------------------------
# lct auth
# ---------------------------------------------------------------------------

@main.group()
def auth() -> None:
    """Управление авторизацией в LeetCode."""
    pass


@auth.command(name="set-cookie")
@click.option("--cookie", "-c", default=None,
              help="Значение LEETCODE_SESSION cookie (если не указано — спросит интерактивно)")
def auth_set_cookie(cookie: str | None) -> None:
    """Сохранить LeetCode session cookie для авторизации в API.

    Cookie можно найти в браузере:
      DevTools → Application → Cookies → leetcode.com → LEETCODE_SESSION
    """
    if not cookie:
        # Не показываем введённое значение в терминале (getpass-style)
        cookie = click.prompt("LEETCODE_SESSION cookie", hide_input=True)

    if not cookie or len(cookie) < 10:
        err_console.print("Cookie выглядит некорректным. Проверьте значение.")
        sys.exit(1)

    save_cookie(cookie)
    console.print("[green]Cookie сохранён.[/green] Авторизация настроена.")


@auth.command(name="status")
def auth_status() -> None:
    """Проверить статус авторизации."""
    if is_cookie_configured():
        console.print("[green]Cookie настроен.[/green] Авторизация активна.")
    else:
        console.print(
            "[yellow]Cookie не настроен.[/yellow] "
            "Используйте: lct auth set-cookie"
        )


@auth.command(name="clear")
@click.confirmation_option(prompt="Удалить сохранённый cookie?")
def auth_clear() -> None:
    """Удалить сохранённый cookie."""
    delete_cookie()
    console.print("[green]Cookie удалён.[/green]")


# ---------------------------------------------------------------------------
# lct sync (продвинутая команда: синхронизация с API)
# ---------------------------------------------------------------------------

@main.command()
@click.argument("username")
@click.option("--limit", "-l", default=50, help="Максимальное количество задач")
def sync(username: str, limit: int) -> None:
    """Синхронизировать решённые задачи с LeetCode API.

    USERNAME — имя пользователя на LeetCode.
    Требует настроенного cookie ('lct auth set-cookie').
    """
    if not is_cookie_configured():
        err_console.print(
            "Cookie не настроен. Выполните: lct auth set-cookie"
        )
        sys.exit(1)

    console.print(f"[dim]Загружаем задачи пользователя '{username}'...[/dim]")

    try:
        with LeetCodeClient() as client:
            # Получаем последние accepted submissions
            submissions = client.get_recent_accepted(username, limit=limit)
    except Exception as e:
        err_console.print(f"Ошибка API: {e}")
        sys.exit(1)

    if not submissions:
        console.print("[yellow]Нет решённых задач или API недоступен.[/yellow]")
        return

    added = 0
    with db_session() as db:
        prob_repo = ProblemRepository(db)
        review_repo = ReviewRepository(db)

        with LeetCodeClient() as client:
            with console.status("[bold green]Синхронизация..."):
                for sub in submissions:
                    slug = sub.get("titleSlug", "")
                    if not slug:
                        continue

                    # Проверяем — уже есть в БД?
                    existing = prob_repo.get_by_slug(slug)
                    if existing:
                        continue

                    # Получаем детали задачи
                    detail = client.get_problem_detail(slug)
                    if not detail:
                        continue

                    problem = prob_repo.create(
                        slug=detail.slug,
                        title=detail.title,
                        difficulty=Difficulty(detail.difficulty),
                        tags=detail.tags,
                        url=detail.url,
                        frontend_id=detail.frontend_id,
                    )
                    # Планируем повторение
                    review_repo.schedule(problem)
                    added += 1

    console.print(f"[green]Синхронизация завершена.[/green] Добавлено новых задач: [bold]{added}[/bold]")


if __name__ == "__main__":
    main()