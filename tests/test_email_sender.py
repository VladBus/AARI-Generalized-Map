"""Unit tests for product email building and safe-send checks."""

import tempfile
import unittest
from email.message import EmailMessage
from unittest.mock import patch
from typing import cast
from datetime import date
from pathlib import Path
from email_sender import (
    Attachment,
    EmailJob,
    _build_message,
    _fingerprint,
    build_email_jobs,
    process_email_job,
    process_test_email_suite,
    TEST_RECIPIENTS,
)


class EmailTests(unittest.TestCase):
    """Verify email recipients, bodies, attachments, and duplicate protection."""

    def test_five_mailouts_and_attachment_counts(self):
        """Build exactly five emails with the required attachment counts."""
        root = Path(r"Z:\МОРЕ\ОБОБЩЕНКА_ОТПРАВКА\2026-10-21")
        jobs = build_email_jobs(
            root, date(2026, 10, 20), Path("email_templates"), "18-20 октября 2026 года"
        )
        self.assertEqual(len(jobs), 5)
        self.assertEqual([len(j.attachments) for j in jobs], [1, 8, 4, 1, 1])
        self.assertEqual(
            jobs[0].subject, "Обобщенная карта Арктики за 18-20 октября 2026 года"
        )
        self.assertEqual(
            jobs[1].subject, "Sigrid запад и восток за 18-20 октября 2026 года"
        )
        self.assertEqual(
            jobs[4].subject, "Обобщенная карта Арктики за 18-20 октября 2026 года"
        )

    def test_template_body_and_recipients_are_preserved(self):
        """Keep template recipients and body text while changing the subject."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.eml"
            attachment = root / "map.jpg"
            template_text = "\n".join(
                [
                    "To: Test User <to@example.org>",
                    "Cc: copy@example.org",
                    "Subject: old",
                    "MIME-Version: 1.0",
                    "Content-Type: text/html; charset=UTF-8",
                    "",
                    "<p>Keep signature</p>",
                    "",
                ]
            )
            template.write_text(template_text, encoding="utf-8")
            attachment.write_bytes(b"image bytes")
            job = EmailJob(
                "test",
                "Test",
                template,
                "Updated subject",
                (Attachment(attachment, "none"),),
            )
            msg, recipients = _build_message(job, "sender@example.org", "Sender")
            self.assertEqual(msg["Subject"], "Updated subject")
            self.assertIn("to@example.org", recipients)
            self.assertIn("copy@example.org", recipients)
            body_part = msg.get_body(preferencelist=("html",))
            self.assertIsNotNone(body_part)
            assert body_part is not None
            typed_body_part = cast(EmailMessage, body_part)
            self.assertIn("Keep signature", typed_body_part.get_content())

    def test_test_message_overrides_all_template_recipients(self):
        """Test mode strips production To/Cc/Bcc/Reply-To and uses the allowlist."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.eml"
            attachment = root / "map.jpg"
            template.write_text(
                "\n".join(
                    [
                        "To: production@example.org",
                        "Cc: copy@example.org",
                        "Bcc: hidden@example.org",
                        "Reply-To: reply@example.org",
                        "Subject: old",
                        "MIME-Version: 1.0",
                        "Content-Type: text/plain; charset=UTF-8",
                        "",
                        "Keep the original message body.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            attachment.write_bytes(b"image bytes")
            job = EmailJob(
                "test",
                "Test",
                template,
                "Product mail subject",
                (Attachment(attachment, "none"),),
            )
            message, recipients = _build_message(
                job,
                "sender@example.org",
                "Sender",
                recipient_override=TEST_RECIPIENTS,
                subject_prefix="[TEST] ",
                test_notice=True,
            )
        self.assertEqual(recipients, list(TEST_RECIPIENTS))
        self.assertEqual(
            message["To"], "vvbusev@aari.ru, sanovikov@aari.ru"
        )
        self.assertIsNone(message.get("Cc"))
        self.assertIsNone(message.get("Bcc"))
        self.assertIsNone(message.get("Reply-To"))
        self.assertEqual(message["Subject"], "[TEST] Product mail subject")
        body_part = message.get_body(preferencelist=("plain",))
        self.assertIsNotNone(body_part)
        assert body_part is not None
        body = body_part.get_content()
        self.assertIn("[TEST MESSAGE", body)
        self.assertIn("Keep the original message body.", body)
        self.assertNotIn("production@example.org", str(message))
        self.assertNotIn("hidden@example.org", str(message))

    def test_test_suite_preview_builds_six_messages_without_smtp(self):
        """Test-suite preview validates five product mails and the report without SMTP."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.eml"
            template.write_text(
                "To: production@example.org\n"
                "Cc: copied@example.org\n"
                "Reply-To: reply@example.org\n"
                "Subject: template\n"
                "MIME-Version: 1.0\n"
                "Content-Type: text/plain; charset=UTF-8\n\n"
                "Test body.\n",
                encoding="utf-8",
            )
            jobs = []
            for index in range(5):
                attachment = root / f"attachment_{index}.bin"
                attachment.write_bytes(f"test attachment {index}".encode("utf-8"))
                jobs.append(
                    EmailJob(
                        f"test_{index}",
                        f"Test product email {index}",
                        template,
                        f"Product subject {index}",
                        (Attachment(attachment, "none"),),
                    )
                )
            with self.assertLogs("aari_generalized_map.email", level="INFO") as captured:
                with patch("email_sender.smtplib.SMTP_SSL") as smtp_factory:
                    results = process_test_email_suite(
                        jobs,
                        date(2026, 10, 21),
                        "Weekly report subject",
                        "Weekly report body",
                        dry_run=True,
                        smtp_server="smtp.example.org",
                        smtp_port=465,
                        sender_email="sender@example.org",
                        sender_name="Test sender",
                        password="",
                        production_report_recipients=["production-report@example.org"],
                        size_baselines={},
                        min_size_ratio=0.35,
                        max_size_ratio=2.5,
                    )
                    smtp_factory.assert_not_called()

        self.assertEqual(len(results), 6)
        self.assertTrue(all(result.status == "DRY-RUN" for result in results))
        log = "\n".join(captured.output)
        self.assertIn("TEST_MAIL_REDIRECT", log)
        self.assertIn("TEST_MAIL_PLAN", log)
        self.assertIn("TEST_REPORT_PLAN", log)
        self.assertIn("production@example.org", log)
        self.assertIn("vvbusev@aari.ru, sanovikov@aari.ru", log)

    def test_live_test_suite_sends_only_to_allowlist(self):
        """A live test suite delivers six marked messages only to approved test mailboxes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.eml"
            template.write_text(
                "To: production@example.org\n"
                "Cc: copied@example.org\n"
                "Bcc: hidden@example.org\n"
                "Reply-To: reply@example.org\n"
                "Subject: template\n"
                "MIME-Version: 1.0\n"
                "Content-Type: text/plain; charset=UTF-8\n\n"
                "Keep the template body.\n",
                encoding="utf-8",
            )
            jobs = []
            for index in range(5):
                attachment = root / f"attachment_{index}.bin"
                attachment.write_bytes(f"test attachment {index}".encode("utf-8"))
                jobs.append(
                    EmailJob(
                        f"live_test_{index}",
                        f"Live test product email {index}",
                        template,
                        f"Product subject {index}",
                        (Attachment(attachment, "none"),),
                    )
                )

            with self.assertLogs("aari_generalized_map.email", level="INFO"):
                with patch("email_sender.smtplib.SMTP_SSL") as smtp_factory:
                    smtp = smtp_factory.return_value
                    smtp.send_message.return_value = {}
                    results = process_test_email_suite(
                        jobs,
                        date(2026, 10, 21),
                        "Weekly report subject",
                        "Weekly report body",
                        dry_run=False,
                        smtp_server="smtp.example.org",
                        smtp_port=465,
                        sender_email="sender@example.org",
                        sender_name="Test sender",
                        password="not-a-real-password",
                        production_report_recipients=["production-report@example.org"],
                        size_baselines={},
                        min_size_ratio=0.35,
                        max_size_ratio=2.5,
                    )

            self.assertEqual(len(results), 6)
            self.assertTrue(all(result.status == "SENT" for result in results))
            smtp_factory.assert_called_once()
            smtp.login.assert_called_once_with("sender@example.org", "not-a-real-password")
            self.assertEqual(smtp.send_message.call_count, 6)
            smtp.quit.assert_called_once()
            for call in smtp.send_message.call_args_list:
                message = call.args[0]
                self.assertEqual(call.kwargs["to_addrs"], list(TEST_RECIPIENTS))
                self.assertEqual(
                    message["To"], "vvbusev@aari.ru, sanovikov@aari.ru"
                )
                self.assertTrue(str(message["Subject"]).startswith("[TEST]"))
                self.assertIsNone(message.get("Cc"))
                self.assertIsNone(message.get("Bcc"))
                self.assertIsNone(message.get("Reply-To"))
                self.assertNotIn("production@example.org", str(message))
                self.assertNotIn("hidden@example.org", str(message))

    def test_dry_run_does_not_send(self):
        """A dry-run produces a preview without SMTP credentials or connection."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.eml"
            attachment = root / "file.bin"
            template.write_text(
                "To: recipient@example.org\nContent-Type: text/plain; charset=UTF-8\n\n",
                encoding="utf-8",
            )
            attachment.write_bytes(b"contents")
            job = EmailJob(
                "dry", "Dry", template, "Subject", (Attachment(attachment, "none"),)
            )
            result = process_email_job(
                job,
                date(2026, 10, 21),
                log_path=root / "missing.log",
                dry_run=True,
                smtp_server="localhost",
                smtp_port=465,
                sender_email="sender@example.org",
                sender_name="Sender",
                password="",
                size_baselines={},
                min_size_ratio=0.35,
                max_size_ratio=2.5,
            )
            self.assertEqual(result.status, "DRY-RUN")

    def test_log_markers_prevent_duplicate_send(self):
        """Do not repeat an email already marked as sent in the log."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.eml"
            attachment = root / "file.bin"
            log = root / "run.log"
            template.write_text(
                "To: recipient@example.org\nContent-Type: text/plain; charset=UTF-8\n\n",
                encoding="utf-8",
            )
            attachment.write_bytes(b"contents")
            job = EmailJob(
                "dry", "Dry", template, "Subject", (Attachment(attachment, "none"),)
            )
            log.write_text(
                f"2026 INFO MAIL_SENT|2026-10-21|dry|{_fingerprint(job)}\n",
                encoding="utf-8",
            )
            result = process_email_job(
                job,
                date(2026, 10, 21),
                log_path=log,
                dry_run=False,
                smtp_server="localhost",
                smtp_port=465,
                sender_email="sender@example.org",
                sender_name="Sender",
                password="secret",
                size_baselines={},
                min_size_ratio=0.35,
                max_size_ratio=2.5,
            )
            self.assertEqual(result.status, "ALREADY_SENT")


if __name__ == "__main__":
    unittest.main()
