# Unified PDF Download Strategy (Survey-Mining + Fulltext)

## 背景

当前 pipeline 有两个 stage 需要下载 PDF：
1. **survey-mining (s03)** — 326 篇 survey candidates，其中 216 篇 ready（有 arxiv_id），107 篇 missing（无来源）
2. **fulltext (s08)** — 所有被 classify 为 core/related/adjacent 的论文，规模更大，venue 更杂

本策略不仅解决 survey-mining 的 107 篇 missing，更要设计为 **fulltext 阶段可复用的通用多源下载组件**。

---

## 核心决策（来自访谈）

| 议题 | 决策 |
|------|------|
| **Scope** | 同时为 survey-mining 和 fulltext 设计通用策略 |
| **Source 范围** | 官方平台优先；同时接受任何 HTTP 200 + 有效 PDF 的链接（含 ResearchGate、GitHub、个人主页） |
| **Playwright** | 共用单 browser + 多 context；每下完一篇立即保存；支持断点续传 |
| **Desktop/Server 分离** | 有链接的在 server 直接下；missing 的包出独立脚本，用户可在 notebook desktop（校园网）上跑 |
| **文件名** | 包含论文标题 slug + dblp_key，如 `benchmarking_long_context_llm_conf_acl_LiGLZLTLTZJ25.pdf` |
| **PDF 验证** | pdfplumber 解析第一页，确认是真正可读的 PDF |
| **彻底失败的论文** | 不做任何记录（就当不存在） |
| **Rate limit** | 每个 source 独立配置，重点考虑 |

---

## 一、Source 优先级矩阵

### Tier 1: 官方开放获取（高优先级，无 auth）

| Source | Venues | URL 模式 | 获取方式 | Rate Limit |
|--------|--------|----------|----------|------------|
| **arXiv** | 通用 | `arxiv.org/pdf/{id}.pdf` | 直接下载 | 无官方 limit， polite 0.5s |
| **ACL Anthology** | ACL/EMNLP/NAACL | `aclanthology.org/{id}.pdf` | Playwright 渲染搜索页 | 无 |
| **OpenReview** | ICLR/ICML/NeurIPS/COLM | `openreview.net/pdf?id={forum_id}` | API 搜索 + 直接下载 | polite 1s |
| **AAAI OJS** | AAAI | `ojs.aaai.org/.../article/download/{aid}/{pid}` | 搜索页 → 文章页提取 `citation_pdf_url` | polite 1.5s |
| **NeurIPS Proceedings** | NeurIPS | `papers.nips.cc/paper/...` | 官网搜索或 DBLP 外链 | polite 1s |
| **PMLR** | ICML | `proceedings.mlr.press/...` | DBLP 外链或官网 | 无 |

### Tier 2: 需校园网/订阅（中优先级）

| Source | Venues | URL 模式 | 获取方式 | 备注 |
|--------|--------|----------|----------|------|
| **ACM DL** | ICSE/TOSEM/CHI/AAAI(部分) | `dl.acm.org/doi/pdf/{doi}` | Playwright 模拟点击下载 | 校园网可访问；httpx 常 403 |
| **IEEE Xplore** | IEEE 会议 | `ieeexplore.ieee.org/...` | Playwright 或 DOI 直链 | 需订阅 |

### Tier 3: 通用搜索引擎（fallback）

| Source | 获取方式 | 问题 |
|--------|----------|------|
| **Bing 国际版** | Playwright 渲染 + 提取链接 | 国内 IP 强制跳转 cn.bing.com，需点击"国际版"标签 |
| **DuckDuckGo HTML** | `html.duckduckgo.com/html/?q=...` | 服务端渲染，无 IP 跳转；待充分测试 |
| **Google Scholar** | 需要 API 或代理 | 反爬极严，不推荐 |

### Tier 4: 非官方/社区来源（信任但记录实际域名）

- ResearchGate (`researchgate.net/publication/...`)
- GitHub (`github.com/.../*.pdf`)
- 作者个人主页 / 大学机构库
- Semantic Scholar（部分 PDF 直链）

---

## 二、各 Venue 的标准处理流程

