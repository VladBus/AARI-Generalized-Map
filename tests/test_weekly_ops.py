import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import main
from email_sender import parse_report_recipients, send_weekly_report


class WeeklyOperationsTests(unittest.TestCase):
    def test_late_wednesday_run_retries_old_shore(self):
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

    def test_recipients_accept_commas_semicolons_and_spaces(self):
        self.assertEqual(
            parse_report_recipients(
                "vvbusev@aari.ru, a.sokolov@aari.ru; sanovikov@aari.ru"
            ),
            ["vvbusev@aari.ru", "a.sokolov@aari.ru", "sanovikov@aari.ru"],
        )

    def test_weekly_report_dry_run_does_not_connect_to_smtp(self):
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
