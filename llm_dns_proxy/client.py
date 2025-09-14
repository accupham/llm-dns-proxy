"""
CLI client for the DNS-based LLM proxy system.
"""

import socket
import time
import uuid
import random
import threading
import sys
import click
from typing import Dict, List, Optional
from dnslib import DNSRecord, QTYPE, DNSQuestion, DNSHeader

from .crypto import CryptoManager
#from .native_crypto import CryptoManager
from .chunking import DNSChunker
from .version import get_version_string
from .config import format_dns_query


class SimpleSpinner:
    def __init__(self, message="Loading"):
        self.message = message
        self.running = False
        self.thread = None
        self.spinner_chars = "|/-\\"
        self.current = 0

    def _spin(self):
        while self.running:
            sys.stdout.write(f"\r{self.message} {self.spinner_chars[self.current % len(self.spinner_chars)]}")
            sys.stdout.flush()
            self.current += 1
            time.sleep(0.1)
        sys.stdout.write("\r" + " " * (len(self.message) + 2) + "\r")
        sys.stdout.flush()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._spin)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()


class DNSLLMClient:
    def __init__(self, server_host: str = "127.0.0.1", server_port: int = 5353, crypto_key: bytes = None, verbose: bool = False, poll_interval: float = 0.5, model: str = "LLM"):
        self.server_host = server_host
        self.server_port = server_port
        self.crypto = CryptoManager(crypto_key)
        self.chunker = DNSChunker()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(30.0)
        self.verbose = verbose
        self.poll_interval = poll_interval
        self.model = model
        self.client_version = get_version_string()
        # Use a single session ID for the entire client session to avoid collisions
        # Use 3-digit session ID (000-999) for much better uniqueness
        # Mix timestamp and random for collision avoidance
        time_component = int(time.time()) % 1000
        random_component = uuid.uuid4().int % 1000
        session_num = (time_component + random_component) % 1000
        self.session_id = f"{session_num:03d}"  # Zero-padded 3 digits

    def _send_dns_query(self, query_name: str) -> Optional[str]:
        """Send a DNS query and return the TXT record response."""
        try:
            # Manual DNS record construction to avoid dnslib issues
            question = DNSQuestion(query_name, QTYPE.TXT)
            header = DNSHeader(id=random.randint(1, 65535))
            q = DNSRecord(header, q=question)
            query_data = q.pack()

            self.sock.sendto(query_data, (self.server_host, self.server_port))

            response_data, _ = self.sock.recvfrom(4096)
            response = DNSRecord.parse(response_data)

            for rr in response.rr:
                if rr.rtype == QTYPE.TXT:
                    # Handle TXT RDATA which can be a list of strings (each ≤255 bytes)
                    rdata = rr.rdata

                    # dnslib TXT RDATA has a 'data' attribute that's a list of byte strings
                    if hasattr(rdata, 'data') and isinstance(rdata.data, list):
                        # Join all byte strings and decode
                        txt_bytes = b''.join(rdata.data)
                        txt_data = txt_bytes.decode('utf-8', errors='ignore')
                    else:
                        # Fallback to string conversion
                        txt_data = str(rdata)
                        # Handle quoted TXT records
                        if txt_data.startswith('"') and txt_data.endswith('"'):
                            txt_data = txt_data[1:-1]

                    return txt_data

            return None

        except Exception as e:
            if self.verbose:
                click.echo(f"DNS query error: {e}")
            return None

    def send_message(self, message: str, show_spinner: bool = True, streaming: bool = True) -> Optional[str]:
        """Send a message to the LLM through DNS and get the response.

        Args:
            message: The message to send
            show_spinner: Whether to show spinner during processing
            streaming: Whether to display streaming response (default True)
        """
        # Use the persistent session ID for this client instance
        session_id = self.session_id
        if self.verbose:
            click.echo(f"Using session ID: {session_id}")
        spinner = None

        try:
            if self.verbose:
                click.echo(f"Encrypting message...")
            encrypted_data = self.crypto.encrypt(message)

            if self.verbose:
                click.echo(f"Creating message chunks...")
            chunks = self.chunker.create_chunks(encrypted_data, session_id)

            if show_spinner and not self.verbose:
                spinner = SimpleSpinner("...")
                spinner.start()

            if self.verbose:
                click.echo(f"Sending {len(chunks)} chunks...")

            for i, chunk in enumerate(chunks):
                if self.verbose:
                    click.echo(f"Sending chunk {i+1}/{len(chunks)}")
                response = self._send_dns_query(chunk)
                if response != "OK" and self.verbose:
                    click.echo(f"Warning: Unexpected response for chunk {i+1}: {response}")

            if spinner:
                spinner.stop()

            if streaming and not self.verbose:
                return self._handle_streaming_response(session_id)
            else:
                return self._handle_traditional_response(session_id, show_spinner)

        finally:
            if spinner:
                spinner.stop()

    def _handle_streaming_response(self, session_id: str) -> Optional[str]:
        """Handle streaming response by polling for partial updates."""
        import sys

        last_content = ""
        final_response = None
        start_time = time.time()
        max_wait_time = 60  # Maximum wait time in seconds
        last_content_change_time = time.time()

        # Initial wait for processing to start
        time.sleep(self.poll_interval)

        while True:
            # Check for timeout
            current_time = time.time()
            if current_time - start_time > max_wait_time:
                if self.verbose:
                    click.echo(f"\nTimeout waiting for response after {max_wait_time}s")
                final_response = last_content.rstrip('[EOS]') if last_content else "Timeout - no response received"
                break

            # Check if content hasn't changed for too long (indicates completion)
            # But only if we have some content and it doesn't end with [EOS]
            if last_content and current_time - last_content_change_time > 15:  # 15 seconds without change
                if last_content.endswith('[EOS]'):
                    final_response = last_content.rstrip('[EOS]')
                    break
                elif len(last_content) > 50:  # Only timeout if we have substantial content
                    final_response = last_content + "\n[Response may be incomplete - connection timed out]"
                    break

            response_chunks = self._get_current_response_chunks(session_id)

            if not response_chunks:
                time.sleep(self.poll_interval)
                continue

            try:
                # Try streaming decryption first (new method)
                try:
                    current_content = self.chunker.reassemble_streaming_chunks(self.crypto, response_chunks)
                    # If empty, fall back to traditional method
                    if not current_content:
                        current_encrypted = self.chunker.reassemble_response(response_chunks)
                        current_content = self.crypto.decrypt(current_encrypted)
                except Exception:
                    # Fall back to traditional decryption
                    current_encrypted = self.chunker.reassemble_response(response_chunks)
                    current_content = self.crypto.decrypt(current_encrypted)

                # Display new content
                if len(current_content) > len(last_content):
                    new_content = current_content[len(last_content):]

                    # Don't display [EOS] marker to user
                    display_content = new_content.replace('[EOS]', '')
                    if display_content:  # Only write if there's content after removing [EOS]
                        sys.stdout.write(display_content)
                        sys.stdout.flush()

                    last_content = current_content
                    last_content_change_time = current_time  # Update the last change time

                    # Check if response is complete by looking for [EOS] marker
                    looks_complete = current_content.endswith('[EOS]')

                    if looks_complete:
                        time.sleep(0.5)  # Wait to see if more content comes

                        # Check again
                        new_chunks = self._get_current_response_chunks(session_id)
                        if new_chunks:
                            try:
                                # Try streaming decryption first
                                try:
                                    new_content_check = self.chunker.reassemble_streaming_chunks(self.crypto, new_chunks)
                                    if not new_content_check:
                                        new_encrypted = self.chunker.reassemble_response(new_chunks)
                                        new_content_check = self.crypto.decrypt(new_encrypted)
                                except Exception:
                                    new_encrypted = self.chunker.reassemble_response(new_chunks)
                                    new_content_check = self.crypto.decrypt(new_encrypted)

                                if new_content_check == current_content:
                                    # No change, response is complete
                                    # Remove [EOS] marker from final response
                                    final_response = current_content.rstrip('[EOS]')
                                    break

                            except Exception:
                                pass

                time.sleep(self.poll_interval)  # Small delay between polls

            except Exception as e:
                if self.verbose:
                    click.echo(f"\nError processing streaming response: {e}")
                time.sleep(0.2)
                continue

        return final_response

    def _get_current_response_chunks(self, session_id: str) -> dict:
        """Get current response chunks from server."""
        response_chunks = {}
        chunk_index = 0
        max_chunks = 100  # Increased limit for large responses
        total_chunks = None
        consecutive_not_found = 0
        max_consecutive_not_found = 50  # Allow more gaps - server may be generating chunks slowly

        while chunk_index < max_chunks and consecutive_not_found < max_consecutive_not_found:
            query = format_dns_query("g", session_id, chunk_index)
            response = self._send_dns_query(query)

            if response == "NOT_FOUND":
                consecutive_not_found += 1
                chunk_index += 1
                continue
            else:
                consecutive_not_found = 0  # Reset counter on successful retrieval

            if response and ':' in response:
                parts = response.split(':', 2)
                if len(parts) == 3:
                    try:
                        current_index = int(parts[0])
                        chunk_total = int(parts[1])
                        response_chunks[current_index] = response

                        # Update total_chunks if we haven't seen it yet or if it's larger
                        if total_chunks is None or chunk_total > total_chunks:
                            total_chunks = chunk_total
                            # Don't limit max_chunks yet - server might still be generating more

                        # If we have all chunks we expect, we can break early
                        if total_chunks and len(response_chunks) >= total_chunks:
                            # Verify we have a contiguous sequence from 0 to total_chunks-1
                            if all(i in response_chunks for i in range(total_chunks)):
                                break
                    except (ValueError, IndexError):
                        if self.verbose:
                            click.echo(f"Error parsing chunk response: {response}")

            chunk_index += 1

        # If we know how many chunks we should have, try to wait for missing ones
        if total_chunks and len(response_chunks) < total_chunks:
            missing_chunks = [i for i in range(total_chunks) if i not in response_chunks]
            if self.verbose:
                click.echo(f"Waiting for {len(missing_chunks)} missing chunks: {missing_chunks}")

            # Implement chunk-level retries with exponential backoff for flaky networks
            max_retries = 5
            for retry in range(max_retries):
                if not missing_chunks:
                    break

                if self.verbose:
                    click.echo(f"Retry {retry + 1}/{max_retries}: Requesting {len(missing_chunks)} missing chunks...")

                # Exponential backoff: 0.5, 1.0, 2.0, 4.0, 8.0 seconds
                import time
                wait_time = 0.5 * (2 ** retry)
                time.sleep(wait_time)

                # Request specific missing chunks
                chunks_retrieved_this_round = 0
                for missing_idx in missing_chunks[:]:
                    query = format_dns_query("g", session_id, missing_idx)
                    response = self._send_dns_query(query)

                    if self._validate_chunk_response(response, missing_idx):
                        response_chunks[missing_idx] = response
                        missing_chunks.remove(missing_idx)
                        chunks_retrieved_this_round += 1
                        if self.verbose:
                            click.echo(f"  ✓ Retrieved missing chunk {missing_idx}")
                    elif self.verbose and response and response != "NOT_FOUND":
                        click.echo(f"  ✗ Invalid chunk {missing_idx}: {response[:30]}...")

                if self.verbose:
                    click.echo(f"  Retrieved {chunks_retrieved_this_round} chunks this round")

                if not missing_chunks:  # All chunks found
                    break

            if self.verbose and missing_chunks:
                click.echo(f"Still missing {len(missing_chunks)} chunks after all retries: {missing_chunks}")

        return response_chunks

    def _validate_chunk_response(self, response: str, expected_index: int) -> bool:
        """Validate chunk response format and integrity.

        Args:
            response: Raw TXT record response
            expected_index: Expected chunk index

        Returns:
            True if valid, False otherwise
        """
        if not response or response == "NOT_FOUND":
            return False

        parts = response.split(':', 2)
        if len(parts) != 3:
            return False

        try:
            actual_index = int(parts[0])
            total_chunks = int(parts[1])
            data = parts[2]

            # Validate index matches expectation
            if actual_index != expected_index:
                return False

            # Validate data is not empty
            if not data:
                return False

            # Basic format validation - should be base64-like Fernet token
            if len(data) < 20:  # Fernet tokens are at least ~44 chars
                return False

            return True

        except (ValueError, IndexError):
            return False

    def _handle_traditional_response(self, session_id: str, show_spinner: bool) -> Optional[str]:
        """Handle traditional non-streaming response."""
        spinner = None

        try:
            if show_spinner and not self.verbose:
                spinner = SimpleSpinner("-->")
                spinner.start()
            elif self.verbose:
                click.echo("Message sent, waiting for processing...")

            # Wait longer for server to generate response, especially for long responses
            time.sleep(8)  # Increased wait time for server generation

            if spinner:
                spinner.stop()
                spinner = SimpleSpinner("<--")
                spinner.start()
            elif self.verbose:
                click.echo("Retrieving response chunks...")

            # Use the improved chunk retrieval method
            # Try multiple times until we get a complete response (marked with [EOS])
            response_chunks = {}
            max_attempts = 5

            for attempt in range(max_attempts):
                response_chunks = self._get_current_response_chunks(session_id)

                if response_chunks:
                    # Try to reassemble and check if it's complete
                    try:
                        reassembled = self.chunker.reassemble_response(response_chunks)
                        if reassembled:
                            decrypted = self.crypto.decrypt(reassembled)
                            if '[EOS]' in decrypted:
                                # Response is complete
                                break
                    except Exception:
                        pass  # Decryption failed, keep trying

                if attempt < max_attempts - 1:  # Don't sleep on last attempt
                    if self.verbose:
                        click.echo(f"Response incomplete, waiting... (attempt {attempt + 1}/{max_attempts})")
                    time.sleep(2)  # Wait before retrying

            if spinner:
                spinner.stop()

            if not response_chunks:
                if not self.verbose:
                    click.echo("No response received from server")
                return None

            if self.verbose:
                click.echo(f"Received {len(response_chunks)} response chunks")

            try:
                complete_encrypted_response = self.chunker.reassemble_response(response_chunks)
                decrypted_response = self.crypto.decrypt(complete_encrypted_response)
                return decrypted_response
            except Exception as e:
                if self.verbose:
                    click.echo(f"Error decrypting response: {e}")
                    click.echo(f"Encrypted data length: {len(complete_encrypted_response) if complete_encrypted_response else 0}")
                    if complete_encrypted_response:
                        click.echo(f"Encrypted data starts with: {complete_encrypted_response[:50]}")
                return None

        finally:
            if spinner:
                spinner.stop()

    def get_server_info(self) -> Optional[Dict[str, str]]:
        """Get the server version and model info."""
        import json
        try:
            version_query = format_dns_query("v")
            response = self._send_dns_query(version_query)
            if response and response != "NOT_FOUND":
                # Handle quoted TXT records
                if response.startswith('"') and response.endswith('"'):
                    response = response[1:-1]

                # Try to parse as JSON (new format)
                try:
                    return json.loads(response)
                except json.JSONDecodeError:
                    # Fallback to old format (just version string)
                    return {"version": response, "model": None}
            return None
        except Exception:
            return None

    def test_connection(self) -> bool:
        """Test basic connectivity to the DNS server."""
        try:
            # Try a simple DNS query to test connectivity
            test_query = format_dns_query("t")
            question = DNSQuestion(test_query, QTYPE.TXT)
            header = DNSHeader(id=random.randint(1, 65535))
            q = DNSRecord(header, q=question)
            query_data = q.pack()

            # Set shorter timeout for connection test
            original_timeout = self.sock.gettimeout()
            self.sock.settimeout(5.0)

            self.sock.sendto(query_data, (self.server_host, self.server_port))
            response_data, _ = self.sock.recvfrom(4096)

            # Restore original timeout
            self.sock.settimeout(original_timeout)

            # If we got any response, connection is working
            return True
        except Exception:
            return False

    def cleanup_session(self):
        """Send cleanup signal to server to clear session data."""
        try:
            # Send a cleanup query to help server clear session data
            cleanup_query = format_dns_query("c", self.session_id)  # 'c' for cleanup
            self._send_dns_query(cleanup_query)
        except Exception:
            pass  # Cleanup is best-effort

    def close(self):
        """Close the client connection."""
        self.cleanup_session()
        self.sock.close()


