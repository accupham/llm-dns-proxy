"""
Tests for DNS message chunking utilities.
"""

import pytest
import base64
from llm_dns_proxy.chunking import DNSChunker
from llm_dns_proxy.config import get_dns_suffix, format_dns_query
from .test_utils import dns_suffix_override, get_test_dns_suffix


class TestDNSChunker:
    def test_create_chunks_small_message(self):
        chunker = DNSChunker()
        data = b"small message"

        chunks = chunker.create_chunks(data, "test123")
        assert len(chunks) == 1
        assert chunks[0].startswith("m.test123.0.1.")
        suffix = get_dns_suffix()
        assert chunks[0].endswith(f".{suffix}")

    def test_create_chunks_large_message(self):
        chunker = DNSChunker()
        data = b"A" * 1000

        chunks = chunker.create_chunks(data, "test123")
        assert len(chunks) > 1

        suffix_parts = get_dns_suffix().split('.')
        for i, chunk in enumerate(chunks):
            parts = chunk.split('.')
            assert parts[0] == "m"
            assert parts[1] == "test123"
            assert parts[2] == str(i)
            assert parts[3] == str(len(chunks))
            assert parts[-len(suffix_parts):] == suffix_parts

    def test_process_chunk_query_single_chunk(self):
        chunker = DNSChunker()
        data = b"test message"

        chunks = chunker.create_chunks(data, "session1")
        session_id, complete_data = chunker.process_chunk_query(chunks[0])

        assert session_id == "session1"
        assert complete_data == data

    def test_process_chunk_query_multiple_chunks(self):
        chunker = DNSChunker()
        data = b"A" * 1000

        chunks = chunker.create_chunks(data, "session2")

        complete_data = None
        for chunk in chunks:
            session_id, complete_data = chunker.process_chunk_query(chunk)
            assert session_id == "session2"

        assert complete_data == data

    def test_process_chunk_query_out_of_order(self):
        chunker = DNSChunker()
        data = b"B" * 500

        chunks = chunker.create_chunks(data, "session3")

        if len(chunks) > 1:
            reversed_chunks = chunks[::-1]

            complete_data = None
            for chunk in reversed_chunks:
                session_id, complete_data = chunker.process_chunk_query(chunk)
                assert session_id == "session3"

            assert complete_data == data

    def test_invalid_chunk_query(self):
        chunker = DNSChunker()

        suffix = get_dns_suffix()
        invalid_queries = [
            "invalid.query",
            f"m.session.invalid.total.data.{suffix}",
            f"m.session.0.invalid.data.{suffix}",
            f"wrong.session.0.1.data.{suffix}",
            "m.session.0.1.data.wrong.domain",
        ]

        for query in invalid_queries:
            session_id, complete_data = chunker.process_chunk_query(query)
            assert session_id is None
            assert complete_data is None

    def test_create_response_chunks(self):
        chunker = DNSChunker()
        data = b"response data"

        chunks = chunker.create_response_chunks(data, "resp123")
        assert len(chunks) >= 1

        for chunk_index, chunk_data in chunks.items():
            assert isinstance(chunk_index, int)
            assert ":" in chunk_data
            parts = chunk_data.split(":", 2)
            assert len(parts) == 3
            assert parts[0] == str(chunk_index)

    def test_parse_response_query_valid(self):
        chunker = DNSChunker()
        query = format_dns_query("g", "session123", "5")

        session_id, chunk_index = chunker.parse_response_query(query)
        assert session_id == "session123"
        assert chunk_index == 5

    def test_parse_response_query_invalid(self):
        chunker = DNSChunker()

        suffix = get_dns_suffix()
        invalid_queries = [
            "invalid.query",
            f"g.session.invalid.{suffix}",
            f"wrong.session.0.{suffix}",
            "g.session.0.wrong.domain",
            f"g.session123.5.{suffix.split('.')[0]}.wrong",
        ]

        for query in invalid_queries:
            session_id, chunk_index = chunker.parse_response_query(query)
            assert session_id is None
            assert chunk_index is None

    def test_reassemble_response(self):
        chunker = DNSChunker()
        original_data = b"test response data"

        response_chunks = chunker.create_response_chunks(original_data, "test")
        reassembled = chunker.reassemble_response(response_chunks)

        assert reassembled == original_data

    def test_reassemble_response_empty(self):
        chunker = DNSChunker()
        reassembled = chunker.reassemble_response({})
        assert reassembled == b''

    def test_session_isolation(self):
        chunker = DNSChunker()

        data1 = b"message for session 1"
        data2 = b"different message for session 2"

        chunks1 = chunker.create_chunks(data1, "session1")
        chunks2 = chunker.create_chunks(data2, "session2")

        for chunk in chunks1[:-1]:
            session_id, complete_data = chunker.process_chunk_query(chunk)
            assert session_id == "session1"
            assert complete_data is None

        for chunk in chunks2:
            session_id, complete_data = chunker.process_chunk_query(chunk)
            assert session_id == "session2"

        assert complete_data == data2

        session_id, complete_data = chunker.process_chunk_query(chunks1[-1])
        assert session_id == "session1"
        assert complete_data == data1

    def test_configurable_dns_suffix(self):
        """Test that DNS suffix can be configured via environment variable."""
        chunker = DNSChunker()
        data = b"test message"

        # Test with custom suffix
        with dns_suffix_override("custom.example.com"):
            chunks = chunker.create_chunks(data, "test")
            assert len(chunks) == 1
            assert chunks[0].endswith(".custom.example.com")

            # Test parsing works with custom suffix
            session_id, complete_data = chunker.process_chunk_query(chunks[0])
            assert session_id == "test"
            assert complete_data == data

            # Test response queries with custom suffix
            query = format_dns_query("g", "session", "0")
            assert query == "g.session.0.custom.example.com"

        # Test with default suffix
        chunks_default = chunker.create_chunks(data, "test")
        default_suffix = get_dns_suffix()
        assert chunks_default[0].endswith(f".{default_suffix}")