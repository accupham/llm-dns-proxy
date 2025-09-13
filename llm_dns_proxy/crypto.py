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
        """Encrypt a message and return raw Fernet token bytes."""
        # Fernet.encrypt() already returns URL-safe base64 bytes, no need to double-encode
        encrypted = self.fernet.encrypt(message.encode())
        return encrypted

    def decrypt(self, encrypted_data: bytes) -> str:
        """Decrypt raw Fernet token bytes."""
        # Direct decryption of Fernet token (already in proper format)
        decrypted = self.fernet.decrypt(encrypted_data)
        return decrypted.decode()


# # pip install python-fernet  (pure Python)
# import os
# from fernet import Fernet  # implements spec-compatible Fernet
#
# class CryptoManager:
#     def __init__(self, key: bytes = None):
#         if key is None:
#             key = os.getenv('LLM_PROXY_KEY')
#             key = key.encode() if key else Fernet.generate_key()
#         if isinstance(key, str):
#             key = key.encode()
#         self.fernet = Fernet(key)
#
#     @classmethod
#     def generate_key(cls) -> bytes:
#         return Fernet.generate_key()
#
#     def encrypt(self, message: str) -> bytes:
#         return self.fernet.encrypt(message.encode())
#
#     def decrypt(self, encrypted_data: bytes) -> str:
#         return self.fernet.decrypt(encrypted_data).decode()
