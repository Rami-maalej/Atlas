"""MARK XL — typed IMAP mail client.

Pure, dependency-free (stdlib only) IMAP layer used by the Gmail-style
mail screen (``core.mail_overlay``). All network work happens here so the
UI stays thin and every parsing rule is unit-testable without a server.

Providers
---------
Presets for Gmail / Outlook / Yahoo / iCloud / Proton ship in
:data:`PROVIDERS`; a ``custom`` entry lets the user type any IMAP host.

Credentials
-----------
* Non-secret settings (provider, host, port, address) -> ``config/mail.json``
* App password                             -> ``config/.mail_creds.json`` (0600)
* Legacy fallback: ``email_user``/``email_pass`` in ``config/api_keys.json``
  (written by older Jarvis versions) is read when the new files are absent.

Example:
    >>> acct = load_account()
    >>> if acct:
    ...     with connect(acct) as conn:
    ...         msgs = fetch_messages(conn, "INBOX", limit=5)
"""

from __future__ import annotations

import imaplib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email import message_from_bytes, message_from_string
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
ACCOUNT_FILE = CONFIG_DIR / "mail.json"
SECRET_FILE = CONFIG_DIR / ".mail_creds.json"
LEGACY_KEYS_FILE = CONFIG_DIR / "api_keys.json"

#: provider id -> (display label, imap host, imap port)
PROVIDERS: dict[str, tuple[str, str, int]] = {
    "gmail": ("Gmail", "imap.gmail.com", 993),
    "outlook": ("Outlook / Hotmail", "outlook.office365.com", 993),
    "yahoo": ("Yahoo Mail", "imap.mail.yahoo.com", 993),
    "icloud": ("iCloud Mail", "imap.mail.me.com", 993),
    "proton": ("Proton Mail (bridge)", "127.0.0.1", 1143),
    "custom": ("Custom IMAP", "", 993),
}

#: IMAP search keys for the well-known folders (Gmail-compatible names).
DEFAULT_FOLDERS: tuple[str, ...] = (
    "INBOX",
    "Sent",
    "Drafts",
    "Junk",
    "Trash",
    "Archive",
)


class MailError(RuntimeError):
    """Raised for any IMAP or credential failure with a user-safe message."""


# ── Data model ──────────────────────────────────────────────────────────────
@dataclass(slots=True)
class MailAccount:
    """IMAP account configuration (password kept out of repr)."""

    email: str
    password: str = field(default="", repr=False)
    provider: str = "gmail"
    host: str = "imap.gmail.com"
    port: int = 993

    @property
    def label(self) -> str:
        """Human label for the account line in the UI."""
        return PROVIDERS.get(self.provider, (self.provider, "", 0))[0]


@dataclass(slots=True)
class MailFolder:
    """One IMAP folder with unread/total counters."""

    name: str
    unread: int = 0
    total: int = 0


@dataclass(slots=True)
class MailMessage:
    """One message as shown in the list and reading pane."""

    uid: str
    subject: str = "(no subject)"
    sender: str = ""
    sender_address: str = ""
    date: datetime | None = None
    date_text: str = ""
    preview: str = ""
    body: str = ""
    is_unread: bool = False
    is_starred: bool = False
    has_attachments: bool = False
    to: str = ""

    @property
    def display_sender(self) -> str:
        """Sender name, falling back to the raw address."""
        return self.sender or self.sender_address or "(unknown)"


# ── Pure parsing helpers (fully unit-tested) ────────────────────────────────
def decode_mime(value: str | None) -> str:
    """Decode an RFC 2047 encoded header (``=?utf-8?b?...?=``) to ``str``.

    Args:
        value: Raw header value, possibly containing encoded words.

    Returns:
        Decoded, whitespace-normalised text (empty string for ``None``).
    """
    if not value:
        return ""
    chunks: list[str] = []
    try:
        parts = decode_header(value)
    except (LookupError, ValueError):
        return value
    for text, charset in parts:
        if isinstance(text, bytes):
            for enc in (charset, "utf-8", "latin-1"):
                if not enc:
                    continue
                try:
                    chunks.append(text.decode(enc, errors="replace"))
                    break
                except (LookupError, UnicodeDecodeError):
                    continue
            else:
                chunks.append(text.decode("utf-8", errors="replace"))
        else:
            chunks.append(text)
    return re.sub(r"\s+", " ", "".join(chunks)).strip()