```
论文(venue=X, title=T, dblp_key=K)
    │
    ▼
Step 1: 查 DB
    ├── pdf_url 存在且非 arxiv？→ 直接下载（Tier 2/3/4 来源）
    ├── arxiv_id 存在？→ arxiv.org/pdf/{id}.pdf
    │
    ▼
Step 2: 按 Venue 路由到官方平台
    ├── ACL/EMNLP/NAACL → ACL Anthology Playwright 搜索
    ├── ICLR/ICML/NeurIPS → OpenReview API 搜索
    ├── AAAI → OJS 搜索 → 提取 citation_pdf_url
    ├── NeurIPS → papers.nips.cc 搜索
    └── 其他 → 跳过官方平台，直接进入 Step 3
    │
    ▼
Step 3: 搜索引擎 Fallback（DuckDuckGo / Bing）
    ├── 搜索标题，提取前 5 个结果链接
    ├── 标题匹配验证（归一化比对）
    ├── 访问匹配链接，验证返回的是 PDF（Content-Type + pdfplumber）
    └── 记录实际来源域名
    │
    ▼
Step 4: 彻底失败 → 放弃（不做任何记录）
```

---

## 三、Playwright 架构

### 核心设计：单 Browser + 多 Context

```python
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)

def download_one(paper, context_pool):
    # 每个论文一个独立 context（cookie/session 隔离）
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 ...",
        locale="en-US",
    )
    page = ctx.new_page()
    # ... 执行下载 ...
    ctx.close()
```

### 断点续传机制

1. **每下载完一篇立即写 DB** — 不要等 batch 完成
2. **状态追踪表** — 记录每篇论文的下载状态：`pending` / `downloading` / `verified` / `failed`
3. **重启后跳过已完成** — 脚本启动时查询 DB，只处理 `pending` 或 `failed` 的论文
4. **临时文件保护** — 下载时先写 `.tmp` 文件，验证通过后再重命名为 `.pdf`，避免中断留下损坏文件

### Headless 反爬应对

如果服务器 headless 被检测（如 ACM DL 返回 CAPTCHA）：
1. 服务器端脚本检测到反爬标记（`captcha`、`unusual traffic`、`please verify` 等文字）
2. 将该论文标记为 `needs_desktop`
3. 导出 `needs_desktop` 列表 + 下载脚本，用户复制到 notebook desktop 上跑
4. Desktop 跑完后，将 PDF 文件传回 server，执行迁移脚本更新 DB

---

## 四、Rate Limit 配置

```yaml
# config.yaml 新增
pdf_download:
  source_pools:
    arxiv:
      workers: 10
      delay: 0.5        # polite delay between downloads
      max_retries: 2
    acl_anthology:
      workers: 5
      delay: 1.0
      playwright: true  # 需要浏览器渲染
    openreview:
      workers: 5
      delay: 1.0
      max_retries: 3
    aaai_ojs:
      workers: 3
      delay: 1.5        # OJS 搜索 + 文章页 = 2 次请求/论文
      max_retries: 2
    neurips:
      workers: 3
      delay: 1.0
    search_engines:       # DuckDuckGo / Bing
      workers: 3
      delay: 2.0        # 搜索引擎反爬更严
      max_retries: 2
    acm_dl:
      workers: 1          # ACM 极严，单线程
      delay: 5.0
      playwright: true
```

---

## 五、PDF 验证

使用 `pdfplumber` 解析第一页，确认：
1. 文件以 `%PDF` 开头（magic bytes）
2. 文件大小 > 10KB（过滤掉 HTML 错误页）
3. `pdfplumber.open(path).pages[0].extract_text()` 能提取到非空文本

```python
def validate_pdf(path: Path) -> bool:
    if path.stat().st_size < 10240:
        return False
    if not path.read_bytes()[:4] == b'%PDF':
        return False
    try:
        with pdfplumber.open(path) as pdf:
            text = pdf.pages[0].extract_text()
            return bool(text and len(text.strip()) > 50)
    except Exception:
        return False
```

验证失败 → 删除文件 → 标记为 `failed` → 允许重试（最多 3 次）。

---

## 六、Server / Desktop 分离工作流

### Server 端（自动跑）

