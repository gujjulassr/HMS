"""
Chat Schemas — Pydantic models for the AI chatbot.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ChatMessageRequest(BaseModel):
    """Send a message to the AI chatbot. Server maintains conversation memory."""
    message: str = Field(min_length=1, max_length=2000, description="User's message")
    patient_context: Optional[str] = Field(
        None,
        description="Pre-filled patient form context (only sent on first message)",
    )


class ChatMessageResponse(BaseModel):
    """AI chatbot response."""
    reply: str
    timestamp: str
