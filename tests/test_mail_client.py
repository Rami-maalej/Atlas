"""Tests for core.mail_client — parsing, config, and IMAP flows (offline)."""

from __future__ import annotations

import json
from datetime import datetime
from email.message import EmailMessage

import pytest

from core import mail_client as mc


# ── decode_mime ─────────────────────────────────────────────────────────────
def test_decode_mime_plain_passthrough() -> None:
    assert mc.decode_mime("Hello world") == "Hello world"


def test_decode_mime_encoded_word() -> None:
    assert mc.decode_mime("=?utf-8?b?SGVsbG8gV29ybGQ=?=") == "Hello World"


def test_decode_mime_none_and_empty() -> None:
    assert mc.decode_mime(None) == ""
    assert mc.decode_mime("") == ""


def test_decode_mime_collapses_whitespace() -> None:
    assert mc.decode_mime("  spaced   out  ") == "spaced out"


# ── parse_address ───────────────────────────────────────────────────────────
def test_parse_address_full() -> None:
    name, addr = mc.parse_address("Jane Doe <jane@example.com>")
    assert name == "Jane Doe"
    assert addr == "jane@example.com"


def test_parse_address_bare() -> None:
    name, addr = mc.parse_address("bob@example.org")
    assert addr == "bob@example.org"
    assert name == ""


def test_parse_address_empty() -> None:
    assert mc.parse_address("") == ("", "")
    assert mc.parse_address(None) == ("", "")


# ── parse_date / format_date ────────────────────────────────────────────────
def test_parse_date_valid() -> None:
    dt = mc.parse_date("Mon, 22 Sep 2025 10:03:11 +0200")
    assert dt is not None
    assert dt.year == 2025


def test_parse_date_invalid_returns_none() -> None:
    assert mc.parse_date("not a date") is None
    assert mc.parse_date(None) is None


NOW = datetime(2025, 9, 22, 15, 0, 0)


def test_format_date_today() -> None:
    assert mc.format_date(datetime(2025, 9, 22, 14, 3), NOW) == "14:03"


def test_format_date_yesterday() -> None:
    assert mc.format_date(datetime(2025, 9, 21, 9, 30), NOW) == "Yesterday"


def test_format_date_this_year() -> None:
    assert mc.format_date(datetime(2025, 3, 4, 9, 30), NOW) == "04 Mar"


def test_format_date_other_year() -> None:
    assert mc.format_date(datetime(2024, 3, 4, 9, 30), NOW) == "04 Mar 2024"


def test_format_date_none() -> None:
    assert mc.format_date(None, NOW) == ""


# ── html_to_text / make_snippet ─────────────────────────────────────────────
def test_html_to_text_paragraphs() -> None:
    html = "<html><style>p{color:red}</style><body><p>Hi there</p><p>Second</p></body></html>"
    text = mc.html_to_text(html)
    assert "Hi there" in text
    assert "Second" in text
    assert "<p>" not in text
    assert "color:red" not in text


def test_html_to_text_empty() -> None:
    assert mc.html_to_text("") == ""


def test_make_snippet_short() -> None:
    assert mc.make_snippet("hello world") == "hello world"


def test_make_snippet_truncates_at_word() -> None:
    long = "word " * 80
    snip = mc.make_snippet(long, limit=50)
    assert len(snip) <= 51
    assert snip.endswith("…")
    assert "  " not in snip


# ── extract_body ────────────────────────────────────────────────────────────
def test_extract_body_plain() -> None:
    msg = EmailMessage()
    msg["From"] = "a@b.c"
    msg.set_content("Plain body here")
    body, has_att = mc.extract_body(msg)
    assert "Plain body here" in body
    assert has_att is False


def test_extract_body_html_fallback() -> None:
    msg = EmailMessage()
    msg.set_content("<p>Rich body</p>", subtype="html")
    body, _ = mc.extract_body(msg)
    assert "Rich body" in body


def test_extract_body_detects_attachment() -> None:
    msg = EmailMessage()
    msg.set_content("hi")
    msg.add_attachment(
        b"bytes", maintype="application", subtype="octet-stream", filename="f.bin"
    )
    body, has_att = mc.extract_body(msg)
    assert has_att is True
    assert "hi" in body


