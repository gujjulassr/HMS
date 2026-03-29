"""
Email Service — sends transactional emails via the configured Email Adapter.

Usage:
    from go.services.email_service import send_booking_confirmation, send_cancellation_email

The service builds HTML templates and delegates actual sending to the EmailAdapter.
Swap providers (Gmail → SendGrid → SES) by changing config — no code changes here.

Fails silently (logs errors) so email issues never block core functionality.
"""

import logging
from typing import Optional

from go.adapters.email_adapter import EmailPayload, EmailAttachment, get_email_adapter
from go.services.calendar_service import build_booking_event, build_cancellation_event

logger = logging.getLogger(__name__)


# ─── Core sender (adapter-backed) ───────────────────────────────

async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: Optional[str] = None,
    attachments: Optional[list[EmailAttachment]] = None,
) -> bool:
    """
    Send an email via the configured adapter.
    Returns True on success, False on failure. Never raises.
    """
    adapter = get_email_adapter()
    payload = EmailPayload(
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        attachments=attachments or [],
    )
    return await adapter.send(payload)


# ─── Fire-and-forget helper ───────────────────────────────────

def send_email_background(to_email: str, subject: str, html_body: str, plain_body: Optional[str] = None):
    """
    Schedule email sending in the background so it doesn't block the request.
    """
    adapter = get_email_adapter()
    payload = EmailPayload(
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
    )
    adapter.send_background(payload)


# ─── HTML email templates ────────────────────────────────────