```bash
# 1. 处理所有"有明确链接"的论文（arxiv, pdf_url）
survey_agent survey-mining --phase download --skip-resolve

# 2. 处理官方平台可 API/爬虫 获取的（OpenReview, AAAI OJS, NeurIPS）
python scripts/download_official.py --venues AAAI,ICLR,ICML,NeurIPS

# 3. 生成"需要 desktop"的清单
python scripts/export_desktop_batch.py
# 输出: desktop_batch/needs_desktop.json + download_desktop.py
```

### Desktop 端（用户手动跑）

```bash
# 用户将 desktop_batch/ 目录复制到笔记本
# 在笔记本上（校园网环境）：
cd desktop_batch
python download_desktop.py

# 完成后将 pdfs/ 目录传回 server
rsync -av pdfs/ server:/path/to/output/llm-context-management/pdfs/
```

### Server 端（迁移）

```bash
# 4. 将 desktop 下载的 PDF 迁移到正式目录并更新 DB
python scripts/migrate_desktop_pdfs.py --source desktop_batch/pdfs/
```

---

## 七、文件命名规范

格式：
```
{title_slug}_{dblp_key_suffix}.pdf
```

示例：
```
benchmarking_long_context_language_models_conf_acl_LiGLZLTLTZJ25.pdf
```

- `title_slug`: 前 5-8 个单词的小写连字符形式，方便肉眼核对
- `dblp_key_suffix`: DBLP key 的最后部分（唯一标识符），保证不冲突

数据库 `papers.pdf_path` 存相对路径（`output/llm-context-management/pdfs/...`），`pdf_source` 存实际来源（`arxiv`, `acl_anthology`, `openreview`, `aaai_ojs`, `bing_search`, `desktop_manual` 等）。

---

## 八、集成到 Fulltext (s08)

当前 fulltext 只有 arxiv 单源下载。未来 fulltext 应复用本策略的通用下载器：

```python
# 未来 fulltext 的伪代码
def download_fulltext(paper):
    if paper.arxiv_id:
        return download_arxiv(paper.arxiv_id)
    if paper.pdf_url:
        return download_direct(paper.pdf_url)
    # 按 venue 路由到官方平台
    return venue_router.download(paper)
```

复用组件：
- `services/pdf_downloader.py` — 通用下载器（支持多 source、rate limit、验证）
- `services/venue_router.py` — venue → source 路由表
- `services/playwright_pool.py` — 共享 browser context 池

---

## 九、行动项

| 优先级 | 任务 | 负责人 | 备注 |
|--------|------|--------|------|
| P0 | 实现 `scripts/download_official.py`（OpenReview + AAAI OJS + NeurIPS）| Claude | 先用 httpx/API，不需要 Playwright |
| P0 | 修复 ACL Anthology 下载（Playwright 搜索页渲染）| Claude | 单 browser + 多 context |
| P1 | 实现 DuckDuckGo 搜索引擎 fallback | Claude | 服务端渲染，无需浏览器 |
| P1 | 实现断点续传 + PDF 验证（pdfplumber）| Claude | 每篇下载完立即写 DB |
| P1 | 生成 desktop batch 导出脚本 | Claude | `export_desktop_batch.py` |
| P2 | 集成到 fulltext (s08) | 后续 | 等 survey-mining 稳定后 |
| P2 | ACM DL Playwright 下载 | 后续 | 需要校园网环境测试 |

---

## 附录：各平台搜索接口速查

| 平台 | 搜索 URL | 结果提取 |
|------|----------|----------|
| arXiv API | `https://export.arxiv.org/api/query?search_query=ti:"..."` | XML Atom feed |
| ACL Anthology | `https://aclanthology.org/search/?q=...` | Playwright 渲染 |
| OpenReview | `https://api.openreview.net/notes/search?term=...&limit=10` | JSON API |
| AAAI OJS | `https://ojs.aaai.org/index.php/AAAI/search?query=...` | HTML 正则 |
| NeurIPS | `https://papers.nips.cc/cgi-bin/search.py?search=...` | HTML 正则 |
| DuckDuckGo | `https://html.duckduckgo.com/html/?q=...` | HTML 正则 |
| DBLP | `https://dblp.org/rec/{dblp_key}.html` | HTML 外链提取 |
