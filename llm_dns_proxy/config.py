"""
Configuration utilities for DNS suffix and other settings.
"""

import os


def get_dns_suffix() -> str:
    """Get the DNS suffix from environment variable or return default."""
    return os.getenv('LLM_DNS_SUFFIX', '_sonos._tcp.local')


def get_dns_suffix_parts() -> list:
    """Get DNS suffix as a list of parts for validation."""
    suffix = get_dns_suffix()
    return suffix.split('.')


def format_dns_query(prefix: str, *parts) -> str:
    """Format a complete DNS query with the configured suffix."""
    suffix = get_dns_suffix()
    if parts:
        middle_parts = '.'.join(str(part) for part in parts)
        return f"{prefix}.{middle_parts}.{suffix}"
    else:
        return f"{prefix}.{suffix}"


def validate_dns_suffix_in_query(query_parts: list) -> bool:
    """Validate that query ends with the configured DNS suffix."""
    expected_parts = get_dns_suffix_parts()

    # Handle trailing dot
    if query_parts and query_parts[-1] == '':
        query_parts = query_parts[:-1]

    if len(query_parts) < len(expected_parts):
        return False

    return query_parts[-len(expected_parts):] == expected_parts