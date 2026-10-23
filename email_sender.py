"""Build and send the five mailouts using the supplied .eml templates."""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import date
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, getaddresses
from pathlib import Path
from typing import Sequence, cast

LOG = logging.getLogger("aari_generalized_map.email")
COMPONENTS = (".shp", ".shx", ".dbf", ".prj")
# Test mail is deliberately redirected to this fixed allowlist, never template recipients.
TEST_RECIPIENTS = ("vvbusev@aari.ru", "sanovikov@aari.ru")


@dataclass(frozen=True)
class Attachment:
    """An attachment path paired with its size-validation category."""

    path: Path
    family: str


@dataclass(frozen=True)
class EmailJob:
    """Description of one product email and the files it contains."""

    key: str
    name: str
    template: Path
    subject: str
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True)
class EmailResult:
    """Outcome and human-readable details for one email operation."""

    name: str
    status: str
    detail: str


def _components(folder: Path, stem: str, family: str) -> tuple[Attachment, ...]:
    """Return the four sidecar files for a shapefile stem."""
    return tuple(
        Attachment(folder / f"{stem}{suffix}", family) for suffix in COMPONENTS
    )


def build_email_jobs(
    source_folder: Path, chart_date: date, template_dir: Path, date_phrase: str
) -> list[EmailJob]:
    """Build the five product emails and their attachments for this chart date."""
    stamp = chart_date.strftime("%Y%m%d")
    pic, sigrid = source_folder / "PIC", source_folder / "sigrid"
    fsb_template = template_dir / "Шаблон ФСБ.eml"
    if not fsb_template.is_file():
        fsb_template = (
            template_dir / "Шалон ФСБ.eml"
        )  # Filename currently present in the repository.
    jpg = (Attachment(pic / f"{stamp}.jpg", "pic.jpg"),)
    return [
        EmailJob(
            "overview_jpg",
            "Обобщённая карта Арктики — JPG",
            template_dir / "Обобщенная карта Арктики.eml",
            f"Обобщенная карта Арктики за {date_phrase}",
            jpg,
        ),
        EmailJob(
            "sigrid_west_east",
            "SIGRID Запад и Восток",
            template_dir / "Sigrid запад и восток.eml",
            f"Sigrid запад и восток за {date_phrase}",
            _components(sigrid, f"aari_west_{stamp}_pl_a", "sigrid.west")
            + _components(sigrid, f"aari_east_{stamp}_pl_a", "sigrid.east"),
        ),
        EmailJob(
            "sigrid_arctic",
            "SIGRID Арктика",
            template_dir / "Sigrid Арктика за.eml",
            f"Sigrid Арктика за {date_phrase}",
            _components(sigrid, f"aari_arc_{stamp}_pl_a", "sigrid.arc"),
        ),
        EmailJob(
            "common_bmp",
            "Общая карта — BMP",
            template_dir / "Общая_bmp.eml",
            f"Общая_bmp за {date_phrase}",
            (Attachment(pic / "Общая.bmp", "pic.bmp"),),
        ),
        EmailJob(
            "fsb_jpg",
            "ФСБ — JPG",
            fsb_template,
            f"Обобщенная карта Арктики за {date_phrase}",
            jpg,
        ),
    ]


def _parse_template(path: Path) -> EmailMessage:
    """Parse an .eml template with the modern email content API."""
    with path.open("rb") as stream:
        parsed = BytesParser(policy=policy.default).parse(stream)
    # With policy.default the parser creates an EmailMessage; cast communicates
    # that guarantee to static analyzers whose stubs expose the base Message type.
    return cast(EmailMessage, parsed)


def _body(template: EmailMessage) -> tuple[str, str]:
    """Extract the preferred HTML/plain body without depending on broad Message stubs."""
    if template.is_multipart():
        part = template.get_body(preferencelist=("html", "plain"))
        if part is None:
            return "", "plain"
        body_part = cast(EmailMessage, part)
        return str(body_part.get_content()), body_part.get_content_subtype()
    return str(template.get_content()), template.get_content_subtype()


