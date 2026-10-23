"""Distribution automation for the AARI Arctic overview chart."""
from __future__ import annotations

import argparse
import filecmp
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Sequence

try:
    from dotenv import load_dotenv
except ImportError:  # Basic diagnostics remain available if dependencies are missing.
    load_dotenv = None

PROJECT_DIR = Path(__file__).resolve().parent
if load_dotenv:
    load_dotenv(PROJECT_DIR / ".env")

COMPONENTS = (".shp", ".shx", ".dbf", ".prj")
SOURCE_ROOT = Path(os.getenv("AARI_SOURCE_ROOT", r"\\10.31.34.60\Tiris\МОРЕ\ОБОБЩЕНКА_ОТПРАВКА"))
MORE_ROOT = Path(os.getenv("AARI_MORE_ROOT", r"\\10.31.34.60\Tiris\МОРЕ"))
ICE_CHARTS_ROOT = Path(os.getenv("AARI_ICE_CHARTS_ROOT", r"\\files.aari.ru\Ice_charts"))
MORSPASS_ROOT = Path(os.getenv("AARI_MORSPASS_ROOT", r"\\files.aari.ru\morspass"))
SOVBEZ_ROOT = Path(os.getenv("AARI_SOVBEZ_ROOT", r"\\files.aari.ru\sovbez"))
ICECHARTS_V_ROOT = Path(os.getenv("AARI_ICECHARTS_V_ROOT", r"\\10.31.34.110\C373\IceCharts"))
LVP_WAVE_ROOT = Path(os.getenv("AARI_LVP_WAVE_ROOT", r"\\10.31.34.60\Tiris\LVP_WAVE"))
WEBSITE_ROOT = Path(os.getenv("AARI_WEBSITE_ROOT", r"\\data.aari.ru\d0015\arctic"))
LOG_FILE = Path(os.getenv("AARI_LOG_FILE", str(SOURCE_ROOT / "aari_generalized_map.log")))
STATUS_FILE = Path(os.getenv("AARI_STATUS_FILE", str(SOURCE_ROOT / "STATUS.txt")))
MIN_SIZE_RATIO = float(os.getenv("AARI_SIZE_MIN_RATIO", "0.35"))
MAX_SIZE_RATIO = float(os.getenv("AARI_SIZE_MAX_RATIO", "2.5"))

