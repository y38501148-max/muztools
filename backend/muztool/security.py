from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from typing import Any

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes

from . import config


def _secret() -> bytes:
    config.ensure_dirs()
    if not config.SECRET_FILE.exists():
        config.SECRET_FILE.write_bytes(secrets.token_bytes(32))
        config.SECRET_FILE.chmod(0o600)
    return config.SECRET_FILE.read_bytes()


def _vault_key() -> bytes:
    config.ensure_dirs()
    if not config.VAULT_KEY_FILE.exists():
        config.VAULT_KEY_FILE.write_bytes(secrets.token_bytes(32))
        config.VAULT_KEY_FILE.chmod(0o600)
    key = config.VAULT_KEY_FILE.read_bytes()
    if len(key) != 32:
        raise RuntimeError("凭据加密密钥格式无效")
    return key


def _rsa_private_key() -> RSA.RsaKey:
    config.ensure_dirs()
    if not config.RSA_PRIVATE_KEY_FILE.exists():
        key = RSA.generate(2048)
        config.RSA_PRIVATE_KEY_FILE.write_bytes(key.export_key(format="PEM", passphrase=None, pkcs=8))
        config.RSA_PRIVATE_KEY_FILE.chmod(0o600)
    return RSA.import_key(config.RSA_PRIVATE_KEY_FILE.read_bytes())


def public_transport_key() -> dict[str, Any]:
    key = _rsa_private_key().public_key()
    modulus = int(key.n)
    return {
        "algorithm": "RSA-PKCS1-v1_5",
        "key_id": hashlib.sha256(key.export_key(format="DER")).hexdigest()[:16],
        "modulus_hex": format(modulus, "x"),
        "exponent": int(key.e),
        "key_size": key.size_in_bytes(),
    }


def decrypt_transport_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        ciphertext = base64.b64decode(text, validate=True)
    except Exception as exc:
        raise ValueError("加密字段格式无效") from exc
    sentinel = get_random_bytes(32)
    plaintext = PKCS1_v1_5.new(_rsa_private_key()).decrypt(ciphertext, sentinel)
    if plaintext == sentinel:
        raise ValueError("加密字段解密失败，请刷新页面后重试")
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("加密字段编码无效") from exc


def decrypt_transport_payload(payload: dict[str, Any], fields: tuple[str, ...]) -> dict[str, str]:
    encrypted = payload.get("encrypted")
    if not isinstance(encrypted, dict):
        raise ValueError("此接口仅接受加密凭据，请更新客户端后重试")
    return {field: decrypt_transport_value(encrypted.get(field)) for field in fields}



def decrypt_hybrid_secret(payload: dict[str, Any], field: str = "encrypted_secret", max_plaintext: int = 262_144) -> str:
    """Decrypt an RSA-wrapped AES-256-GCM envelope.

    The RSA key protects only the random AES key, so large secrets such as a
    browser cookie export never exceed the RSA block size.
    """
    envelope = payload.get(field)
    if not isinstance(envelope, dict):
        raise ValueError("此接口仅接受加密凭据，请更新客户端后重试")
    try:
        encrypted_key = base64.b64decode(str(envelope.get("key") or ""), validate=True)
        nonce = base64.b64decode(str(envelope.get("nonce") or ""), validate=True)
        sealed = base64.b64decode(str(envelope.get("ciphertext") or ""), validate=True)
    except Exception as exc:
        raise ValueError("加密凭据格式无效") from exc
    if len(encrypted_key) != _rsa_private_key().size_in_bytes() or len(nonce) != 12 or len(sealed) < 16:
        raise ValueError("加密凭据格式无效")
    sentinel = get_random_bytes(32)
    aes_key = PKCS1_v1_5.new(_rsa_private_key()).decrypt(encrypted_key, sentinel)
    if aes_key == sentinel or len(aes_key) != 32:
        raise ValueError("加密凭据解密失败，请刷新页面后重试")
    ciphertext, tag = sealed[:-16], sealed[-16:]
    if len(ciphertext) > max_plaintext:
        raise ValueError("加密凭据过长")
    try:
        plaintext = AES.new(aes_key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ciphertext, tag)
        if len(plaintext) > max_plaintext:
            raise ValueError("加密凭据过长")
        return plaintext.decode("utf-8")
    except ValueError as exc:
        if str(exc) == "加密凭据过长":
            raise
        raise ValueError("加密凭据校验失败，请重新提交") from exc
    except UnicodeDecodeError as exc:
        raise ValueError("加密凭据编码无效") from exc

def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    nonce = get_random_bytes(12)
    cipher = AES.new(_vault_key(), AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(value.encode("utf-8"))
    return "v1:" + base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")


def decrypt_secret(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if not text.startswith("v1:"):
        # Legacy plaintext is accepted only for one-time migration at rest.
        return text
    try:
        raw = base64.urlsafe_b64decode(text[3:].encode("ascii"))
        nonce, tag, ciphertext = raw[:12], raw[12:28], raw[28:]
        cipher = AES.new(_vault_key(), AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
    except Exception as exc:
        raise ValueError("服务器保存的加密凭据无法解密") from exc


def hash_password(password: str, salt: str | None = None) -> str:
    raw_salt = salt.encode("utf-8") if salt else secrets.token_hex(16).encode("utf-8")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), raw_salt, 200_000)
    return f"{raw_salt.decode('utf-8')}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, f"{salt}${digest}")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_id() -> str:
    return secrets.token_hex(8)


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{6,18}$")


def validate_username(username: str) -> str:
    name = (username or "").strip()
    if not USERNAME_RE.fullmatch(name):
        raise ValueError("账号须为 6～18 位字母、数字或下划线")
    return name


def validate_password(password: str) -> str:
    if not 6 <= len(password or "") <= 18:
        raise ValueError("密码须为 6～18 位")
    if not re.search(r"[0-9]", password):
        raise ValueError("密码必须包含数字")
    if not re.search(r"[a-z]", password):
        raise ValueError("密码必须包含小写字母")
    if not re.search(r"[A-Z]", password):
        raise ValueError("密码必须包含大写字母")
    return password
