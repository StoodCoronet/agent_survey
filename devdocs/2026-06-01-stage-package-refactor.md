# Stage Package 统一重构规范

> 目标：让每个 stage 按需拆分为 package，统一爬虫系 / LLM 系 / 数据处理系的内部结构，提取 LLM batch 公共模板，为后续策略细化（venue-specific fetcher、per-topic prompt、taxonomy 维度扩展）提供可插拔的骨架。

---

## 一、Stage 三分类体系

| 分类 | 包含 Stage | 核心特征 |
|------|-----------|---------|
| **爬虫系 (Crawler)** | `s00_harvest`, `s01_enrich`, `s01_enrich_web`, `s04_fulltext` | 依赖外部网络/IO，多数据源，有 rate limit 和 retry |
| **LLM 系 (LLM)** | `s03_classify`, `s05_deepdive`, `s07_taxonomy`, `s09_short_titles`, `s10_category_desc`, `s11_summary` | 核心逻辑是 "构建 prompt → batch 调用 LLM → 解析结果 → 写入 DB" |
| **数据处理系 (Transform)** | `s00b_search_recall`, `s02_prefilter`, `s06b_subtopic_dedup` | 纯本地计算/过滤，无外部网络或 LLM 依赖 |

> **废弃**：`s06_topics` 已合并入 `s07_taxonomy`，本次重构直接删除 `s06_topics/`。

---

## 二、每类 Stage 的目录结构规范

### 2.1 爬虫系 (Crawler)

```
stages/s01_enrich/                # 示例：enrich
  __init__.py                     # from .run import run
  run.py                          # 主入口：线程池、进度条、DB 写入、checkpoint
  sources.py                      # 通用数据源查询（S2 / arXiv / OpenReview）
  strategies/                     # venue-specific 策略子包
    __init__.py                   # VENUE_FETCHERS 显式注册表
    usenix.py                     # USS fetcher
    ndss.py                       # NDSS fetcher
    ...                           # 未来新增 venue 策略
```

**命名约定**（爬虫系内部统一）：
- `run.py`：主入口，必须导出 `run(cfg, **kwargs) -> dict`
- `sources.py`：通用数据源查询逻辑（不绑定具体 venue）
- `strategies/`：venue-specific 或 platform-specific 的策略子包
- 策略文件以平台/venue 命名（如 `usenix.py`, `ndss.py`, `acm.py`）

**策略注册**（显式注册）：
```python
# strategies/__init__.py
from .usenix import fetch_usenix_abstract
from .ndss import fetch_ndss_abstract

VENUE_FETCHERS: dict[str, callable] = {
    "USS": fetch_usenix_abstract,
    "NDSS": fetch_ndss_abstract,
}
```

### 2.2 LLM 系 (LLM)

```
stages/s03_classify/              # 示例：classify
  __init__.py                     # from .run import run
  run.py                          # 薄层：读取配置 → 调用 llm_batch_framework
  prompts.py                      # prompt 构建：build_messages(papers, cfg) -> list[dict]
  parsers.py                      # 结果解析：parse_result(raw, paper) -> dict
```

**命名约定**（LLM 系内部统一）：
- `run.py`：主入口，调用公共框架完成全流程
- `prompts.py`：所有与 prompt 构建相关的函数（`build_messages`, `build_system_prompt` 等）
- `parsers.py`：所有与 LLM 输出解析相关的函数（`parse_result`, `validate_output` 等）
- 不允许在 `run.py` 里写内联 prompt 字符串或解析逻辑

**公共框架使用**：
```python
# run.py
from ...core.llm_pipeline import llm_batch_run
from .prompts import build_messages
from .parsers import parse_result

def run(cfg: Config, **kwargs) -> dict:
    return llm_batch_run(
        cfg=cfg,
        stage="classify",
        build_messages=build_messages,
        parse_result=parse_result,
        db_update_fn=_update_paper_topics,
        **kwargs,
    )
```

### 2.3 数据处理系 (Transform)

```
stages/s02_prefilter/             # 示例：prefilter
  __init__.py                     # from .run import run
  run.py                          # 主逻辑（通常很短，可保持单文件）
```

**规则**：数据处理系 stage 当前都只有几百行，功能单一，**保持扁平**（`__init__.py` 单文件搞定）。只有当出现多种策略（比如 prefilter 未来支持 "regex 模式" 和 "LLM 轻量过滤模式"）时才拆分。

