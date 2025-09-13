"""
Version utilities for the LLM DNS Proxy.
"""

import subprocess
import os
from typing import Optional


def get_git_sha() -> Optional[str]:
    """Get the short git SHA hash of the current repository."""
    try:
        # Get the directory of this file to find the git repo root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(current_dir)  # Go up one level from llm_dns_proxy/

        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return None

    except Exception:
        return None


def get_version_string() -> str:
    """Get a version string with git SHA if available."""
    sha = get_git_sha()
    if sha:
        return f"git-{sha}"
    else:
        return "unknown"