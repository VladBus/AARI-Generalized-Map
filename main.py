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

from email_sender import (
    build_email_jobs,
    parse_report_recipients,
    process_email_jobs,
    send_weekly_report,
)

try:
    from dotenv import load_dotenv
except ImportError:  # Basic diagnostics remain available if dependencies are missing.
    load_dotenv = None

PROJECT_DIR = Path(__file__).resolve().parent
if load_dotenv:
    load_dotenv(PROJECT_DIR / ".env")

COMPONENTS = (".shp", ".shx", ".dbf", ".prj")
SOURCE_ROOT = Path(
    os.getenv("AARI_SOURCE_ROOT", r"\\10.31.34.60\Tiris\МОРЕ\ОБОБЩЕНКА_ОТПРАВКА")
)
MORE_ROOT = Path(os.getenv("AARI_MORE_ROOT", r"\\10.31.34.60\Tiris\МОРЕ"))
ICE_CHARTS_ROOT = Path(os.getenv("AARI_ICE_CHARTS_ROOT", r"\\files.aari.ru\Ice_charts"))
MORSPASS_ROOT = Path(os.getenv("AARI_MORSPASS_ROOT", r"\\files.aari.ru\morspass"))
SOVBEZ_ROOT = Path(os.getenv("AARI_SOVBEZ_ROOT", r"\\files.aari.ru\sovbez"))
ICECHARTS_V_ROOT = Path(
    os.getenv("AARI_ICECHARTS_V_ROOT", r"\\10.31.34.110\C373\IceCharts")
)
LVP_WAVE_ROOT = Path(os.getenv("AARI_LVP_WAVE_ROOT", r"\\10.31.34.60\Tiris\LVP_WAVE"))
WEBSITE_ROOT = Path(os.getenv("AARI_WEBSITE_ROOT", r"\\data.aari.ru\d0015\arctic"))
LOG_FILE = Path(
    os.getenv("AARI_LOG_FILE", str(SOURCE_ROOT / "aari_generalized_map.log"))
)
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
    "pic.jpg": {".jpg": 1003764},
    "pic.gif": {".gif": 464915},
    "pic.bmp": {".bmp": 4178442},
    "pic.east_png": {".png": 10514759},
    "pic.west_png": {".png": 9155920},
    "website.sigrid": {
        ".shp": 13361888,
        ".shx": 7996,
        ".dbf": 133791,
        ".prj": 145,
        ".zip": 10746612,
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOG = logging.getLogger("aari_generalized_map")


@dataclass(frozen=True)
class CopyJob:
    """One group of source files and its target directory."""

    name: str
    sources: tuple[Path, ...]
    target_dir: Path
    size_family: str


@dataclass(frozen=True)
class Result:
    """Status and details for one copy or automation action."""

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
    logging.basicConfig(
        level=os.getenv("AARI_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def product_date(release_folder_date: date) -> date:
    """Return the Tuesday chart date for a Wednesday release folder."""
    return release_folder_date - timedelta(days=1)


def release_range(chart_date: date) -> tuple[date, date]:
    """Return the Sunday-to-Tuesday period represented by a Tuesday chart date."""
    return chart_date - timedelta(days=2), chart_date


def russian_date_range(chart_date: date) -> str:
    """Format the chart's Sunday-to-Tuesday period in Russian."""
    start, end = release_range(chart_date)
    months = (
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    )
    if start.year == end.year and start.month == end.month:
        return f"{start.day}-{end.day} {months[end.month - 1]} {end.year} года"
    return (
        f"{start.day} {months[start.month - 1]}-"
        f"{end.day} {months[end.month - 1]} {end.year} года"
    )


def shape_components(folder: Path, stem: str) -> tuple[Path, ...]:
    """Build the standard four-component shapefile set for a base name."""
    return tuple(folder / f"{stem}{suffix}" for suffix in COMPONENTS)


def png_name(chart_date: date, region: str) -> str:
    """Return the standard regional PNG name for a chart date."""
    start, end = release_range(chart_date)
    return f"{start.year}_{start.month:02d}_{start.day:02d}-{end.day:02d}_{region}.png"


def build_jobs(run_date: date, stage: str) -> list[CopyJob]:
    """Build the copy list for one invocation; date arguments are real run dates."""
    jobs: list[CopyJob] = []
    if stage == "oldshore":
        stamp = (run_date - timedelta(days=1)).strftime("%Y%m%d")
        folder = SOURCE_ROOT / run_date.isoformat() / "old_shore"
        return [
            CopyJob(
                "Арктика SHP по старому берегу",
                shape_components(folder, f"{stamp}О"),
                ICE_CHARTS_ROOT / "Арктика" / "SHP",
                "shp.oldshore",
            )
        ]

    if stage == "wednesday":
        chart = product_date(run_date)
        stamp = chart.strftime("%Y%m%d")
        folder = SOURCE_ROOT / run_date.isoformat()
        pic, shp, sigrid = (folder / name for name in ("PIC", "SHP", "sigrid"))
        west_png, east_png = pic / png_name(chart, "Запад"), pic / png_name(
            chart, "Восток"
        )
        arc = shape_components(sigrid, f"aari_arc_{stamp}_pl_a")
        jobs.extend(
            [
                CopyJob("МОРЕ: Общая.bmp", (pic / "Общая.bmp",), MORE_ROOT, "pic.bmp"),
                CopyJob("МОРЕ: PNG Запад", (west_png,), MORE_ROOT, "pic.west_png"),
                CopyJob("МОРЕ: PNG Восток", (east_png,), MORE_ROOT, "pic.east_png"),
                CopyJob(
                    "V IceCharts: JPG",
                    (pic / f"{stamp}.jpg",),
                    ICECHARTS_V_ROOT,
                    "pic.jpg",
                ),
                CopyJob(
                    "V IceCharts: SHP общей карты",
                    shape_components(shp, stamp),
                    ICECHARTS_V_ROOT,
                    "shp.general",
                ),
                CopyJob(
                    "Запад: PNG",
                    (west_png,),
                    ICE_CHARTS_ROOT / "Запад" / "PIC",
                    "pic.west_png",
                ),
                CopyJob(
                    "Восток: PNG",
                    (east_png,),
                    ICE_CHARTS_ROOT / "Восток" / "PIC",
                    "pic.east_png",
                ),
                CopyJob(
                    "Запад: SHP",
                    shape_components(shp, f"{stamp}З"),
                    ICE_CHARTS_ROOT / "Запад" / "SHP",
                    "shp.west",
                ),
                CopyJob(
                    "Восток: SHP",
                    shape_components(shp, f"{stamp}В"),
                    ICE_CHARTS_ROOT / "Восток" / "SHP",
                    "shp.east",
                ),
                CopyJob(
                    "Запад: SIGRID3",
                    shape_components(sigrid, f"aari_west_{stamp}_pl_a"),
                    ICE_CHARTS_ROOT / "Запад" / "SIGRID3",
                    "sigrid.west",
                ),
                CopyJob(
                    "Восток: SIGRID3",
                    shape_components(sigrid, f"aari_east_{stamp}_pl_a"),
                    ICE_CHARTS_ROOT / "Восток" / "SIGRID3",
                    "sigrid.east",
                ),
                CopyJob(
                    "Обобщенная: JPG",
                    (pic / f"{stamp}.jpg",),
                    ICE_CHARTS_ROOT
                    / "Обобщенная"
                    / "PIC"
                    / str(chart.year)
                    / f"{chart.month:02d}",
                    "pic.jpg",
                ),
                CopyJob(
                    "Обобщенная: SIGRID3",
                    arc,
                    ICE_CHARTS_ROOT
                    / "Обобщенная"
                    / "SIGRID3"
                    / str(chart.year)
                    / f"{chart.month:02d}",
                    "sigrid.arc",
                ),
                CopyJob(
                    "Морспас: JPG",
                    (pic / f"{stamp}.jpg",),
                    MORSPASS_ROOT / run_date.strftime("%Y%m%d"),
                    "pic.jpg",
                ),
                CopyJob(
                    "Морспас: SIGRID3",
                    arc,
                    MORSPASS_ROOT / run_date.strftime("%Y%m%d"),
                    "sigrid.arc",
                ),
                CopyJob(
                    "Совбез: JPG",
                    (pic / f"{stamp}.jpg",),
                    SOVBEZ_ROOT / run_date.strftime("%Y%m%d"),
                    "pic.jpg",
                ),
                CopyJob(
                    "Совбез: SIGRID3",
                    arc,
                    SOVBEZ_ROOT / run_date.strftime("%Y%m%d"),
                    "sigrid.arc",
                ),
            ]
        )
        return jobs

    if stage == "thursday":
        release_day = run_date - timedelta(days=1)  # Wednesday folder.
        chart = product_date(release_day)
        stamp = chart.strftime("%Y%m%d")
        release_folder = SOURCE_ROOT / release_day.isoformat()
        jobs.append(
            CopyJob(
                "LVP_WAVE",
                shape_components(release_folder / "LVP", stamp),
                LVP_WAVE_ROOT,
                "lvp",
            )
        )

        previous_release_day = release_day - timedelta(days=7)
        previous_chart = product_date(previous_release_day)
        previous_stamp = previous_chart.strftime("%Y%m%d")
        website = SOURCE_ROOT / previous_release_day.isoformat() / "website"
        gif = (
            website / f"{previous_stamp}.gif"
        )  # One bilingual GIF is copied to both locations.
        jobs.extend(
            [
                CopyJob(
                    "Сайт: GIF EN",
                    (gif,),
                    WEBSITE_ROOT / "gif.en" / str(previous_chart.year),
                    "pic.gif",
                ),
                CopyJob(
                    "Сайт: GIF RU",
                    (gif,),
                    WEBSITE_ROOT / "gif.ru" / str(previous_chart.year),
                    "pic.gif",
                ),
                CopyJob(
                    "Сайт: SIGRID + ZIP",
                    shape_components(website, f"aari_arc_{previous_stamp}_pl_a")
                    + (website / f"aari_arc_{previous_stamp}_pl_a.zip",),
                    WEBSITE_ROOT / "sigrid" / str(previous_chart.year),
                    "website.sigrid",
                ),
            ]
        )
        return jobs

    raise ValueError(f"Неизвестный этап: {stage}")


def inspect_job(job: CopyJob) -> list[str]:
    """Check expected source presence, component sets, and approximate sizes."""
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
                errors.append(
                    f"подозрительный размер {source.name}: {size:,} байт; "
                    f"эталон {baseline:,}; допустимо "
                    f"{MIN_SIZE_RATIO:.2f}–{MAX_SIZE_RATIO:.2f} от эталона"
                )
    return errors


def copy_job(job: CopyJob, dry_run: bool) -> Result:
    """Copy one checked file group, replacing older target files if needed."""
    errors = inspect_job(job)
    if errors:
        for error in errors:
            LOG.error("COPY_BLOCKED | %s | %s", job.name, error)
        return Result(job.name, "BLOCKED", "; ".join(errors))

    if dry_run:
        LOG.info(
            "DRY_RUN_COPY | %s | %d file(s) -> %s",
            job.name,
            len(job.sources),
            job.target_dir,
        )
        for source in job.sources:
            LOG.info(
                "DRY_RUN_FILE | %s | %s -> %s",
                job.name,
                source,
                job.target_dir / source.name,
            )
        return Result(
            job.name,
            "DRY-RUN",
            f"{len(job.sources)} файл(ов) → {job.target_dir}",
        )

    copied, replaced, unchanged = 0, 0, 0
    try:
        job.target_dir.mkdir(parents=True, exist_ok=True)
        for source in job.sources:
            target = job.target_dir / source.name
            if target.is_file() and filecmp.cmp(source, target, shallow=False):
                unchanged += 1
                LOG.info("UNCHANGED | %s | %s → %s", source.name, source, target)
                continue
            was_present = target.exists()
            shutil.copy2(source, target)
            if was_present:
                replaced += 1
                LOG.info("REPLACED | %s | %s → %s", source.name, source, target)
            else:
                copied += 1
                LOG.info("COPIED | %s | %s → %s", source.name, source, target)
        detail = (
            f"скопировано: {copied}; заменено: {replaced}; "
            f"без изменений: {unchanged}; каталог: {job.target_dir}"
        )
        return Result(job.name, "OK", detail)
    except OSError as exc:
        LOG.exception("COPY_ERROR | %s", job.name)
        return Result(
            job.name, "ERROR", f"ошибка копирования в {job.target_dir}: {exc}"
        )


def resolve_stage(requested: str, run_date: date, now: datetime) -> str | None:
    """Select the automation stage based on the day and current time."""
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
        return Result(
            "Шаблон следующей недели",
            "DRY-RUN",
            f"будет создана/дополнена папка {target_root} с подпапками: {', '.join(subfolders)}",
        )
    try:
        target_root.mkdir(parents=True, exist_ok=True)
        created: list[str] = []
        existing: list[str] = []
        for name in subfolders:
            path = target_root / name
            if path.exists():
                if not path.is_dir():
                    return Result(
                        "Шаблон следующей недели",
                        "ERROR",
                        f"{path} уже существует, но это не папка",
                    )
                existing.append(name)
            else:
                path.mkdir()
                created.append(name)
        details = []
        if created:
            details.append("созданы: " + ", ".join(created))
        if existing:
            details.append("уже существовали и сохранены: " + ", ".join(existing))
        result = Result(
            "Шаблон следующей недели", "OK", f"{target_root}; " + "; ".join(details)
        )
        LOG.info("NEXT_WEEK_FOLDER | %s | %s", target_root, result.detail)
        return result
    except OSError as exc:
        LOG.exception("NEXT_WEEK_FOLDER_ERROR | %s", target_root)
        return Result(
            "Шаблон следующей недели",
            "ERROR",
            f"не удалось создать {target_root}: {exc}",
        )


def read_status_snapshot() -> str:
    """Read the latest operational status for inclusion in the weekly report."""
    try:
        return STATUS_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return f"Файл статуса не найден: {STATUS_FILE}. Проверьте журнал {LOG_FILE}."


def write_status(
    run_date: date, stage: str, dry_run: bool, results: Sequence[Result]
) -> None:
    """Write a concise current-release summary; detailed events belong in the log."""
    release_folder_date = run_date
    if stage == "thursday" or (stage == "validate" and run_date.weekday() != 2):
        release_folder_date = run_date - timedelta(days=1)

    previous_sections: dict[str, list[str]] = {}
    try:
        previous_lines = STATUS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        previous_lines = []

    previous_release = next(
        (
            line.partition(":")[2].strip()
            for line in previous_lines
            if line.startswith("Дата выпуска (каталог среды): ")
        ),
        "",
    )
    section_marker = "КРАТКИЕ РЕЗУЛЬТАТЫ ПО ЭТАПАМ ВЫПУСКА:"
    if (
        previous_release == release_folder_date.isoformat()
        and section_marker in previous_lines
    ):
        in_sections = False
        current_stage: str | None = None
        current_lines: list[str] = []
        for line in previous_lines:
            if line == section_marker:
                in_sections = True
                continue
            if not in_sections:
                continue
            if line.startswith("ЭТАП: "):
                if current_stage is not None:
                    previous_sections[current_stage] = current_lines
                current_stage = line[len("ЭТАП: ") :].split("|", 1)[0].strip()
                current_lines = [line]
            elif current_stage is not None:
                current_lines.append(line)
        if current_stage is not None:
            previous_sections[current_stage] = current_lines

    mode = "DRY-RUN — без копирования/отправки" if dry_run else "РАБОЧИЙ РЕЖИМ"
    stage_lines = [
        f"ЭТАП: {stage} | {mode} | {datetime.now():%Y-%m-%d %H:%M:%S}"
    ]
    if stage == "validate":
        release_day = (
            run_date if run_date.weekday() == 2 else run_date - timedelta(days=1)
        )
        for job in build_stage_jobs(release_day, "wednesday"):
            errors = inspect_job(job)
            if errors:
                for error in errors:
                    LOG.error("VALIDATION_ERROR | %s | %s", job.name, error)
            else:
                LOG.info(
                    "VALIDATION_OK | %s | files=%d | target=%s",
                    job.name,
                    len(job.sources),
                    job.target_dir,
                )
            for source in job.sources:
                LOG.info(
                    "VALIDATION_FILE | %s | %s -> %s",
                    job.name,
                    source,
                    job.target_dir / source.name,
                )
            results.append(
                Result(
                    job.name,
                    "ERROR" if errors else "OK",
                    (
                        "; ".join(errors)
                        if errors
                        else f"проверено файлов: {len(job.sources)}; "
                        f"назначение: {job.target_dir}"
                    ),
                )
            )
    elif stage != "inactive":
        for job in build_stage_jobs(run_date, stage):
            result = copy_job(job, dry_run)
            results.append(result)
            LOG.info("[%s] %s: %s", result.status, result.name, result.detail)

        if stage == "wednesday" and not dry_run and now.time() < dt_time(14, 50):
            waiting = Result(
                "Почта",
                "WAITING",
                "рассылка отложена до финального запуска в 14:50; "
                "до этого проверяются и обновляются только файлы",
            )
            results.append(waiting)
            LOG.info(
                "EMAIL_WAITING | финальная попытка рассылки запланирована на 14:50"
            )
        elif stage == "wednesday":
            chart = product_date(run_date)
            email_jobs = build_email_jobs(
                SOURCE_ROOT / run_date.isoformat(),
                chart,
                PROJECT_DIR / "email_templates",
                russian_date_range(chart),
            )
            mail_results = process_email_jobs(
                email_jobs,
                run_date,
                log_path=LOG_FILE,
                dry_run=dry_run,
                smtp_server=os.getenv("AARI_SMTP_SERVER", "zmail.aari.ru"),
                smtp_port=int(os.getenv("AARI_SMTP_PORT", "465")),
                sender_email=os.getenv("AARI_EMAIL_ADDRESS", "").strip(),
                sender_name=os.getenv("AARI_EMAIL_NAME", "").strip(),
                password=os.getenv("AARI_EMAIL_PASSWORD", ""),
                size_baselines=SIZE_BASELINES,
                min_size_ratio=MIN_SIZE_RATIO,
                max_size_ratio=MAX_SIZE_RATIO,
                resend_changed=args.resend_changed_email,
            )
            for result in mail_results:
                results.append(Result(result.name, result.status, result.detail))
                LOG.info("[%s] %s: %s", result.status, result.name, result.detail)
    else:
        LOG.info("INACTIVE | today is not a scheduled Wednesday/Thursday run")

    write_status(run_date, stage, dry_run, results)
    errors = [
        item
        for item in results
        if item.status
        in {"BLOCKED", "ERROR", "CONFIG_ERROR", "MAIL_ERROR", "REVIEW_REQUIRED"}
    ]
    LOG.info("END | results=%s | errors=%d", len(results), len(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
