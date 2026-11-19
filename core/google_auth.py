"""Google OAuth for installed desktop apps and multi-account token storage.

One OAuth run authorizes exactly one Google account. Refresh tokens go to the
OS keyring; if keyring is unavailable they are encrypted with a local Fernet
key. Only non-secret metadata is kept in the accounts JSON file.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.paths import config_path, memory_path

logger = logging.getLogger("google_auth")

SCOPES: tuple[str, ...] = (
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
)

ACCOUNTS_FILE = memory_path("google_accounts.json")
TOKEN_FILE = config_path("google_tokens.enc")
KEY_FILE = config_path(".google_key")
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleAuthError(RuntimeError):
    """Raised when OAuth or token storage fails."""


@dataclass(frozen=True)
class AccountInfo:
    """Non-secret metadata for one connected Google account."""

    email: str
    name: str = ""
    avatar_url: str = ""
    added: str = ""
    needs_reauth: bool = False
    last_sync: str = ""


def credentials_path(explicit: str | None = None) -> Path:
    """Resolve credentials.json from config, .env or the config directory."""
    candidate = (
        explicit
        or os.environ.get("GOOGLE_CREDENTIALS_PATH", "")
        or _config_value("google_credentials_path")
    )
    if candidate:
        return Path(candidate).expanduser().resolve()
    return config_path("credentials.json")


def _config_value(key: str) -> str:
    try:
        cfg = json.loads(config_path("api_keys.json").read_text(encoding="utf-8"))
        return str(cfg.get(key, "") or "")
    except Exception:
        return ""


def _load_accounts() -> list[dict[str, Any]]:
    try:
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        return data.get("accounts", []) if isinstance(data, dict) else []
    except Exception:
        return []


def _save_accounts(accounts: list[dict[str, Any]]) -> None:
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_FILE.write_text(
        json.dumps({"accounts": accounts}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _keyring():
    try:
        import keyring

        return keyring
    except Exception:
        return None


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except Exception:
        return None
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if KEY_FILE.exists():
        key = KEY_FILE.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        KEY_FILE.write_bytes(key)
        os.chmod(KEY_FILE, 0o600)
    return Fernet(key)


def store_token(email: str, token: dict[str, Any]) -> None:
    """Persist a refresh token keyed by email, never in plaintext JSON."""
    payload = json.dumps(token, separators=(",", ":"))
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password("jarvis-google", email.lower(), payload)
            return
        except Exception as e:
            logger.warning("Keyring unavailable (%s); using encrypted file", type(e).__name__)
    fernet = _fernet()
    if fernet is None:
        raise GoogleAuthError("No keyring and cryptography is not installed")
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tokens: dict[str, str] = {}
    if TOKEN_FILE.exists():
        try:
            tokens = json.loads(fernet.decrypt(TOKEN_FILE.read_bytes()).decode())
        except Exception:
            tokens = {}
    tokens[email.lower()] = payload
    TOKEN_FILE.write_bytes(fernet.encrypt(json.dumps(tokens).encode()))
    os.chmod(TOKEN_FILE, 0o600)


def load_token(email: str) -> dict[str, Any] | None:
    kr = _keyring()
    if kr is not None:
        try:
            raw = kr.get_password("jarvis-google", email.lower())
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    fernet = _fernet()
    if fernet is None or not TOKEN_FILE.exists():
        return None
    try:
        tokens = json.loads(fernet.decrypt(TOKEN_FILE.read_bytes()).decode())
        raw = tokens.get(email.lower())
        return json.loads(raw) if raw else None
    except Exception:
        return None


def delete_token(email: str) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password("jarvis-google", email.lower())
        except Exception:
            pass
    fernet = _fernet()
    if fernet is None or not TOKEN_FILE.exists():
        return
    try:
        tokens = json.loads(fernet.decrypt(TOKEN_FILE.read_bytes()).decode())
        tokens.pop(email.lower(), None)
        TOKEN_FILE.write_bytes(fernet.encrypt(json.dumps(tokens).encode()))
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _code_challenge(verifier: str) -> str:
    """S256 PKCE challenge for the installed-app flow."""
    import base64
    import hashlib

    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _catch_redirect(port: int) -> str:
    """Open a one-shot loopback server and return the authorization code."""
    import http.server
    import urllib.parse

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self.server.code = (query.get("code") or [""])[0]  # type: ignore[attr-defined]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h2>Authorization complete.</h2><p>You can close this window.</p>"
            )

        def log_message(self, *_args):
            return

    server = http.server.HTTPServer(("localhost", port), Handler)
    try:
        server.handle_request()
    finally:
        server.server_close()
    return str(getattr(server, "code", "") or "")


def run_oauth(credentials_file: str | Path | None = None) -> dict[str, Any]:
    """PKCE installed-app flow: system browser consent, loopback redirect."""
    import secrets
    import webbrowser

    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError as e:
        raise GoogleAuthError("google-auth-oauthlib is not installed") from e

    path = credentials_path(str(credentials_file) if credentials_file else None)
    if not path.exists():
        raise GoogleAuthError(f"credentials.json not found at {path}")

    port = _free_port()
    redirect_uri = f"http://localhost:{port}/"
    verifier = secrets.token_urlsafe(64)[:128]
    try:
        flow = Flow.from_client_secrets_file(
            str(path), list(SCOPES), redirect_uri=redirect_uri
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
            code_challenge=_code_challenge(verifier),
            code_challenge_method="S256",
        )
        webbrowser.open(auth_url)
        code = _catch_redirect(port)
        if not code:
            raise GoogleAuthError("No authorization code was returned")
        flow.fetch_token(code=code, code_verifier=verifier)
        creds = flow.credentials
        token = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or SCOPES),
            "expiry": creds.expiry.isoformat() if creds.expiry else "",
        }
        return {"credentials": creds, "token": token, "userinfo": fetch_userinfo(creds)}
    except GoogleAuthError:
        raise
    except Exception as e:
        logger.warning("OAuth failed: %s", type(e).__name__)
        raise GoogleAuthError(f"OAuth failed: {e}") from e

def fetch_userinfo(creds: Any) -> dict[str, str]:
    """Fetch the authorized account's email and profile."""
    import requests

    response = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("email"):
        raise GoogleAuthError("Google did not return an email for this account")
    return {
        "email": str(data["email"]).lower(),
        "name": str(data.get("name", "")),
        "avatar_url": str(data.get("picture", "")),
    }


