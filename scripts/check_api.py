#!/usr/bin/env python3
"""Check DeepSeek API connectivity and diagnose connection issues."""
from __future__ import annotations

import os
import socket
import ssl
import sys
import time
import urllib.request
from pathlib import Path

# Load .env
dotenv = Path(__file__).parent.parent / ".env"
if dotenv.exists():
    for line in dotenv.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = "deepseek-v4-flash"


def check_dns():
    """Check if api.deepseek.com resolves."""
    host = BASE_URL.replace("https://", "").replace("http://", "").split("/")[0]
    try:
        ip = socket.gethostbyname(host)
        print(f"✅ DNS OK: {host} -> {ip}")
        return True
    except Exception as e:
        print(f"❌ DNS FAIL: {host} -> {e}")
        return False


def check_tcp():
    """Check TCP connection to port 443."""
    host = BASE_URL.replace("https://", "").replace("http://", "").split("/")[0]
    try:
        sock = socket.create_connection((host, 443), timeout=10)
        sock.close()
        print(f"✅ TCP OK: {host}:443 connected")
        return True
    except Exception as e:
        print(f"❌ TCP FAIL: {host}:443 -> {e}")
        return False


def check_tls():
    """Check TLS handshake."""
    host = BASE_URL.replace("https://", "").replace("http://", "").split("/")[0]
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                print(f"✅ TLS OK: {ssock.version()} cert={ssock.getpeercert()['subject']}")
        return True
    except Exception as e:
        print(f"❌ TLS FAIL: {e}")
        return False


def check_http():
    """Check HTTP GET to base URL."""
    try:
        req = urllib.request.Request(
            BASE_URL,
            headers={"User-Agent": "survey-agent-check/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"✅ HTTP OK: {BASE_URL} -> {resp.status}")
            return True
    except Exception as e:
        print(f"❌ HTTP FAIL: {BASE_URL} -> {e}")
        return False


def check_api_openai():
    """Check API call via OpenAI SDK."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        start = time.monotonic()
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=10,
            timeout=30,
        )
        elapsed = time.monotonic() - start
        content = resp.choices[0].message.content or "(empty)"
        print(f"✅ API OK ({elapsed:.1f}s): model={resp.model} -> '{content}'")
        return True
    except Exception as e:
        print(f"❌ API FAIL: {type(e).__name__}: {e}")
        return False


def check_api_urllib():
    """Check API call via raw urllib (bypass OpenAI SDK)."""
    if not API_KEY:
        print("⚠️  SKIP: No DEEPSEEK_API_KEY in .env")
        return None
    url = f"{BASE_URL}/v1/chat/completions"
    payload = (
        b'{"model":"'
        + MODEL.encode()
        + b'","messages":[{"role":"user","content":"Say OK"}],"max_tokens":10}'
    )
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = time.monotonic() - start
            body = resp.read().decode()[:200]
            print(f"✅ API(urllib) OK ({elapsed:.1f}s): {body}")
            return True
    except Exception as e:
        print(f"❌ API(urllib) FAIL: {type(e).__name__}: {e}")
        return False


def main():
    print(f"Config: BASE_URL={BASE_URL}")
    print(f"Config: API_KEY={'set' if API_KEY else 'NOT SET'}")
    print(f"Config: MODEL={MODEL}")
    print()

    results = {
        "DNS": check_dns(),
        "TCP": check_tcp(),
        "TLS": check_tls(),
        "HTTP": check_http(),
        "API(urllib)": check_api_urllib(),
        "API(OpenAI)": check_api_openai(),
    }

    print()
    ok = [k for k, v in results.items() if v is True]
    fail = [k for k, v in results.items() if v is False]
    skip = [k for k, v in results.items() if v is None]
    print(f"Summary: {len(ok)} passed, {len(fail)} failed, {len(skip)} skipped")
    if fail:
        print(f"Failed: {', '.join(fail)}")
        print("\nDiagnosis:")
        if "DNS" in fail:
            print("  - Network/DNS issue. Check internet connection.")
        elif "TCP" in fail:
            print("  - Firewall or network block. Check VPN/proxy.")
        elif "TLS" in fail:
            print("  - SSL/TLS issue. Check system CA certificates.")
        elif "HTTP" in fail:
            print("  - DeepSeek server returning errors. Check status page.")
        elif "API(urllib)" in fail or "API(OpenAI)" in fail:
            print("  - API key invalid, rate limited, or model unavailable.")


if __name__ == "__main__":
    main()
