"""
Chat Routes — AI Chatbot API endpoints.

POST /api/chat/message  — Send message to AI chatbot (any authenticated user)
POST /api/chat/clear    — Clear conversation thread (New Chat)
GET  /api/chat/health   — Check if chatbot is configured
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from dependencies import get_current_user
from go.models.user import User
from api.schemas.chat_schemas import ChatMessageRequest, ChatMessageResponse
from go.services.chat_agent import run_chat, clear_conversation
from config import get_settings
from datetime import datetime

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
        if user.role == "patient":
            from database import async_session
            async with async_session() as db:
                from go.models.patient import PatientModel
                patient = await PatientModel.get_by_user_id(db, user.id)
                if patient:
                    patient_id = str(patient.id)

        reply = await run_chat(
            message=req.message,
            token=token,
            role=user.role,
            user_id=str(user.id),
            patient_id=patient_id,
            patient_context=req.patient_context or "",
        )

        return ChatMessageResponse(
            reply=reply,
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat service error: {str(e)}")


@router.post("/clear")
async def clear_chat(
    user: User = Depends(get_current_user),
):
    """Clear the user's conversation thread (New Chat)."""
    await clear_conversation(str(user.id))
    return {"status": "cleared"}
