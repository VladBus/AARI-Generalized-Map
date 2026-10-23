"""Unit tests for weekly scheduling, reporting, and folder preparation."""

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import main
from email_sender import parse_report_recipients, send_weekly_report


class WeeklyOperationsTests(unittest.TestCase):
    """Test weekly automation logic independently of live shares and SMTP."""

    def test_late_wednesday_run_retries_old_shore(self):
        """Include the old-shore job in later Wednesday distribution runs."""
        source = Path(r"Z:\МОРЕ\ОБОБЩЕНКА_ОТПРАВКА")
        target = Path(r"\\files.aari.ru\Ice_charts")
        with patch.multiple(main, SOURCE_ROOT=source, ICE_CHARTS_ROOT=target):
            jobs = main.build_stage_jobs(date(2026, 10, 21), "wednesday")
        self.assertEqual(jobs[0].name, "Арктика SHP по старому берегу")
        self.assertEqual(
            jobs[0].sources[0],
            source / "2026-10-21" / "old_shore" / "20261020О.shp",
        )

    def test_auto_stage_uses_report_trigger_after_1500_wednesday(self):
        """Select the report stage for the one-time 15:00 trigger."""
        run_day = date(2026, 10, 21)
        self.assertEqual(
            main.resolve_stage("auto", run_day, datetime(2026, 10, 21, 14, 50)),
            "wednesday",
        )
        self.assertEqual(
            main.resolve_stage("auto", run_day, datetime(2026, 10, 21, 15, 0)),
            "report",
        )

    def test_next_week_folders_are_created_and_existing_files_preserved(self):
        """Create missing subfolders while preserving existing expert files."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            next_pic = root / "2026-10-28" / "PIC"
            next_pic.mkdir(parents=True)
            sentinel = next_pic / "expert_file.txt"
            sentinel.write_text("keep", encoding="utf-8")
            with patch.object(main, "SOURCE_ROOT", root):
                result = main.create_next_week_template_folder(
                    date(2026, 10, 21), dry_run=False
                )
            self.assertEqual(result.status, "OK")
            self.assertTrue(sentinel.is_file())
            for name in ("LVP", "PIC", "SHP", "old_shore", "sigrid", "website"):
                self.assertTrue((root / "2026-10-28" / name).is_dir())

    def test_status_accumulates_stages_for_one_release_and_resets_next_week(self):
        """Keep file-level results for all stages until a new release begins."""
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "STATUS.txt"
            with patch.object(main, "STATUS_FILE", status_path):
                main.write_status(
                    date(2026, 10, 21),
                    "wednesday",
                    True,
                    [main.Result("Overview JPG", "DRY-RUN", "source.jpg -> target/source.jpg")],
                )
                main.write_status(
                    date(2026, 10, 22),
                    "thursday",
                    True,
                    [main.Result("LVP_WAVE", "DRY-RUN", "source.shp -> target/source.shp")],
                )
                same_release = status_path.read_text(encoding="utf-8")
                self.assertIn("ЭТАП: wednesday", same_release)
                self.assertIn("ЭТАП: thursday", same_release)
                self.assertIn("source.jpg", same_release)
                self.assertIn("source.shp", same_release)

                main.write_status(
                    date(2026, 10, 28),
                    "wednesday",
                    True,
                    [main.Result("Next release", "DRY-RUN", "next-week file")],
                )
                next_release = status_path.read_text(encoding="utf-8")
                self.assertIn("Дата выпуска (каталог среды): 2026-10-28", next_release)
                self.assertNotIn("ЭТАП: thursday", next_release)
                self.assertNotIn("source.jpg", next_release)

    def test_recipients_accept_commas_semicolons_and_spaces(self):
        """Parse the configurable weekly report recipient list."""
        self.assertEqual(
            parse_report_recipients(
                "vvbusev@aari.ru, a.sokolov@aari.ru; sanovikov@aari.ru"
            ),
            ["vvbusev@aari.ru", "a.sokolov@aari.ru", "sanovikov@aari.ru"],
        )

    def test_weekly_report_dry_run_does_not_connect_to_smtp(self):
        """Generate a weekly report preview without authenticating to SMTP."""
        with tempfile.TemporaryDirectory() as tmp:
            result = send_weekly_report(
                "Тестовый отчёт",
                "Статус: все задания выполнены.",
                date(2026, 10, 21),
                log_path=Path(tmp) / "missing.log",
                smtp_server="invalid.local",
                smtp_port=465,
                sender_email="sender@example.org",
                sender_name="Test",
                password="",
                recipient_list=["one@example.org", "two@example.org"],
                dry_run=True,
            )
        self.assertEqual(result.status, "DRY-RUN")

    def test_report_is_not_sent_twice_on_same_release_date(self):
        """Use the log marker to suppress a duplicate weekly report."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "run.log"
            log.write_text(
                "2026-10-21 15:00:00 | INFO | "
                "REPORT_SENT|2026-10-21|" + ("a" * 64) + "\n",
                encoding="utf-8",
            )
            result = send_weekly_report(
                "Тестовый отчёт",
                "Тело отчёта",
                date(2026, 10, 21),
                log_path=log,
                smtp_server="invalid.local",
                smtp_port=465,
                sender_email="sender@example.org",
                sender_name="Test",
                password="secret",
                recipient_list=["one@example.org"],
                dry_run=False,
            )
        self.assertEqual(result.status, "ALREADY_SENT")


if __name__ == "__main__":
    unittest.main()
