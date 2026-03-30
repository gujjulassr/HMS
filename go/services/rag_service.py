"""
RAG Service — Embedding + Retrieval for Doctor Feedback/Ratings
================================================================
Uses ChromaDB for vector storage and OpenAI embeddings.

Flow:
  1. Patient submits review → embed_review() stores vector in ChromaDB
  2. Anyone asks about feedback → search_reviews() finds semantically similar reviews
  3. AI agent uses results to summarize patient feedback naturally

ChromaDB collection: "doctor_reviews"
  - document: the review text
  - metadata: doctor_id, patient_id, appointment_id, rating, sentiment_score, created_at
  - id: doctor_rating UUID (same as PostgreSQL primary key)
"""

import logging
from typing import Optional
from uuid import UUID

import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import OpenAI

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ─── ChromaDB Client (persistent, on-disk) ───────────────────
_chroma_client: Optional[chromadb.ClientAPI] = None
_COLLECTION_NAME = "doctor_reviews"


def _get_chroma() -> chromadb.ClientAPI:
    """Lazy-init ChromaDB persistent client."""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIRECTORY,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        logger.info(f"[RAG] ChromaDB initialized at {settings.CHROMA_PERSIST_DIRECTORY}")
    return _chroma_client


def _get_collection() -> chromadb.Collection:
    """Get or create the doctor_reviews collection."""
    client = _get_chroma()
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},  # cosine similarity
    )


# ─── OpenAI Embeddings ───────────────────────────────────────

def _get_embedding(text: str) -> list[float]:
    """Generate embedding vector for text using OpenAI."""
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.embeddings.create(
        model=settings.OPENAI_EMBEDDING_MODEL,  # text-embedding-3-small
        input=text,
    )
    return response.data[0].embedding


# ─── Sentiment Analysis ──────────────────────────────────────

def compute_sentiment(review_text: str) -> float:
    """Use OpenAI to compute sentiment score (-1.0 to 1.0) for a review."""
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "You are a sentiment analyzer. Given a hospital review, "
                    "return ONLY a number between -1.0 (very negative) and 1.0 (very positive). "
                    "No explanation, just the number."
                )},
                {"role": "user", "content": review_text},
            ],
            max_tokens=10,
            temperature=0,
        )
        score_str = response.choices[0].message.content.strip()
        score = float(score_str)
        return max(-1.0, min(1.0, score))  # clamp
    except Exception as e:
        logger.warning(f"[RAG] Sentiment analysis failed: {e}")
        return 0.0  # neutral fallback


# ─── Embed + Store ────────────────────────────────────────────

def embed_review(
    rating_id: str,
    doctor_id: str,
    patient_id: str,
    appointment_id: str,
    rating: int,
    review_text: str,
    doctor_name: str = "",
    sentiment_score: float = 0.0,
    created_at: str = "",
) -> None:
    """Embed a review and store it in ChromaDB.

    Called when a patient submits a rating with review text.
    """
    if not review_text or not review_text.strip():
        logger.info(f"[RAG] Skipping embed for rating {rating_id} — no review text")
        return

    try:
        # Build a rich document for embedding (includes context for better retrieval)
        doc = f"Doctor: {doctor_name}. Rating: {rating}/5. Review: {review_text}"

        embedding = _get_embedding(doc)

        collection = _get_collection()
        collection.upsert(
            ids=[rating_id],
            embeddings=[embedding],
            documents=[review_text],  # store raw review as the document
            metadatas=[{
                "doctor_id": doctor_id,
                "patient_id": patient_id,
                "appointment_id": appointment_id,
                "rating": rating,
                "sentiment_score": sentiment_score,
                "doctor_name": doctor_name,
                "created_at": created_at,
            }],
        )
        logger.info(f"[RAG] Embedded review {rating_id} for doctor {doctor_name} ({doctor_id})")
    except Exception as e:
        logger.error(f"[RAG] Failed to embed review {rating_id}: {e}", exc_info=True)


# ─── Search / Retrieve ───────────────────────────────────────

def search_reviews(
    query: str,
    doctor_id: str = "",
    n_results: int = 10,
    min_rating: int = 0,
) -> list[dict]:
    """Search reviews by semantic similarity.

    Args:
        query: Natural language query (e.g., "complaints about wait times")
        doctor_id: Optional — filter to a specific doctor
        n_results: Max results to return
        min_rating: Optional — only include reviews with rating >= this value

    Returns:
        List of {review, rating, doctor_id, doctor_name, sentiment_score, distance}
    """
    try:
        embedding = _get_embedding(query)
        collection = _get_collection()

        # Build where filter
        where_filter = None
        if doctor_id:
            where_filter = {"doctor_id": doctor_id}

        results = collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        if not results or not results["ids"] or not results["ids"][0]:
            return []

        reviews = []
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            rating_val = meta.get("rating", 0)

            # Apply min_rating filter (ChromaDB where doesn't support >= on ints well)
            if min_rating and rating_val < min_rating:
                continue

            reviews.append({
                "review": results["documents"][0][i],
                "rating": rating_val,
                "doctor_id": meta.get("doctor_id", ""),
                "doctor_name": meta.get("doctor_name", ""),
                "sentiment_score": meta.get("sentiment_score", 0.0),
                "created_at": meta.get("created_at", ""),
                "distance": results["distances"][0][i] if results.get("distances") else None,
            })

        return reviews
    except Exception as e:
        logger.error(f"[RAG] Search failed: {e}", exc_info=True)
        return []


def get_review_stats(doctor_id: str) -> dict:
    """Get aggregated review stats from ChromaDB for a doctor."""
    try:
        collection = _get_collection()
        results = collection.get(
            where={"doctor_id": doctor_id},
            include=["metadatas"],
        )

        if not results or not results["ids"]:
            return {"total_reviews": 0, "avg_rating": 0, "avg_sentiment": 0}

        ratings = [m.get("rating", 0) for m in results["metadatas"]]
        sentiments = [m.get("sentiment_score", 0) for m in results["metadatas"]]

        return {
            "total_reviews": len(ratings),
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else 0,
            "avg_sentiment": round(sum(sentiments) / len(sentiments), 2) if sentiments else 0,
        }
    except Exception as e:
        logger.error(f"[RAG] Stats failed: {e}", exc_info=True)
        return {"total_reviews": 0, "avg_rating": 0, "avg_sentiment": 0}
