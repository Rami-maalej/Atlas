"""Google account management and Gmail access for Jarvis (read-only)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from core import gmail_store, google_auth
from core.google_auth import AccountInfo

logger = logging.getLogger("google_service")

SYNC_DAYS_KEY = "gmail_sync_days"


class GoogleServiceError(RuntimeError):
    """Raised when Google services cannot be used."""


def _config() -> dict[str, Any]:
    try:
        from memory.config_manager import load_config

        return load_config()
    except Exception:
        return {}


class GoogleAccountManager:
    """Manage multiple independently-authorized Google accounts."""

    def add_account(self, credentials_file: str | Path | None = None) -> AccountInfo:
        """Run one OAuth consent flow and store the resulting account."""
        result = google_auth.run_oauth(credentials_file)
        userinfo = result["userinfo"]
        email = str(userinfo["email"]).lower()
        google_auth.store_token(email, result["token"])
        account = google_auth.add_account_record(userinfo)
        logger.info("Connected Google account %s", email)
        return account

    def remove_account(self, email: str) -> bool:
        """Remove tokens and metadata for one account."""
        google_auth.delete_token(email)
        google_auth.remove_account_record(email)
        logger.info("Removed Google account %s", email)
        return True

    def list_accounts(self) -> list[AccountInfo]:
        """Return non-secret metadata for every connected account."""
        return google_auth.list_account_records()

    def get_credentials(self, email: str) -> Any:
        """Return valid credentials, refreshing them when expired."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        token = google_auth.load_token(email)
        if not token:
            google_auth.mark_needs_reauth(email)
            raise GoogleServiceError(f"No stored credentials for {email}")

        try:
            creds = Credentials(
                token=token.get("token"),
                refresh_token=token.get("refresh_token"),
                token_uri=token.get("token_uri"),
                client_id=token.get("client_id"),
                client_secret=token.get("client_secret"),
                scopes=token.get("scopes"),
                expiry=(
                    datetime.fromisoformat(token["expiry"])
                    if token.get("expiry") else None
                ),
            )
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token["token"] = creds.token
                token["refresh_token"] = creds.refresh_token or token.get("refresh_token")
                token["expiry"] = creds.expiry.isoformat() if creds.expiry else ""
                google_auth.store_token(email, token)
        except Exception as e:
            google_auth.mark_needs_reauth(email)
            logger.warning("Token refresh failed for %s: %s", email, type(e).__name__)
            raise GoogleServiceError(f"Re-authorization required for {email}") from e
        return creds


class GmailClient:
    """Read-only Gmail client backed by the local SQLite cache."""

    def __init__(self, email: str, manager: GoogleAccountManager | None = None):
        self.email = email.lower()
        self.manager = manager or GoogleAccountManager()

    def _service(self) -> Any:
        from googleapiclient.discovery import build

        creds = self.manager.get_credentials(self.email)
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def list_messages(
        self, query: str = "", max_results: int = 25, page_token: str | None = None
    ) -> dict[str, Any]:
        """Call Gmail users.messages.list with retry/backoff."""
        service = self._service()
        kwargs: dict[str, Any] = {
            "userId": "me", "maxResults": min(max(1, max_results), 500)
        }
        if query:
            kwargs["q"] = query
        if page_token:
            kwargs["pageToken"] = page_token
        return gmail_store.with_backoff(lambda: service.users().messages().list(**kwargs).execute())

    def get_message(self, message_id: str) -> dict[str, Any]:
        """Fetch, parse and cache one message by id."""
        cached = gmail_store.get_message(self.email, message_id)
        if cached:
            return cached
        service = self._service()
        raw = gmail_store.with_backoff(
            lambda: service.users().messages().get(
                userId="me", id=message_id, format="full"
            ).execute()
        )
        parsed = gmail_store.parse_message(raw)
        gmail_store.upsert_message(self.email, parsed)
        return gmail_store.get_message(self.email, message_id) or parsed

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search the local cache using Gmail-like terms."""
        return gmail_store.search(query, account=self.email, limit=limit)

    def _iter_remote(self, query: str, batch_size: int = 100) -> Iterator[dict[str, Any]]:
        token = None
        while True:
            page = self.list_messages(query, max_results=batch_size, page_token=token)
            yield from page.get("messages", [])
            token = page.get("nextPageToken")
            if not token:
                break

    def sync(self, days: int | None = None, incremental: bool = True) -> int:
        """Initial (last N days) or incremental (historyId) sync into cache."""
        history_id, _ = gmail_store.get_sync_state(self.email)
        if incremental and history_id:
            return self._sync_history(history_id)
        days = int(days or _config().get(SYNC_DAYS_KEY, 30) or 30)
        after = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y/%m/%d")
        query = f"after:{after}"
        count = 0
        for ref in self._iter_remote(query):
            self.get_message(str(ref["id"]))
            count += 1
        gmail_store.set_sync_state(self.email, self._profile_history_id())
        google_auth.set_last_sync(self.email, datetime.now(UTC).isoformat())
        logger.info("Initial sync for %s imported %d messages", self.email, count)
        return count

    def _profile_history_id(self) -> str:
        """Get the mailbox's current historyId to seed incremental sync."""
        try:
            profile = gmail_store.with_backoff(
                lambda: self._service().users().getProfile(userId="me").execute()
            )
            return str(profile.get("historyId", ""))
        except Exception as e:
            logger.debug("Could not read profile historyId: %s", e)
            return ""

    def _sync_history(self, history_id: str) -> int:
        service = self._service()
        token = None
        count = 0
        cursor = history_id
        try:
            while True:
                kwargs = {
                    "userId": "me",
                    "startHistoryId": cursor,
                    "historyTypes": ["messageAdded", "messageDeleted"],
                }
                if token:
                    kwargs["pageToken"] = token
                history = gmail_store.with_backoff(
                    lambda: service.users().history().list(**kwargs).execute()
                )
                for item in history.get("history", []):
                    for added in item.get("messagesAdded", []):
                        message = added.get("message") or {}
                        if message.get("id"):
                            self.get_message(str(message["id"]))
                            count += 1
                    for removed in item.get("messagesDeleted", []):
                        message = removed.get("message") or {}
                        if message.get("id"):
                            gmail_store.delete_message(self.email, str(message["id"]))
                cursor = str(history.get("historyId") or cursor)
                token = history.get("nextPageToken")
                if not token:
                    break
        except Exception as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            if status == 404:
                logger.info("History expired for %s; falling back to full sync", self.email)
                return self.sync(incremental=False)
            raise
        gmail_store.set_sync_state(self.email, cursor)
        google_auth.set_last_sync(self.email, datetime.now(UTC).isoformat())
        return count
