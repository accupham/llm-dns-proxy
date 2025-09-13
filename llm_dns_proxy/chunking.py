"""
DNS message chunking and reassembly utilities.
Handles the splitting of encrypted messages into DNS-compatible chunks.
"""

import base64
import math
import uuid
from typing import List, Dict, Optional, Tuple


class DNSChunker:
    MAX_DNS_LABEL_LENGTH = 63
    MAX_DNS_RECORD_LENGTH = 255

    def __init__(self):
        self.pending_messages: Dict[str, Dict[int, str]] = {}
        self.total_chunks: Dict[str, int] = {}

    def create_chunks(self, encrypted_data: bytes, session_id: str = None) -> List[str]:
        """
        Split encrypted data into DNS-compatible chunks.
        Returns list of DNS query strings in format: msg.sessionid.index.total.data.llm.local
        """
        if session_id is None:
            session_id = str(uuid.uuid4())[:8]

        data_b64 = base64.b64encode(encrypted_data).decode()

        max_data_per_chunk = self.MAX_DNS_LABEL_LENGTH - 10
        total_chunks = math.ceil(len(data_b64) / max_data_per_chunk)

        chunks = []
        for i in range(total_chunks):
            start = i * max_data_per_chunk
            end = min(start + max_data_per_chunk, len(data_b64))
            chunk_data = data_b64[start:end]

            query = f"msg.{session_id}.{i}.{total_chunks}.{chunk_data}.llm.local"
            chunks.append(query)

        return chunks

    def process_chunk_query(self, query: str) -> Tuple[Optional[str], Optional[bytes]]:
        """
        Process incoming DNS query chunk and return (session_id, complete_message) if ready.
        Returns (session_id, None) if still waiting for more chunks.
        Returns (None, None) if invalid query.
        """
        parts = query.split('.')
        if len(parts) < 6 or parts[0] != 'msg' or parts[-2:] != ['llm', 'local']:
            return None, None

        try:
            session_id = parts[1]
            chunk_index = int(parts[2])
            total_chunks = int(parts[3])
            chunk_data = parts[4]

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

                return session_id, base64.b64decode(complete_data.encode())

            return session_id, None

        except (ValueError, IndexError, base64.binascii.Error):
            return None, None

    def create_response_chunks(self, encrypted_data: bytes, session_id: str) -> Dict[int, str]:
        """
        Create response chunks as TXT records indexed by chunk number.
        Client will query get.sessionid.index.llm.local to retrieve chunks.
        """
        data_b64 = base64.b64encode(encrypted_data).decode()
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
        Parse response retrieval query: get.sessionid.index.llm.local
        Returns (session_id, chunk_index) or (None, None) if invalid.
        """
        parts = query.split('.')
        if len(parts) != 5 or parts[0] != 'get' or parts[-2:] != ['llm', 'local']:
            return None, None

        try:
            session_id = parts[1]
            chunk_index = int(parts[2])
            return session_id, chunk_index
        except (ValueError, IndexError):
            return None, None

    def reassemble_response(self, chunks: Dict[int, str]) -> bytes:
        """
        Reassemble response chunks into complete encrypted data.
        """
        if not chunks:
            return b''

        sorted_chunks = sorted(chunks.items())
        complete_data = ''

        for _, chunk in sorted_chunks:
            parts = chunk.split(':', 2)
            if len(parts) == 3:
                complete_data += parts[2]

        return base64.b64decode(complete_data)