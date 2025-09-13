# DNS-based LLM Proxy

A DNS-based LLM proxy system that tunnels encrypted chat messages through DNS TXT records, providing a covert channel for AI interactions.

## Features

- End-to-end encryption using Fernet (symmetric encryption)
- DNS TXT record transport for covert communication
- Automatic message chunking to handle DNS size limitations
- Session-based message handling with unique session IDs
- CLI client and server for easy deployment and usage
- OpenAI integration for LLM processing

## How It Works

1. Client encrypts message with Fernet encryption
2. Encrypted data is base64-encoded and split into DNS-compatible chunks
3. Chunks sent as DNS queries: msg.sessionid.index.total.data.llm.local
4. Server reassembles, decrypts, and processes with LLM (OpenAI)
5. Response is encrypted, chunked, and returned via DNS TXT records
6. Client fetches chunks: get.sessionid.index.llm.local
7. Client reassembles and decrypts the response

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd llm-dns-proxy

# Install dependencies
uv pip install -e .
```

## Configuration

Set up the following environment variables:

```bash
# Required: OpenAI API key
export OPENAI_API_KEY="your-openai-api-key"

# Optional: Custom OpenAI base URL (for LocalAI, Ollama, etc.)
export OPENAI_BASE_URL="https://api.openai.com/v1"

# Optional: OpenAI model (defaults to gpt-3.5-turbo)
export OPENAI_MODEL="gpt-4"

# Optional: Custom encryption key (will generate one if not provided)
export LLM_PROXY_KEY="your-base64-encryption-key"
```

### Supported Providers

The system supports any OpenAI-compatible API:

- **OpenAI**: `https://api.openai.com/v1` (default)
- **LocalAI**: `http://localhost:8080/v1`
- **Ollama**: `http://localhost:11434/v1`
- **OpenRouter**: `https://openrouter.ai/api/v1`
- **Any custom OpenAI-compatible server**

## Usage

### Generate Encryption Key

```bash
python -m llm_dns_proxy.cli server --generate-key
```

### Start the DNS Server

```bash
# Basic server (uses environment variables)
python -m llm_dns_proxy.cli server --host 127.0.0.1 --port 5353

# With custom OpenAI-compatible server
python -m llm_dns_proxy.cli server \
  --openai-base-url http://localhost:8080/v1 \
  --openai-model llama-2-7b-chat

# With Ollama
python -m llm_dns_proxy.cli server \
  --openai-base-url http://localhost:11434/v1 \
  --openai-model llama2
```

### Start a Chat Session

```bash
# Interactive chat
python -m llm_dns_proxy.cli client chat

# Single message
python -m llm_dns_proxy.cli client chat -m "Hello, how are you?"

# Custom server
python -m llm_dns_proxy.cli client chat --server 192.168.1.100 --port 5353
```

### Test Connection

```bash
python -m llm_dns_proxy.cli client test-connection
```

## Testing

Run the comprehensive test suite:

```bash
pytest
```

## License

Educational and research purposes only.