@click.group()
def cli():
    """DNS-based LLM proxy client."""
    pass


@cli.command()
@click.option('--server', default='127.0.0.1', help='DNS server address')
@click.option('--port', default=5353, help='DNS server port')
@click.option('--message', '-m', help='Single message to send')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.option('--poll-interval', default=0.5, help='Polling interval in seconds for streaming responses')
@click.option('--model', default='LLM', help='Model name to display in chat (for display purposes only)')
def chat(server, port, message, verbose, poll_interval, model):
    """Start a chat session with the LLM through DNS."""
    client = DNSLLMClient(server, port, verbose=verbose, poll_interval=poll_interval, model=model)

    # Test connection first
    if not verbose:
        spinner = SimpleSpinner("Testing connection")
        spinner.start()

    connection_ok = client.test_connection()

    if not verbose:
        spinner.stop()

    if connection_ok:
        # Get server info
        server_info = client.get_server_info()
        client_version = client.client_version

        if server_info:
            server_version = server_info.get("version")
            server_model = server_info.get("model")

            if server_model:
                click.echo(f"✓ Connected to DNS server at {server}:{port}")
                click.echo(f"  Server: {server_version} (model: {server_model})")
                click.echo(f"  Client: {client_version}")
            else:
                click.echo(f"✓ Connected to DNS server at {server}:{port} (server: {server_version}, client: {client_version})")

            # Check for version mismatch
            if server_version and server_version != client_version:
                click.echo(f"⚠️  WARNING: Version mismatch detected!")
                click.echo(f"   Server version: {server_version}")
                click.echo(f"   Client version: {client_version}")
        else:
            click.echo(f"✓ Connected to DNS server at {server}:{port} (client: {client_version})")
            click.echo("⚠️  Could not retrieve server version - using older server?")

        if verbose:
            click.echo("Connection test successful - chat is ready!")
    else:
        click.echo(f"✗ Failed to connect to DNS server at {server}:{port}")
        click.echo("Please check that the server is running and accessible.")
        client.close()
        return

    try:
        if message:
            response = client.send_message(message, show_spinner=not verbose, streaming=not verbose)
            if response and verbose:
                click.echo(response)
            elif not verbose:
                click.echo()  # Add newline after streaming response
        else:
            click.echo("Chat session started. Type '/quit' to exit, '/help' for commands.")
            click.echo()

            while True:
                try:
                    user_input = input("> ")
                    if user_input.lower() in ['/quit', '/exit']:
                        break

                    # Move cursor up one line and overwrite the input with grey color
                    print(f"\033[1A\033[K> \033[90m{user_input}\033[0m")

                    response = client.send_message(user_input, show_spinner=not verbose, streaming=not verbose)
                    if response and verbose:
                        click.echo(response)
                    elif response and not verbose:
                        click.echo()  # Add newline after streaming response
                    else:
                        click.echo("No response received or error occurred.")

                except (KeyboardInterrupt, EOFError):
                    break

    finally:
        client.close()
        click.echo("Chat session ended.")