def _base_template(title: str, content: str) -> str:
    """Wrap content in a clean hospital-themed email template."""
    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                 background: #f3f4f6; padding: 20px; margin: 0;">
        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 12px;
                     overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #2563eb, #1d4ed8); padding: 24px 30px;">
                <h1 style="color: white; margin: 0; font-size: 22px;">🏥 HMS Hospital</h1>
                <p style="color: #bfdbfe; margin: 4px 0 0 0; font-size: 14px;">{title}</p>
            </div>
            <!-- Content -->
            <div style="padding: 30px;">
                {content}
            </div>
            <!-- Footer -->
            <div style="background: #f9fafb; padding: 16px 30px; border-top: 1px solid #e5e7eb;">
                <p style="color: #9ca3af; font-size: 12px; margin: 0;">
                    This is an automated message from HMS Hospital Management System.
                    Please do not reply to this email.
                </p>
            </div>
        </div>
    </body>
    </html>
    """


# ─── Transactional email builders ────────────────────────────

async def send_booking_confirmation(
    to_email: str,
    patient_name: str,
    doctor_name: str,
    specialization: str,
    session_date: str,
    slot_time: str,
    slot_number: int,
    appointment_id: str = "",
    duration_minutes: int = 15,
) -> bool:
    """Send booking confirmation email with calendar event attached."""
    content = f"""
    <h2 style="color: #059669; margin-top: 0;">✅ Appointment Confirmed</h2>
    <p>Dear <strong>{patient_name}</strong>,</p>
    <p>Your appointment has been successfully booked. Here are the details:</p>
    <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 10px 0; color: #6b7280;">Doctor</td>
            <td style="padding: 10px 0; font-weight: 600;">🩺 {doctor_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 10px 0; color: #6b7280;">Department</td>
            <td style="padding: 10px 0; font-weight: 600;">{specialization}</td>
        </tr>
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 10px 0; color: #6b7280;">Date</td>
            <td style="padding: 10px 0; font-weight: 600;">📅 {session_date}</td>
        </tr>
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 10px 0; color: #6b7280;">Time</td>
            <td style="padding: 10px 0; font-weight: 600;">🕐 {slot_time}</td>
        </tr>
        <tr>
            <td style="padding: 10px 0; color: #6b7280;">Slot</td>
            <td style="padding: 10px 0; font-weight: 600;">#{slot_number}</td>
        </tr>
    </table>
    <div style="background: #eff6ff; border-left: 4px solid #3b82f6; padding: 12px 16px;
                border-radius: 4px; margin: 16px 0;">
        <p style="margin: 0; font-size: 14px; color: #1e40af;">
            💡 <strong>Reminder:</strong> Please arrive 15 minutes before your scheduled time.
            Bring your ID and any previous medical records.
        </p>
        <p style="margin: 8px 0 0 0; font-size: 14px; color: #1e40af;">
            📅 A calendar event is attached — open it to add this appointment to your calendar.
        </p>
    </div>
    """

    # Build calendar event attachment
    attachments = []
    if appointment_id:
        ics_bytes = build_booking_event(
            appointment_id=appointment_id,
            patient_name=patient_name,
            patient_email=to_email,
            doctor_name=doctor_name,
            specialization=specialization,
            session_date=session_date,
            slot_time=slot_time,
            slot_number=slot_number,
            duration_minutes=duration_minutes,
        )
        if ics_bytes:
            attachments.append(EmailAttachment(
                filename="appointment.ics",
                content=ics_bytes,
                mime_type="text/calendar",
                mime_subtype="calendar",
            ))

    return await send_email(
        to_email,
        f"Appointment Confirmed — {doctor_name} on {session_date}",
        _base_template("Booking Confirmation", content),
        plain_body=f"Hi {patient_name}, your appointment with {doctor_name} ({specialization}) "
                   f"is confirmed for {session_date} at {slot_time}, slot #{slot_number}.",
        attachments=attachments,
    )


async def send_cancellation_email(
    to_email: str,
    patient_name: str,
    doctor_name: str,
    session_date: str,
    slot_time: str,
    reason: str = "",
    appointment_id: str = "",
) -> bool:
    """Send appointment cancellation email with calendar cancellation event attached."""
    reason_html = f'<p style="color: #6b7280;">Reason: <em>{reason}</em></p>' if reason else ""
    content = f"""
    <h2 style="color: #dc2626; margin-top: 0;">❌ Appointment Cancelled</h2>
    <p>Dear <strong>{patient_name}</strong>,</p>
    <p>Your appointment has been cancelled.</p>
    <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 10px 0; color: #6b7280;">Doctor</td>
            <td style="padding: 10px 0;">🩺 {doctor_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 10px 0; color: #6b7280;">Date</td>
            <td style="padding: 10px 0;">📅 {session_date}</td>
        </tr>
        <tr>
            <td style="padding: 10px 0; color: #6b7280;">Time</td>
            <td style="padding: 10px 0;">🕐 {slot_time}</td>
        </tr>
    </table>
    {reason_html}
    <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 12px 16px;
                border-radius: 4px; margin: 16px 0;">
        <p style="margin: 0; font-size: 14px; color: #991b1b;">
            📅 A calendar update is attached — open it to remove this appointment from your calendar.
        </p>
    </div>
    <p>You can book a new appointment anytime through the patient portal.</p>
    """

    # Build calendar cancellation event
    attachments = []
    if appointment_id:
        ics_bytes = build_cancellation_event(
            appointment_id=appointment_id,
            patient_name=patient_name,
            patient_email=to_email,
            doctor_name=doctor_name,
            session_date=session_date,
            slot_time=slot_time,
            reason=reason,
        )
        if ics_bytes:
            attachments.append(EmailAttachment(
                filename="cancellation.ics",
                content=ics_bytes,
                mime_type="text/calendar",
                mime_subtype="calendar",
            ))

    return await send_email(
        to_email,
        f"Appointment Cancelled — {doctor_name} on {session_date}",
        _base_template("Cancellation Notice", content),
        plain_body=f"Hi {patient_name}, your appointment with {doctor_name} on {session_date} "
                   f"at {slot_time} has been cancelled. {reason}",
        attachments=attachments,
    )


async def send_delay_notification(
    to_email: str,
    patient_name: str,
    doctor_name: str,
    session_date: str,
    original_time: str,
    estimated_delay_minutes: int,
) -> bool:
    """Notify patient about doctor running behind schedule."""
    content = f"""
    <h2 style="color: #d97706; margin-top: 0;">⏳ Schedule Update</h2>
    <p>Dear <strong>{patient_name}</strong>,</p>
    <p>We want to let you know that <strong>{doctor_name}</strong> is currently running
    approximately <strong>{estimated_delay_minutes} minutes</strong> behind schedule.</p>
    <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 10px 0; color: #6b7280;">Your scheduled time</td>
            <td style="padding: 10px 0; font-weight: 600;">🕐 {original_time}</td>
        </tr>
        <tr>
            <td style="padding: 10px 0; color: #6b7280;">Estimated delay</td>
            <td style="padding: 10px 0; font-weight: 600; color: #d97706;">~{estimated_delay_minutes} min</td>
        </tr>
    </table>
    <div style="background: #fefce8; border-left: 4px solid #eab308; padding: 12px 16px;
                border-radius: 4px; margin: 16px 0;">
        <p style="margin: 0; font-size: 14px; color: #854d0e;">
            We apologize for the inconvenience. The doctor is treating patients as
            quickly and carefully as possible. Please plan accordingly.
        </p>
    </div>
    """
    return await send_email(
        to_email,
        f"Schedule Delay — {doctor_name} running ~{estimated_delay_minutes}min late",
        _base_template("Schedule Update", content),
        plain_body=f"Hi {patient_name}, {doctor_name} is running approximately "
                   f"{estimated_delay_minutes} minutes behind schedule for your "
                   f"{original_time} appointment on {session_date}.",
    )


async def send_session_cancelled_email(
    to_email: str,
    patient_name: str,
    doctor_name: str,
    session_date: str,
    reason: str = "",
) -> bool:
    """Notify patient that an entire session has been cancelled."""
    reason_html = f'<p style="color: #6b7280;">Reason: <em>{reason}</em></p>' if reason else ""
    content = f"""
    <h2 style="color: #dc2626; margin-top: 0;">🚫 Session Cancelled</h2>
    <p>Dear <strong>{patient_name}</strong>,</p>
    <p>We regret to inform you that <strong>{doctor_name}'s</strong> session on
    <strong>{session_date}</strong> has been cancelled.</p>
    {reason_html}
    <p>All appointments for this session have been cancelled.
    You will not be penalized for this cancellation.</p>
    <p>Please log in to the patient portal to rebook your appointment with the same
    or another doctor.</p>
    """
    return await send_email(
        to_email,
        f"Session Cancelled — {doctor_name} on {session_date}",
        _base_template("Session Cancelled", content),
        plain_body=f"Hi {patient_name}, {doctor_name}'s session on {session_date} has been "
                   f"cancelled. {reason} Please rebook through the portal.",
    )


async def send_checkin_reminder(
    to_email: str,
    patient_name: str,
    doctor_name: str,
    session_date: str,
    slot_time: str,
) -> bool:
    """Send a reminder to check in for upcoming appointment."""
    content = f"""
    <h2 style="color: #2563eb; margin-top: 0;">📋 Appointment Reminder</h2>
    <p>Dear <strong>{patient_name}</strong>,</p>
    <p>This is a reminder for your upcoming appointment:</p>
    <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 10px 0; color: #6b7280;">Doctor</td>
            <td style="padding: 10px 0; font-weight: 600;">🩺 {doctor_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 10px 0; color: #6b7280;">Date</td>
            <td style="padding: 10px 0; font-weight: 600;">📅 {session_date}</td>
        </tr>
        <tr>
            <td style="padding: 10px 0; color: #6b7280;">Time</td>
            <td style="padding: 10px 0; font-weight: 600;">🕐 {slot_time}</td>
        </tr>
    </table>
    <p>Please arrive 15 minutes early and bring your ID.</p>
    """
    return await send_email(
        to_email,
        f"Appointment Reminder — {doctor_name} on {session_date} at {slot_time}",
        _base_template("Appointment Reminder", content),
        plain_body=f"Hi {patient_name}, reminder: you have an appointment with {doctor_name} "
                   f"on {session_date} at {slot_time}. Please arrive 15 minutes early.",
    )
