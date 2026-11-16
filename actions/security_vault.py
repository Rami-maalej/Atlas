import base64
import json
import logging
import os

from core.paths import memory_path

logger = logging.getLogger("security_vault")

VAULT_PATH = memory_path("secrets.vault.json")
_VAULT_KEY = os.environ.get("JARVIS_VAULT_KEY", "")

# ── Encryption helpers (Fernet) ──────────────────────────────────────────

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    def _derive_key(passphrase: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                         iterations=600_000)
        return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))

    _HAVE_FERNET = True
except ImportError:
    _HAVE_FERNET = False


def _encrypt(plaintext: str) -> str:
    """Encrypt plaintext JSON string. Returns base64 ciphertext."""
    if not _HAVE_FERNET or not _VAULT_KEY:
        return plaintext  # fallback to plaintext
    salt = os.urandom(16)
    key = _derive_key(_VAULT_KEY, salt)
    cipher = Fernet(key)
    token = cipher.encrypt(plaintext.encode("utf-8"))
    # Prepend salt (hex) so we can derive the same key on decrypt
    return salt.hex() + ":" + token.decode("utf-8")


def _decrypt(ciphertext: str) -> str:
    """Decrypt string that was produced by _encrypt."""
    if not _HAVE_FERNET or not _VAULT_KEY:
        return ciphertext
    if ":" not in ciphertext:
        logger.warning("Vault data missing salt header — treating as plaintext")
        return ciphertext
    try:
        salt_hex, token = ciphertext.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        key = _derive_key(_VAULT_KEY, salt)
        cipher = Fernet(key)
        return cipher.decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error("Vault decryption failed: %s", e)
        return ""


# ── Vault I/O ────────────────────────────────────────────────────────────

def _get_vault() -> dict:
    if not VAULT_PATH.exists():
        return {}
    try:
        raw = VAULT_PATH.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        decrypted = _decrypt(raw)
        return json.loads(decrypted) if decrypted else {}
    except Exception:
        return {}


def _save_vault(data: dict):
    VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(data, indent=2, ensure_ascii=False)
    encrypted = _encrypt(plaintext)
    VAULT_PATH.write_text(encrypted, encoding="utf-8")


def store_secret(key: str, value: str) -> str:
    vault = _get_vault()
    vault[key] = value
    _save_vault(vault)
    logger.info("Secret stored: %s", key)
    return f"Secret '{key}' stored."


def get_secret(key: str) -> str:
    vault = _get_vault()
    return vault.get(key, "")


def list_secrets() -> list[str]:
    vault = _get_vault()
    return list(vault.keys())


def delete_secret(key: str) -> str:
    vault = _get_vault()
    if key in vault:
        del vault[key]
        _save_vault(vault)
        return f"Secret '{key}' deleted."
    return f"Secret '{key}' not found."


# ── HashiCorp Vault integration ────────────────────────────────────────
