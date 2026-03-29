"""
Auth Adapter — abstract interface for OAuth providers.

To add a new provider (e.g., Microsoft, Apple):
  1. Subclass AuthAdapter
  2. Implement get_authorization_url() and exchange_code()
  3. Register it in get_auth_adapter()

The route layer only talks to the adapter interface — never directly to Google/Microsoft APIs.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass
class OAuthUserInfo:
    """Standardized user info returned by any OAuth provider."""
    email: str
    full_name: str
    picture_url: Optional[str] = None
    provider: str = "unknown"           # "google", "microsoft", "apple", etc.
    provider_user_id: Optional[str] = None  # Provider's unique user ID


class AuthAdapter(ABC):
    """Abstract base class for OAuth authentication providers."""

    @abstractmethod
    def get_authorization_url(self) -> str:
        """Return the URL to redirect the user to for OAuth consent."""
        ...

    @abstractmethod
    async def exchange_code(self, code: str) -> OAuthUserInfo:
        """
        Exchange an authorization code for user info.
        Raises ValueError on failure.
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name (e.g., 'Google', 'Microsoft')."""
        ...


class GoogleAuthAdapter(AuthAdapter):
    """Google OAuth2 adapter using Google's OpenID Connect flow."""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    @property
    def provider_name(self) -> str:
        return "Google"

    def get_authorization_url(self) -> str:
        import urllib.parse
        params = urllib.parse.urlencode({
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent",
        })
        return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"

    async def exchange_code(self, code: str) -> OAuthUserInfo:
        import httpx

        # Step 1: Exchange code for tokens
        try:
            async with httpx.AsyncClient() as client:
                token_resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "code": code,
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "redirect_uri": self._redirect_uri,
                        "grant_type": "authorization_code",
                    },
                    timeout=15,
                )
                if token_resp.status_code != 200:
                    logger.error("Google token exchange failed: %s", token_resp.text)
                    raise ValueError("Failed to exchange Google authorization code")
                google_tokens = token_resp.json()
        except httpx.HTTPError as e:
            logger.error("Google token request error: %s", e)
            raise ValueError("Could not connect to Google") from e

        # Step 2: Get user info
        try:
            async with httpx.AsyncClient() as client:
                userinfo_resp = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {google_tokens['access_token']}"},
                    timeout=10,
                )
                if userinfo_resp.status_code != 200:
                    raise ValueError("Failed to get Google user info")
                guser = userinfo_resp.json()
        except httpx.HTTPError as e:
            logger.error("Google userinfo error: %s", e)
            raise ValueError("Could not get user info from Google") from e

        email = guser.get("email", "").lower()
        if not email:
            raise ValueError("Google account has no email")

        return OAuthUserInfo(
            email=email,
            full_name=guser.get("name", email.split("@")[0]),
            picture_url=guser.get("picture"),
            provider="google",
            provider_user_id=guser.get("id"),
        )


@lru_cache()
def get_auth_adapter(provider: str = "google") -> AuthAdapter:
    """
    Factory — returns the configured adapter for the given provider.
    Cached so the same instance is reused across requests.
    """
    from config import get_settings
    settings = get_settings()

    if provider == "google":
        if not settings.GOOGLE_CLIENT_ID:
            raise RuntimeError("Google OAuth not configured — set GOOGLE_CLIENT_ID in .env")
        return GoogleAuthAdapter(
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
        )

    raise ValueError(f"Unknown auth provider: {provider}")
