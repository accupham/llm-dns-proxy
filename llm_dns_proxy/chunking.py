"""
DNS message chunking and reassembly utilities.
Handles the splitting of encrypted messages into DNS-compatible chunks.
"""

import base64
import math
import uuid
import zlib
from typing import List, Dict, Optional, Tuple


def base36encode(number: int) -> str:
    """Convert integer to base36 string using 0-9a-z"""
    if number == 0:
        return '0'

    alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'
    result = ''
    while number:
        number, remainder = divmod(number, 36)
        result = alphabet[remainder] + result
    return result


def base36decode(string: str) -> int:
    """Convert base36 string to integer"""
    return int(string, 36)


def bytes_to_base36(data: bytes) -> str:
    """Convert bytes to base36 string with length prefix"""
    # Convert bytes to big integer
    number = int.from_bytes(data, byteorder='big')
    encoded = base36encode(number)
    # Prefix with original length to preserve it during decode
    length_prefix = base36encode(len(data))
    return f"{length_prefix}z{encoded}"


def base36_to_bytes(string: str) -> bytes:
    """Convert base36 string back to bytes"""
    # Split at 'z' separator
    parts = string.split('z', 1)
    if len(parts) != 2:
        raise ValueError("Invalid base36 format")

    length_str, data_str = parts
    original_length = base36decode(length_str)
    number = base36decode(data_str)

    # Convert back to bytes with original length
    if number == 0:
        return b'\x00' * original_length

    byte_length = (number.bit_length() + 7) // 8
    result = number.to_bytes(byte_length, byteorder='big')

    # Pad with leading zeros if needed
    if len(result) < original_length:
        result = b'\x00' * (original_length - len(result)) + result

    return result


