"""
Email Adapter — abstract interface for sending transactional emails.

To add a new provider (e.g., SendGrid, AWS SES):
  1. Subclass EmailAdapter
  2. Implement send() and is_configured()
  3. Register it in get_email_adapter()

The notification dispatcher only talks to this interface — never directly to SMTP/API.
"""

import logging
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import lru_cache

logger = logging.getLogger(__name__)


# ─── Standardized email payload ────────────────────────────────

@dataclass
class EmailPayload:
    """Provider-agnostic email payload."""
    to_email: str
    subject: str
    html_body: str
    plain_body: Optional[str] = None
    reply_to: Optional[str] = None
    tags: list[str] = field(default_factory=list)  # e.g., ["booking", "transactional"]


# ─── Abstract interface ───────────────────────────────────────

class EmailAdapter(ABC):
    """Abstract base class for email sending providers."""

    @abstractmethod
    async def send(self, payload: EmailPayload) -> bool:
        """
        Send an email. Returns True on success, False on failure.
        Implementations must never raise — log errors instead.
        """
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if this adapter has valid credentials configured."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name (e.g., 'Gmail SMTP', 'SendGrid')."""
        ...

    def send_background(self, payload: EmailPayload) -> None:
        """Fire-and-forget: schedule email in the background event loop."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.send(payload))
        except RuntimeError:
            pass  # No running loop — skip silently


# ─── Gmail SMTP implementation ────────────────────────────────

class GmailEmailAdapter(EmailAdapter):
    """Send emails via Gmail SMTP using aiosmtplib."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_name: str,
    ):
        self._host = smtp_host
        self._port = smtp_port
        self._username = username
        self._password = password
        self._from_name = from_name

    @property
    def provider_name(self) -> str:
        return "Gmail SMTP"

    def is_configured(self) -> bool:
        return bool(self._username and self._password)

    async def send(self, payload: EmailPayload) -> bool:
        if not self.is_configured():
            logger.warning("Gmail SMTP not configured — skipping email to %s", payload.to_email)
            return False

        import aiosmtplib

        msg = MIMEMultipart("alternative")
        msg["From"] = f"{self._from_name} <{self._username}>"
        msg["To"] = payload.to_email
        msg["Subject"] = payload.subject
        if payload.reply_to:
            msg["Reply-To"] = payload.reply_to

        if payload.plain_body:
            msg.attach(MIMEText(payload.plain_body, "plain"))
        msg.attach(MIMEText(payload.html_body, "html"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=self._host,
                port=self._port,
                start_tls=True,
                username=self._username,
                password=self._password,
                timeout=15,
            )
            logger.info("Email sent via Gmail SMTP to %s: %s", payload.to_email, payload.subject)
            return True
        except Exception as e:
            logger.error("Gmail SMTP send failed to %s: %s", payload.to_email, e)
            return False


# ─── Factory ──────────────────────────────────────────────────

@lru_cache()
def get_email_adapter(provider: str = "gmail") -> EmailAdapter:
    """
    Factory — returns the configured email adapter.
    Cached so the same instance is reused across requests.
    """
    from config import get_settings
    settings = get_settings()

    if provider == "gmail":
        return GmailEmailAdapter(
            smtp_host=settings.SMTP_HOST,
            smtp_port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            from_name=settings.EMAIL_FROM_NAME,
        )

    raise ValueError(f"Unknown email provider: {provider}")
