"""Semantic Scholar client — abstract lookup + relevance search."""
from __future__ import annotations

import time
from typing import Iterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ._curl_fallback import curl_get_json

S2_API = "https://api.semanticscholar.org/graph/v1"

# polite rate — unauthenticated API is ~1 req/sec
DEFAULT_DELAY = 1.1


class S2Client:
    def __init__(self, api_key: str = "", timeout: int = 30):
        headers = {"User-Agent": "agent-survey/0.1"}
        if api_key:
            headers["x-api-key"] = api_key
        self.client = httpx.Client(timeout=timeout, headers=headers)
        self.delay = 0.3 if api_key else DEFAULT_DELAY

    def close(self) -> None:
        self.client.close()

    def _request_with_backoff(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json: dict | None = None,
        max_retries: int = 3,
    ) -> dict | list:
        """Send request with 429 backoff and retry."""
        for attempt in range(max_retries):
            if method == "GET":
                r = self.client.get(f"{S2_API}{path}", params=params)
            else:
                r = self.client.post(f"{S2_API}{path}", params=params, json=json)

            if r.status_code == 429:
                wait = 5 * (2 ** attempt)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        raise httpx.HTTPStatusError(
            f"429 after {max_retries} retries",
            request=r.request,
            response=r,
        )

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._request_with_backoff("GET", path, params=params)

    def _post(self, path: str, json: dict, params: dict | None = None) -> dict | list:
        return self._request_with_backoff("POST", path, params=params, json=json)

    # --------- abstract lookup ---------

    def batch_lookup(
        self, ids: list[str], fields: str = "title,abstract,externalIds,openAccessPdf,year,venue"
    ) -> list[dict | None]:
        """Batch look up by S2 IDs or DOI: / ARXIV: prefixes.

        Returns list aligned with input; entries may be None if not found.
        """
        if not ids:
            return []
        out: list[dict | None] = []
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            data = self._post(
                "/paper/batch", json={"ids": chunk}, params={"fields": fields}
            )
            if isinstance(data, list):
                out.extend(data)
            else:
                out.extend([None] * len(chunk))
            time.sleep(self.delay)
        return out

    def search_by_title(
        self, title: str, fields: str = "title,abstract,externalIds,openAccessPdf,year,venue"
    ) -> dict | None:
        """Fuzzy title search -> best match."""
        params = {"query": title[:300], "fields": fields}
        data: dict | None = None
        try:
            data = self._get("/paper/search/match", params=params)
        except Exception:
            # macOS Anaconda OpenSSL 3.0 TLS handshake failure — fallback to curl
            data = curl_get_json(f"{S2_API}/paper/search/match", params=params)
        time.sleep(self.delay)
        if isinstance(data, dict):
            items = data.get("data") or []
            if items:
                return items[0]
        return None

    # --------- keyword search (recall branch) ---------

    def search_relevance(
        self,
        query: str,
        *,
        year_start: int | None = None,
        year_end: int | None = None,
        limit_per_page: int = 100,
        max_results: int = 1000,
        fields: str = "title,abstract,externalIds,venue,year,openAccessPdf",
    ) -> Iterator[dict]:
        params: dict = {"query": query, "limit": limit_per_page, "fields": fields}
        if year_start and year_end:
            params["year"] = f"{year_start}-{year_end}"
        elif year_start:
            params["year"] = f"{year_start}-"
        offset = 0
        got = 0
        while got < max_results:
            params["offset"] = offset
            data = self._get("/paper/search", params=params)
            items = data.get("data") or []
            if not items:
                break
            for it in items:
                yield it
                got += 1
                if got >= max_results:
                    break
            nxt = data.get("next")
            if nxt is None or nxt == offset:
                break
            offset = nxt
            time.sleep(self.delay)
