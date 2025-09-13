"""
Encryption utilities using Fernet for secure message transport.
"""

import base64
import os
import zlib
from cryptography.fernet import Fernet


class CryptoManager:
    def __init__(self, key: bytes = None):
        if key is None:
            key = os.getenv('LLM_PROXY_KEY')
            if key:
                key = key.encode()
            else:
                key = Fernet.generate_key()

        if isinstance(key, str):
            key = key.encode()

        self.fernet = Fernet(key)

    @classmethod
    def generate_key(cls) -> bytes:
        """Generate a new encryption key."""
        return Fernet.generate_key()

    def encrypt(self, message: str) -> bytes:
        """Encrypt a message with compression and return raw Fernet token bytes."""
        # Compress first for better efficiency
        compressed = zlib.compress(message.encode(), level=9)
        # Fernet.encrypt() returns URL-safe base64 bytes
        encrypted = self.fernet.encrypt(compressed)
        return encrypted

    def decrypt(self, encrypted_data: bytes) -> str:
        """Decrypt and decompress raw Fernet token bytes."""
        # Decrypt the Fernet token
        decrypted = self.fernet.decrypt(encrypted_data)
        # Decompress the result
        decompressed = zlib.decompress(decrypted)
        return decompressed.decode()