class DNSChunker:
    MAX_DNS_LABEL_LENGTH = 63
    MAX_DNS_RECORD_LENGTH = 255
    MAX_DNS_QNAME_LENGTH = 253
    MAX_DATA_LABEL_LENGTH = 50  # Conservative limit for single label

    def __init__(self):
        self.pending_messages: Dict[str, Dict[int, str]] = {}
        self.total_chunks: Dict[str, int] = {}

    def _split_data_into_labels(self, data: str, max_per_label: int) -> List[str]:
        """Split long data into multiple DNS labels"""
        labels = []
        for i in range(0, len(data), max_per_label):
            labels.append(data[i:i + max_per_label])
        return labels

    def create_chunks(self, encrypted_data: bytes, session_id: str = None) -> List[str]:
        """
        Split encrypted data into DNS-compatible chunks with proper qname length validation.
        Returns list of DNS query strings in format: m.sessionid.index.total.data1.data2.llm.local
        """
        if session_id is None:
            # Use 1-char base36 session ID for max 10 concurrent users (0-9)
            # Keep it simple with just digits for better readability
            session_id = str(uuid.uuid4().int % 10)

        # Convert Fernet token to DNS-safe base36 for labels
        # Base36 uses only 0-9a-z which is DNS-safe and more efficient than base32
        data_b36 = bytes_to_base36(encrypted_data)

        # Calculate base qname overhead: "m." + sessionid + "." + index + "." + total + "." + ".llm.local"
        # Worst case: m.9.999.999..llm.local = ~20 chars + dots
        base_overhead = 25  # Conservative estimate with single-char commands and session IDs

        max_data_per_chunk = self.MAX_DNS_QNAME_LENGTH - base_overhead
        total_chunks = math.ceil(len(data_b36) / max_data_per_chunk)

        chunks = []
        for i in range(total_chunks):
            start = i * max_data_per_chunk
            end = min(start + max_data_per_chunk, len(data_b36))
            chunk_data = data_b36[start:end]

            # Split chunk_data into multiple labels if needed
            data_labels = self._split_data_into_labels(chunk_data, self.MAX_DATA_LABEL_LENGTH)

            # Build query with multiple data labels (m = message)
            data_part = '.'.join(data_labels)
            query = f"m.{session_id}.{i}.{total_chunks}.{data_part}.llm.local"

            # Validate qname length
            if len(query) > self.MAX_DNS_QNAME_LENGTH:
                # If still too long, reduce data further
                reduced_data_len = self.MAX_DNS_QNAME_LENGTH - len(query) + len(data_part)
                if reduced_data_len > 0:
                    chunk_data = chunk_data[:reduced_data_len]
                    data_labels = self._split_data_into_labels(chunk_data, self.MAX_DATA_LABEL_LENGTH)
                    data_part = '.'.join(data_labels)
                    query = f"m.{session_id}.{i}.{total_chunks}.{data_part}.llm.local"
                else:
                    raise ValueError(f"Cannot fit data into DNS qname constraints for chunk {i}")

            chunks.append(query)

        return chunks

    def process_chunk_query(self, query: str) -> Tuple[Optional[str], Optional[bytes]]:
        """
        Process incoming DNS query chunk and return (session_id, complete_message) if ready.
        Returns (session_id, None) if still waiting for more chunks.
        Returns (None, None) if invalid query.

        Expected format: m.sessionid.index.total.data1.data2...dataN.llm.local
        """
        parts = query.split('.')
        if len(parts) < 6 or parts[0] != 'm' or parts[-2:] != ['llm', 'local']:
            return None, None

        try:
            session_id = parts[1]
            chunk_index = int(parts[2])
            total_chunks = int(parts[3])

            # Extract data labels (everything between total_chunks and llm.local)
            data_labels = parts[4:-2]  # Skip 'llm.local' at end
            chunk_data = ''.join(data_labels)  # Rejoin data parts

            if session_id not in self.pending_messages:
                self.pending_messages[session_id] = {}
                self.total_chunks[session_id] = total_chunks

            self.pending_messages[session_id][chunk_index] = chunk_data

            if len(self.pending_messages[session_id]) == self.total_chunks[session_id]:
                complete_data = ''
                for i in range(self.total_chunks[session_id]):
                    complete_data += self.pending_messages[session_id][i]

                del self.pending_messages[session_id]
                del self.total_chunks[session_id]

                # Decode using base36
                return session_id, base36_to_bytes(complete_data)

            return session_id, None

        except (ValueError, IndexError, base64.binascii.Error) as e:
            return None, None

    def create_response_chunks(self, encrypted_data: bytes, session_id: str) -> Dict[int, str]:
        """
        Create response chunks as TXT records indexed by chunk number.
        Client will query g.sessionid.index.llm.local to retrieve chunks.
        """
        # Fernet tokens are already URL-safe base64 bytes, just decode to string for TXT
        # No double-encoding needed - TXT records can handle the Fernet format directly
        data_b64 = encrypted_data.decode('ascii')
        max_chunk_size = self.MAX_DNS_RECORD_LENGTH - 50

        total_chunks = math.ceil(len(data_b64) / max_chunk_size)
        chunks = {}

        for i in range(total_chunks):
            start = i * max_chunk_size
            end = min(start + max_chunk_size, len(data_b64))
            chunk_data = data_b64[start:end]

            txt_record = f"{i}:{total_chunks}:{chunk_data}"
            chunks[i] = txt_record

        return chunks

    def parse_response_query(self, query: str) -> Tuple[Optional[str], Optional[int]]:
        """
        Parse response retrieval query: g.sessionid.index.llm.local
        Returns (session_id, chunk_index) or (None, None) if invalid.
        """
        parts = query.split('.')
        if len(parts) != 5 or parts[0] != 'g' or parts[-2:] != ['llm', 'local']:
            return None, None

        try:
            session_id = parts[1]
            chunk_index = int(parts[2])
            return session_id, chunk_index
        except (ValueError, IndexError):
            return None, None

    def reassemble_response(self, chunks: Dict[int, str]) -> bytes:
        """
        Reassemble response chunks into complete encrypted Fernet token bytes.
        """
        if not chunks:
            return b''

        sorted_chunks = sorted(chunks.items())
        complete_data = ''

        for _, chunk in sorted_chunks:
            parts = chunk.split(':', 2)
            if len(parts) == 3:
                complete_data += parts[2]

        # Return the Fernet token as bytes (already in proper format)
        return complete_data.encode('ascii')