def parse_address(raw: str | None) -> tuple[str, str]:
    """Split a ``From``/``To`` header into ``(display name, address)``.

    Args:
        raw: Header value such as ``"Jane Doe <jane@example.com>"``.

    Returns:
        Tuple of display name and bare email address (either may be empty).
    """
    if not raw:
        return "", ""
    name, addr = parseaddr(decode_mime(raw))
    return decode_mime(name), (addr or "").strip()


def parse_date(raw: str | None) -> datetime | None:
    """Parse an RFC 2822 ``Date`` header into a naive ``datetime``.

    Args:
        raw: Raw date header, e.g. ``"Mon, 22 Sep 2025 10:03:11 +0200"``.

    Returns:
        Local naive datetime, or ``None`` when unparseable.
    """
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def format_date(dt: datetime | None, now: datetime | None = None) -> str:
    """Format a message date the way Gmail does in the list.

    Args:
        dt: Message timestamp (naive local time).
        now: Reference time; defaults to ``datetime.now()``.

    Returns:
        ``"14:03"`` today, ``"Yesterday"``, ``"22 Sep"`` this year,
        ``"22 Sep 2024"`` otherwise, or ``""`` for ``None``.
    """
    if dt is None:
        return ""
    now = now or datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    if dt.date() == (now - timedelta(days=1)).date():
        return "Yesterday"
    if dt.year == now.year:
        return dt.strftime("%d %b")
    return dt.strftime("%d %b %Y")


class _TextExtractor(HTMLParser):
    """Convert an HTML mail body into readable plain text."""

    _SKIP = {"script", "style", "head", "title"}
    _BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        """Return the flattened plain-text rendering."""
        joined = "".join(self._chunks)
        lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in joined.splitlines()]
        return "\n".join(ln for ln in lines if ln)


def html_to_text(html: str) -> str:
    """Render an HTML document as plain text.

    Args:
        html: Raw HTML body.

    Returns:
        Readable text with paragraph breaks preserved.
    """
    if not html:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    return parser.text()


def make_snippet(text: str, limit: int = 160) -> str:
    """Build a single-line preview of a body for the message list.

    Args:
        text: Body text (already plain).
        limit: Maximum characters before truncation.

    Returns:
        Whitespace-collapsed snippet, ellipsis-terminated when cut.
    """
    flat = re.sub(r"\s+", " ", text or "").strip()
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def extract_body(msg: Message) -> tuple[str, bool]:
    """Pull the readable body out of a parsed email message.

    Prefers ``text/plain``, falls back to ``text/html``.

    Args:
        msg: Parsed message.

    Returns:
        Tuple of ``(plain text body, has attachments)``.
    """
    has_attachments = False
    plain_parts: list[str] = []
    html_parts: list[str] = []
    parts: list[Message] = [msg] if not msg.is_multipart() else list(msg.walk())
    for part in parts:
        if part.get_content_disposition() == "attachment":
            has_attachments = True
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, (bytes, bytearray)):
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        (plain_parts if ctype == "text/plain" else html_parts).append(text)

    if plain_parts:
        body = "\n".join(plain_parts)
    elif html_parts:
        body = html_to_text("\n".join(html_parts))
    else:
        body = ""
    return body.strip(), has_attachments