def _build_message(
    job: EmailJob,
    sender: str,
    sender_name: str,
    *,
    recipient_override: Sequence[str] | None = None,
    subject_prefix: str = "",
    test_notice: bool = False,
) -> tuple[EmailMessage, list[str]]:
    """Apply template content, optional isolated recipients, and attachments."""
    template = _parse_template(job.template)
    if recipient_override is None:
        recipients = [
            address
            for _name, address in getaddresses(
                [
                    str(v)
                    for key in ("To", "Cc", "Bcc")
                    for v in template.get_all(key, [])
                ]
            )
            if address
        ]
    else:
        recipients = list(
            dict.fromkeys(
                address.strip() for address in recipient_override if address.strip()
            )
        )
    if not recipients:
        raise ValueError(f"В шаблоне нет адресатов: {job.template.name}")

    message = EmailMessage(policy=policy.SMTP)
    message["From"] = formataddr((sender_name, sender)) if sender_name else sender
    if recipient_override is None:
        for key in ("To", "Cc", "Bcc", "Reply-To"):
            vals = template.get_all(key, [])
            if vals:
                message[key] = ", ".join(str(value) for value in vals)
    else:
        # In test mode do not copy any To/Cc/Bcc/Reply-To headers from production templates.
        message["To"] = ", ".join(recipients)
    message["Subject"] = f"{subject_prefix}{job.subject}"
    text, subtype = _body(template)
    if test_notice:
        if subtype == "html":
            notice = (
                '<div style="border:2px solid #d97706;padding:12px;margin:0 0 16px 0">'
                "<strong>[TEST MESSAGE — NOT FOR OPERATIONAL DISTRIBUTION]</strong>"
                "<p>This email was sent only to the approved AARI test recipients. "
                "Production template recipients were not contacted.</p></div>"
            )
            text = notice + text
        else:
            text = (
                "[TEST MESSAGE — NOT FOR OPERATIONAL DISTRIBUTION]\n"
                "This email was sent only to the approved AARI test recipients. "
                "Production template recipients were not contacted.\n\n" + text
            )
    message.set_content(
        text,
        subtype=subtype if subtype in ("plain", "html") else "plain",
        charset="utf-8",
    )
    for attachment in job.attachments:
        mime, _ = mimetypes.guess_type(attachment.path.name)
        major, minor = (
            mime.split("/", 1)
            if mime and "/" in mime
            else ("application", "octet-stream")
        )
        message.add_attachment(
            attachment.path.read_bytes(),
            maintype=major,
            subtype=minor,
            filename=attachment.path.name,
        )
    return message, recipients


def _fingerprint(job: EmailJob) -> str:
    """Hash attachment names and contents to recognize repeat sends."""
    digest = hashlib.sha256()
    for attachment in job.attachments:
        digest.update(attachment.path.name.encode("utf-8") + b"\0")
        with attachment.path.open("rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def _mail_history(
    log_path: Path, release_date: date, key: str
) -> list[tuple[str, str]]:
    """Read mail markers from the normal log; no separate state file is needed."""
    matches: list[tuple[str, str]] = []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return matches
    for line in lines:
        marker = re.search(
            r"MAIL_(SENT|ATTEMPT|FAILED_BEFORE_SEND|UNCERTAIN)\|([^|]+)\|([^|]+)\|([0-9a-f]{64})",
            line,
        )
        if (
            marker
            and marker.group(2) == release_date.isoformat()
            and marker.group(3) == key
        ):
            matches.append((marker.group(1), marker.group(4)))
    return matches