def add_account_record(info: dict[str, str]) -> AccountInfo:
    """Add or refresh non-secret metadata for an account."""
    from datetime import datetime

    accounts = _load_accounts()
    email = info["email"].lower()
    record = {
        "email": email,
        "name": info.get("name", ""),
        "avatar_url": info.get("avatar_url", ""),
        "added": next(
            (a.get("added", "") for a in accounts if a.get("email") == email),
            datetime.now().isoformat(timespec="seconds"),
        ),
        "needs_reauth": False,
        "last_sync": "",
    }
    accounts = [a for a in accounts if a.get("email") != email] + [record]
    _save_accounts(accounts)
    return AccountInfo(
        email=str(record["email"]), name=str(record["name"]),
        avatar_url=str(record["avatar_url"]), added=str(record["added"]),
        needs_reauth=False, last_sync="",
    )


def list_account_records() -> list[AccountInfo]:
    records = []
    for raw in _load_accounts():
        try:
            records.append(AccountInfo(
                email=str(raw.get("email", "")),
                name=str(raw.get("name", "")),
                avatar_url=str(raw.get("avatar_url", "")),
                added=str(raw.get("added", "")),
                needs_reauth=bool(raw.get("needs_reauth")),
                last_sync=str(raw.get("last_sync", "")),
            ))
        except Exception:
            continue
    return records


def mark_needs_reauth(email: str) -> None:
    accounts = _load_accounts()
    for account in accounts:
        if account.get("email", "").lower() == email.lower():
            account["needs_reauth"] = True
    _save_accounts(accounts)


def remove_account_record(email: str) -> None:
    _save_accounts([a for a in _load_accounts()
                    if a.get("email", "").lower() != email.lower()])


def set_last_sync(email: str, value: str) -> None:
    accounts = _load_accounts()
    for account in accounts:
        if account.get("email", "").lower() == email.lower():
            account["last_sync"] = value
            account["needs_reauth"] = False
    _save_accounts(accounts)
