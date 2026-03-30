"""
DPMS v2 — Main Application Entry Point

Run:   uvicorn main:app --reload
Docs:  http://localhost:8000/docs
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import init_db, close_db
from go.services.mongo_chat_store import ensure_indexes as mongo_ensure_indexes, close_mongo
from api.routes.auth import router as auth_router
from api.routes.patient import router as patient_router
from api.routes.doctor import router as doctor_router
from api.routes.appointment import router as appointment_router
from api.routes.session_mgmt import router as session_mgmt_router
from api.routes.queue import router as queue_router
from api.routes.admin import router as admin_router
from api.routes.chat import router as chat_router
from api.routes.rating import router as rating_router


# ─── Lifespan: startup + shutdown events ─────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: connect to PostgreSQL (creates connection pool)
    Shutdown: close connection pool (releases DB connections)
    """
    await init_db()
    await mongo_ensure_indexes()
    yield
    await close_mongo()
    await close_db()


# ─── Create the FastAPI app ──────────────────────────────────
app = FastAPI(
    title="DPMS_v2",
    description="Doctor-Patient Management System — Online Booking with AI Chatbot",
    version="2.0.0",
    lifespan=lifespan,
)


# ─── CORS: allow frontend (Streamlit) to talk to backend ────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000", "http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health check ────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def health_check():
    return {"status": "healthy", "service": "DPMS_v2"}


# ─── Mount routes ────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])

app.include_router(patient_router, prefix="/api/patients", tags=["Patients"])

app.include_router(doctor_router, prefix="/api/doctors", tags=["Doctors"])

app.include_router(appointment_router, prefix="/api/appointments", tags=["Appointments"])
app.include_router(session_mgmt_router, prefix="/api/sessions", tags=["Session Management"])

app.include_router(queue_router, prefix="/api/queue", tags=["Queue"])

app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])

app.include_router(chat_router, prefix="/api/chat", tags=["Chat"])

app.include_router(rating_router, prefix="/api/ratings", tags=["Ratings"])