def _validate(
    job: EmailJob,
    baselines: dict[str, dict[str, int]],
    min_ratio: float,
    max_ratio: float,
) -> list[str]:
    """Return issues with template, attachment set, or reference file sizes."""
    errors: list[str] = []
    suffixes = {a.path.suffix.lower() for a in job.attachments}
    if suffixes.intersection(COMPONENTS) and not set(COMPONENTS).issubset(suffixes):
        errors.append("комплект SIGRID должен содержать .shp, .shx, .dbf и .prj")
    for item in job.attachments:
        if not item.path.is_file():
            errors.append(f"нет вложения {item.path.name}")
            continue
        size = item.path.stat().st_size
        if size <= 0:
            errors.append(f"пустое вложение {item.path.name}")
            continue
        baseline = baselines.get(item.family, {}).get(item.path.suffix.lower())
        if baseline and not min_ratio <= size / baseline <= max_ratio:
            errors.append(
                f"подозрительный размер {item.path.name}: {size:,} байт; эталон {baseline:,}"
            )
    if not job.template.is_file():
        errors.append(f"нет шаблона {job.template.name}")
    return errors


def process_email_job(
    job: EmailJob,
    release_date: date,
    *,
    log_path: Path,
    dry_run: bool,
    smtp_server: str,
    smtp_port: int,
    sender_email: str,
    sender_name: str,
    password: str,
    size_baselines: dict[str, dict[str, int]],
    min_size_ratio: float,
    max_size_ratio: float,
    resend_changed: bool = False,
) -> EmailResult:
    """Validate and send one product email, avoiding silent duplicate sends."""
    errors = _validate(job, size_baselines, min_size_ratio, max_size_ratio)
    if errors:
        return EmailResult(job.name, "BLOCKED", "; ".join(errors))
    if not sender_email:
        return EmailResult(
            job.name, "CONFIG_ERROR", "не задан AARI_EMAIL_ADDRESS в .env"
        )
    try:
        message, recipients = _build_message(job, sender_email, sender_name)
        fingerprint = _fingerprint(job)
    except (OSError, ValueError) as exc:
        return EmailResult(job.name, "ERROR", f"ошибка подготовки письма: {exc}")

    history = _mail_history(log_path, release_date, job.key)
    matching = [status for status, fp in history if fp == fingerprint]
    sent_hashes = [fp for status, fp in history if status == "SENT"]
    if "SENT" in matching:
        return EmailResult(
            job.name, "ALREADY_SENT", "это письмо с такими же вложениями уже отправлено"
        )
    if sent_hashes and fingerprint not in sent_hashes and not resend_changed:
        return EmailResult(
            job.name,
            "REVIEW_REQUIRED",
            "вложения изменились после отправки; автоматическая повторная отправка остановлена",
        )
    if matching and matching[-1] in ("ATTEMPT", "UNCERTAIN") and not resend_changed:
        return EmailResult(
            job.name,
            "REVIEW_REQUIRED",
            "предыдущая отправка не подтверждена; проверьте почту перед повтором",
        )
    LOG.info(
        "MAIL_PLAN | date=%s | job=%s | subject=%s | recipients=%s | attachments=%d",
        release_date.isoformat(),
        job.key,
        job.subject,
        ", ".join(recipients),
        len(job.attachments),
    )
    for item in job.attachments:
        LOG.info("MAIL_ATTACHMENT | job=%s | %s", job.key, item.path)

    if dry_run:
        return EmailResult(
            job.name,
            "DRY-RUN",
            f"тема: {job.subject}; адресаты: {', '.join(recipients)}; "
            f"вложений: {len(job.attachments)}",
        )
    if not password:
        return EmailResult(
            job.name, "CONFIG_ERROR", "не задан AARI_EMAIL_PASSWORD в .env"
        )

    try:
        server = smtplib.SMTP_SSL(
            smtp_server, smtp_port, timeout=30, context=ssl.create_default_context()
        )
        server.login(sender_email, password)
    except (OSError, smtplib.SMTPException) as exc:
        LOG.error(
            "MAIL_FAILED_BEFORE_SEND|%s|%s|%s",
            release_date.isoformat(),
            job.key,
            fingerprint,
        )
        return EmailResult(
            job.name,
            "MAIL_ERROR",
            f"не удалось подключиться к SMTP/авторизоваться: {exc}",
        )
    try:
        LOG.info(
            "MAIL_ATTEMPT|%s|%s|%s", release_date.isoformat(), job.key, fingerprint
        )
        refused = server.send_message(
            message, from_addr=sender_email, to_addrs=recipients
        )
        if refused:
            LOG.error(
                "MAIL_UNCERTAIN|%s|%s|%s",
                release_date.isoformat(),
                job.key,
                fingerprint,
            )
            return EmailResult(
                job.name,
                "REVIEW_REQUIRED",
                f"SMTP отклонил адресатов: {refused}; проверьте доставку вручную",
            )
        LOG.info("MAIL_SENT|%s|%s|%s", release_date.isoformat(), job.key, fingerprint)
        return EmailResult(
            job.name,
            "SENT",
            f"передано SMTP; тема: {job.subject}; "
            f"адресаты: {', '.join(recipients)}; "
            f"вложений: {len(job.attachments)}",
        )
    except (OSError, smtplib.SMTPException) as exc:
        LOG.error(
            "MAIL_UNCERTAIN|%s|%s|%s", release_date.isoformat(), job.key, fingerprint
        )
        return EmailResult(
            job.name,
            "REVIEW_REQUIRED",
            f"SMTP не подтвердил результат отправки, проверьте почту: {exc}",
        )
    finally:
        try:
            server.quit()
        except (OSError, smtplib.SMTPException):
            pass


