"""DeepSeek client via the OpenAI-compatible endpoint."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import Config
from ..db import DB


def input_hash(stage: str, model: str, prompt_version: str, messages: list[dict]) -> str:
    h = hashlib.sha256()
    h.update(stage.encode())
    h.update(b"|")
    h.update(model.encode())
    h.update(b"|")
    h.update(prompt_version.encode())
    h.update(b"|")
    h.update(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode())
    return h.hexdigest()[:32]


class DeepSeekClient:
    def __init__(self, cfg: Config):
        if not cfg.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set in .env")
        self.client = OpenAI(
            api_key=cfg.deepseek_api_key,
            base_url=cfg.deepseek_base_url,
        )

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30))
    def chat_json(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        resp = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # best-effort cleanup
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
) -> dict[str, Any]:
    ih = input_hash(stage, model, prompt_version, messages)
    hit = db.get_llm_cached(ih)
    if hit and hit.get("response"):
        resp = dict(hit["response"])
        resp["cached"] = True
        return resp
    result = client.chat_json(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    result["cached"] = False
    db.save_llm_call(
        paper_id=paper_id,
        stage=stage,
        model=model,
        prompt_version=prompt_version,
        input_hash=ih,
        response=result,
    )
    return result
