"""Read-only Gmail tools exposed to the LLM through the tool dispatcher."""

from __future__ import annotations

import logging
from typing import Any

from core import gmail_store
from core.google_service import GmailClient, GoogleAccountManager, GoogleServiceError

logger = logging.getLogger("google_tools")


def _accounts(account: str | None) -> list[str]:
    manager = GoogleAccountManager()
    if account:
        return [account.lower()]
    return [a.email for a in manager.list_accounts() if not a.needs_reauth]


def search_emails(
    query: str, account: str | None = None, limit: int = 20
) -> str:
    """Search cached email across one or all connected Google accounts."""
    accounts = _accounts(account)
    if not accounts:
        return "No Google accounts are connected."
    rows: list[dict[str, Any]] = []
    for email in accounts:
        for row in gmail_store.search(query, account=email, limit=limit):
            rows.append({**row, "account": email})
    rows.sort(key=lambda r: r.get("date", ""), reverse=True)
    if not rows:
        return f"No emails found for '{query}'."
    lines = [f"Found {len(rows)} email(s) for '{query}':"]
    for row in rows[:limit]:
        lines.append(
            f"  [{row['account']}] {row.get('date', '')[:16]} — "
            f"{row.get('sender', '')}: {row.get('subject', '')}"
        )
    return "\n".join(lines)


def get_email(message_id: str, account: str | None = None) -> str:
    """Return one message's headers and plain-text body from cache or Gmail."""
    accounts = _accounts(account)
    for email in accounts:
        row = gmail_store.get_message(email, message_id)
        if row:
            body = row.get("body_text", "").strip()
            return (
                f"From: {row.get('sender', '')}\n"
                f"To: {row.get('recipient', '')}\n"
                f"Subject: {row.get('subject', '')}\n"
                f"Date: {row.get('date', '')}\n"
                f"Account: {email}\n\n{body[:6000]}"
            )
    target = account or (accounts[0] if accounts else "")
    if not target:
        return "No Google account is connected."
    try:
        message = GmailClient(target).get_message(message_id)
        body = message.get("body_text", "").strip()
        return f"Subject: {message.get('subject', '')}\n\n{body[:6000]}"
    except GoogleServiceError as e:
        return str(e)


def list_recent_emails(account: str | None = None, limit: int = 20) -> str:
    """List the most recent cached emails across one or all accounts."""
    accounts = _accounts(account)
    if not accounts:
        return "No Google accounts are connected."
    rows: list[dict[str, Any]] = []
    for email in accounts:
        for row in gmail_store.list_recent(account=email, limit=limit):
            rows.append({**row, "account": email})
    rows.sort(key=lambda r: r.get("date", ""), reverse=True)
    if not rows:
        return "No emails cached yet — connect an account and sync first."
    lines = [f"Recent emails ({len(rows)}):"]
    for row in rows[:limit]:
        lines.append(
            f"  [{row['account']}] {row.get('date', '')[:16]} — "
            f"{row.get('sender', '')}: {row.get('subject', '')}"
        )
    return "\n".join(lines)


def summarize_unread(account: str | None = None, limit: int = 20) -> str:
    """Build a short read-only digest of unread cached messages."""
    accounts = _accounts(account)
    unread: list[dict[str, Any]] = []
    for email in accounts:
        for row in gmail_store.list_recent(account=email, limit=limit * 3):
            if "UNREAD" in (row.get("labels") or []):
                unread.append(row)
    if not unread:
        return "No unread emails found in the local cache."
    lines = [f"You have {len(unread)} unread email(s):"]
    for row in unread[:limit]:
        lines.append(f"  • {row.get('sender', '')}: {row.get('subject', '')}")
    return "\n".join(lines)