---

## 三、LLM Batch 公共框架设计

### 3.1 定位

中层模板：提供 "读取论文 → 分批 → 构建 messages → 调用 LLM → 解析 JSON → 写入 DB" 的完整骨架。各 stage 只需填充 `build_messages()` 和 `parse_result()` 两个函数。

### 3.2 文件位置

`src/agent_survey/core/llm_pipeline.py`

### 3.3 接口

```python
def llm_batch_run(
    cfg: Config,
    stage: str,                    # stage 名称，用于缓存 key 和 stats
    build_messages: Callable[[list[dict], Config], list[dict]],
    parse_result: Callable[[dict | str, dict], dict | None],
    db_update_fn: Callable[[DB, str, dict], None],  # (db, paper_id, parsed) -> None
    *,
    topic_name: str = "",
    workers: int = 5,
    batch_size: int = 10,
    dry_run: bool = False,
) -> dict:
    """
    通用 LLM batch 处理框架。

    流程：
    1. 从 DB 读取待处理论文（根据 stage + topic_name 的 completion 状态过滤）
    2. 按 batch_size 分批
    3. 每批调用 build_messages() 构造 LLM messages
    4. 并发调用 LLM（带缓存、重试、进度条）
    5. 每批调用 parse_result() 解析结果
    6. 调用 db_update_fn() 写入 DB
    7. 每 100 篇 commit 一次
    8. 输出统一格式的 stats JSON
    """
```

### 3.4 框架内置能力

- **LLM 缓存**：自动查询 `llm_calls` 表，缓存命中跳过 API 调用
- **进度条**：Rich Progress，显示 processed / filled / failed / rate
- **并发控制**：`ThreadPoolExecutor`，可配置 workers
- **重试**：429/5xx 自动重试（指数退避）
- **Checkpoint**：每 100 篇 `db.commit()`，中断可续跑
- **Dry-run**：`dry_run=True` 时只构建请求、不调用 LLM、不写入 DB，用于验证 prompt
- **Stats 输出**：统一 JSON 格式
  ```json
  {
    "stage": "classify",
    "topic": "gui-agent",
    "processed": 11460,
    "filled": 5230,
    "failed": 120,
    "cached": 3400,
    "by_source": {"llm": 5230, "cache": 3400},
    "success_rate_pct": 45.6,
    "elapsed_sec": 1200
  }
  ```

### 3.5 各 LLM Stage 的适配方式

| Stage | build_messages 输入 | parse_result 输出 | db_update_fn 操作 |
|-------|-------------------|------------------|------------------|
| classify | list[paper] | {relevance, domain, method, ...} | INSERT/UPDATE paper_topics |
| deepdive | list[paper] + PDF text | {problem, approach, evaluation, ...} | INSERT topic_deepdive |
| taxonomy | list[paper] | {tree_path, labels, ...} | UPDATE paper_topics.taxonomy_json |
| short_titles | list[paper] | {short_title} | UPDATE paper_topics.short_title |
| category_desc | list[paper] + tree path | {desc_en, desc_zh} | INSERT taxonomy_descriptions |
| summary | list[paper] | {summary_en, summary_zh} | UPDATE paper_topics.summary_* |

> deepdive 特殊：输入不是论文列表而是单篇论文的 PDF 全文。框架需要支持 `batch_size=1` 和自定义输入加载逻辑。

---

## 四、策略注册机制

### 4.1 原则

不按统一方式强制所有 stage，而是**按业务特征选择最适合的注册方式**。

### 4.2 选择矩阵

| 场景 | 推荐方式 | 理由 |
|------|---------|------|
| Venue fetcher (enrich) | **显式注册** | 策略数量固定（就那么几个会议），一目了然 |
| Taxonomy tree 维度 | **自动发现** | 可能频繁新增，按目录扫描减少 boilerplate |
| Classify prompt 模板 | **配置驱动** | 本质上是文本配置，应放在 topic yaml 中 |

### 4.3 显式注册示例（enrich）

```python
# s01_enrich/strategies/__init__.py
from .usenix import fetch_usenix_abstract
from .ndss import fetch_ndss_abstract

VENUE_FETCHERS: dict[str, callable] = {
    "USS": fetch_usenix_abstract,
    "NDSS": fetch_ndss_abstract,
}
```