# ── Credential storage ──────────────────────────────────────────────────────
def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_account() -> MailAccount | None:
    """Load the saved IMAP account.

    Returns:
        The configured :class:`MailAccount`, or ``None`` when nothing
        is configured yet.

    Raises:
        MailError: If configured files exist but are unreadable/invalid.
    """
    settings = _read_json(ACCOUNT_FILE)
    secrets = _read_json(SECRET_FILE)

    if not settings:
        # Legacy location: config/api_keys.json (email_user / email_pass)
        legacy = _read_json(LEGACY_KEYS_FILE)
        email_addr = str(legacy.get("email_user") or "").strip()
        password = str(legacy.get("email_pass") or "").strip()
        if not email_addr or not password:
            return None
        provider = _provider_for_host(str(legacy.get("imap_server") or "imap.gmail.com"))
        host = str(legacy.get("imap_server") or PROVIDERS[provider][1])
        port = int(legacy.get("imap_port") or 993)
        return MailAccount(
            email=email_addr, password=password, provider=provider, host=host, port=port
        )

    email_addr = str(settings.get("email") or "").strip()
    if not email_addr:
        raise MailError("Mail account is incomplete: missing address.")
    provider = str(settings.get("provider") or "gmail").strip().lower()
    if provider not in PROVIDERS:
        provider = "custom"
    host = str(settings.get("host") or PROVIDERS[provider][1]).strip()
    try:
        port = int(settings.get("port") or PROVIDERS[provider][2])
    except (TypeError, ValueError) as exc:
        raise MailError(f"Invalid IMAP port: {settings.get('port')!r}") from exc
    password = str(secrets.get("password") or "")
    return MailAccount(
        email=email_addr, password=password, provider=provider, host=host, port=port
    )


