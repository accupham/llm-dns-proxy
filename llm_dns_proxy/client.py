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
from .chunking import DNSChunker


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
    def __init__(self, server_host: str = "127.0.0.1", server_port: int = 5353, crypto_key: bytes = None, verbose: bool = False):
        self.server_host = server_host
        self.server_port = server_port
        self.crypto = CryptoManager(crypto_key)
        self.chunker = DNSChunker()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(30.0)
        self.verbose = verbose

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
        session_id = str(uuid.uuid4())[:8]
        spinner = None

        try:
            if self.verbose:
                click.echo(f"Encrypting message...")
            encrypted_data = self.crypto.encrypt(message)

            if self.verbose:
                click.echo(f"Creating message chunks...")
            chunks = self.chunker.create_chunks(encrypted_data, session_id)

            if show_spinner and not self.verbose:
                spinner = SimpleSpinner("-->")
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

        # Initial wait for processing to start
        time.sleep(1)

        while True:
            response_chunks = self._get_current_response_chunks(session_id)

            if not response_chunks:
                time.sleep(0.1)
                continue

            try:
                current_encrypted = self.chunker.reassemble_response(response_chunks)
                current_content = self.crypto.decrypt(current_encrypted)

                # Display new content
                if len(current_content) > len(last_content):
                    new_content = current_content[len(last_content):]
                    sys.stdout.write(new_content)
                    sys.stdout.flush()
                    last_content = current_content

                    # Check if this looks like a complete response
                    # Simple heuristic: if content ends with sentence punctuation and hasn't changed for a bit
                    if current_content.rstrip().endswith(('.', '!', '?', '\n')):
                        time.sleep(0.5)  # Wait to see if more content comes

                        # Check again
                        new_chunks = self._get_current_response_chunks(session_id)
                        if new_chunks:
                            try:
                                new_encrypted = self.chunker.reassemble_response(new_chunks)
                                new_content_check = self.crypto.decrypt(new_encrypted)

                                if new_content_check == current_content:
                                    # No change, likely complete
                                    final_response = current_content
                                    break

                            except Exception:
                                pass

                time.sleep(0.1)  # Small delay between polls

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
        max_chunks = 50  # Reasonable limit

        while chunk_index < max_chunks:
            query = f"get.{session_id}.{chunk_index}.llm.local"
            response = self._send_dns_query(query)

            if response == "NOT_FOUND":
                break

            if response and ':' in response:
                parts = response.split(':', 2)
                if len(parts) == 3:
                    current_index = int(parts[0])
                    total_chunks = int(parts[1])
                    response_chunks[current_index] = response

                    if len(response_chunks) >= total_chunks:
                        break

            chunk_index += 1

        return response_chunks

    def _handle_traditional_response(self, session_id: str, show_spinner: bool) -> Optional[str]:
        """Handle traditional non-streaming response."""
        spinner = None

        try:
            if show_spinner and not self.verbose:
                spinner = SimpleSpinner("...")
                spinner.start()
            elif self.verbose:
                click.echo("Message sent, waiting for processing...")

            time.sleep(2)

            if spinner:
                spinner.stop()
                spinner = SimpleSpinner("<--")
                spinner.start()
            elif self.verbose:
                click.echo("Retrieving response chunks...")

            response_chunks = {}
            chunk_index = 0
            max_retries = 10

            while chunk_index < max_retries:
                query = f"get.{session_id}.{chunk_index}.llm.local"
                response = self._send_dns_query(query)

                if response == "NOT_FOUND":
                    if chunk_index == 0:
                        time.sleep(1)
                        continue
                    else:
                        break

                if response and ':' in response:
                    parts = response.split(':', 2)
                    if len(parts) == 3:
                        current_index = int(parts[0])
                        total_chunks = int(parts[1])
                        response_chunks[current_index] = response

                        if len(response_chunks) >= total_chunks:
                            break

                chunk_index += 1

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
                return None

        finally:
            if spinner:
                spinner.stop()

    def test_connection(self) -> bool:
        """Test basic connectivity to the DNS server."""
        try:
            # Try a simple DNS query to test connectivity
            test_query = "test.connection.llm.local"
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

    def close(self):
        """Close the client connection."""
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
def chat(server, port, message, verbose):
    """Start a chat session with the LLM through DNS."""
    client = DNSLLMClient(server, port, verbose=verbose)

    # Test connection first
    if not verbose:
        spinner = SimpleSpinner("Testing connection")
        spinner.start()

    connection_ok = client.test_connection()

    if not verbose:
        spinner.stop()

    if connection_ok:
        click.echo(f"✓ Connected to DNS server at {server}:{port}")
        if verbose:
            click.echo("Connection test successful - chat is ready!")
    else:
        click.echo(f"✗ Failed to connect to DNS server at {server}:{port}")
        click.echo("Please check that the server is running and accessible.")
        client.close()
        return

    try:
        if message:
            click.echo(f"You: {message}")
            if not verbose:
                click.echo("Assistant: ", nl=False)
            response = client.send_message(message, show_spinner=not verbose, streaming=not verbose)
            if response and verbose:
                click.echo(f"Assistant: {response}")
            elif not verbose:
                click.echo()  # Add newline after streaming response
        else:
            click.echo("Starting DNS LLM chat. Type 'quit' to exit.")
            click.echo("=" * 50)

            while True:
                try:
                    user_input = click.prompt("You", type=str)
                    if user_input.lower() in ['quit', 'exit']:
                        break

                    if not verbose:
                        click.echo("Assistant: ", nl=False)
                    response = client.send_message(user_input, show_spinner=not verbose, streaming=not verbose)
                    if response and verbose:
                        click.echo(f"Assistant: {response}")
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
def test_connection(server, port, verbose):
    """Test connection to the DNS server."""
    client = DNSLLMClient(server, port, verbose=verbose)

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

        click.echo("✓ Basic connectivity test passed")

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