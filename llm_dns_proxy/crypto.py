"""
Encryption utilities using Fernet for secure message transport.
"""

import base64
import os
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
        """Encrypt a message and return base64-encoded bytes."""
        encrypted = self.fernet.encrypt(message.encode())
        return base64.b64encode(encrypted)

    def decrypt(self, encrypted_data: bytes) -> str:
        """Decrypt base64-encoded encrypted data."""
        decoded = base64.b64decode(encrypted_data)
        decrypted = self.fernet.decrypt(decoded)
        return decrypted.decode()