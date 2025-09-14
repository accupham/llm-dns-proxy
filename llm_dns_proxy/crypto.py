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

    def encrypt_chunk(self, text_chunk: str, sequence: int = 0) -> bytes:
        """Encrypt a small text chunk for streaming.

        Args:
            text_chunk: Small piece of text to encrypt
            sequence: Sequence number for ordering (optional metadata)

        Returns:
            Encrypted chunk as Fernet token bytes
        """
        # For streaming, we don't compress individual small chunks as it's inefficient
        # and can actually increase size for small strings
        chunk_data = text_chunk.encode('utf-8')
        return self.fernet.encrypt(chunk_data)

    def decrypt_chunk(self, encrypted_chunk: bytes) -> str:
        """Decrypt a streaming text chunk.

        Args:
            encrypted_chunk: Encrypted chunk bytes

        Returns:
            Decrypted text chunk
        """
        decrypted_data = self.fernet.decrypt(encrypted_chunk)
        return decrypted_data.decode('utf-8')