def save_account(account: MailAccount) -> None:
    """Persist an account; the password goes to a 0600 secrets file.

    Args:
        account: Account to store.

    Raises:
        MailError: If the config directory cannot be written.
    """
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ACCOUNT_FILE.write_text(
            json.dumps(
                {
                    "provider": account.provider,
                    "host": account.host,
                    "port": account.port,
                    "email": account.email,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        SECRET_FILE.write_text(
            json.dumps({"password": account.password}, indent=2), encoding="utf-8"
        )
        try:
            SECRET_FILE.chmod(0o600)
        except OSError:
            pass
    except OSError as exc:
        raise MailError(f"Could not save mail settings: {exc}") from exc


def delete_account() -> None:
    """Remove any stored mail account (both settings and secret)."""
    for path in (ACCOUNT_FILE, SECRET_FILE):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _provider_for_host(host: str) -> str:
    for pid, (_label, preset_host, _port) in PROVIDERS.items():
        if preset_host and preset_host == host:
            return pid
    return "custom"


# ── IMAP session helpers ────────────────────────────────────────────────────
@contextmanager
def connect(
    account: MailAccount, timeout: float = 20.0
) -> Iterator[imaplib.IMAP4_SSL]:
    """Open an authenticated IMAP session.

    Args:
        account: Credentials to log in with.
        timeout: Socket timeout in seconds.

    Yields:
        Authenticated, selected-less connection.

    Raises:
        MailError: On network failure or bad credentials.
    """
    if not account.password:
        raise MailError("No mail password saved — open Mail ▸ Settings and add it.")
    try:
        conn = imaplib.IMAP4_SSL(account.host, account.port, timeout=timeout)
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailError(f"Cannot reach {account.host}:{account.port} — {exc}") from exc
    try:
        conn.login(account.email, account.password)
    except imaplib.IMAP4.error as exc:
        try:
            conn.logout()
        except Exception:
            pass
        raise MailError(
            "Login failed — check the app password (Gmail: Google Account ▸ "
            "App passwords)."
        ) from exc
    try:
        yield conn
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _parse_flags_and_headers(raw: bytes, flags_blob: str) -> MailMessage:
    """Parse one FETCH response into a :class:`MailMessage` (headers only)."""
    msg = MailMessage(uid="")
    if flags_blob:
        upper = flags_blob.upper()
        msg.is_unread = "\\SEEN" not in upper
        msg.is_starred = "\\FLAGGED" in upper
    uid_match = re.search(r"UID\s+(\d+)", flags_blob)
    if uid_match:
        msg.uid = uid_match.group(1)
    headers = raw.decode("utf-8", errors="replace")
    parsed = message_from_string(headers)
    msg.subject = decode_mime(parsed.get("Subject")) or "(no subject)"
    name, addr = parse_address(parsed.get("From"))
    msg.sender = name
    msg.sender_address = addr
    msg.to = decode_mime(parsed.get("To"))
    msg.date = parse_date(parsed.get("Date"))
    msg.date_text = format_date(msg.date)
    return msg


def list_folders(conn: Any) -> list[MailFolder]:
    """List selectable folders with unread/total counters.

    Args:
        conn: Authenticated IMAP connection.

    Returns:
        Folder list (INBOX first), sorted by the server's order.
    """
    try:
        status, data = conn.list()
    except imaplib.IMAP4.error:
        return []
    if (status or "").upper() != "OK":
        return []

    names: list[str] = []
    for entry in data or []:
        if not entry:
            continue
        line = entry.decode("utf-8", errors="replace") if isinstance(entry, bytes) else str(entry)
        match = re.search(r'"([^"]*)"\s*"?([^"]+)$', line.strip())
        if match:
            names.append(match.group(2).strip())
        else:
            parts = line.split()
            names.append(parts[-1].strip('"') if parts else line)

    folders: list[MailFolder] = []
    seen: set[str] = set()
    ordered = ["INBOX"] + [n for n in names if n.upper() != "INBOX"]
    for name in ordered:
        if name in seen:
            continue
        seen.add(name)
        folders.append(MailFolder(name=name))
    for folder in folders:
        try:
            conn.select(folder.name)
            st, all_data = conn.search(None, "ALL")
            st2, un_data = conn.search(None, "UNSEEN")
            if (st or "").upper() == "OK" and all_data and all_data[0]:
                folder.total = len(all_data[0].split())
            if (st2 or "").upper() == "OK" and un_data and un_data[0]:
                folder.unread = len(un_data[0].split())
        except imaplib.IMAP4.error:
            continue
    try:
        conn.select("INBOX")
    except imaplib.IMAP4.error:
        pass
    return folders


def fetch_messages(
    conn: Any,
    folder: str = "INBOX",
    limit: int = 30,
    unread_only: bool = False,
    query: str = "",
) -> list[MailMessage]:
    """Fetch message headers (bodies stay lazy — see :func:`fetch_body`).

    Args:
        conn: Authenticated IMAP connection.
        folder: Folder to search in.
        limit: Maximum messages returned (newest first).
        unread_only: Restrict to unseen messages.
        query: Free-text search (subject/sender/body).

    Returns:
        Messages newest-first with flags, never bodies.

    Raises:
        MailError: If the folder cannot be selected.
    """
    try:
        status, _ = conn.select(folder, readonly=True)
    except imaplib.IMAP4.error as exc:
        raise MailError(f"Cannot open folder {folder!r}: {exc}") from exc
    if (status or "").upper() != "OK":
        raise MailError(f"Cannot open folder {folder!r}.")

    criteria: list[str] = []
    if unread_only:
        criteria.append("UNSEEN")
    if query:
        safe = query.replace('"', "").replace("\\", "")
        criteria.append(f'TEXT "{safe}"')
    search_key = " ".join(criteria) if criteria else "ALL"

    try:
        status, data = conn.uid("search", None, search_key)
    except imaplib.IMAP4.error:
        status, data = conn.uid("search", None, "ALL")
    if (status or "").upper() != "OK" or not data or not data[0]:
        return []
    uids = data[0].split()
    wanted = list(reversed(uids))[: max(limit * 3, limit)]

    header_fields = "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])"
    messages: list[MailMessage] = []
    for uid in wanted:
        if len(messages) >= limit:
            break
        try:
            st, fetched = conn.uid("fetch", uid, header_fields)
        except imaplib.IMAP4.error:
            continue
        if (st or "").upper() != "OK" or not fetched:
            continue
        meta = ""
        raw = b""
        for item in fetched:
            if isinstance(item, tuple) and len(item) == 2:
                meta_blob, body = item[0], item[1]
                meta = (
                    meta_blob.decode("utf-8", errors="replace")
                    if isinstance(meta_blob, bytes)
                    else str(meta_blob)
                )
                raw = body if isinstance(body, bytes) else bytes(body)
            elif isinstance(item, bytes) and not raw:
                meta = item.decode("utf-8", errors="replace")
        if not raw and not meta:
            continue
        parsed = _parse_flags_and_headers(raw, meta)
        if not parsed.uid:
            uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
            parsed.uid = uid_str
        messages.append(parsed)
    return messages


def fetch_body(conn: Any, uid: str, folder: str = "INBOX") -> MailMessage:
    """Fetch the full body of one message (marks it read).

    Args:
        conn: Authenticated IMAP connection.
        uid: Message UID.
        folder: Folder the UID lives in.

    Returns:
        The message with ``body`` (and attachment flag) filled in.

    Raises:
        MailError: If the message cannot be fetched.
    """
    try:
        conn.select(folder, readonly=False)
    except imaplib.IMAP4.error as exc:
        raise MailError(f"Cannot open folder {folder!r}: {exc}") from exc
    status, data = conn.uid("fetch", uid, "(FLAGS BODY.PEEK[])")
    if (status or "").upper() != "OK" or not data:
        raise MailError(f"Message {uid} not found in {folder!r}.")
    raw = b""
    meta = ""
    for item in data:
        if isinstance(item, tuple) and len(item) == 2:
            meta_blob, payload = item[0], item[1]
            meta = (
                meta_blob.decode("utf-8", errors="replace")
                if isinstance(meta_blob, bytes)
                else str(meta_blob)
            )
            raw = payload if isinstance(payload, bytes) else bytes(payload)
        elif isinstance(item, bytes):
            text = item.decode("utf-8", errors="replace")
            if "UID" in text or "FLAGS" in text:
                meta = text
    if not raw:
        raise MailError(f"Message {uid} returned no content.")
    parsed = _parse_flags_and_headers(raw, meta)
    parsed.uid = uid
    msg_obj = message_from_bytes(raw)
    parsed.body, parsed.has_attachments = extract_body(msg_obj)
    parsed.preview = make_snippet(parsed.body)
    return parsed


def set_seen(conn: Any, uid: str, seen: bool = True, folder: str = "INBOX") -> None:
    """Mark a message read/unread.

    Args:
        conn: Authenticated connection (must not be read-only).
        uid: Message UID.
        seen: ``True`` marks read, ``False`` marks unread.
        folder: Folder containing the message.
    """
    action = "+FLAGS" if seen else "-FLAGS"
    try:
        conn.select(folder)
        conn.uid("STORE", uid, action, "(\\Seen)")
    except imaplib.IMAP4.error as exc:
        raise MailError(f"Could not update read state: {exc}") from exc


def set_starred(conn: Any, uid: str, starred: bool = True, folder: str = "INBOX") -> None:
    """Star/unstar a message.

    Args:
        conn: Authenticated connection.
        uid: Message UID.
        starred: ``True`` stars, ``False`` unstars.
        folder: Folder containing the message.
    """
    action = "+FLAGS.SILENT" if starred else "-FLAGS.SILENT"
    try:
        conn.select(folder)
        conn.uid("STORE", uid, action, "(\\Flagged)")
    except imaplib.IMAP4.error as exc:
        raise MailError(f"Could not update star: {exc}") from exc


def mark_folder_read(conn: Any, folder: str = "INBOX") -> int:
    """Mark every message in a folder as read.

    Args:
        conn: Authenticated connection.
        folder: Folder to process.

    Returns:
        Number of messages updated.
    """
    try:
        conn.select(folder)
        status, data = conn.search(None, "UNSEEN")
    except imaplib.IMAP4.error:
        return 0
    if (status or "").upper() != "OK" or not data or not data[0]:
        return 0
    uids = data[0].split()
    count = 0
    for uid in uids:
        try:
            conn.uid("STORE", uid, "+FLAGS.SILENT", "(\\Seen)")
            count += 1
        except imaplib.IMAP4.error:
            continue
    return count


def webmail_url(account: MailAccount) -> str:
    """Return the webmail URL used by the "Open in browser" button.

    Args:
        account: Configured account.

    Returns:
        Provider webmail URL (Gmail inbox by default).
    """
    return {
        "gmail": "https://mail.google.com/mail/u/0/#inbox",
        "outlook": "https://outlook.live.com/mail/0/inbox",
        "yahoo": "https://mail.yahoo.com",
        "icloud": "https://www.icloud.com/mail",
        "proton": "https://mail.proton.me",
    }.get(account.provider, "https://mail.google.com/mail/u/0/#inbox")
