"""
Adapters — pluggable interfaces for external services.

Auth adapters:   Google OAuth, (future: Microsoft, Apple, SAML)
Email adapters:  Gmail SMTP, (future: SendGrid, AWS SES, Twilio SendGrid)
"""
from go.adapters.auth_adapter import AuthAdapter, GoogleAuthAdapter, get_auth_adapter
from go.adapters.email_adapter import EmailAdapter, GmailEmailAdapter, get_email_adapter

__all__ = [
    "AuthAdapter", "GoogleAuthAdapter", "get_auth_adapter",
    "EmailAdapter", "GmailEmailAdapter", "get_email_adapter",
]