# ── Account config ──────────────────────────────────────────────────────────
@pytest.fixture
def config_paths(tmp_path, monkeypatch):
    account = tmp_path / "mail.json"
    secret = tmp_path / ".mail_creds.json"
    legacy = tmp_path / "api_keys.json"
    monkeypatch.setattr(mc, "ACCOUNT_FILE", account)
    monkeypatch.setattr(mc, "SECRET_FILE", secret)
    monkeypatch.setattr(mc, "LEGACY_KEYS_FILE", legacy)
    monkeypatch.setattr(mc, "CONFIG_DIR", tmp_path)
    return account, secret, legacy


def test_load_account_absent(config_paths) -> None:
    assert mc.load_account() is None


def test_save_and_load_roundtrip(config_paths) -> None:
    _acc, secret, _legacy = config_paths
    account = mc.MailAccount(
        email="me@gmail.com", password="app-pass-123", provider="gmail"
    )
    mc.save_account(account)
    loaded = mc.load_account()
    assert loaded is not None
    assert loaded.email == "me@gmail.com"
    assert loaded.password == "app-pass-123"
    assert loaded.host == "imap.gmail.com"
    assert loaded.port == 993
    assert secret.exists()
    # secret file permissions are restrictive where the OS supports it
    assert oct(secret.stat().st_mode)[-3:] == "600"


def test_load_account_legacy_fallback(config_paths) -> None:
    _acc, _secret, legacy = config_paths
    legacy.write_text(
        json.dumps(
            {"email_user": "old@example.com", "email_pass": "pw",
             "imap_server": "imap.mail.yahoo.com", "imap_port": 993}
        ),
        encoding="utf-8",
    )
    loaded = mc.load_account()
    assert loaded is not None
    assert loaded.email == "old@example.com"
    assert loaded.provider == "yahoo"


def test_load_account_missing_email_raises(config_paths) -> None:
    acc, _secret, _legacy = config_paths
    acc.write_text(json.dumps({"host": "imap.gmail.com"}), encoding="utf-8")
    with pytest.raises(mc.MailError):
        mc.load_account()


def test_load_account_bad_port_raises(config_paths) -> None:
    acc, _secret, _legacy = config_paths
    acc.write_text(
        json.dumps({"email": "a@b.c", "port": "not-a-number"}), encoding="utf-8"
    )
    with pytest.raises(mc.MailError):
        mc.load_account()


def test_delete_account(config_paths) -> None:
    acc, secret, _legacy = config_paths
    mc.save_account(mc.MailAccount(email="a@b.c", password="x"))
    mc.delete_account()
    assert not acc.exists()
    assert not secret.exists()


def test_webmail_urls() -> None:
    gmail = mc.MailAccount(email="a@b.c", password="x", provider="gmail")
    assert mc.webmail_url(gmail).startswith("https://mail.google.com")
    custom = mc.MailAccount(email="a@b.c", password="x", provider="custom")
    assert mc.webmail_url(custom).startswith("https://")


def test_connect_requires_password() -> None:
    account = mc.MailAccount(email="a@b.c", password="")
    with pytest.raises(mc.MailError), mc.connect(account):
        pass


# ── Fake IMAP ───────────────────────────────────────────────────────────────
class FakeIMAP:
    """Minimal IMAP stand-in recording commands and serving canned data."""

    def __init__(self) -> None:
        # uid -> {"flags": str, "headers": bytes, "body": bytes}
        self.messages: dict[int, dict[str, object]] = {}
        self.folders: list[bytes] = [b'(\\HasNoChildren) "/" "INBOX"',
                                     b'(\\HasNoChildren) "/" "Sent"']
        self.commands: list[tuple] = []
        self.selected = ""
        self.readonly = False

    def select(self, folder: str, readonly: bool = False):
        self.selected = folder
        self.readonly = readonly
        return ("OK", [b"1"])

    def list(self):
        return ("OK", self.folders)

    def search(self, charset, key):
        if key == "ALL":
            uids = sorted(self.messages)
        elif key == "UNSEEN":
            uids = sorted(
                u for u, m in self.messages.items()
                if "\\Seen" not in str(m["flags"])
            )
        else:
            uids = sorted(self.messages)
        return ("OK", [b" ".join(str(u).encode() for u in uids)])

    def uid(self, command: str, *args):
        self.commands.append((command, *args))
        if command == "search":
            return self.search(None, args[-1] if args else "ALL")
        if command == "fetch":
            uid = int(args[0])
            spec = str(args[1])
            msg = self.messages.get(uid)
            if msg is None:
                return ("NO", [None])
            if "HEADER.FIELDS" in spec:
                meta = (
                    f'1 (UID {uid} FLAGS ({msg["flags"]}) '
                    f'BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)] {{0}}'
                ).encode()
                return ("OK", [(meta, msg["headers"])])
            meta = f'1 (UID {uid} FLAGS ({msg["flags"]})'.encode()
            return ("OK", [(meta, msg["body"])])
        if command == "STORE":
            return ("OK", [b""])
        return ("NO", [None])


