"""
Calendar Service — generates calendar events (ICS) for appointment emails.

Usage:
    from go.services.calendar_service import build_booking_event, build_cancellation_event

Generates .ics bytes that are attached to emails. When the patient opens the
email, the calendar event is automatically added to their Google Calendar,
Apple Calendar, Outlook, or any other calendar app.

Fails silently — calendar issues never block core functionality.
"""

import logging
from datetime import datetime, date, time
from typing import Optional

from go.adapters.calendar_adapter import CalendarEvent, get_calendar_adapter

logger = logging.getLogger(__name__)


def build_booking_event(
    appointment_id: str,
    patient_name: str,
    patient_email: str,
    doctor_name: str,
    specialization: str,
    session_date: str,
    slot_time: str,
    slot_number: int,
    duration_minutes: int = 15,
    organizer_email: str = "",
) -> Optional[bytes]:
    """
    Build an .ics calendar event for a new booking.
    Returns ICS bytes to attach to the confirmation email, or None on failure.
    """
    try:
        adapter = get_calendar_adapter()

        # Parse date and time
        start_dt = _parse_datetime(session_date, slot_time)
        if not start_dt:
            logger.warning("Could not parse date/time for calendar event: %s %s", session_date, slot_time)
            return None

        event = CalendarEvent(
            summary=f"Appointment — Dr. {doctor_name} ({specialization})",
            description=(
                f"Patient: {patient_name}\n"
                f"Doctor: Dr. {doctor_name}\n"
                f"Department: {specialization}\n"
                f"Slot: #{slot_number}\n"
                f"Duration: {duration_minutes} minutes\n\n"
                f"Please arrive 15 minutes early.\n"
                f"Bring your ID and previous medical records."
            ),
            location="HMS Hospital",
            start_time=start_dt,
            duration_minutes=duration_minutes,
            organizer_email=organizer_email,
            attendee_email=patient_email,
            attendee_name=patient_name,
            uid=f"hms-appt-{appointment_id}@hms-hospital.local",
        )

        return adapter.create_event(event)

    except Exception as e:
        logger.error("Failed to build booking calendar event: %s", e)
        return None


def build_cancellation_event(
    appointment_id: str,
    patient_name: str,
    patient_email: str,
    doctor_name: str,
    session_date: str,
    slot_time: str,
    reason: str = "",
    duration_minutes: int = 15,
) -> Optional[bytes]:
    """
    Build an .ics CANCEL event for a cancelled booking.
    Returns ICS bytes to attach to the cancellation email, or None on failure.
    The UID must match the original booking event so calendar apps can remove it.
    """
    try:
        adapter = get_calendar_adapter()

        start_dt = _parse_datetime(session_date, slot_time)
        if not start_dt:
            logger.warning("Could not parse date/time for cancel event: %s %s", session_date, slot_time)
            return None

        event = CalendarEvent(
            summary=f"CANCELLED — Dr. {doctor_name}",
            description=(
                f"This appointment has been cancelled.\n"
                f"Patient: {patient_name}\n"
                f"Doctor: Dr. {doctor_name}\n"
                f"{f'Reason: {reason}' if reason else ''}"
            ),
            location="HMS Hospital",
            start_time=start_dt,
            duration_minutes=duration_minutes,
            attendee_email=patient_email,
            attendee_name=patient_name,
            uid=f"hms-appt-{appointment_id}@hms-hospital.local",
        )

        return adapter.cancel_event(event)

    except Exception as e:
        logger.error("Failed to build cancellation calendar event: %s", e)
        return None


# ─── Helpers ─────────────────────────────────────────────────

def _parse_datetime(session_date: str, slot_time: str) -> Optional[datetime]:
    """Parse session_date and slot_time strings into a datetime object."""
    try:
        # session_date can be "2026-03-30" or "2026-03-30 00:00:00" etc.
        date_str = str(session_date).split(" ")[0].split("T")[0]
        d = datetime.strptime(date_str, "%Y-%m-%d").date()

        # slot_time can be "09:30", "09:30:00", or "—"
        time_str = str(slot_time).strip()
        if time_str in ("—", "-", "", "None"):
            # Default to 9:00 AM if time unknown
            t = time(9, 0)
        else:
            parts = time_str.split(":")
            t = time(int(parts[0]), int(parts[1]))

        return datetime.combine(d, t)

    except (ValueError, IndexError) as e:
        logger.error("Failed to parse date/time '%s' '%s': %s", session_date, slot_time, e)
        return None
