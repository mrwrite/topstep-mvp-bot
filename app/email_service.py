from __future__ import annotations

import requests

from app import database
from app.observability import log_event


class EmailDeliveryError(RuntimeError):
    pass


class ResendEmailService:
    endpoint = "https://api.resend.com/emails"

    def send_email(self, *, to_email: str, subject: str, html: str, text: str) -> dict:
        config = database.APP_CONFIG
        if not config.resend_api_key:
            log_event(
                "email",
                "email_delivery_skipped",
                provider="resend",
                to_email=to_email,
                subject=subject,
                reason="RESEND_API_KEY not configured",
            )
            return {"status": "skipped", "provider": "resend"}

        response = requests.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {config.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": config.resend_from_email,
                "to": [to_email],
                "subject": subject,
                "html": html,
                "text": text,
            },
            timeout=10,
        )
        if response.status_code >= 400:
            raise EmailDeliveryError(f"Resend email delivery failed with status {response.status_code}.")
        return {"status": "sent", "provider": "resend", "response": response.json() if response.content else {}}

    def send_verification(self, *, to_email: str, token: str) -> dict:
        url = f"{database.APP_CONFIG.frontend_url}/verify-email?token={token}"
        return self.send_email(
            to_email=to_email,
            subject="Verify your paper beta account",
            html=f"<p>Verify your email to continue setting up paper trading.</p><p><a href=\"{url}\">Verify email</a></p>",
            text=f"Verify your email to continue setting up paper trading: {url}",
        )

    def send_password_reset(self, *, to_email: str, token: str) -> dict:
        url = f"{database.APP_CONFIG.frontend_url}/reset-password?token={token}"
        return self.send_email(
            to_email=to_email,
            subject="Reset your paper beta password",
            html=f"<p>Use this link to reset your password.</p><p><a href=\"{url}\">Reset password</a></p>",
            text=f"Use this link to reset your password: {url}",
        )


email_service = ResendEmailService()