def _mk_message(subject: str, sender: str, flags: str = "(\\Recent)",
                body: bytes = b"Body text") -> dict[str, object]:
    headers = (
        f"From: {sender}\r\n"
        f"To: me@example.com\r\n"
        f"Subject: {subject}\r\n"
        f"Date: Mon, 22 Sep 2025 10:03:11 +0000\r\n\r\n"
    ).encode()
    return {"flags": flags, "headers": headers, "body": body}


def test_fetch_messages_newest_first_and_flags() -> None:
    conn = FakeIMAP()
    conn.messages[1] = _mk_message("Old one", "old@x.com", flags="(\\Seen)")
    conn.messages[2] = _mk_message("New one", "new@x.com", flags="()")
    msgs = mc.fetch_messages(conn, folder="INBOX", limit=10)
    assert [m.subject for m in msgs] == ["New one", "Old one"]
    assert msgs[0].is_unread is True
    assert msgs[1].is_unread is False
    assert msgs[0].sender_address == "new@x.com"
    assert msgs[0].uid == "2"


def test_fetch_messages_limit() -> None:
    conn = FakeIMAP()
    for i in range(1, 6):
        conn.messages[i] = _mk_message(f"Subject {i}", f"s{i}@x.com")
    msgs = mc.fetch_messages(conn, limit=2)
    assert len(msgs) == 2
    assert msgs[0].subject == "Subject 5"


def test_fetch_messages_unread_only() -> None:
    conn = FakeIMAP()
    conn.messages[1] = _mk_message("Seen", "a@x.com", flags="(\\Seen)")
    conn.messages[2] = _mk_message("Unseen", "b@x.com", flags="()")
    msgs = mc.fetch_messages(conn, unread_only=True)
    assert [m.subject for m in msgs] == ["Unseen"]


def test_fetch_messages_query_uses_text() -> None:
    conn = FakeIMAP()
    conn.messages[1] = _mk_message("Invoice", "a@x.com")
    mc.fetch_messages(conn, query='in"voice')
    searches = [c for c in conn.commands if c[0] == "search"]
    assert searches, "search command expected"
    assert 'TEXT "invoice"' in searches[0][-1]


def test_fetch_body_returns_body() -> None:
    conn = FakeIMAP()
    raw = (
        b"From: a@x.com\r\nSubject: Hi\r\n"
        b"Date: Mon, 22 Sep 2025 10:03:11 +0000\r\n\r\nThe body content"
    )
    conn.messages[7] = {"flags": "(\\Seen)", "headers": raw, "body": raw}
    msg = mc.fetch_body(conn, "7", folder="INBOX")
    assert "The body content" in msg.body
    assert msg.subject == "Hi"
    assert msg.uid == "7"


def test_list_folders_counts() -> None:
    conn = FakeIMAP()
    conn.messages[1] = _mk_message("a", "a@x.com", flags="(\\Seen)")
    conn.messages[2] = _mk_message("b", "b@x.com", flags="()")
    folders = mc.list_folders(conn)
    names = [f.name for f in folders]
    assert "INBOX" in names
    inbox = next(f for f in folders if f.name == "INBOX")
    assert inbox.total == 2
    assert inbox.unread == 1


def test_set_seen_and_starred() -> None:
    conn = FakeIMAP()
    conn.messages[1] = _mk_message("a", "a@x.com")
    mc.set_seen(conn, "1", seen=True, folder="INBOX")
    mc.set_starred(conn, "1", starred=True, folder="INBOX")
    stores = [c for c in conn.commands if c[0] == "STORE"]
    assert any("+FLAGS" in c for c in stores)
    assert any("Flagged" in str(c) for c in stores)


def test_mark_folder_read() -> None:
    conn = FakeIMAP()
    conn.messages[1] = _mk_message("a", "a@x.com")
    conn.messages[2] = _mk_message("b", "b@x.com")
    count = mc.mark_folder_read(conn, "INBOX")
    assert count == 2
