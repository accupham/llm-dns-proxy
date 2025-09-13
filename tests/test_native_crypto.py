"""
Tests for native encryption utilities.
"""

import pytest
from llm_dns_proxy.native_crypto import CryptoManager


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
        key = CryptoManager.generate_key()
        crypto = CryptoManager(key)
        message = "Test with custom key"

        encrypted = crypto.encrypt(message)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == message

    def test_with_string_key(self):
        key = CryptoManager.generate_key().decode()
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

    def test_incremental_message_lengths(self):
        """Test encryption/decryption with incremental message lengths to catch padding issues."""
        crypto = CryptoManager()

        # Test various lengths including block size boundaries
        for length in range(0, 513):  # Test 0 to 512 characters
            message = 'X' * length
            encrypted = crypto.encrypt(message)
            decrypted = crypto.decrypt(encrypted)
            assert decrypted == message, f"Failed at message length {length}"

    def test_padding_boundary_cases(self):
        """Test specific padding boundary cases that might reveal issues."""
        crypto = CryptoManager()

        # Test around common block sizes (8, 16, 32, 64, 128, 256)
        boundary_lengths = [
            7, 8, 9,
            15, 16, 17,
            31, 32, 33,
            63, 64, 65,
            127, 128, 129,
            255, 256, 257,
            511, 512, 513,
            1023, 1024, 1025
        ]

        for length in boundary_lengths:
            message = 'B' * length
            encrypted = crypto.encrypt(message)
            decrypted = crypto.decrypt(encrypted)
            assert decrypted == message, f"Failed at boundary length {length}"

    def test_special_characters(self):
        """Test encryption of various special characters and edge cases."""
        crypto = CryptoManager()

        special_cases = [
            "\n\r\t",  # Whitespace characters
            "\x00\x01\x02\x03",  # Null and control characters
            "🔐🔑🛡️",  # Emojis
            "café naïve résumé",  # Accented characters
            "你好世界",  # Chinese characters
            "こんにちは",  # Japanese characters
            "Здравствуй мир",  # Cyrillic
            "مرحبا بالعالم",  # Arabic
            "\u0000\uffff",  # Unicode boundaries
            " " * 100,  # Only spaces
            "\t" * 50,  # Only tabs
            "\n" * 25,  # Only newlines
            "a\x00b\x00c",  # Mixed with null bytes
        ]

        for message in special_cases:
            encrypted = crypto.encrypt(message)
            decrypted = crypto.decrypt(encrypted)
            assert decrypted == message, f"Failed for special message: {repr(message)}"

    # def test_invalid_key_formats(self):
    #     """Test that invalid key formats raise appropriate errors."""
    #     with pytest.raises((ValueError, TypeError)):
    #         CryptoManager(b"short")  # Too short (< 8 bytes)
    #
    #     # Test invalid 44-char key that looks like base64 but isn't
    #     # with pytest.raises((ValueError, TypeError)):
    #     #     CryptoManager("invalid_base64_format_with_exactly_44chars!!")
    #
    #     with pytest.raises((ValueError, TypeError)):
    #         CryptoManager(12345)  # Wrong type

    def test_decrypt_with_wrong_key(self):
        """Test that decrypting with wrong key raises appropriate error."""
        crypto1 = CryptoManager()
        crypto2 = CryptoManager()

        message = "Secret message"
        encrypted = crypto1.encrypt(message)

        with pytest.raises(Exception):  # Should raise cryptography exception
            crypto2.decrypt(encrypted)

    def test_decrypt_invalid_data(self):
        """Test that decrypting invalid data raises appropriate errors."""
        crypto = CryptoManager()

        invalid_data_cases = [
            b"not_encrypted_data",
            b"",
            b"too_short",
            b"x" * 100,  # Random bytes
            "string_instead_of_bytes",
        ]

        for invalid_data in invalid_data_cases:
            with pytest.raises(Exception):
                if isinstance(invalid_data, str):
                    crypto.decrypt(invalid_data.encode())
                else:
                    crypto.decrypt(invalid_data)

    def test_encryption_determinism(self):
        """Test that encryption is non-deterministic (same message produces different ciphertexts)."""
        crypto = CryptoManager()
        message = "Test determinism"

        encryptions = [crypto.encrypt(message) for _ in range(10)]

        # All encryptions should be different (uses random IV)
        for i, enc1 in enumerate(encryptions):
            for j, enc2 in enumerate(encryptions):
                if i != j:
                    assert enc1 != enc2, "Encryption should be non-deterministic"

    def test_key_generation_uniqueness(self):
        """Test that key generation produces unique keys."""
        keys = [CryptoManager.generate_key() for _ in range(100)]

        # All keys should be unique
        assert len(set(keys)) == 100, "Generated keys should be unique"

        # All keys should be proper length
        for key in keys:
            assert len(key) == 44, "Generated key should be 44 bytes (base64 encoded 32-byte key)"

    def test_concurrent_encryption_safety(self):
        """Test that the same CryptoManager instance can safely encrypt/decrypt concurrently."""
        import threading

        crypto = CryptoManager()
        messages = [f"Message {i}" for i in range(100)]
        results = [None] * 100

        def encrypt_decrypt(index, message):
            encrypted = crypto.encrypt(message)
            decrypted = crypto.decrypt(encrypted)
            results[index] = (message, decrypted)

        threads = []
        for i, message in enumerate(messages):
            thread = threading.Thread(target=encrypt_decrypt, args=(i, message))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify all operations succeeded
        for original, decrypted in results:
            assert original == decrypted, "Concurrent encryption/decryption should work correctly"

    def test_very_large_message(self):
        """Test encryption of very large messages."""
        crypto = CryptoManager()

        # Test with 1MB message
        large_message = "A" * (1024 * 1024)
        encrypted = crypto.encrypt(large_message)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == large_message

    def test_message_with_all_byte_values(self):
        """Test encryption of message containing all possible byte values."""
        crypto = CryptoManager()

        # Create message with all byte values 0-255
        message = ''.join(chr(i) for i in range(256))
        encrypted = crypto.encrypt(message)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == message