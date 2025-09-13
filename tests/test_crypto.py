"""
Tests for encryption utilities.
"""

import pytest
from cryptography.fernet import Fernet
from llm_dns_proxy.crypto import CryptoManager


class TestCryptoManager:
    def test_generate_key(self):
        key = CryptoManager.generate_key()
        assert isinstance(key, bytes)
        assert len(key) == 44

    def test_encrypt_decrypt_cycle(self):
        crypto = CryptoManager()
        message = "Hello, world! This is a test message."

        encrypted = crypto.encrypt(message)
        assert isinstance(encrypted, bytes)
        assert encrypted != message.encode()

        decrypted = crypto.decrypt(encrypted)
        assert decrypted == message

    def test_with_custom_key(self):
        key = Fernet.generate_key()
        crypto = CryptoManager(key)
        message = "Test with custom key"

        encrypted = crypto.encrypt(message)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == message

    def test_with_string_key(self):
        key = Fernet.generate_key().decode()
        crypto = CryptoManager(key)
        message = "Test with string key"

        encrypted = crypto.encrypt(message)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == message

    def test_different_keys_different_results(self):
        crypto1 = CryptoManager()
        crypto2 = CryptoManager()
        message = "Same message"

        encrypted1 = crypto1.encrypt(message)
        encrypted2 = crypto2.encrypt(message)

        assert encrypted1 != encrypted2

    def test_unicode_message(self):
        crypto = CryptoManager()
        message = "Hello 🌍! This contains unicode: café, naïve, résumé"

        encrypted = crypto.encrypt(message)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == message

    def test_empty_message(self):
        crypto = CryptoManager()
        message = ""

        encrypted = crypto.encrypt(message)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == message

    def test_long_message(self):
        crypto = CryptoManager()
        message = "A" * 10000

        encrypted = crypto.encrypt(message)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == message