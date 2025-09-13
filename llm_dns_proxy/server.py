"""
DNS server that handles encrypted LLM queries through DNS TXT records.
"""

import logging
import socket
import threading
from typing import Dict, Optional
from dnslib import DNSRecord, DNSHeader, QTYPE, RR, TXT
from dnslib.server import DNSServer, BaseResolver

from .crypto import CryptoManager
from .chunking import DNSChunker
from .llm import LLMProcessor


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMDNSResolver(BaseResolver):
    def __init__(self, crypto_key: bytes = None, openai_api_key: str = None,
                 openai_base_url: str = None, openai_model: str = None):
        self.crypto = CryptoManager(crypto_key)
        self.chunker = DNSChunker()
        self.llm = LLMProcessor(openai_api_key, openai_base_url, openai_model)
        self.response_cache: Dict[str, Dict[int, str]] = {}
        self.lock = threading.Lock()

    def resolve(self, request, handler):
        """
        Resolve DNS queries for the LLM proxy system.
        """
        reply = request.reply()
        qname = str(request.q.qname).lower()

        if qname.endswith('.llm.local.'):
            qname = qname[:-1]

        logger.info(f"Received query: {qname}")

        if qname.startswith('msg.'):
            return self._handle_message_chunk(request, reply, qname)
        elif qname.startswith('get.'):
            return self._handle_response_request(request, reply, qname)
        else:
            logger.warning(f"Unknown query type: {qname}")
            return reply

    def _handle_message_chunk(self, request, reply, qname):
        """Handle incoming message chunks."""
        session_id, complete_data = self.chunker.process_chunk_query(qname)

        if session_id is None:
            logger.error(f"Invalid chunk query: {qname}")
            return reply

        if complete_data is not None:
            logger.info(f"Complete message received for session {session_id}")

            try:
                decrypted_message = self.crypto.decrypt(complete_data)
                logger.info(f"Decrypted message: {decrypted_message[:100]}...")

                llm_response = self.llm.process_message_sync(decrypted_message)
                logger.info(f"LLM response: {llm_response[:100]}...")

                encrypted_response = self.crypto.encrypt(llm_response)

                response_chunks = self.chunker.create_response_chunks(encrypted_response, session_id)

                with self.lock:
                    self.response_cache[session_id] = response_chunks

                logger.info(f"Cached {len(response_chunks)} response chunks for session {session_id}")

            except Exception as e:
                logger.error(f"Error processing message: {e}")
                error_response = f"Error: {str(e)}"
                encrypted_error = self.crypto.encrypt(error_response)
                error_chunks = self.chunker.create_response_chunks(encrypted_error, session_id)

                with self.lock:
                    self.response_cache[session_id] = error_chunks

        txt_record = TXT("OK")
        reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=txt_record, ttl=60))
        return reply

    def _handle_response_request(self, request, reply, qname):
        """Handle requests for response chunks."""
        session_id, chunk_index = self.chunker.parse_response_query(qname)

        if session_id is None or chunk_index is None:
            logger.error(f"Invalid response query: {qname}")
            return reply

        with self.lock:
            if session_id in self.response_cache and chunk_index in self.response_cache[session_id]:
                chunk_data = self.response_cache[session_id][chunk_index]
                txt_record = TXT(chunk_data)
                reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=txt_record, ttl=60))
                logger.info(f"Served chunk {chunk_index} for session {session_id}")
            else:
                logger.warning(f"Chunk not found: session={session_id}, chunk={chunk_index}")
                txt_record = TXT("NOT_FOUND")
                reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=txt_record, ttl=60))

        return reply


class LLMDNSServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 5353, crypto_key: bytes = None,
                 openai_api_key: str = None, openai_base_url: str = None, openai_model: str = None):
        self.host = host
        self.port = port
        self.resolver = LLMDNSResolver(crypto_key, openai_api_key, openai_base_url, openai_model)
        self.server = None

    def start(self):
        """Start the DNS server."""
        logger.info(f"Starting LLM DNS server on {self.host}:{self.port}")
        self.server = DNSServer(self.resolver, port=self.port, address=self.host)
        self.server.start_thread()
        logger.info("Server started successfully")

    def stop(self):
        """Stop the DNS server."""
        if self.server:
            self.server.stop()
            logger.info("Server stopped")

    def run(self):
        """Run the server (blocking)."""
        self.start()
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down server...")
            self.stop()