"""Internal API client utilities for the chat service.

Handles HTTP requests, time parsing, and slot resolution.
"""

import json
import logging
import os
from datetime import date

import httpx

logger = logging.getLogger(__name__)

# ─── Internal API client ─────────────────────────────────────
API_BASE = "http://localhost:8000/api"


def _clear_proxy_env():
    """Remove proxy env vars that break httpx (socks5h not supported)."""
    for v in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
              "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy"):
        os.environ.pop(v, None)


async def _api(
    method: str, path: str, token: str,
    payload: dict | None = None, params: dict | None = None,
) -> dict:
    """Authenticated call to FastAPI backend."""
    _clear_proxy_env()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{API_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            if method == "GET":
                r = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                r = await client.post(url, headers=headers, json=payload)
            elif method == "PUT":
                r = await client.put(url, headers=headers, json=payload)
            else:
                return {"error": f"Unsupported method: {method}"}
            if r.status_code >= 400:
                try:
                    err = r.json()
                except Exception:
                    err = r.text
                return {"error": str(err), "status_code": r.status_code}
            return r.json()
    except httpx.ConnectError as e:
        logger.error(f"API connection error for {url}: {e}")
        return {"error": f"Cannot connect to backend at {url}. Is the server running?"}
    except httpx.TimeoutException:
        logger.error(f"API timeout for {url}")
        return {"error": f"Request timed out for {url}"}
    except Exception as e:
        logger.error(f"API call error for {url}: {e}", exc_info=True)
        return {"error": f"API call failed: {type(e).__name__}: {e}"}


def _j(obj) -> str:
    """JSON-serialize for agent output."""
    return json.dumps(obj, default=str)


# ─── Shared time helpers ─────────────────────────────────────

def _parse_hhmm(time_str: str) -> int:
    """Parse "HH:MM" or "HH:MM:SS" → total minutes since midnight."""
    parts = str(time_str).strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _fmt_hhmm(total_minutes: int) -> str:
    """Total minutes since midnight → "HH:MM"."""
    h, m = divmod(total_minutes, 60)
    return f"{h:02d}:{m:02d}"


def _next_available_slot_min(start_min: int, duration: int, now_min: int) -> int:
    """First slot start time (minutes) that is still in the future."""
    t = start_min
    while t <= now_min:
        t += duration
    return t


async def _resolve_preferred_time_to_slot(
    preferred_time: str, session_id: str, token: str,
) -> dict:
    """Convert a preferred HH:MM time to a 1-based slot number.

    Returns {"slot_number": int} on success or {"error": str} on failure.
    """
    session_data = await _api("GET", f"/sessions/{session_id}", token)
    if not isinstance(session_data, dict) or "error" in session_data:
        return {"error": f"Could not fetch session details: {session_data}"}

    start_min = _parse_hhmm(session_data.get("start_time", "09:00"))
    duration = session_data.get("slot_duration_minutes", 15)
    total_slots = session_data.get("total_slots", 0)
    sess_date = str(session_data.get("session_date", ""))
    pref_min = _parse_hhmm(preferred_time)

    # Reject past times for today's sessions
    from datetime import datetime as _dt
    now = _dt.now()
    if sess_date == now.strftime("%Y-%m-%d"):
        now_min = now.hour * 60 + now.minute
        if pref_min <= now_min:
            nxt = _next_available_slot_min(start_min, duration, now_min)
            return {
                "error": (
                    f"Cannot book at {preferred_time} — that time has already passed. "
                    f"Current time is {_fmt_hhmm(now_min)}. "
                    f"The next available slot is at {_fmt_hhmm(nxt)}."
                )
            }

    # Compute slot number
    diff = pref_min - start_min
    if diff < 0:
        return {"error": f"Time {preferred_time} is before session start."}
    slot_number = (diff // duration) + 1
    if slot_number > total_slots:
        return {"error": f"Time {preferred_time} is outside session hours (max slot {total_slots})."}
    return {"slot_number": slot_number}
