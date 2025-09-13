"""
CLI client for the DNS-based LLM proxy system.
"""

import socket
import time
import uuid
import random
import click
from typing import Dict, List, Optional
from dnslib import DNSRecord, QTYPE, DNSQuestion, DNSHeader

from .crypto import CryptoManager
from .chunking import DNSChunker


class DNSLLMClient:
    def __init__(self, server_host: str = "127.0.0.1", server_port: int = 5353, crypto_key: bytes = None):
        self.server_host = server_host
        self.server_port = server_port
        self.crypto = CryptoManager(crypto_key)
        self.chunker = DNSChunker()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(30.0)

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
                    txt_data = str(rr.rdata)
                    # Handle quoted TXT records
                    if txt_data.startswith('"') and txt_data.endswith('"'):
                        return txt_data[1:-1]
                    return txt_data

            return None

        except Exception as e:
            click.echo(f"DNS query error: {e}")
            return None

    def send_message(self, message: str) -> Optional[str]:
        """Send a message to the LLM through DNS and get the response."""
        session_id = str(uuid.uuid4())[:8]

        click.echo(f"Encrypting message...")
        encrypted_data = self.crypto.encrypt(message)

        click.echo(f"Creating message chunks...")
        chunks = self.chunker.create_chunks(encrypted_data, session_id)

        click.echo(f"Sending {len(chunks)} chunks...")
        for i, chunk in enumerate(chunks):
            click.echo(f"Sending chunk {i+1}/{len(chunks)}")
            response = self._send_dns_query(chunk)
            if response != "OK":
                click.echo(f"Warning: Unexpected response for chunk {i+1}: {response}")

        click.echo("Message sent, waiting for processing...")
        time.sleep(2)

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

        if not response_chunks:
            click.echo("No response received from server")
            return None

        click.echo(f"Received {len(response_chunks)} response chunks")

        try:
            complete_encrypted_response = self.chunker.reassemble_response(response_chunks)
            decrypted_response = self.crypto.decrypt(complete_encrypted_response)
            return decrypted_response
        except Exception as e:
            click.echo(f"Error decrypting response: {e}")
            return None

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
def chat(server, port, message):
    """Start a chat session with the LLM through DNS."""
    client = DNSLLMClient(server, port)

    try:
        if message:
            click.echo(f"You: {message}")
            response = client.send_message(message)
            if response:
                click.echo(f"Assistant: {response}")
        else:
            click.echo("Starting DNS LLM chat. Type 'quit' to exit.")
            click.echo("=" * 50)

            while True:
                try:
                    user_input = click.prompt("You", type=str)
                    if user_input.lower() in ['quit', 'exit']:
                        break

                    response = client.send_message(user_input)
                    if response:
                        click.echo(f"Assistant: {response}")
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
def test_connection(server, port):
    """Test connection to the DNS server."""
    client = DNSLLMClient(server, port)

    try:
        click.echo(f"Testing connection to {server}:{port}")
        response = client.send_message("Hello, this is a test message.")

        if response:
            click.echo(f"✓ Connection successful!")
            click.echo(f"Response: {response}")
        else:
            click.echo("✗ Connection failed or no response received")

    finally:
        client.close()


if __name__ == '__main__':
    cli()