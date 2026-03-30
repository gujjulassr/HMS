"""
Rating Routes — Doctor feedback/review endpoints.

POST /api/ratings              — Submit a rating (patient, after completed appointment)
GET  /api/ratings/doctor/{id}  — Get ratings for a doctor
GET  /api/ratings/doctor/{id}/stats  — Get avg rating + sentiment stats
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user
from go.models.user import User
from lo.models.doctor_rating import RatingModel
from lo.models.appointment import AppointmentModel
from go.models.doctor import DoctorModel
from go.models.session import SessionModel

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────

class SubmitRatingRequest(BaseModel):
    appointment_id: str = Field(description="Completed appointment to rate")
    rating: int = Field(ge=1, le=5, description="1-5 star rating")
    review: Optional[str] = Field(None, max_length=2000, description="Optional text review")


class RatingResponse(BaseModel):
    id: str
    appointment_id: str
    patient_id: str
    doctor_id: str
    rating: int
    review: Optional[str]
    sentiment_score: Optional[float]
    created_at: str


class RatingStatsResponse(BaseModel):
    doctor_id: str
    avg_rating: float
    total_ratings: int
    avg_sentiment: Optional[float] = None


# ─── Submit Rating ────────────────────────────────────────────

@router.post("/", response_model=RatingResponse)
async def submit_rating(
    req: SubmitRatingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a rating for a completed appointment. Patients only."""
    if user.role not in ("patient", "admin"):
        raise HTTPException(status_code=403, detail="Only patients can submit ratings")

    # Verify appointment exists and is completed
    appt = await AppointmentModel.get_by_id(db, UUID(req.appointment_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != "completed":
        raise HTTPException(status_code=400, detail="Can only rate completed appointments")

    # Check if already rated
    existing = await RatingModel.get_by_appointment(db, UUID(req.appointment_id))
    if existing:
        raise HTTPException(status_code=409, detail="This appointment has already been rated")

    # Verify the patient owns this appointment (unless admin)
    if user.role == "patient":
        from go.models.patient import PatientModel
        patient = await PatientModel.get_by_user_id(db, user.id)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient profile not found")
        if appt.patient_id != patient.id and appt.booked_by_patient_id != patient.id:
            raise HTTPException(status_code=403, detail="You can only rate your own appointments")
        patient_id = patient.id
    else:
        patient_id = appt.patient_id

    # Get doctor_id from the session (appointments link to sessions, sessions link to doctors)
    session_obj = await SessionModel.get_by_id(db, appt.session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found for this appointment")
    doctor_id_val = session_obj.doctor_id

    # Compute sentiment if review text provided
    sentiment_score = None
    if req.review and req.review.strip():
        from go.services.rag_service import compute_sentiment
        sentiment_score = compute_sentiment(req.review)

    # Save to PostgreSQL
    rating_obj = await RatingModel.create(
        db=db,
        appointment_id=UUID(req.appointment_id),
        patient_id=patient_id,
        doctor_id=doctor_id_val,
        rating=req.rating,
        review=req.review,
        sentiment_score=sentiment_score,
    )
    await db.commit()

    # Embed in ChromaDB for RAG (non-blocking — don't fail the request if this errors)
    if req.review and req.review.strip():
        try:
            # Get doctor name for richer embedding
            doctor_name = ""
            doctor = await DoctorModel.get_by_id(db, doctor_id_val)
            if doctor:
                from go.models.user import UserModel
                doc_user = await UserModel.get_by_id(db, doctor.user_id)
                doctor_name = doc_user.full_name if doc_user else ""

            from go.services.rag_service import embed_review
            embed_review(
                rating_id=str(rating_obj.id),
                doctor_id=str(doctor_id_val),
                patient_id=str(rating_obj.patient_id),
                appointment_id=str(rating_obj.appointment_id),
                rating=req.rating,
                review_text=req.review,
                doctor_name=doctor_name,
                sentiment_score=float(sentiment_score) if sentiment_score else 0.0,
                created_at=rating_obj.created_at.isoformat(),
            )
        except Exception as e:
            logger.error(f"[RAG] Failed to embed review (non-fatal): {e}", exc_info=True)

    return RatingResponse(
        id=str(rating_obj.id),
        appointment_id=str(rating_obj.appointment_id),
        patient_id=str(rating_obj.patient_id),
        doctor_id=str(rating_obj.doctor_id),
        rating=rating_obj.rating,
        review=rating_obj.review,
        sentiment_score=float(rating_obj.sentiment_score) if rating_obj.sentiment_score else None,
        created_at=rating_obj.created_at.isoformat(),
    )


# ─── Get Ratings for a Doctor ────────────────────────────────

@router.get("/doctor/{doctor_id}", response_model=list[RatingResponse])
async def get_doctor_ratings(
    doctor_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get all ratings for a doctor. Accessible to all authenticated users."""
    ratings = await RatingModel.get_by_doctor(db, UUID(doctor_id), limit=limit, offset=offset)
    return [
        RatingResponse(
            id=str(r.id),
            appointment_id=str(r.appointment_id),
            patient_id=str(r.patient_id),
            doctor_id=str(r.doctor_id),
            rating=r.rating,
            review=r.review,
            sentiment_score=float(r.sentiment_score) if r.sentiment_score else None,
            created_at=r.created_at.isoformat(),
        )
        for r in ratings
    ]


# ─── Get Rating Stats ────────────────────────────────────────

@router.get("/doctor/{doctor_id}/stats", response_model=RatingStatsResponse)
async def get_doctor_rating_stats(
    doctor_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get average rating and total count for a doctor."""
    stats = await RatingModel.get_avg_rating(db, UUID(doctor_id))

    # Also get sentiment from ChromaDB if available
    avg_sentiment = None
    try:
        from go.services.rag_service import get_review_stats
        rag_stats = get_review_stats(doctor_id)
        if rag_stats["total_reviews"] > 0:
            avg_sentiment = rag_stats["avg_sentiment"]
    except Exception:
        pass

    return RatingStatsResponse(
        doctor_id=doctor_id,
        avg_rating=stats["avg_rating"],
        total_ratings=stats["total_ratings"],
        avg_sentiment=avg_sentiment,
    )
