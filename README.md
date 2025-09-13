# Tunneling LLM Conversations Through DNS

**What if you could access your favorite LLM from airplane WiFi without paying fees for internet?**

This project exploits a fundamental oversight in network restrictions: while most traffic gets blocked until you authenticate or pay, DNS queries almost always work. That "Sign in to continue" page on airplane WiFi? It still needs DNS to load. This tool tunnels encrypted LLM conversations through that same DNS channel for free, unrestricted access.

The technique, known as DNS tunneling, is an old school hack inspired by tools like [iodine](https://github.com/yarrick/iodine) that have been smuggling data through DNS for years. This implementation adapts the classic approach for the AI era: masking your conversations as mundane DNS lookups, chunking and encrypting messages across multiple queries that sail right through captive portals, corporate firewalls, and network filters. Perfect for when you need AI access but the network wants your credit card first.


## Demo

What it looks like to an outside observer:
```bash
# Network admin sees innocent DNS queries
dig msg.abc123.1.2.SGVsbG8gV29ybGQ.llm.example.com TXT
dig get.abc123.1.llm.example.com TXT
```

What's actually happening:
```bash
You: "What's the weather in Tokyo?"
AI: "Currently 22°C and sunny in Tokyo, with light winds..."
```

The conversation is fully encrypted and split across multiple DNS queries that look like routine network activity.

## Features

- **End-to-end encryption** using Fernet (AES-128) symmetric encryption
- **DNS steganography** - conversations hidden in normal-looking DNS queries
- **Automatic chunking** - handles message size limitations transparently
- **Token streaming** - receive LLM responses in real-time, chunk by chunk
- **Session persistence** - maintains conversation context across requests
- **Multiple LLM providers** - OpenAI, LocalAI, Ollama, or any OpenAI-compatible API
- **Web search integration** - real-time information via Perplexity AI
- **Production deployment** - works anywhere DNS resolution is available
- **Simple architecture** - client/server model with minimal dependencies

## How It Works

The protocol works by encoding encrypted chat messages as DNS subdomain queries:

1. **Message encryption**: Client encrypts message using Fernet symmetric encryption
2. **Chunking**: Encrypted data is base64-encoded and split into DNS-compatible segments
3. **DNS encoding**: Each chunk becomes a subdomain query:
   ```
   msg.sessionid.index.total.encrypted_data.llm.yourdomain.com
   ```
4. **Server processing**: DNS server receives queries, reassembles chunks, decrypts, and sends to LLM
5. **Response encoding**: AI response is encrypted, chunked, and stored as DNS TXT records
6. **Response retrieval**: Client fetches response chunks via DNS TXT queries:
   ```
   get.sessionid.chunk_index.llm.yourdomain.com
   ```
7. **Decryption**: Client reassembles chunks and decrypts the final response

To external observers, this appears as standard DNS resolution activity.

# Disclaimer
This is a proof of concept for educational purposes only. I'm not responsible if you get into trouble using this tool. Use at your own risk and always comply with network policies and terms of service.

## Installation

```bash
git clone https://github.com/accupham/llm-dns-proxy
cd llm-dns-proxy
uv sync
```

## Configuration

Set up the following environment variables:

```bash
# Required: OpenAI API key
export OPENAI_API_KEY="your-openai-api-key"

# Optional: Custom OpenAI base URL (for LocalAI, Ollama, etc.)
export OPENAI_BASE_URL="https://api.openai.com/v1"

# Optional: OpenAI model (defaults to gpt-4o)
export OPENAI_MODEL="gpt-4"

# Optional: Custom encryption key (will generate one if not provided)
export LLM_PROXY_KEY="your-base64-encryption-key"

# Optional: Perplexity API key for web search capabilities
export PERPLEXITY_API_KEY="your-perplexity-api-key"
```

### Web Search Setup

To enable web search capabilities via Perplexity AI:

1. **Get Perplexity API Key**: Visit [Perplexity AI](https://www.perplexity.ai/) to obtain an API key
2. **Set Environment Variable**: `export PERPLEXITY_API_KEY="your-perplexity-api-key"`
3. **Use in Conversations**: The LLM will automatically use the `web_search` tool when needed

Example usage:
```bash
You: "What's the weather like in New York today?"
Assistant: I'll search for current weather information...
[Uses web_search tool automatically]
```

You can also explicitly request web searches:
```bash
You: "Use web search to find the latest news about AI developments"
Assistant: [Searches the web and provides current information]
```

### Supported Providers

The system supports any OpenAI-compatible API:

- **OpenAI**: `https://api.openai.com/v1` (default)
- **LocalAI**: `http://localhost:8080/v1`
- **Ollama**: `http://localhost:11434/v1`
- **OpenRouter**: `https://openrouter.ai/api/v1`
- **Any custom OpenAI-compatible server**

## DNS Server Setup

### Local Testing

For local testing, the default setup works out of the box:

```bash
# Generate encryption key
python -m llm_dns_proxy.cli server --generate-key

# Start server on localhost
python -m llm_dns_proxy.cli server --host 127.0.0.1 --port 5353

# Start client (in another terminal)
python -m llm_dns_proxy.cli client chat
```

### Production Deployment

For production deployment where clients will connect over the internet, you need to set up proper DNS infrastructure:

#### 1. Domain Setup

You need a domain (or subdomain) that you control. For this example, we'll use `llm.yourdomain.com`.

#### 2. DNS Records Configuration

Configure these DNS records with your domain provider:

```dns
; A record pointing to your server's public IP
llm.yourdomain.com.     IN  A       203.0.113.10

; NS record for the subdomain (delegates DNS queries to your server)
*.llm.yourdomain.com.   IN  NS      llm.yourdomain.com.
```

**Alternative approach using subdomain delegation:**
```dns
; Create a subdomain specifically for the proxy
proxy.yourdomain.com.   IN  A       203.0.113.10
*.proxy.yourdomain.com. IN  NS      proxy.yourdomain.com.
```

#### 3. Server Configuration

Deploy the server on your target machine:

```bash
# Install on target server
git clone <your-repo>
cd llm-dns-proxy
uv pip install -e .

# Set environment variables
export OPENAI_API_KEY="your-api-key"
export LLM_PROXY_KEY="your-encryption-key"
export PERPLEXITY_API_KEY="your-perplexity-api-key"  # Optional: for web search

# Start server on port 53 (requires root/sudo)
sudo python -m llm_dns_proxy.cli server --host 0.0.0.0 --port 53

# Or use port 5353 with systemctl/supervisor and port forwarding
python -m llm_dns_proxy.cli server --host 0.0.0.0 --port 5353
```

#### 4. Firewall Configuration

Ensure DNS traffic can reach your server:

```bash
# Ubuntu/Debian with UFW
sudo ufw allow 53/udp
sudo ufw allow 53/tcp

# CentOS/RHEL with firewalld
sudo firewall-cmd --permanent --add-port=53/udp
sudo firewall-cmd --permanent --add-port=53/tcp
sudo firewall-cmd --reload

# Check if port is listening
sudo netstat -tulpn | grep :53
```

#### 5. Testing DNS Resolution

Test your DNS setup before running the proxy:

```bash
# Test A record resolution
dig llm.yourdomain.com A

# Test NS delegation
dig @llm.yourdomain.com test.llm.yourdomain.com TXT

# Test with external DNS resolver
dig @8.8.8.8 test.llm.yourdomain.com TXT
```

#### 6. Production Server Commands

```bash
# Start server for production domain
sudo python -m llm_dns_proxy.cli server \
  --host 0.0.0.0 \
  --port 53 \
  --openai-base-url https://api.openai.com/v1 \
  --openai-model gpt-4

# With custom OpenAI-compatible server
sudo python -m llm_dns_proxy.cli server \
  --host 0.0.0.0 \
  --port 53 \
  --openai-base-url http://localhost:8080/v1 \
  --openai-model llama-2-7b-chat
```

#### 7. Client Configuration for Production

Update client to use your domain:

```python
# Edit client.py or use environment variable
DEFAULT_SERVER = "llm.yourdomain.com"  # Replace with your domain
```

Or use command line options:

```bash
# Connect to production server
python -m llm_dns_proxy.cli client chat \
  --server llm.yourdomain.com \
  --port 53
```

#### 8. Service Management (Optional)

Create a systemd service for automatic startup:

```bash
# Create service file
sudo tee /etc/systemd/system/llm-dns-proxy.service > /dev/null <<EOF
[Unit]
Description=LLM DNS Proxy Server
After=network.target

[Service]
Type=simple
User=llm-proxy
WorkingDirectory=/opt/llm-dns-proxy
Environment=OPENAI_API_KEY=your-api-key-here
Environment=LLM_PROXY_KEY=your-encryption-key-here
Environment=PERPLEXITY_API_KEY=your-perplexity-api-key-here
ExecStart=/usr/local/bin/python -m llm_dns_proxy.cli server --host 0.0.0.0 --port 53
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl enable llm-dns-proxy
sudo systemctl start llm-dns-proxy
sudo systemctl status llm-dns-proxy
```

## Usage

### Local Development

```bash
# Generate encryption key
python -m llm_dns_proxy.cli server --generate-key

# Start server
python -m llm_dns_proxy.cli server --host 127.0.0.1 --port 5353

# Start client (in another terminal)
python -m llm_dns_proxy.cli client chat
```

### Chat Commands

```bash
# Interactive chat (tests connection automatically)
python -m llm_dns_proxy.cli client chat

# Single message
python -m llm_dns_proxy.cli client chat -m "Hello, how are you?"

# Clear conversation history
python -m llm_dns_proxy.cli client chat -m "/clear"

# Custom server and port
python -m llm_dns_proxy.cli client chat --server your.domain.com --port 53

# Verbose mode (shows detailed progress, no spinner)
python -m llm_dns_proxy.cli client chat -v

# Verbose mode with single message
python -m llm_dns_proxy.cli client chat -v -m "Hello, how are you?"

# Examples with web search (requires PERPLEXITY_API_KEY)
python -m llm_dns_proxy.cli client chat -m "What's the latest news about AI?"
python -m llm_dns_proxy.cli client chat -m "Search for current weather in Tokyo"
python -m llm_dns_proxy.cli client chat -m "Find recent updates on cryptocurrency prices"
```

### Web Search Features

When `PERPLEXITY_API_KEY` is configured, the system supports:

- **Automatic Web Search**: The AI automatically decides when to search the web for current information
- **Real-time Data**: Get up-to-date information on news, weather, prices, etc.
- **Source-backed Responses**: Web search results include citations and sources
- **Tool Call Integration**: Seamless integration using OpenAI's function calling system

Examples of queries that trigger web search:
- "What's the current stock price of Apple?"
- "Latest news about space exploration"
- "Today's weather in London"
- "Recent developments in quantum computing"
- "Current exchange rate USD to EUR"

### Test Connection

```bash
# Test local server (with spinner)
python -m llm_dns_proxy.cli client test-connection

# Test remote server
python -m llm_dns_proxy.cli client test-connection --server your.domain.com --port 53

# Verbose mode (detailed output, no spinner)
python -m llm_dns_proxy.cli client test-connection -v
```

### User Experience Features

- **Automatic Connection Testing**: Chat commands now test connectivity before starting
- **Visual Feedback**: Spinner animations show progress during message processing (disabled in verbose mode)
- **Verbose Mode**: Use `-v` flag to see detailed debugging information instead of spinners
- **Better Error Messages**: Clear indication of connection status and failure reasons

## Security Considerations

### Encryption
- Messages are encrypted using Fernet (AES 128) symmetric encryption
- Generate a strong encryption key and keep it secure
- Use different keys for different deployments

### Network Security
- DNS queries are visible to network infrastructure (though encrypted)
- Some IDS/IPS systems may flag unusual DNS patterns

### Key Management
```bash
# Generate a secure encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Store securely
export LLM_PROXY_KEY="your-generated-key-here"
```

## Troubleshooting

### Common Issues

**1. "Permission denied" when binding to port 53**
```bash
# Use sudo for port 53
sudo python -m llm_dns_proxy.cli server --host 0.0.0.0 --port 53

# Or use port 5353 and configure port forwarding
iptables -t nat -A PREROUTING -p udp --dport 53 -j REDIRECT --to-port 5353
```

**2. "DNS query timeout" errors**
```bash
# Check if server is listening
sudo netstat -tulpn | grep :53

# Test DNS resolution
dig @your-server-ip test.llm.yourdomain.com TXT

# Check firewall
sudo ufw status
```

**3. "Base64 decoding errors"**
- Ensure proper domain delegation (NS records)
- Check that DNS queries preserve case sensitivity
- Verify encryption keys match between client and server

**4. OpenAI API errors**
```bash
# Test API key
curl -H "Authorization: Bearer $OPENAI_API_KEY" https://api.openai.com/v1/models

# For custom endpoints
curl -H "Authorization: Bearer $OPENAI_API_KEY" $OPENAI_BASE_URL/models
```

**5. Web search not working**
```bash
# Test Perplexity API key
curl -H "Authorization: Bearer $PERPLEXITY_API_KEY" https://api.perplexity.ai/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"sonar-pro","messages":[{"role":"user","content":"test"}]}'

# Check if web_search tool is available (should show 1 tool)
# Look for "Tools available: 1" in server logs when starting

# Verify environment variable is set
echo $PERPLEXITY_API_KEY
```

### Debug Mode

Enable verbose logging for troubleshooting:

```python
# Add to server startup
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Monitoring

Monitor DNS query patterns and server performance:

```bash
# Monitor DNS queries (requires tcpdump)
sudo tcpdump -i any -n port 53

# Monitor server logs
journalctl -u llm-dns-proxy -f

# Check system resources
htop
```

## Testing

Run the comprehensive test suite:

```bash
pytest
```

Test individual components:

```bash
# Test encryption
pytest tests/test_crypto.py -v

# Test chunking
pytest tests/test_chunking.py -v

# Test LLM integration
pytest tests/test_llm.py -v

# Test server functionality
pytest tests/test_server.py -v
```


## See Also
- https://ch.at/