@cli.command()
@click.option('--server', default='127.0.0.1', help='DNS server address')
@click.option('--port', default=5353, help='DNS server port')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.option('--poll-interval', default=0.5, help='Polling interval in seconds for streaming responses')
@click.option('--model', default='LLM', help='Model name to display in chat (for display purposes only)')
def test_connection(server, port, verbose, poll_interval, model):
    """Test connection to the DNS server."""
    client = DNSLLMClient(server, port, verbose=verbose, poll_interval=poll_interval, model=model)

    try:
        click.echo(f"Testing connection to {server}:{port}")

        # First test basic connectivity
        if not verbose:
            spinner = SimpleSpinner("Testing basic connectivity")
            spinner.start()

        basic_connection = client.test_connection()

        if not verbose:
            spinner.stop()

        if not basic_connection:
            click.echo("✗ Basic connectivity test failed")
            click.echo("Server is not reachable or not responding to DNS queries")
            return

        # Get server info
        server_info = client.get_server_info()
        client_version = client.client_version

        if server_info:
            server_version = server_info.get("version")
            server_model = server_info.get("model")

            if server_model:
                click.echo(f"✓ Basic connectivity test passed")
                click.echo(f"  Server: {server_version} (model: {server_model})")
                click.echo(f"  Client: {client_version}")
            else:
                click.echo(f"✓ Basic connectivity test passed (server: {server_version}, client: {client_version})")

            # Check for version mismatch
            if server_version and server_version != client_version:
                click.echo(f"⚠️  WARNING: Version mismatch detected!")
                click.echo(f"   Server version: {server_version}")
                click.echo(f"   Client version: {client_version}")
        else:
            click.echo(f"✓ Basic connectivity test passed (client: {client_version})")
            click.echo("⚠️  Could not retrieve server version - using older server?")

        # Test full message flow
        click.echo("Testing full message flow...")
        response = client.send_message("Hello, this is a test message.", show_spinner=not verbose)

        if response:
            click.echo(f"✓ Full test successful!")
            click.echo(f"Response: {response}")
        else:
            click.echo("✗ Message flow test failed - no response received")

    finally:
        client.close()


if __name__ == '__main__':
    cli()