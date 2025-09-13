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
```

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
- Consider using DNS over HTTPS (DoH) or DNS over TLS (DoT) for additional transport security
- Monitor DNS query patterns to avoid detection

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

## License

Educational and research purposes only.