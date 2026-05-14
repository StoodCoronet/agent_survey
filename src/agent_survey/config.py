"""Configuration loading."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"
DEFAULT_ENV = PROJECT_ROOT / ".env"

_PATH_ALIASES = {"json": "json_dir"}


class VenueCfg(BaseModel):
    name: str
    area: str
    aliases: list[str] = Field(default_factory=list)
    key_prefixes: list[str] = Field(default_factory=list)
    # When set, skip DBLP `venue:` search and fetch the per-year TOC XML
    # directly from https://dblp.org/db/<toc_stream><year>.xml.
    # Use for venues whose venue: index is broken (e.g. USENIX Security).
    toc_stream: str | None = None
    # For journals whose per-year `venue:` index is missing: fetch the
    # per-volume XML from https://dblp.org/db/<journal_stream><vol>.xml.
    # `journal_volumes` maps year -> list of volumes that belong to that year.
    journal_stream: str | None = None
    journal_volumes: dict[int, list[int]] = Field(default_factory=dict)
    # External JSON source (e.g. COLM mini-conf serve_papers.json).
    # {year} placeholder will be substituted.
    json_source_url: str | None = None
    # Years to skip for this venue (e.g. NAACL 2023 does not exist).
    skip_years: list[int] = Field(default_factory=list)


class VenuesCfg(BaseModel):
    conferences: list[VenueCfg] = Field(default_factory=list)
    journals: list[VenueCfg] = Field(default_factory=list)


class YearsCfg(BaseModel):
    start: int
    end: int


class KeywordsCfg(BaseModel):
    agent_core: list[str] = Field(default_factory=list)
    agent_generic: list[str] = Field(default_factory=list)
    se_context: list[str] = Field(default_factory=list)
    sec_context: list[str] = Field(default_factory=list)


class LLMStageCfg(BaseModel):
    model: str
    temperature: float = 0.0
    max_tokens: int = 1024
    prompt_version: str = "v1"


class LLMCfg(BaseModel):
    stage3_classify: LLMStageCfg
    stage5_deepdive: LLMStageCfg


class PathsCfg(BaseModel):
    model_config = {"populate_by_name": True}

    db: str
    json_dir: str = Field(alias="json")
    markdown: str
    obsidian: str
    pdfs: str
    llm_cache: str


class NetworkCfg(BaseModel):
    user_agent: str = "agent-survey/0.1"
    max_concurrency: int = 6
    request_timeout: int = 30


class Config(BaseModel):
    years: YearsCfg
    venues: VenuesCfg
    keywords: KeywordsCfg
    llm: LLMCfg
    paths: PathsCfg
    network: NetworkCfg = Field(default_factory=NetworkCfg)

    # resolved at load time
    project_root: Path = PROJECT_ROOT
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    semantic_scholar_api_key: str = ""

    def abs_path(self, key: str) -> Path:
        attr = _PATH_ALIASES.get(key, key)
        rel = getattr(self.paths, attr)
        p = Path(rel)
        if not p.is_absolute():
            p = self.project_root / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def abs_dir(self, key: str) -> Path:
        p = self.abs_path(key)
        p.mkdir(parents=True, exist_ok=True)
        return p


def load_config(config_path: Path | None = None, env_path: Path | None = None) -> Config:
    config_path = config_path or DEFAULT_CONFIG
    env_path = env_path or DEFAULT_ENV
    if env_path.exists():
        load_dotenv(env_path)
    data: dict[str, Any] = yaml.safe_load(config_path.read_text())
    cfg = Config(**data)
    cfg.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "")
    cfg.deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", cfg.deepseek_base_url)
    cfg.semantic_scholar_api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    return cfg
