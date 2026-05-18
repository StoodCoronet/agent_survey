"""Curl fallback for Python SSL/TLS failures on macOS Anaconda."""
from __future__ import annotations

import json
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any


def _build_url(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    qs = urllib.parse.urlencode(params)
    return f"{url}?{qs}"


def curl_get_text(url: str, params: dict[str, Any] | None = None, timeout: int = 30) -> str | None:
    """GET URL via curl, return body text or None on failure."""
    full_url = _build_url(url, params)
    try:
        result = subprocess.run(
            ["curl", "-s", "-L", "--max-time", str(timeout), full_url],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except Exception:
        pass
    return None


def curl_get_json(url: str, params: dict[str, Any] | None = None, timeout: int = 30) -> dict | None:
    text = curl_get_text(url, params, timeout)
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return None


def curl_get_xml_text(url: str, params: dict[str, Any] | None = None, timeout: int = 30) -> str | None:
    text = curl_get_text(url, params, timeout)
    # arXiv returns a 301 redirect with no body, then HTTPS with body
    if text:
        # Some APIs return HTML redirect pages — skip if no XML tags
        if "<" not in text:
            return None
    return text