# Approximate byte sizes from the reference release of 20 October 2026.
# A broad range is used only to flag obviously anomalous files.
SIZE_BASELINES: dict[str, dict[str, int]] = {
    "shp.general": {".shp": 13361888, ".shx": 7996, ".dbf": 197503, ".prj": 390},
    "shp.east": {".shp": 7239624, ".shx": 7276, ".dbf": 179593, ".prj": 390},
    "shp.west": {".shp": 7413208, ".shx": 3084, ".dbf": 75317, ".prj": 390},
    "shp.arctic": {".shp": 14641544, ".shx": 10116, ".dbf": 250238, ".prj": 390},
    "shp.oldshore": {".shp": 3409080, ".shx": 5284, ".dbf": 130042, ".prj": 390},
    "sigrid.arc": {".shp": 13361888, ".shx": 7996, ".dbf": 133791, ".prj": 145},
    "sigrid.east": {".shp": 7239624, ".shx": 7276, ".dbf": 121641, ".prj": 145},
    "sigrid.west": {".shp": 7413208, ".shx": 3084, ".dbf": 50901, ".prj": 145},
    "lvp": {".shp": 15411720, ".shx": 10868, ".dbf": 268944, ".prj": 390},
    "pic.jpg": {".jpg": 1003764}, "pic.gif": {".gif": 464915},
    "pic.bmp": {".bmp": 4178442}, "pic.east_png": {".png": 10514759},
    "pic.west_png": {".png": 9155920},
    "website.sigrid": {".shp": 13361888, ".shx": 7996, ".dbf": 133791, ".prj": 145, ".zip": 10746612},
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
LOG = logging.getLogger("aari_generalized_map")


@dataclass(frozen=True)
class CopyJob:
    name: str
    sources: tuple[Path, ...]
    target_dir: Path
    size_family: str


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str


def setup_logging() -> None:
    """Write the run log to the shared source folder; fall back to the console."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handlers.insert(0, logging.FileHandler(LOG_FILE, encoding="utf-8"))
    except OSError as exc:
        print(f"Не удалось открыть сетевой лог {LOG_FILE}: {exc}")
    logging.basicConfig(level=os.getenv("AARI_LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s | %(levelname)s | %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers, force=True)


def product_date(release_folder_date: date) -> date:
    """Return the Tuesday chart date for a Wednesday release folder."""
    return release_folder_date - timedelta(days=1)


def release_range(chart_date: date) -> tuple[date, date]:
    return chart_date - timedelta(days=2), chart_date


def russian_date_range(chart_date: date) -> str:
    start, end = release_range(chart_date)
    months = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
    if start.year == end.year and start.month == end.month:
        return f"{start.day}-{end.day} {months[end.month - 1]} {end.year} года"
    return f"{start.day} {months[start.month - 1]}-{end.day} {months[end.month - 1]} {end.year} года"


def shape_components(folder: Path, stem: str) -> tuple[Path, ...]:
    return tuple(folder / f"{stem}{suffix}" for suffix in COMPONENTS)


def png_name(chart_date: date, region: str) -> str:
    start, end = release_range(chart_date)
    return f"{start.year}_{start.month:02d}_{start.day:02d}-{end.day:02d}_{region}.png"


def build_jobs(run_date: date, stage: str) -> list[CopyJob]:
    """Build the copy list for one invocation; date arguments are real run dates."""
    jobs: list[CopyJob] = []
    if stage == "oldshore":
        stamp = (run_date - timedelta(days=1)).strftime("%Y%m%d")
        folder = SOURCE_ROOT / run_date.isoformat() / "old_shore"
        return [CopyJob("Арктика SHP по старому берегу", shape_components(folder, f"{stamp}О"), ICE_CHARTS_ROOT / "Арктика" / "SHP", "shp.oldshore")]

    if stage == "wednesday":
        chart = product_date(run_date)
        stamp = chart.strftime("%Y%m%d")
        folder = SOURCE_ROOT / run_date.isoformat()
        pic, shp, sigrid = (folder / name for name in ("PIC", "SHP", "sigrid"))
        west_png, east_png = pic / png_name(chart, "Запад"), pic / png_name(chart, "Восток")
        arc = shape_components(sigrid, f"aari_arc_{stamp}_pl_a")
        jobs.extend([
            CopyJob("МОРЕ: Общая.bmp", (pic / "Общая.bmp",), MORE_ROOT, "pic.bmp"),
            CopyJob("МОРЕ: PNG Запад", (west_png,), MORE_ROOT, "pic.west_png"),
            CopyJob("МОРЕ: PNG Восток", (east_png,), MORE_ROOT, "pic.east_png"),
            CopyJob("V IceCharts: JPG", (pic / f"{stamp}.jpg",), ICECHARTS_V_ROOT, "pic.jpg"),
            CopyJob("V IceCharts: SHP общей карты", shape_components(shp, stamp), ICECHARTS_V_ROOT, "shp.general"),
            CopyJob("Запад: PNG", (west_png,), ICE_CHARTS_ROOT / "Запад" / "PIC", "pic.west_png"),
            CopyJob("Восток: PNG", (east_png,), ICE_CHARTS_ROOT / "Восток" / "PIC", "pic.east_png"),
            CopyJob("Запад: SHP", shape_components(shp, f"{stamp}З"), ICE_CHARTS_ROOT / "Запад" / "SHP", "shp.west"),
            CopyJob("Восток: SHP", shape_components(shp, f"{stamp}В"), ICE_CHARTS_ROOT / "Восток" / "SHP", "shp.east"),
            CopyJob("Запад: SIGRID3", shape_components(sigrid, f"aari_west_{stamp}_pl_a"), ICE_CHARTS_ROOT / "Запад" / "SIGRID3", "sigrid.west"),
            CopyJob("Восток: SIGRID3", shape_components(sigrid, f"aari_east_{stamp}_pl_a"), ICE_CHARTS_ROOT / "Восток" / "SIGRID3", "sigrid.east"),
            CopyJob("Обобщенная: JPG", (pic / f"{stamp}.jpg",), ICE_CHARTS_ROOT / "Обобщенная" / "PIC" / str(chart.year) / f"{chart.month:02d}", "pic.jpg"),
            CopyJob("Обобщенная: SIGRID3", arc, ICE_CHARTS_ROOT / "Обобщенная" / "SIGRID3" / str(chart.year) / f"{chart.month:02d}", "sigrid.arc"),
            CopyJob("Морспас: JPG", (pic / f"{stamp}.jpg",), MORSPASS_ROOT / run_date.strftime("%Y%m%d"), "pic.jpg"),
            CopyJob("Морспас: SIGRID3", arc, MORSPASS_ROOT / run_date.strftime("%Y%m%d"), "sigrid.arc"),
            CopyJob("Совбез: JPG", (pic / f"{stamp}.jpg",), SOVBEZ_ROOT / run_date.strftime("%Y%m%d"), "pic.jpg"),
            CopyJob("Совбез: SIGRID3", arc, SOVBEZ_ROOT / run_date.strftime("%Y%m%d"), "sigrid.arc"),
        ])
        return jobs

    if stage == "thursday":
        release_day = run_date - timedelta(days=1)  # Wednesday folder.
        chart = product_date(release_day)
        stamp = chart.strftime("%Y%m%d")
        release_folder = SOURCE_ROOT / release_day.isoformat()
        jobs.append(CopyJob("LVP_WAVE", shape_components(release_folder / "LVP", stamp), LVP_WAVE_ROOT, "lvp"))

        previous_release_day = release_day - timedelta(days=7)
        previous_chart = product_date(previous_release_day)
        previous_stamp = previous_chart.strftime("%Y%m%d")
        website = SOURCE_ROOT / previous_release_day.isoformat() / "website"
        gif = website / f"{previous_stamp}.gif"  # One bilingual GIF is copied to both locations.
        jobs.extend([
            CopyJob("Сайт: GIF EN", (gif,), WEBSITE_ROOT / "gif.en" / str(previous_chart.year), "pic.gif"),
            CopyJob("Сайт: GIF RU", (gif,), WEBSITE_ROOT / "gif.ru" / str(previous_chart.year), "pic.gif"),
            CopyJob("Сайт: SIGRID + ZIP", shape_components(website, f"aari_arc_{previous_stamp}_pl_a") + (website / f"aari_arc_{previous_stamp}_pl_a.zip",), WEBSITE_ROOT / "sigrid" / str(previous_chart.year), "website.sigrid"),
        ])
        return jobs

    raise ValueError(f"Неизвестный этап: {stage}")


def inspect_job(job: CopyJob) -> list[str]:
    errors: list[str] = []
    suffixes = {path.suffix.lower() for path in job.sources}
    if suffixes.intersection(COMPONENTS) and not set(COMPONENTS).issubset(suffixes):
        errors.append("комплект SHP должен содержать .shp, .shx, .dbf и .prj")
    for source in job.sources:
        if not source.is_file():
            errors.append(f"не найден файл {source.name}")
            continue
        size = source.stat().st_size
        if size <= 0:
            errors.append(f"файл пустой: {source.name}")
            continue
        baseline = SIZE_BASELINES.get(job.size_family, {}).get(source.suffix.lower())
        if baseline:
            ratio = size / baseline
            if not MIN_SIZE_RATIO <= ratio <= MAX_SIZE_RATIO:
                errors.append(f"подозрительный размер {source.name}: {size:,} байт; эталон {baseline:,}; допустимо {MIN_SIZE_RATIO:.2f}–{MAX_SIZE_RATIO:.2f} от эталона")
    return errors


def copy_job(job: CopyJob, dry_run: bool) -> Result:
    errors = inspect_job(job)
    if errors:
        return Result(job.name, "BLOCKED", "; ".join(errors))
    if dry_run:
        return Result(job.name, "DRY-RUN", f"{len(job.sources)} файл(ов) → {job.target_dir}")
    copied, replaced, unchanged = 0, 0, 0
    try:
        job.target_dir.mkdir(parents=True, exist_ok=True)
        for source in job.sources:
            target = job.target_dir / source.name
            if target.is_file() and filecmp.cmp(source, target, shallow=False):
                unchanged += 1
                continue
            was_present = target.exists()
            shutil.copy2(source, target)  # Direct replacement; no extra archive/backup.
            if was_present:
                replaced += 1
                LOG.info("REPLACED | %s | %s → %s", source.name, source, target)
            else:
                copied += 1
                LOG.info("COPIED | %s | %s → %s", source.name, source, target)
        return Result(job.name, "OK", f"скопировано: {copied}; заменено: {replaced}; без изменений: {unchanged}; каталог: {job.target_dir}")
    except OSError as exc:
        LOG.exception("COPY_ERROR | %s", job.name)
        return Result(job.name, "ERROR", f"ошибка копирования в {job.target_dir}: {exc}")


def resolve_stage(requested: str, run_date: date, now: datetime) -> str | None:
    if requested != "auto":
        return requested
    if run_date.weekday() == 2:  # Wednesday
        if now.time() < dt_time(12, 0):
            return "oldshore"
        if now.time() < dt_time(15, 0):
            return "wednesday"
        return "report"
    if run_date.weekday() == 3:  # Thursday
        return "thursday"
    return None


def build_stage_jobs(run_date: date, stage: str) -> list[CopyJob]:
    """Wednesday's later runs retry old_shore as well as the main distribution."""
    if stage == "wednesday":
        return build_jobs(run_date, "oldshore") + build_jobs(run_date, "wednesday")
    return build_jobs(run_date, stage)


def create_next_week_template_folder(run_date: date, dry_run: bool) -> Result:
    """Create next Wednesday's folder structure without overwriting existing work."""
    next_date = run_date + timedelta(days=7)
    target_root = SOURCE_ROOT / next_date.isoformat()
    subfolders = ("LVP", "PIC", "SHP", "old_shore", "sigrid", "website")
    if dry_run:
        return Result("Шаблон следующей недели", "DRY-RUN", f"будет создана/дополнена папка {target_root} с подпапками: {', '.join(subfolders)}")
    try:
        target_root.mkdir(parents=True, exist_ok=True)
        created: list[str] = []
        existing: list[str] = []
        for name in subfolders:
            path = target_root / name
            if path.exists():
                if not path.is_dir():
                    return Result("Шаблон следующей недели", "ERROR", f"{path} уже существует, но это не папка")
                existing.append(name)
            else:
                path.mkdir()
                created.append(name)
        details = []
        if created:
            details.append("созданы: " + ", ".join(created))
        if existing:
            details.append("уже существовали и сохранены: " + ", ".join(existing))
        result = Result("Шаблон следующей недели", "OK", f"{target_root}; " + "; ".join(details))
        LOG.info("NEXT_WEEK_FOLDER | %s | %s", target_root, result.detail)
        return result
    except OSError as exc:
        LOG.exception("NEXT_WEEK_FOLDER_ERROR | %s", target_root)
        return Result("Шаблон следующей недели", "ERROR", f"не удалось создать {target_root}: {exc}")


def read_status_snapshot() -> str:
    try:
        return STATUS_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return f"Файл статуса не найден: {STATUS_FILE}. Проверьте журнал {LOG_FILE}."


def write_status(run_date: date, stage: str, dry_run: bool, results: Sequence[Result]) -> None:
    lines = [
        "ААНИИ / ЦЛГМИ — ОБОБЩЕНКА: ТЕКУЩИЙ СТАТУС",
        f"Время: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Дата рабочего каталога: {run_date.isoformat()}",
        f"Этап: {stage}",
        f"Режим: {'ПРОВЕРКА БЕЗ ЗАПИСИ' if dry_run else 'РАБОЧИЙ'}",
        "",
        "КУДА ВЫКЛАДЫВАЮТСЯ ФАЙЛЫ:",
        f"МОРЕ: {MORE_ROOT}", f"IceCharts: {ICECHARTS_V_ROOT}",
        f"Ice_charts Восток/Запад/Обобщенная/Арктика: {ICE_CHARTS_ROOT}",
        f"morspass: {MORSPASS_ROOT}", f"sovbez: {SOVBEZ_ROOT}",
        f"LVP_WAVE: {LVP_WAVE_ROOT}", f"Сайт: {WEBSITE_ROOT}",
        f"Журнал: {LOG_FILE}",
        "",
        "РЕЗУЛЬТАТ ПОСЛЕДНЕГО ЗАПУСКА:",
    ]
    lines.extend(f"[{result.status}] {result.name}: {result.detail}" for result in results)
    if not results:
        lines.append("Нет действий: запуск не попал в среднее/четверговое окно.")
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        LOG.error("Не удалось обновить STATUS.txt (%s): %s", STATUS_FILE, exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Автоматизация рассылки и публикации результатов Обобщёнки.")
    parser.add_argument("--date", help="Дата запуска для тестирования, YYYY-MM-DD.")
    parser.add_argument("--stage", choices=("auto", "validate", "oldshore", "wednesday", "thursday", "report"), default="auto")
    parser.add_argument("--execute", action="store_true", help="Выполнить копирование и отправку. Без флага работает dry-run.")
    parser.add_argument("--resend-changed-email", action="store_true", help="Разрешить повторную отправку изменившихся вложений после проверки экспертом.")
    args = parser.parse_args()
    setup_logging()
    try:
        run_date = date.fromisoformat(args.date) if args.date else date.today()
    except ValueError:
        parser.error("--date должен иметь формат YYYY-MM-DD")
    now = datetime.now()
    stage = resolve_stage(args.stage, run_date, now) or "inactive"
    dry_run = not args.execute
    LOG.info("START | date=%s | stage=%s | dry_run=%s", run_date, stage, dry_run)
    results: list[Result] = []

    if stage == "report":
        folder_result = create_next_week_template_folder(run_date, dry_run)
        LOG.info("[%s] %s: %s", folder_result.status, folder_result.name, folder_result.detail)
        status_snapshot = read_status_snapshot()
        chart = product_date(run_date)
        subject = f"Обобщёнка: отчёт за {russian_date_range(chart)}"
        report_body = (
            "Еженедельный отчёт по автоматизации «Обобщёнка»\n"
            f"Дата формирования: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"Период карты: {russian_date_range(chart)}\n\n"
            f"Подготовка каталога следующего выпуска: [{folder_result.status}] {folder_result.detail}\n\n"
            "Состояние основных операций (последний STATUS.txt):\n"
            f"{status_snapshot}\n\n"
            f"Полный журнал: {LOG_FILE}\n"
        )
        from email_sender import parse_report_recipients, send_weekly_report
        report_result = send_weekly_report(
            subject, report_body, run_date, log_path=LOG_FILE,
            smtp_server=os.getenv("AARI_SMTP_SERVER", "zmail.aari.ru"),
            smtp_port=int(os.getenv("AARI_SMTP_PORT", "465")),
            sender_email=os.getenv("AARI_EMAIL_ADDRESS", "").strip(),
            sender_name=os.getenv("AARI_EMAIL_NAME", "").strip(),
            password=os.getenv("AARI_EMAIL_PASSWORD", ""),
            recipient_list=parse_report_recipients(os.getenv("AARI_REPORT_RECIPIENTS", "")),
            dry_run=dry_run,
        )
        LOG.info("[%s] %s: %s", report_result.status, report_result.name, report_result.detail)
        report_failed = report_result.status in {"ERROR", "CONFIG_ERROR", "MAIL_ERROR", "REVIEW_REQUIRED"}
        return 1 if report_failed or folder_result.status == "ERROR" else 0

    if stage == "validate":
        release_day = run_date if run_date.weekday() == 2 else run_date - timedelta(days=1)
        for job in build_stage_jobs(release_day, "wednesday"):
            errors = inspect_job(job)
            results.append(Result(job.name, "ERROR" if errors else "OK", "; ".join(errors) if errors else f"файлы проверены: {len(job.sources)}"))
    elif stage != "inactive":
        for job in build_stage_jobs(run_date, stage):
            result = copy_job(job, dry_run)
            results.append(result)
            LOG.info("[%s] %s: %s", result.status, result.name, result.detail)

        if stage == "wednesday" and now.time() < dt_time(14, 50):
            waiting = Result("Почта", "WAITING", "рассылка отложена до финального запуска в 14:50; до этого проверяются и обновляются только файлы")
            results.append(waiting)
            LOG.info("EMAIL_WAITING | финальная попытка рассылки запланирована на 14:50")
        elif stage == "wednesday":
            from email_sender import build_email_jobs, process_email_jobs
            chart = product_date(run_date)
            email_jobs = build_email_jobs(SOURCE_ROOT / run_date.isoformat(), chart, PROJECT_DIR / "email_templates", russian_date_range(chart))
            mail_results = process_email_jobs(
                email_jobs, run_date, log_path=LOG_FILE, dry_run=dry_run,
                smtp_server=os.getenv("AARI_SMTP_SERVER", "zmail.aari.ru"),
                smtp_port=int(os.getenv("AARI_SMTP_PORT", "465")),
                sender_email=os.getenv("AARI_EMAIL_ADDRESS", "").strip(),
                sender_name=os.getenv("AARI_EMAIL_NAME", "").strip(),
                password=os.getenv("AARI_EMAIL_PASSWORD", ""),
                size_baselines=SIZE_BASELINES, min_size_ratio=MIN_SIZE_RATIO,
                max_size_ratio=MAX_SIZE_RATIO, resend_changed=args.resend_changed_email,
            )
            for result in mail_results:
                results.append(Result(result.name, result.status, result.detail))
                LOG.info("[%s] %s: %s", result.status, result.name, result.detail)
    else:
        LOG.info("INACTIVE | today is not a scheduled Wednesday/Thursday run")

    write_status(run_date, stage, dry_run, results)
    errors = [item for item in results if item.status in {"BLOCKED", "ERROR", "CONFIG_ERROR", "MAIL_ERROR", "REVIEW_REQUIRED"}]
    LOG.info("END | results=%s | errors=%d", len(results), len(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