新增 venue：
1. 创建 `strategies/<venue>.py`，实现 `fetch_<venue>_abstract(url) -> str | None`
2. 在 `strategies/__init__.py` 中导入并注册

### 4.4 自动发现示例（taxonomy tree）

```python
# services/taxonomy.py
import importlib
from pathlib import Path

def _load_tree_modules() -> dict[str, callable]:
    trees_dir = Path(__file__).parent / "trees"
    modules = {}
    for f in trees_dir.glob("*.py"):
        if f.stem.startswith("_"):
            continue
        mod = importlib.import_module(f"agent_survey.services.trees.{f.stem}")
        modules[f.stem] = mod.build_tree
    return modules
```

新增 tree：丢一个 `.py` 文件到 `services/trees/` 即可。

---

## 五、实施步骤与优先级

### Phase 1: 基础设施（先做）
1. **删除 `s06_topics/`**：确认 `s07_taxonomy` 已覆盖其功能，删除废弃代码
2. **创建 `core/llm_pipeline.py`**：实现中层模板框架
3. **验证框架**：选一个最简单的 LLM stage（如 `s09_short_titles`）迁移到框架上，验证接口设计是否合理

### Phase 2: 爬虫系拆分
4. **拆分 `s00_harvest`**：提取 `fetchers/` 子包（dblp fetcher, external fetcher, journal fetcher）
5. **拆分 `s01_enrich_web`**：提取 `strategies/` 子包（不同网站的 Playwright 策略）
6. **拆分 `s04_fulltext`**：提取 `sources/` 子包（arXiv PDF, OpenReview PDF, publisher PDF）

### Phase 3: LLM 系拆分
7. **迁移 `s09_short_titles`** → 作为框架验证试点
8. **迁移 `s03_classify`** → 最复杂，prompts.py + parsers.py 拆分
9. **迁移 `s05_deepdive`** → 特殊（单篇输入），验证框架的灵活性
10. **迁移 `s07_taxonomy`, `s10_category_desc`, `s11_summary`**

### Phase 4: 数据处理系（保持扁平，按需处理）
11. `s00b_search_recall`, `s02_prefilter`, `s06b_subtopic_dedup` 保持当前结构，如果未来增加策略再拆分

### Phase 5: 验证
12. 在 `gui-agent` topic 上完整跑一遍 pipeline，确认结果与重构前一致
13. 跑 `abstract-coverage` 和 `keyword-stats` 对比重构前后数据

---

## 六、回滚与调试指南

### 6.1 如果某个 stage 重构后行为异常

1. **对比 import 路径**：确认 `__init__.py` 正确导出了 `run` 函数
   ```python
   # 测试命令
   python -c "from agent_survey.stages.s01_enrich import run; print(run)"
   ```

2. **对比相对导入层级**：package 化后 `..` → `...` 的替换是否完整
   ```bash
   grep -r "from \.\." stages/s01_enrich/  # 应无结果
   ```

3. **对比函数签名**：`run(cfg: Config, **kwargs)` 的签名和返回值必须保持不变

4. **对比 DB 写入**：检查重构前后写入的字段和 `enrich_source` / `stage_status_json` 是否一致

### 6.2 如果公共框架引入 bug

框架设计为**可选使用**，不是强制所有 stage 必须接入。如果某个 stage 迁移到框架后出现问题：
- 临时方案：将该 stage 的 `run.py` 改回内联实现
- 长期方案：修复框架接口，重新迁移

### 6.3 快速回滚

所有重构都在 `multi-topic` 分支上进行，git 保留完整历史：
```bash
# 查看重构前最后一个 commit
git log --oneline | head -20

# 回滚单个文件
git checkout <commit> -- src/agent_survey/stages/s03_classify/

# 回滚整个重构
git reset --hard <pre-refactor-commit>
```

---

## 七、不做的决定

- ❌ 不引入 Pydantic ORM 或 SQLModel
- ❌ 不引入 StageRunner 抽象基类或 DAG 编排框架
- ❌ 不强制所有 stage 统一内部文件名（只统一分类体系内的命名）
- ❌ 数据处理系 stage 当前不拆分（保持扁平）
- ❌ 不做 pytest 单元测试框架（保持轻量，靠集成测试验证）