def process_email_jobs(
    jobs: Sequence[EmailJob],
    release_date: date,
    *,
    log_path: Path,
    dry_run: bool,
    smtp_server: str,
    smtp_port: int,
    sender_email: str,
    sender_name: str,
    password: str,
    size_baselines: dict[str, dict[str, int]],
    min_size_ratio: float,
    max_size_ratio: float,
    resend_changed: bool = False,
) -> list[EmailResult]:
    """Process all five product emails with explicit, checked SMTP options."""
    results: list[EmailResult] = []
    for job in jobs:
        result = process_email_job(
            job,
            release_date,
            log_path=log_path,
            dry_run=dry_run,
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            sender_email=sender_email,
            sender_name=sender_name,
            password=password,
            size_baselines=size_baselines,
            min_size_ratio=min_size_ratio,
            max_size_ratio=max_size_ratio,
            resend_changed=resend_changed,
        )
        results.append(result)
    return results


def parse_report_recipients(raw: str) -> list[str]:
    """Parse a comma- or semicolon-separated recipient list from .env."""
    normalized = raw.replace(";", ",")
    return [
        address.strip()
        for _name, address in getaddresses([normalized])
        if address.strip()
    ]


def send_weekly_report(
    subject: str,
    body: str,
    release_date: date,
    *,
    log_path: Path,
    smtp_server: str,
    smtp_port: int,
    sender_email: str,
    sender_name: str,
    password: str,
    recipient_list: Sequence[str],
    dry_run: bool,
) -> EmailResult:
    """Send one operational report per release Wednesday, tracking delivery in the normal log."""
    recipients = list(
        dict.fromkeys(address.strip() for address in recipient_list if address.strip())
    )
    if not recipients:
        return EmailResult(
            "Еженедельный отчёт",
            "CONFIG_ERROR",
            "AARI_REPORT_RECIPIENTS не задан или не содержит адресов",
        )
    if not sender_email:
        return EmailResult(
            "Еженедельный отчёт", "CONFIG_ERROR", "не задан AARI_EMAIL_ADDRESS в .env"
        )

    fingerprint = hashlib.sha256(
        (subject + "\0" + body + "\0" + ",".join(recipients)).encode("utf-8")
    ).hexdigest()
    date_text = release_date.isoformat()
    try:
        log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        log_lines = []

    for line in log_lines:
        sent = re.search(r"REPORT_SENT\|(\d{4}-\d{2}-\d{2})\|([0-9a-f]{64})", line)
        if sent and sent.group(1) == date_text:
            return EmailResult(
                "Еженедельный отчёт",
                "ALREADY_SENT",
                "отчёт за эту дату уже передан SMTP",
            )
        uncertain = re.search(
            r"REPORT_UNCERTAIN\|(\d{4}-\d{2}-\d{2})\|([0-9a-f]{64})", line
        )
        if uncertain and uncertain.group(1) == date_text:
            return EmailResult(
                "Еженедельный отчёт",
                "REVIEW_REQUIRED",
                "предыдущая передача отчёта не подтверждена; проверьте почту перед повтором",
            )

    if dry_run:
        return EmailResult(
            "Еженедельный отчёт",
            "DRY-RUN",
            f"тема: {subject}; получатели: {', '.join(recipients)}",
        )

    if not password:
        return EmailResult(
            "Еженедельный отчёт", "CONFIG_ERROR", "не задан AARI_EMAIL_PASSWORD в .env"
        )

    message = EmailMessage(policy=policy.SMTP)
    message["From"] = (
        formataddr((sender_name, sender_email)) if sender_name else sender_email
    )
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body, charset="utf-8")

    try:
        server = smtplib.SMTP_SSL(
            smtp_server, smtp_port, timeout=30, context=ssl.create_default_context()
        )
        server.login(sender_email, password)
    except (OSError, smtplib.SMTPException) as exc:
        LOG.error("REPORT_FAILED_BEFORE_SEND|%s|%s", date_text, fingerprint)
        return EmailResult(
            "Еженедельный отчёт",
            "MAIL_ERROR",
            f"не удалось подключиться к SMTP/авторизоваться: {exc}",
        )

    try:
        LOG.info("REPORT_ATTEMPT|%s|%s", date_text, fingerprint)
        refused = server.send_message(
            message, from_addr=sender_email, to_addrs=recipients
        )
        if refused:
            LOG.error("REPORT_UNCERTAIN|%s|%s", date_text, fingerprint)
            return EmailResult(
                "Еженедельный отчёт",
                "REVIEW_REQUIRED",
                f"SMTP отклонил часть получателей: {refused}; проверьте доставку вручную",
            )
        LOG.info("REPORT_SENT|%s|%s", date_text, fingerprint)
        return EmailResult(
            "Еженедельный отчёт",
            "SENT",
            f"передан SMTP; получатели: {', '.join(recipients)}",
        )
    except (OSError, smtplib.SMTPException) as exc:
        LOG.error("REPORT_UNCERTAIN|%s|%s", date_text, fingerprint)
        return EmailResult(
            "Еженедельный отчёт",
            "REVIEW_REQUIRED",
            f"SMTP не подтвердил результат отправки, проверьте почту: {exc}",
        )
    finally:
        try:
            server.quit()
        except (OSError, smtplib.SMTPException):
            pass


