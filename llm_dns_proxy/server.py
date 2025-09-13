"""
DNS server that handles encrypted LLM queries through DNS TXT records.
"""

import logging
import socket
import threading
from typing import Dict, Optional, List
from dnslib import DNSRecord, DNSHeader, QTYPE, RR, TXT
from dnslib.server import DNSServer, BaseResolver

from .crypto import CryptoManager
from .chunking import DNSChunker
from .llm import LLMProcessor
from .version import get_version_string


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMDNSResolver(BaseResolver):
    def __init__(self, crypto_key: bytes = None, openai_api_key: str = None,
                 openai_base_url: str = None, openai_model: str = None):
        self.crypto = CryptoManager(crypto_key)
        self.chunker = DNSChunker()
        self.llm = LLMProcessor(openai_api_key, openai_base_url, openai_model)
        self.response_cache: Dict[str, Dict[int, str]] = {}
        # Conversation state management (maps client IP to conversation history)
        self.conversations: Dict[str, List[Dict[str, str]]] = {}
        self.lock = threading.Lock()
        self.version = get_version_string()
        self.model_name = openai_model or "gpt-4o"  # Default model if not specified

    def resolve(self, request, handler):
        """
        Resolve DNS queries for the LLM proxy system.
        """
        reply = request.reply()
        qname = str(request.q.qname)

        # Handle case-insensitive domain matching but preserve case for data
        if qname.lower().endswith('.llm.local.'):
            qname = qname[:-1]  # Remove trailing dot

        logger.info(f"Received query: {qname}")

        qname_lower = qname.lower()
        if qname_lower.startswith('msg.'):
            return self._handle_message_chunk(request, reply, qname, handler)
        elif qname_lower.startswith('get.'):
            return self._handle_response_request(request, reply, qname)
        elif qname_lower.startswith('version.'):
            return self._handle_version_request(request, reply)
        else:
            logger.warning(f"Unknown query type: {qname}")
            return reply

    def _handle_message_chunk(self, request, reply, qname, handler=None):
        """Handle incoming message chunks."""
        session_id, complete_data = self.chunker.process_chunk_query(qname)

        if session_id is None:
            logger.error(f"Invalid chunk query: {qname}")
            return reply

        if complete_data is not None:
            logger.info(f"Complete message received for session {session_id}")

            # Get client IP for conversation tracking
            client_ip = handler.client_address[0] if handler and hasattr(handler, 'client_address') else "unknown"

            try:
                decrypted_message = self.crypto.decrypt(complete_data)
                logger.info(f"Decrypted message: {decrypted_message[:100]}...")

                # Check for special commands
                command = decrypted_message.lower().strip()
                if command in ['/clear', '/reset']:
                    # Clear conversation history
                    with self.lock:
                        self.conversations[client_ip] = []
                    llm_response = ">>> Conversation History Reset.[EOS]"
                    logger.info(f"Cleared conversation history for client {client_ip}")

                    # Create response chunks for the clear message
                    encrypted_response = self.crypto.encrypt(llm_response)
                    response_chunks = self.chunker.create_response_chunks(encrypted_response, session_id)

                    with self.lock:
                        self.response_cache[session_id] = response_chunks

                elif command == '/list':
                    # List available models
                    models = self.llm.list_models()
                    current_model = self.llm.get_current_model()

                    if models and models[0].startswith("Error"):
                        llm_response = f">>> Error listing models: {models[0]}\n\nCurrent model: {current_model}[EOS]"
                    else:
                        model_list = "\n".join([f"{'* ' if model == current_model else '  '}{model}" for model in models])
                        llm_response = f">>> Available models:\n{model_list}\n\ncurrent model ({current_model}). Use /model <name> to switch.[EOS]"

                    logger.info(f">>> Listed models for client {client_ip}")

                    # Create response chunks for the model list
                    encrypted_response = self.crypto.encrypt(llm_response)
                    response_chunks = self.chunker.create_response_chunks(encrypted_response, session_id)

                    with self.lock:
                        self.response_cache[session_id] = response_chunks

                elif command.startswith('/model '):
                    # Switch model
                    new_model = command[7:].strip()  # Remove '/model ' prefix

                    if not new_model:
                        llm_response = "Usage: /model <model_name>\nUse /list to see available models[EOS]"
                    else:
                        success = self.llm.set_model(new_model)
                        if success:
                            # Update server's stored model name
                            self.model_name = new_model
                            llm_response = f">>> Using model: {new_model}[EOS]"
                            logger.info(f">>> Client {client_ip} switched model to {new_model}")
                        else:
                            current_model = self.llm.get_current_model()
                            llm_response = f">>> Failed to switch to model: {new_model}\nCurrent model remains: {current_model}\nUse /list to see available models[EOS]"

                    # Create response chunks for the model switch response
                    encrypted_response = self.crypto.encrypt(llm_response)
                    response_chunks = self.chunker.create_response_chunks(encrypted_response, session_id)

                    with self.lock:
                        self.response_cache[session_id] = response_chunks

                elif command == '/help':
                    # Show help information
                    help_text = """Available Commands:

/help           - Show this help message
/clear          - Clear conversation history and start fresh
/reset          - Same as /clear
/list           - List all available models (current model marked with *)
/model <name>   - Switch to a specific model (e.g., /model gpt-4-turbo)

Examples:
• /list                    - See what models are available
• /model gpt-3.5-turbo    - Switch to GPT-3.5 Turbo
• /model claude-3-sonnet  - Switch to Claude 3 Sonnet
• /clear                  - Start a new conversation

Current model: """ + self.model_name + "[EOS]"

                    logger.info(f"Showed help to client {client_ip}")

                    # Create response chunks for the help message
                    encrypted_response = self.crypto.encrypt(help_text)
                    response_chunks = self.chunker.create_response_chunks(encrypted_response, session_id)

                    with self.lock:
                        self.response_cache[session_id] = response_chunks

                else:
                    # Get conversation history for this client
                    with self.lock:
                        conversation_history = self.conversations.get(client_ip, []).copy()
                        logger.info(f"Client {client_ip} has {len(conversation_history)} messages in history")

                    # Process message with conversation context (streaming)
                    self._process_streaming_response(decrypted_message, session_id, conversation_history, client_ip)

            except Exception as e:
                logger.error(f"Error processing message: {e}")
                error_response = f"Error: {str(e)}[EOS]"
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

    def _handle_version_request(self, request, reply):
        """Handle version information requests."""
        import json
        version_info = {
            "version": self.version,
            "model": self.model_name
        }
        version_response = json.dumps(version_info)
        txt_record = TXT(version_response)
        reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=txt_record, ttl=60))
        logger.info(f"Served version info: {self.version}, model: {self.model_name}")
        return reply

    def _process_streaming_response(self, decrypted_message: str, session_id: str,
                                  conversation_history: list, client_ip: str):
        """Process message and handle streaming response by creating incremental chunks."""
        import threading
        import time

        def stream_handler():
            try:
                complete_response = ""
                chunk_count = 0

                # Initialize streaming response cache
                with self.lock:
                    if session_id not in self.response_cache:
                        self.response_cache[session_id] = {}

                # Process streaming tokens
                for token_data in self.llm.process_message_stream(decrypted_message,
                                                                conversation_history=conversation_history):
                    if token_data['type'] == 'token':
                        complete_response += token_data['content']

                        # Create encrypted chunk for this partial response
                        encrypted_partial = self.crypto.encrypt(complete_response)
                        partial_chunks = self.chunker.create_response_chunks(encrypted_partial, session_id)

                        # Update cache with current state
                        with self.lock:
                            self.response_cache[session_id] = partial_chunks

                        chunk_count += 1

                        # Small delay to prevent overwhelming the system
                        time.sleep(0.01)

                    elif token_data['type'] == 'complete':
                        # Final complete response
                        complete_response = token_data['content']
                        logger.info(f"LLM response: {complete_response[:100]}...")

                        # Update conversation history
                        with self.lock:
                            if client_ip not in self.conversations:
                                self.conversations[client_ip] = []

                            # Add user message and assistant response to history
                            self.conversations[client_ip].extend([
                                {"role": "user", "content": decrypted_message},
                                {"role": "assistant", "content": complete_response}
                            ])

                            # Keep only last 20 messages (10 exchanges) to prevent context overflow
                            if len(self.conversations[client_ip]) > 20:
                                self.conversations[client_ip] = self.conversations[client_ip][-20:]

                        # Add EOS marker to final response
                        complete_response_with_eos = complete_response + "[EOS]"

                        # Final encrypted response
                        encrypted_response = self.crypto.encrypt(complete_response_with_eos)
                        response_chunks = self.chunker.create_response_chunks(encrypted_response, session_id)

                        with self.lock:
                            self.response_cache[session_id] = response_chunks

                        logger.info(f"Streaming complete. Final response has {len(response_chunks)} chunks for session {session_id}")
                        break

            except Exception as e:
                logger.error(f"Error in streaming handler: {e}")
                # Create error response
                error_response = f"Error: {str(e)}[EOS]"
                encrypted_error = self.crypto.encrypt(error_response)
                error_chunks = self.chunker.create_response_chunks(encrypted_error, session_id)

                with self.lock:
                    self.response_cache[session_id] = error_chunks

        # Start streaming in a separate thread
        stream_thread = threading.Thread(target=stream_handler)
        stream_thread.daemon = True
        stream_thread.start()


class LLMDNSServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 5353, crypto_key: bytes = None,
                 openai_api_key: str = None, openai_base_url: str = None, openai_model: str = None):
        self.host = host
        self.port = port
        self.resolver = LLMDNSResolver(crypto_key, openai_api_key, openai_base_url, openai_model)
        self.server = None

    def start(self):
        """Start the DNS server."""
        version = self.resolver.version
        model = self.resolver.model_name
        logger.info(f"Starting LLM DNS server on {self.host}:{self.port} ({version}, model: {model})")
        self.server = DNSServer(self.resolver, port=self.port, address=self.host)
        self.server.start_thread()
        logger.info(f"Server started successfully ({version}, model: {model})")

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