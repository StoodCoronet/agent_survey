"""Configuration loading."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_ENV = PROJECT_ROOT / ".env"
TOPICS_DIR = PROJECT_ROOT / "topics"

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
    timeout: float = 120.0


class LLMCfg(BaseModel):
    stage3_classify: LLMStageCfg
    stage5_deepdive: LLMStageCfg
    stage10_category_desc: LLMStageCfg | None = None
    stage11_summary: LLMStageCfg | None = None


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
    http_proxy: str = ""
    stage_proxies: dict[str, str | None] = Field(default_factory=dict)


class EnrichSourceWorker(BaseModel):
    s2: int = 2
    arxiv: int = 2
    openreview: int = 5
    openreview_forum: int = 5
    aclanthology: int = 10
    crossref: int = 10
    playwright: int = 8
    cache: int = 20


class EnrichCfg(BaseModel):
    source_workers: EnrichSourceWorker = EnrichSourceWorker()
    venue_strategies: dict[str, list[str]] = {}


class DocsCfg(BaseModel):
    server_port: int = 48000


class ApiKeysCfg(BaseModel):
    deepseek: str = ""
    semantic_scholar: str = ""


class Config(BaseModel):
    years: YearsCfg
    venues: VenuesCfg
    keywords: KeywordsCfg
    llm: LLMCfg
    paths: PathsCfg
    network: NetworkCfg = Field(default_factory=NetworkCfg)
    enrich: EnrichCfg = Field(default_factory=EnrichCfg)
    docs: DocsCfg = Field(default_factory=DocsCfg)
    active_topic: str = ""
    api_keys: ApiKeysCfg = Field(default_factory=ApiKeysCfg)
    deepseek_base_url: str = "https://api.deepseek.com"

    # resolved at load time
    project_root: Path = PROJECT_ROOT

    # Back-compat shortcuts (populated by load_config)
    deepseek_api_key: str = ""
    semantic_scholar_api_key: str = ""
    http_proxy: str = ""

    def get_proxy(self, stage_name: str = "") -> str | None:
        """Return proxy for a stage: stage override > default http_proxy > None.

        Supports two stage_proxies key styles:
          - plain:  "survey_mining"
          - ordered: "s03_survey_mining"
        """
        if stage_name:
            override = self.network.stage_proxies.get(stage_name)
            # Fallback: try sNN_<stage_name> pattern
            if override is None:
                for key in self.network.stage_proxies:
                    if key.endswith(f"_{stage_name}"):
                        override = self.network.stage_proxies[key]
                        break
            if override is not None:
                return override if override else None
        return self.network.http_proxy or None

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

    def abs_topic_dir(self, topic_name: str, kind: str = "") -> Path:
        """Per-topic output: output/<topic_name>/<kind>/"""
        p = self.project_root / "output" / topic_name
        if kind:
            p = p / kind
        p.mkdir(parents=True, exist_ok=True)
        return p


def make_http_client(cfg: Config | None = None, stage_name: str = "", **kwargs) -> httpx.Client:
    """Create an httpx.Client, automatically applying per-stage proxy if configured."""
    import httpx

    proxy = None
    if cfg:
        proxy = cfg.get_proxy(stage_name)

    client_kwargs: dict[str, Any] = {
        "timeout": 30,
        "headers": {"User-Agent": "agent-survey/0.1"},
    }
    client_kwargs.update(kwargs)

    if proxy:
        client_kwargs["proxy"] = proxy

    return httpx.Client(**client_kwargs)


# ------------------------------------------------------------------
# Topic configuration
# ------------------------------------------------------------------

class ClassifyPromptCfg(BaseModel):
    relevance_levels: list[str] = Field(default_factory=list)
    domain_labels: list[str] = Field(default_factory=list)
    method_labels: list[str] = Field(default_factory=list)
    core_venues: list[str] = Field(default_factory=list)
    system_prompt: str = ""
    user_prompt_template: str = ""
    user_prompt_title_only: str = ""
    batch_user_prompt_template: str = ""


class DeepdiveCfg(BaseModel):
    system_prompt: str = ""
    user_prompt_template: str = ""


class SurveyMiningCfg(BaseModel):
    """Prompts for auto-discovering survey papers and extracting keywords."""
    discovery_system: str = ""
    discovery_topic_desc: str = ""
    keyword_system: str = ""


class TaxonomyCfg(BaseModel):
    system_prompt: str = ""
    user_prompt_template: str = ""
    trees: dict[str, dict] = Field(default_factory=dict)
    cross_cutting_tags: list[str] = Field(default_factory=list)
    # Map tree leaf paths to flat topic IDs (replaces seed_topics from s06)
    flat_labels: dict[str, str] = Field(default_factory=dict)
    # ── Auto-create settings (legacy threshold-based) ──
    auto_create_leaves: bool = True
    auto_create_threshold: float = 0.8
    # ── New: fully-automatic maintenance with LLM judge ──
    auto_create_judge_model: str = "deepseek-v4-pro"
    # Minimum number of papers proposing this leaf before submitting to judge
    auto_create_min_papers: int = 3
    # If True, write approved leaves directly back to topics/<name>.yaml
    auto_create_write_yaml: bool = True
    # If True, rejected leaves are downgraded to the closest existing leaf
    auto_create_fallback: bool = True


class TopicConfig(BaseModel):
    """Configuration for a single survey topic (loaded from topics/<name>.yaml)."""
    name: str = ""
    description: str = ""
    keywords: KeywordsCfg = Field(default_factory=KeywordsCfg)
    search_queries: list[str] = Field(default_factory=list)
    classify: ClassifyPromptCfg = Field(default_factory=ClassifyPromptCfg)
    deepdive: DeepdiveCfg = Field(default_factory=DeepdiveCfg)
    taxonomy: TaxonomyCfg = Field(default_factory=TaxonomyCfg)
    survey_mining: SurveyMiningCfg = Field(default_factory=SurveyMiningCfg)

    # set by loader
    topic_name: str = ""
    config_path: Path | None = None


def load_topic_config(topic_name: str) -> TopicConfig:
    """Load a single topic config from topics/<name>.yaml.

    Merges taxonomy extensions (new leaves/trees discovered by LLM in prior runs)
    from output/<topic>/taxonomy_extensions.json.
    """
    path = TOPICS_DIR / f"{topic_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Topic config not found: {path}")
    data: dict[str, Any] = yaml.safe_load(path.read_text())
    tc = TopicConfig(**data)
    tc.topic_name = topic_name
    tc.config_path = path

    # Merge saved taxonomy extensions
    import json
    ext_path = PROJECT_ROOT / "output" / topic_name / "taxonomy_extensions.json"
    if ext_path.exists():
        try:
            ext = json.loads(ext_path.read_text(encoding="utf-8"))
            for tree_name, branches in ext.get("trees", {}).items():
                if tree_name not in tc.taxonomy.trees:
                    tc.taxonomy.trees[tree_name] = {}
                for branch, leaves in branches.items():
                    if branch not in tc.taxonomy.trees[tree_name]:
                        tc.taxonomy.trees[tree_name][branch] = leaves
                    else:
                        old = set(tc.taxonomy.trees[tree_name][branch])
                        old.update(leaves)
                        tc.taxonomy.trees[tree_name][branch] = sorted(old)
            tc.taxonomy.flat_labels.update(ext.get("flat_labels", {}))
        except Exception:
            pass
    return tc


def load_stage_config(stage_name: str) -> dict[str, Any]:
    """Load a stage-specific config from config/stages/.

    Supports two naming conventions (checked in order):
      1. sNN_<stage_name>.yaml  — e.g. s02_enrich.yaml (preferred, pipeline-ordered)
      2. <stage_name>.yaml       — plain name fallback
    """
    stages_dir = CONFIG_DIR / "stages"
    ordered = stages_dir / f"s??_{stage_name}.yaml"
    candidates = sorted(stages_dir.glob(f"s*_{stage_name}.yaml"))
    if candidates:
        return yaml.safe_load(candidates[0].read_text()) or {}
    plain = stages_dir / f"{stage_name}.yaml"
    if plain.exists():
        return yaml.safe_load(plain.read_text()) or {}
    return {}


def list_topics() -> list[str]:
    """List available topic names (from topics/*.yaml files)."""
    if not TOPICS_DIR.exists():
        return []
    return sorted(
        p.stem for p in TOPICS_DIR.glob("*.yaml")
        if not p.name.startswith("_")
    )


def resolve_topic(topic_name: str | None = None, config: Config | None = None) -> str:
    """Resolve topic name: explicit arg > Config.active_topic > raise."""
    if topic_name:
        return topic_name
    if config and config.active_topic:
        return config.active_topic
    available = list_topics()
    if len(available) == 1:
        return available[0]
    raise RuntimeError(
        "No topic specified. Use --topic <name> or set active_topic in config/base.yaml. "
        f"Available topics: {', '.join(available) if available else '(none)'}"
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config(config_path: Path | None = None, env_path: Path | None = None) -> Config:
    env_path = env_path or DEFAULT_ENV
    if env_path.exists():
        load_dotenv(env_path)

    # Prefer config/ directory; fallback to single config.yaml
    if CONFIG_DIR.exists():
        merged: dict[str, Any] = {}
        for f in sorted(CONFIG_DIR.rglob("*.yaml")):
            part = yaml.safe_load(f.read_text()) or {}
            _deep_merge(merged, part)
        cfg = Config(**merged)
    else:
        config_path = config_path or DEFAULT_CONFIG
        data: dict[str, Any] = yaml.safe_load(config_path.read_text())
        cfg = Config(**data)

    # API keys: YAML > .env fallback
    cfg.deepseek_api_key = cfg.api_keys.deepseek or os.getenv("DEEPSEEK_API_KEY", "")
    cfg.semantic_scholar_api_key = cfg.api_keys.semantic_scholar or os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    cfg.deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", cfg.deepseek_base_url)

    # Proxy: network.http_proxy from YAML > .env fallback
    env_proxy = (
        os.getenv("HTTPS_PROXY", "")
        or os.getenv("https_proxy", "")
        or os.getenv("HTTP_PROXY", "")
        or os.getenv("http_proxy", "")
    )
    cfg.network.http_proxy = cfg.network.http_proxy or env_proxy
    cfg.http_proxy = cfg.network.http_proxy  # back-compat shortcut

    # Publish configured proxy back to env so curl / requests subprocesses
    # pick it up automatically.  DeepSeekClient explicitly uses trust_env=False
    # so LLM calls are not affected by these vars.
    if cfg.network.http_proxy:
        os.environ["HTTP_PROXY"] = cfg.network.http_proxy
        os.environ["HTTPS_PROXY"] = cfg.network.http_proxy
        os.environ["http_proxy"] = cfg.network.http_proxy
        os.environ["https_proxy"] = cfg.network.http_proxy
    else:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.pop(key, None)
    return cfg
