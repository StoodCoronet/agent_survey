"""DeepSeek client via the OpenAI-compatible endpoint."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from openai import APIConnectionError, OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.config import Config
from ..core.db import DB


def input_hash(
    stage: str, model: str, prompt_version: str, messages: list[dict], topic_name: str = ""
) -> str:
    h = hashlib.sha256()
    h.update(stage.encode())
    h.update(b"|")
    h.update(model.encode())
    h.update(b"|")
    h.update(prompt_version.encode())
    h.update(b"|")
    if topic_name:
        h.update(topic_name.encode())
        h.update(b"|")
    h.update(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode())
    return h.hexdigest()[:32]


class DeepSeekClient:
    def __init__(self, cfg: Config, stage_name: str = "llm"):
        if not cfg.deepseek_api_key:
            raise RuntimeError(
                "deepseek_api_key not configured. "
                "Set it in config/base.yaml (api_keys.deepseek) or DEEPSEEK_API_KEY in .env"
            )
        self.cfg = cfg
        self.api_key = cfg.deepseek_api_key
        self.base_url = cfg.deepseek_base_url
        import httpx as _httpx
        proxy = cfg.get_proxy(stage_name)
        http_client = _httpx.Client(proxy=proxy, trust_env=False)
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            http_client=http_client,
            default_headers={"User-Agent": "Mozilla/5.0 (compatible; survey-agent/1.0)"},
        )

    def _chat_json_requests(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Fallback using requests when httpx fails (DNS/cache issues)."""
        import requests

        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; survey-agent/1.0)",
        }
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
            proxies={},  # bypass HTTP_PROXY from .env
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content") or "{}"
        usage = data.get("usage")
        return {
            "content": json.loads(content),
            "raw": content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens") if usage else None,
                "completion_tokens": usage.get("completion_tokens") if usage else None,
                "total_tokens": usage.get("total_tokens") if usage else None,
            },
            "model": data.get("model", model),
        }

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=10))
    def chat_json(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                timeout=timeout,
            )
            content = resp.choices[0].message.content or "{}"
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                start = content.find("{")
                end = content.rfind("}")
                if start >= 0 and end > start:
                    data = json.loads(content[start : end + 1])
                else:
                    raise
            usage = getattr(resp, "usage", None)
            return {
                "content": data,
                "raw": content,
                "usage": {
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                } if usage else None,
                "model": model,
            }
        except APIConnectionError:
            # httpx/DNS issue → fallback to requests
            return self._chat_json_requests(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )


def cached_chat_json(
    client: DeepSeekClient,
    db: DB,
    *,
    paper_id: str,
    stage: str,
    model: str,
    prompt_version: str,
    messages: list[dict],
    temperature: float = 0.0,
    max_tokens: int = 1024,
    topic_name: str = "",
    timeout: float = 120.0,
    validate: Callable[[dict], bool] | None = None,
) -> dict[str, Any]:
    ih = input_hash(stage, model, prompt_version, messages, topic_name)
    hit = db.get_llm_cached(ih)

    # --- cache read validation ---
    if hit and hit.get("response"):
        resp = dict(hit["response"])
        if validate is None or validate(resp):
            resp["cached"] = True
            return resp
        # polluted cache: delete and fall through to API call
        db._conn.execute("DELETE FROM llm_calls WHERE input_hash=?", (ih,))
        db._conn.commit()

    # --- API call ---
    result = client.chat_json(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    result["cached"] = False

    # --- cache write validation ---
    if validate is not None and not validate(result):
        raise ValueError(f"LLM response failed validation for {paper_id} (stage={stage})")

    db.save_llm_call(
        paper_id=paper_id,
        stage=stage,
        model=model,
        prompt_version=prompt_version,
        input_hash=ih,
        response=result,
    )
    return result


# Prompts are now loaded from topics/<name>.yaml per-topic configuration.
# See TopicConfig.classify and TopicConfig.deepdive in core/config.py.