def process_test_email_suite(
    jobs: Sequence[EmailJob],
    release_date: date,
    report_subject: str,
    report_body: str,
    *,
    dry_run: bool,
    smtp_server: str,
    smtp_port: int,
    sender_email: str,
    sender_name: str,
    password: str,
    production_report_recipients: Sequence[str],
    size_baselines: dict[str, dict[str, int]],
    min_size_ratio: float,
    max_size_ratio: float,
) -> list[EmailResult]:
    """Preview or send six test messages, hard-routed to TEST_RECIPIENTS only."""
    report_key = "weekly_report_test"
    ordered = [(job.key, job.name) for job in jobs] + [
        (report_key, "Тест еженедельного отчёта")
    ]
    test_recipients = list(TEST_RECIPIENTS)
    LOG.info(
        "TEST_MAIL_REDIRECT | date=%s | test_recipients=%s | production_template_recipients_are_never_used_for_delivery",
        release_date.isoformat(),
        ", ".join(test_recipients),
    )
    LOG.info(
        "TEST_REPORT_PRODUCTION_RECIPIENTS | date=%s | configured=%s",
        release_date.isoformat(),
        (
            ", ".join(production_report_recipients)
            if production_report_recipients
            else "(не заданы)"
        ),
    )

    if not sender_email:
        return [
            EmailResult(name, "CONFIG_ERROR", "не задан AARI_EMAIL_ADDRESS в .env")
            for _key, name in ordered
        ]

    prepared: dict[str, tuple[EmailMessage, str, int]] = {}
    source_recipients: dict[str, list[str]] = {}
    errors: dict[str, EmailResult] = {}

    for job in jobs:
        issues = _validate(job, size_baselines, min_size_ratio, max_size_ratio)
        if issues:
            errors[job.key] = EmailResult(job.name, "BLOCKED", "; ".join(issues))
            continue
        try:
            # Read production template recipients for the preview/log only.
            _production_message, intended_recipients = _build_message(
                job, sender_email, sender_name
            )
            test_message, routed_recipients = _build_message(
                job,
                sender_email,
                sender_name,
                recipient_override=test_recipients,
                subject_prefix="[TEST] ",
                test_notice=True,
            )
            if routed_recipients != test_recipients:
                raise ValueError("список тестовых адресатов не совпадает с разрешённым")
            fingerprint = _fingerprint(job)
            prepared[job.key] = (
                test_message,
                fingerprint,
                len(job.attachments),
            )
            source_recipients[job.key] = intended_recipients
            LOG.info(
                "TEST_MAIL_PLAN | date=%s | job=%s | subject=%s | test_recipients=%s | template_recipients=%s | attachments=%d",
                release_date.isoformat(),
                job.key,
                test_message["Subject"],
                ", ".join(test_recipients),
                ", ".join(intended_recipients),
                len(job.attachments),
            )
            for attachment in job.attachments:
                LOG.info(
                    "TEST_MAIL_ATTACHMENT | job=%s | %s",
                    job.key,
                    attachment.path,
                )
        except (OSError, ValueError) as exc:
            errors[job.key] = EmailResult(
                job.name, "ERROR", f"ошибка подготовки тестового письма: {exc}"
            )

    try:
        report_message = EmailMessage(policy=policy.SMTP)
        report_message["From"] = (
            formataddr((sender_name, sender_email)) if sender_name else sender_email
        )
        report_message["To"] = ", ".join(test_recipients)
        report_message["Subject"] = (
            report_subject
            if report_subject.startswith("[TEST]")
            else f"[TEST] {report_subject}"
        )
        report_message.set_content(
            "[TEST MESSAGE — NOT FOR OPERATIONAL DISTRIBUTION]\n"
            "This diagnostic report is delivered only to the approved test recipients. "
            "The configured production report recipients are not contacted.\n\n"
            + report_body,
            charset="utf-8",
        )
        report_fingerprint = hashlib.sha256(
            (
                str(report_message["Subject"])
                + "\0"
                + report_body
                + "\0"
                + ",".join(test_recipients)
            ).encode("utf-8")
        ).hexdigest()
        prepared[report_key] = (report_message, report_fingerprint, 0)
        LOG.info(
            "TEST_REPORT_PLAN | date=%s | subject=%s | test_recipients=%s",
            release_date.isoformat(),
            report_message["Subject"],
            ", ".join(test_recipients),
        )
    except (OSError, ValueError) as exc:
        errors[report_key] = EmailResult(
            "Тест еженедельного отчёта",
            "ERROR",
            f"ошибка подготовки тестового отчёта: {exc}",
        )

    # Do not send a partial suite when any template, attachment, or message is invalid.
    if errors:
        output = []
        for key, name in ordered:
            output.append(
                errors.get(key)
                or EmailResult(
                    name,
                    "NOT_SENT",
                    "вся тестовая рассылка отменена: обнаружены ошибки предварительной проверки",
                )
            )
        LOG.error(
            "TEST_MAIL_PREFLIGHT_FAILED | date=%s | messages_not_sent=%d",
            release_date.isoformat(),
            len(ordered),
        )
        return output

    if dry_run:
        output = []
        for key, name in ordered:
            message, _fingerprint_value, attachment_count = prepared[key]
            output.append(
                EmailResult(
                    name,
                    "DRY-RUN",
                    f"тема: {message['Subject']}; тестовые получатели: "
                    f"{', '.join(test_recipients)}; вложений: {attachment_count}; "
                    "SMTP не подключался, ничего не отправлено",
                )
            )
        LOG.info(
            "TEST_MAIL_PREVIEW_COMPLETE | date=%s | messages=6 | smtp_connection=no",
            release_date.isoformat(),
        )
        return output

    if not password:
        return [
            EmailResult(
                name,
                "CONFIG_ERROR",
                "не задан AARI_EMAIL_PASSWORD в .env; ничего не отправлено",
            )
            for _key, name in ordered
        ]

    try:
        server = smtplib.SMTP_SSL(
            smtp_server, smtp_port, timeout=30, context=ssl.create_default_context()
        )
        server.login(sender_email, password)
        LOG.info(
            "TEST_SMTP_AUTH_OK | date=%s | server=%s | port=%s",
            release_date.isoformat(),
            smtp_server,
            smtp_port,
        )
    except (OSError, smtplib.SMTPException) as exc:
        LOG.error(
            "TEST_SMTP_AUTH_FAILED | date=%s | server=%s | port=%s | %s",
            release_date.isoformat(),
            smtp_server,
            smtp_port,
            exc,
        )
        return [
            EmailResult(
                name,
                "MAIL_ERROR",
                f"не удалось подключиться к SMTP/авторизоваться; ничего не отправлено: {exc}",
            )
            for _key, name in ordered
        ]

    outcomes: dict[str, EmailResult] = {}
    stopped = False
    try:
        for key, name in ordered:
            message, fingerprint, _attachment_count = prepared[key]
            LOG.info(
                "TEST_MAIL_ATTEMPT | date=%s | job=%s | fingerprint=%s",
                release_date.isoformat(),
                key,
                fingerprint,
            )
            try:
                refused = server.send_message(
                    message,
                    from_addr=sender_email,
                    to_addrs=test_recipients,
                )
                if refused:
                    LOG.error(
                        "TEST_MAIL_UNCERTAIN | date=%s | job=%s | refused=%s | fingerprint=%s",
                        release_date.isoformat(),
                        key,
                        refused,
                        fingerprint,
                    )
                    outcomes[key] = EmailResult(
                        name,
                        "REVIEW_REQUIRED",
                        f"SMTP отклонил часть тестовых адресатов: {refused}; "
                        "проверьте получение вручную и не повторяйте вслепую",
                    )
                    stopped = True
                    break
                marker = "TEST_REPORT_SENT" if key == report_key else "TEST_MAIL_SENT"
                LOG.info(
                    "%s | %s | %s | %s",
                    marker,
                    release_date.isoformat(),
                    key,
                    fingerprint,
                )
                outcomes[key] = EmailResult(
                    name,
                    "SENT",
                    f"передано SMTP; тема: {message['Subject']}; "
                    f"тестовые получатели: {', '.join(test_recipients)}; "
                    f"вложений: {_attachment_count}",
                )
            except (OSError, smtplib.SMTPException) as exc:
                LOG.error(
                    "TEST_MAIL_UNCERTAIN | date=%s | job=%s | fingerprint=%s | %s",
                    release_date.isoformat(),
                    key,
                    fingerprint,
                    exc,
                )
                outcomes[key] = EmailResult(
                    name,
                    "REVIEW_REQUIRED",
                    f"SMTP не подтвердил результат отправки; проверьте почту вручную: {exc}",
                )
                stopped = True
                break
    finally:
        try:
            server.quit()
        except (OSError, smtplib.SMTPException):
            pass

    if stopped:
        next_unprocessed = False
        for key, name in ordered:
            if key in outcomes:
                next_unprocessed = True
                continue
            if next_unprocessed:
                outcomes[key] = EmailResult(
                    name,
                    "NOT_SENT",
                    "отправка следующих тестовых сообщений остановлена после неопределённого SMTP-результата",
                )
    return [outcomes[key] for key, _name in ordered]
