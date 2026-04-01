"""
Chat Routes — AI Chatbot API endpoints.

POST /api/chat/message     — Send text message to AI chatbot
POST /api/chat/transcribe  — Speech-to-text (Whisper ASR)
POST /api/chat/tts         — Text-to-speech (OpenAI TTS)
POST /api/chat/clear       — Clear conversation thread (New Chat)
GET  /api/chat/health      — Check if chatbot is configured
"""
import io
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer

from dependencies import get_current_user
from go.models.user import User
from api.schemas.chat_schemas import ChatMessageRequest, ChatMessageResponse
from go.services.chat import run_chat, clear_conversation, get_conversation_history, save_message
from config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


@router.get("/health")
async def chat_health():
    """Check if chatbot is properly configured."""
    has_key = bool(settings.OPENAI_API_KEY)
    return {
        "status": "ready" if has_key else "not_configured",
        "message": "Chatbot is ready" if has_key else "OPENAI_API_KEY not set in .env",
    }


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    req: ChatMessageRequest,
    token: str = Depends(oauth2_scheme),
    user: User = Depends(get_current_user),
):
    """
    Send a message to the AI chatbot.
    Server maintains conversation memory per user — client only sends new message.
    """
    try:
        patient_id = ""
        doctor_id = ""
        if user.role == "patient":
            from database import async_session
            async with async_session() as db:
                from go.models.patient import PatientModel
                patient = await PatientModel.get_by_user_id(db, user.id)
                if patient:
                    patient_id = str(patient.id)
        elif user.role == "doctor":
            from database import async_session
            async with async_session() as db:
                from go.models.doctor import DoctorModel
                doctor = await DoctorModel.get_by_user_id(db, user.id)
                if doctor:
                    doctor_id = str(doctor.id)

        uid = str(user.id)

        # Save user message to UI history (best-effort — don't block chat)
        try:
            await save_message(uid, "user", req.message)
        except Exception as e:
            logger.error(f"Failed to save user message to UI history: {e}")

        reply = await run_chat(
            message=req.message,
            token=token,
            role=user.role,
            user_id=uid,
            patient_id=patient_id,
            doctor_id=doctor_id,
            patient_context=req.patient_context or "",
        )

        # Save assistant reply to UI history (best-effort)
        try:
            await save_message(uid, "assistant", reply)
        except Exception as e:
            logger.error(f"Failed to save assistant reply to UI history: {e}")

        return ChatMessageResponse(
            reply=reply,
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat service error: {str(e)}")


@router.get("/history")
async def get_chat_history(
    user: User = Depends(get_current_user),
):
    """Retrieve the user's conversation history from server-side storage."""
    messages = await get_conversation_history(str(user.id))
    return {"messages": messages}


@router.post("/clear")
async def clear_chat(
    user: User = Depends(get_current_user),
):
    """Clear the user's conversation thread (New Chat)."""
    await clear_conversation(str(user.id))
    return {"status": "cleared"}


# ─── Speech-to-Text (Whisper ASR) ────────────────────────────

def _clear_proxy_env():
    """Remove proxy env vars that break httpx/openai (socks5h not supported)."""
    for v in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
              "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy"):
        os.environ.pop(v, None)


@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """
    Convert speech audio to text using OpenAI Whisper.
    Accepts audio files (wav, webm, mp3, m4a, ogg).
    Returns: {"text": "transcribed text"}
    """
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")

    _clear_proxy_env()
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

    try:
        from openai import OpenAI
        client = OpenAI()

        # Read the uploaded audio bytes
        audio_bytes = await audio.read()
        if len(audio_bytes) < 100:
            raise HTTPException(status_code=400, detail="Audio file is too small or empty")

        # Whisper needs a filename with extension for format detection
        filename = audio.filename or "audio.wav"

        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, audio_bytes),
            language="en",
        )
        text = transcript.text.strip()
        logger.info(f"Transcribed {len(audio_bytes)} bytes -> '{text[:80]}...'")
        return {"text": text}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transcription error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {type(e).__name__}: {e}")


# ─── Text-to-Speech (OpenAI TTS) ─────────────────────────────

@router.post("/tts")
async def text_to_speech(
    body: dict,
    user: User = Depends(get_current_user),
):
    """
    Convert text to speech using OpenAI TTS.
    Request body: {"text": "...", "voice": "alloy"} (voice is optional)
    Returns: audio/mpeg stream
    """
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")

    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")

    # Truncate very long texts (TTS has limits and it's meant for the chat reply)
    if len(text) > 4096:
        text = text[:4096]

    voice = body.get("voice", "alloy")  # alloy, echo, fable, onyx, nova, shimmer

    _clear_proxy_env()
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

    try:
        from openai import OpenAI
        client = OpenAI()

        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            response_format="mp3",
        )

        # Stream the audio bytes back
        audio_bytes = response.content
        logger.info(f"TTS generated {len(audio_bytes)} bytes for {len(text)} chars")
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=reply.mp3"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TTS failed: {type(e).__name__}: {e}")
