"""
Seed ChromaDB with existing doctor_ratings reviews.
Run this ONCE after the database has ratings data.

Usage: python3 seed_rag.py
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from config import get_settings
settings = get_settings()
os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY


async def seed():
    from database import async_session
    from sqlalchemy import text
    from go.services.rag_service import embed_review

    async with async_session() as db:
        # Get all ratings with doctor names
        result = await db.execute(text("""
            SELECT dr.id, dr.appointment_id, dr.patient_id, dr.doctor_id,
                   dr.rating, dr.review, dr.sentiment_score, dr.created_at,
                   u.full_name as doctor_name
            FROM doctor_ratings dr
            JOIN doctors d ON dr.doctor_id = d.id
            JOIN users u ON d.user_id = u.id
            WHERE dr.review IS NOT NULL AND dr.review != ''
            ORDER BY dr.created_at
        """))
        rows = result.mappings().all()

        print(f"Found {len(rows)} reviews to embed")

        for row in rows:
            print(f"  Embedding: {row['doctor_name']} — {row['rating']}★ — {row['review'][:60]}...")
            embed_review(
                rating_id=str(row["id"]),
                doctor_id=str(row["doctor_id"]),
                patient_id=str(row["patient_id"]),
                appointment_id=str(row["appointment_id"]),
                rating=row["rating"],
                review_text=row["review"],
                doctor_name=row["doctor_name"],
                sentiment_score=float(row["sentiment_score"]) if row["sentiment_score"] else 0.0,
                created_at=row["created_at"].isoformat() if row["created_at"] else "",
            )

        print(f"\nDone! Embedded {len(rows)} reviews into ChromaDB.")
        print(f"ChromaDB path: {settings.CHROMA_PERSIST_DIRECTORY}")


if __name__ == "__main__":
    asyncio.run(seed())
