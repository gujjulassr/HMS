"""
Calendar Adapter — abstract interface for calendar event providers.

To add a new provider (e.g., Google Calendar API, Outlook):
  1. Subclass CalendarAdapter
  2. Implement create_event() and cancel_event()
  3. Register it in get_calendar_adapter()

The default ICS adapter generates .ics file bytes that can be attached to emails.
Works with Google Calendar, Apple Calendar, Outlook — any calendar app.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from functools import lru_cache

logger = logging.getLogger(__name__)


# ─── Standardized calendar event payload ─────────────────────

@dataclass
class CalendarEvent:
    """Provider-agnostic calendar event."""
    summary: str                      # e.g., "Appointment with Dr. Smith"
    description: str                  # Details about the appointment
    location: str = "HMS Hospital"
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_minutes: int = 15
    organizer_email: str = ""
    attendee_email: str = ""
    attendee_name: str = ""
    uid: str = ""                     # Unique ID for the event (for cancellation)

    def __post_init__(self):
        if not self.uid:
            self.uid = f"{uuid.uuid4()}@hms-hospital.local"
        if self.start_time and not self.end_time:
            self.end_time = self.start_time + timedelta(minutes=self.duration_minutes)


# ─── Abstract interface ──────────────────────────────────────

class CalendarAdapter(ABC):
    """Abstract base class for calendar event providers."""

    @abstractmethod
    def create_event(self, event: CalendarEvent) -> bytes:
        """
        Create a calendar event. Returns .ics bytes (for ICS adapter)
        or event ID string (for API-based adapters).
        """
        ...

    @abstractmethod
    def cancel_event(self, event: CalendarEvent) -> bytes:
        """
        Cancel a calendar event. Returns .ics CANCEL bytes (for ICS adapter)
        or confirms deletion (for API-based adapters).
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name."""
        ...


# ─── ICS file implementation ─────────────────────────────────

class ICSCalendarAdapter(CalendarAdapter):
    """
    Generates RFC 5545 .ics calendar files that can be attached to emails.
    When opened, these files add/cancel events in any calendar app.
    """

    @property
    def provider_name(self) -> str:
        return "ICS File"

    def _format_dt(self, dt: datetime) -> str:
        """Format datetime as iCalendar UTC timestamp."""
        # Convert to UTC-like format (YYYYMMDDTHHMMSSZ)
        return dt.strftime("%Y%m%dT%H%M%S")

    def _build_ics(
        self, event: CalendarEvent, method: str = "REQUEST", status: str = "CONFIRMED"
    ) -> bytes:
        """Build an RFC 5545 compliant .ics file."""
        now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        start = self._format_dt(event.start_time) if event.start_time else now
        end = self._format_dt(event.end_time) if event.end_time else now

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//HMS Hospital//Appointment System//EN",
            f"METHOD:{method}",
            "CALSCALE:GREGORIAN",
            "BEGIN:VEVENT",
            f"UID:{event.uid}",
            f"DTSTAMP:{now}",
            f"DTSTART:{start}",
            f"DTEND:{end}",
            f"SUMMARY:{event.summary}",
            f"DESCRIPTION:{event.description}",
            f"LOCATION:{event.location}",
            f"STATUS:{status}",
            "SEQUENCE:0" if status == "CONFIRMED" else "SEQUENCE:1",
        ]

        if event.organizer_email:
            lines.append(f"ORGANIZER;CN=HMS Hospital:mailto:{event.organizer_email}")
        if event.attendee_email:
            cn = event.attendee_name or event.attendee_email
            lines.append(
                f"ATTENDEE;CN={cn};RSVP=TRUE:mailto:{event.attendee_email}"
            )

        # Add alarm reminder (15 min before)
        if status == "CONFIRMED":
            lines.extend([
                "BEGIN:VALARM",
                "TRIGGER:-PT15M",
                "ACTION:DISPLAY",
                "DESCRIPTION:Appointment in 15 minutes",
                "END:VALARM",
            ])

        lines.extend([
            "END:VEVENT",
            "END:VCALENDAR",
        ])

        return "\r\n".join(lines).encode("utf-8")

    def create_event(self, event: CalendarEvent) -> bytes:
        """Generate .ics bytes for a new appointment event."""
        logger.info("ICS event created: %s (%s)", event.summary, event.uid)
        return self._build_ics(event, method="REQUEST", status="CONFIRMED")

    def cancel_event(self, event: CalendarEvent) -> bytes:
        """Generate .ics CANCEL bytes to remove an appointment from calendar."""
        logger.info("ICS event cancelled: %s (%s)", event.summary, event.uid)
        return self._build_ics(event, method="CANCEL", status="CANCELLED")


# ─── Factory ─────────────────────────────────────────────────

@lru_cache()
def get_calendar_adapter(provider: str = "ics") -> CalendarAdapter:
    """
    Factory — returns the configured calendar adapter.
    Default is ICS file generation (works with any calendar app).
    """
    if provider == "ics":
        return ICSCalendarAdapter()

    raise ValueError(f"Unknown calendar provider: {provider}")
