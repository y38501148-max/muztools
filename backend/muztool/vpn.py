from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from Crypto.Cipher import AES

GATEWAY_HOST = "d.buaa.edu.cn"
KEY = b"wrdvpnisthebest!"


def _cfb_transform(data: bytes, iv: bytes) -> bytes:
    aes = AES.new(KEY, AES.MODE_ECB)
    padded_len = (len(data) + 15) // 16 * 16
    padded = data + b"0" * (padded_len - len(data))
    previous = iv
    output = bytearray()
    for index in range(0, padded_len, 16):
        encrypted = aes.encrypt(previous)
        block = bytes(byte ^ encrypted[i] for i, byte in enumerate(padded[index : index + 16]))
        output.extend(block)
        previous = block
    return bytes(output[: len(data)])


def encrypt_host(host: str) -> str:
    cipher = _cfb_transform(host.encode("utf-8"), KEY)
    return KEY.hex() + cipher.hex()


def to_vpn_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.hostname or parsed.hostname == GATEWAY_HOST:
        return url
    if parsed.port:
        protocol = f"{parsed.scheme}-{parsed.port}"
    elif parsed.scheme in {"http", "https"}:
        protocol = parsed.scheme
    else:
        protocol = parsed.scheme
    path = parsed.path or ""
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"https://{GATEWAY_HOST}/{protocol}/{encrypt_host(parsed.hostname)}{path}{query}{fragment}"
