"""
Command-line interface for the DNS-based LLM proxy system.
"""

import os
import click
from .server import LLMDNSServer
from .client import cli as client_cli
from .crypto import CryptoManager


@click.group()
def main():
    """DNS-based LLM proxy system."""
    pass


@main.command()
@click.option('--host', default='127.0.0.1', help='Server host address')
@click.option('--port', default=5353, help='Server port')
@click.option('--openai-base-url', help='OpenAI API base URL (for custom servers like LocalAI, Ollama, etc.)')
@click.option('--openai-model', help='OpenAI model to use (overrides OPENAI_MODEL env var)')
@click.option('--generate-key', is_flag=True, help='Generate a new encryption key')
def server(host, port, openai_base_url, openai_model, generate_key):
    """Start the DNS server."""
    if generate_key:
        key = CryptoManager.generate_key()
        click.echo(f"Generated encryption key: {key.decode()}")
        click.echo("Set this as LLM_PROXY_KEY environment variable")
        return

    crypto_key = os.getenv('LLM_PROXY_KEY')
    if crypto_key:
        crypto_key = crypto_key.encode()

    openai_api_key = os.getenv('OPENAI_API_KEY')
    if not openai_api_key:
        click.echo("Error: OPENAI_API_KEY environment variable is required")
        return

    # Use CLI parameters or fallback to environment variables
    base_url = openai_base_url or os.getenv('OPENAI_BASE_URL')
    model = openai_model or os.getenv('OPENAI_MODEL')

    click.echo(f"Starting DNS server on {host}:{port}")
    if base_url:
        click.echo(f"Using custom OpenAI base URL: {base_url}")
    if model:
        click.echo(f"Using model: {model}")

    server_instance = LLMDNSServer(host, port, crypto_key, openai_api_key, base_url, model)

    try:
        server_instance.run()
    except KeyboardInterrupt:
        click.echo("Server stopped")


main.add_command(client_cli, name='client')


if __name__ == '__main__':
    main()