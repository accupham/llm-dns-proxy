"""
Pure-Python symmetric encryption: ChaCha20 + HMAC-SHA256 (encrypt-then-MAC)
No third-party libraries. Drop-in compatible with the CryptoManager interface
you posted (same method names and return types), but NOT Fernet-token compatible.

Token format (before base64): b"CH20" || nonce(12) || ciphertext || tag(32)
"""

import os
import hmac
import base64
import struct
import hashlib
from typing import Tuple

def _hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    # HKDF-Extract with SHA-256
    return hmac.new(salt if salt is not None else b"\x00" * 32, ikm, hashlib.sha256).digest()

def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    # HKDF-Expand with SHA-256
    out = b""
    t = b""
    counter = 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        out += t
        counter += 1
    return out[:length]

def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    prk = _hkdf_extract(salt, ikm)
    return _hkdf_expand(prk, info, length)

# --- ChaCha20 (12-byte nonce) pure Python ---

def _rotl32(v, n):
    return ((v << n) & 0xffffffff) | (v >> (32 - n))

def _qr(a, b, c, d):
    a = (a + b) & 0xffffffff; d ^= a; d = _rotl32(d, 16)
    c = (c + d) & 0xffffffff; b ^= c; b = _rotl32(b, 12)
    a = (a + b) & 0xffffffff; d ^= a; d = _rotl32(d, 8)
    c = (c + d) & 0xffffffff; b ^= c; b = _rotl32(b, 7)
    return a, b, c, d

def _chacha20_block(key32: bytes, counter: int, nonce12: bytes) -> bytes:
    # State setup
    constants = b"expand 32-byte k"
    def u32le(b): return struct.unpack("<I", b)[0]

    state = [
        u32le(constants[0:4]), u32le(constants[4:8]),
        u32le(constants[8:12]), u32le(constants[12:16]),
        u32le(key32[0:4]), u32le(key32[4:8]), u32le(key32[8:12]), u32le(key32[12:16]),
        u32le(key32[16:20]), u32le(key32[20:24]), u32le(key32[24:28]), u32le(key32[28:32]),
        counter,
        u32le(nonce12[0:4]), u32le(nonce12[4:8]), u32le(nonce12[8:12])
    ]

    working = state[:]
    for _ in range(10):  # 20 rounds (10 column + 10 diagonal)
        # Column rounds
        working[0], working[4], working[8], working[12] = _qr(working[0], working[4], working[8], working[12])
        working[1], working[5], working[9], working[13] = _qr(working[1], working[5], working[9], working[13])
        working[2], working[6], working[10], working[14] = _qr(working[2], working[6], working[10], working[14])
        working[3], working[7], working[11], working[15] = _qr(working[3], working[7], working[11], working[15])
        # Diagonal rounds
        working[0], working[5], working[10], working[15] = _qr(working[0], working[5], working[10], working[15])
        working[1], working[6], working[11], working[12] = _qr(working[1], working[6], working[11], working[12])
        working[2], working[7], working[8], working[13] = _qr(working[2], working[7], working[8], working[13])
        working[3], working[4], working[9], working[14] = _qr(working[3], working[4], working[9], working[14])

    out = []
    for i in range(16):
        out.append((working[i] + state[i]) & 0xffffffff)
    return struct.pack("<16I", *out)

def chacha20_xor(key32: bytes, nonce12: bytes, plaintext: bytes, counter_start: int = 1) -> bytes:
    # XOR plaintext with ChaCha20 keystream
    out = bytearray()
    counter = counter_start
    for block_start in range(0, len(plaintext), 64):
        block = _chacha20_block(key32, counter, nonce12)
        counter = (counter + 1) & 0xffffffff
        chunk = plaintext[block_start:block_start+64]
        out.extend(bytes(a ^ b for a, b in zip(chunk, block[:len(chunk)])))
    return bytes(out)

# --- Encrypt-then-MAC (AEAD-like) ---

MAGIC = b"CH20"        # format marker
NONCE_LEN = 12
TAG_LEN = 32
KEY_LEN = 32           # 256-bit master key

def _split_keys(master_key: bytes) -> Tuple[bytes, bytes]:
    # Derive separate keys for encryption and MAC
    okm = hkdf_sha256(master_key, salt=b"chacha20+hmac", info=b"enc+mac", length=64)
    return okm[:32], okm[32:]

def _mac(mac_key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    # MAC over associated data = MAGIC || nonce || ciphertext
    return hmac.new(mac_key, MAGIC + nonce + ciphertext, hashlib.sha256).digest()

def _b64u_encode(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b)

def _b64u_decode(b: bytes) -> bytes:
    return base64.urlsafe_b64decode(b)

class CryptoManager:
    def __init__(self, key: bytes = None):
        # Accept raw 32-byte key, or base64-encoded forms (like Fernet keys in env)
        if key is None:
            key = os.getenv("LLM_PROXY_KEY")
            if key:
                key = key.encode()

        if isinstance(key, str):
            key = key.encode()

        if key is None:
            # Generate a new random master key (returned by generate_key()) is base64,
            # but internally we store raw bytes.
            key = os.urandom(KEY_LEN)
        else:
            # Try to interpret provided bytes as base64; if it decodes to 32 bytes, use it.
            try:
                decoded = base64.urlsafe_b64decode(key)
                if len(decoded) == KEY_LEN:
                    key = decoded
            except Exception:
                pass

            # If still not 32 bytes, stretch it via HKDF deterministically (last resort).
            if len(key) != KEY_LEN:
                key = hkdf_sha256(key, salt=b"key-normalize", info=b"master", length=KEY_LEN)

        self._master_key = key
        self._enc_key, self._mac_key = _split_keys(self._master_key)

    @classmethod
    def generate_key(cls) -> bytes:
        """
        Generate a new base64-url-encoded 32-byte key (bytes, to match Fernet-like usage).
        """
        raw = os.urandom(KEY_LEN)
        return _b64u_encode(raw)

    def encrypt(self, message: str) -> bytes:
        """
        Encrypt a message and return urlsafe-base64 bytes (opaque token).
        """
        if not isinstance(message, str):
            raise TypeError("encrypt expects a str")

        nonce = os.urandom(NONCE_LEN)
        pt = message.encode("utf-8")
        ct = chacha20_xor(self._enc_key, nonce, pt, counter_start=1)
        tag = _mac(self._mac_key, nonce, ct)
        token = MAGIC + nonce + ct + tag
        return _b64u_encode(token)

    def decrypt(self, encrypted_data: bytes) -> str:
        """
        Decrypt urlsafe-base64 bytes produced by encrypt(). Verifies MAC.
        Raises ValueError on authentication failure or malformed input.
        """
        if isinstance(encrypted_data, str):
            encrypted_data = encrypted_data.encode("utf-8")

        try:
            blob = _b64u_decode(encrypted_data)
        except Exception as e:
            raise ValueError("Invalid token (base64)") from e

        if len(blob) < len(MAGIC) + NONCE_LEN + TAG_LEN:
            raise ValueError("Invalid token (too short)")

        if not blob.startswith(MAGIC):
            raise ValueError("Invalid token (magic)")

        nonce = blob[4:4+NONCE_LEN]
        tag = blob[-TAG_LEN:]
        ct = blob[4+NONCE_LEN:-TAG_LEN]

        expected = _mac(self._mac_key, nonce, ct)
        if not hmac.compare_digest(expected, tag):
            raise ValueError("Authentication failed")

        pt = chacha20_xor(self._enc_key, nonce, ct, counter_start=1)
        return pt.decode("utf-8")