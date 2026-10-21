import tempfile
import unittest
from datetime import date
from pathlib import Path
from email_sender import Attachment, EmailJob, _build_message, _fingerprint, build_email_jobs, process_email_job

class EmailTests(unittest.TestCase):
    def test_five_mailouts_and_attachment_counts(self):
        root=Path(r"Z:\МОРЕ\ОБОБЩЕНКА_ОТПРАВКА\2026-10-21")
        jobs=build_email_jobs(root,date(2026,10,20),Path("email_templates"),"18-20 октября 2026 года")
        self.assertEqual(len(jobs),5)
        self.assertEqual([len(j.attachments) for j in jobs],[1,8,4,1,1])
        self.assertEqual(jobs[0].subject,"Обобщенная карта Арктики за 18-20 октября 2026 года")
        self.assertEqual(jobs[1].subject,"Sigrid запад и восток за 18-20 октября 2026 года")
        self.assertEqual(jobs[4].subject,"Обобщенная карта Арктики за 18-20 октября 2026 года")
    def test_template_body_and_recipients_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); template=root/"template.eml"; attachment=root/"map.jpg"
            template.write_text("To: Test User <to@example.org>\nCc: copy@example.org\nSubject: old\nMIME-Version: 1.0\nContent-Type: text/html; charset=UTF-8\n\n<p>Keep signature</p>\n",encoding="utf-8")
            attachment.write_bytes(b"image bytes")
            job=EmailJob("test","Test",template,"Updated subject",(Attachment(attachment,"none"),))
            msg,recipients=_build_message(job,"sender@example.org","Sender")
            self.assertEqual(msg["Subject"],"Updated subject")
            self.assertIn("to@example.org",recipients); self.assertIn("copy@example.org",recipients)
            self.assertIn("Keep signature",msg.get_body(preferencelist=("html",)).get_content())
    def test_dry_run_does_not_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); template=root/"template.eml"; attachment=root/"file.bin"
            template.write_text("To: recipient@example.org\nContent-Type: text/plain; charset=UTF-8\n\n",encoding="utf-8")
            attachment.write_bytes(b"contents")
            job=EmailJob("dry","Dry",template,"Subject",(Attachment(attachment,"none"),))
            result=process_email_job(job,date(2026,10,21),log_path=root/"missing.log",dry_run=True,smtp_server="localhost",smtp_port=465,sender_email="sender@example.org",sender_name="Sender",password="",size_baselines={},min_size_ratio=.35,max_size_ratio=2.5)
            self.assertEqual(result.status,"DRY-RUN")
    def test_log_markers_prevent_duplicate_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); template=root/"template.eml"; attachment=root/"file.bin"; log=root/"run.log"
            template.write_text("To: recipient@example.org\nContent-Type: text/plain; charset=UTF-8\n\n",encoding="utf-8")
            attachment.write_bytes(b"contents")
            job=EmailJob("dry","Dry",template,"Subject",(Attachment(attachment,"none"),))
            log.write_text(f"2026 INFO MAIL_SENT|2026-10-21|dry|{_fingerprint(job)}\n",encoding="utf-8")
            result=process_email_job(job,date(2026,10,21),log_path=log,dry_run=False,smtp_server="localhost",smtp_port=465,sender_email="sender@example.org",sender_name="Sender",password="secret",size_baselines={},min_size_ratio=.35,max_size_ratio=2.5)
            self.assertEqual(result.status,"ALREADY_SENT")

if __name__ == "__main__":
    unittest.main()
