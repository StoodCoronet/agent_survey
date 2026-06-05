# Survey-Mining 下载策略总结

## 当前状态（截至 2026-06-05）

| 指标 | 数量 |
|------|------|
| 发现 surveys (Phase 1) | **326 篇** |
| 已有本地 PDF | **30 篇** |
| 有 arxiv_id 待下载 | **186 篇** |
| **Missing（无来源）** | **107 篇** |

---

## 一、已有来源的下载流程（已实现）

```
survey_candidates.json
    │
    ▼
查 DB: papers.arxiv_id / papers.pdf_url
    │
    ├── 有 arxiv_id  → pdf_url = https://arxiv.org/pdf/{id}.pdf
    ├── 有 pdf_url   → 直接用 DB 中的 url
    │
    └── 无来源 (missing) ──→ 进入搜索补全（可跳过）
                              │
                              ├── arxiv title search（多 variant 匹配）
                              └── OpenReview fallback（ICLR/ICML/NeurIPS/COLM）
    │
    ▼
生成 download_manifest.json
    │
    ▼
并发下载（5 workers）→ output/{topic}/pdfs/
更新 DB: papers.pdf_path / papers.pdf_source
```

### CLI 调用

```bash
# 完整流程（含搜索补全）
survey_agent survey-mining --phase download

# 跳过 missing 的搜索，只下载 ready 的
survey_agent survey-mining --phase download --skip-resolve
```

---

## 二、Missing 文章处理策略（107 篇）

### Venue 分布

| Venue | 数量 | 推荐渠道 | 开放程度 |
|-------|------|----------|----------|
| **AAAI** | 43 | `ojs.aaai.org` | 高（2023+ 基本开放）|
| **EMNLP** | 18 | `aclanthology.org` | **100% 开放** |
| **ACL** | 10 | `aclanthology.org` | **100% 开放** |
| **ICLR** | 15 | `openreview.net` | **100% 开放** |
| **NeurIPS** | 13 | `papers.nips.cc` / OpenReview | 高 |
| **ICML** | 4 | `openreview.net` / PMLR | **100% 开放** |
| **NAACL** | 4 | `aclanthology.org` | **100% 开放** |

### 分 Venue 处理方案

#### 1. AAAI → OJS 官方平台

- **搜索**: `https://ojs.aaai.org/index.php/AAAI/search?query={title}`
- **文章页**: `https://ojs.aaai.org/index.php/AAAI/article/view/{article_id}`
- **PDF**: 从文章页提取 `<meta name="citation_pdf_url" content="..." />`
- **状态**: ✅ 已验证可行（测试 2/2 成功）

#### 2. ACL / EMNLP / NAACL → ACL Anthology

- **特点**: 全开放，每篇都有 `.pdf` 直链
- **URL 规律**: `https://aclanthology.org/{year}.{venue}-{collection}.{paper_id}/`
- **问题**: Anthology 搜索页是 **JS 渲染**，httpx 抓不到结果
- **替代方案**:
  - 从 **DBLP 页面**提取 anthology 外链（`https://dblp.org/rec/{dblp_key}.html`）
  - DBLP 页面聚合了所有外部链接（Anthology、OpenReview、arXiv、DOI）

#### 3. ICLR / ICML → OpenReview

- **搜索 API**: `https://api.openreview.net/notes/search?term={title}&limit=10`
- **PDF**: `https://openreview.net/pdf?id={forum_id}`
- **状态**: API 可用，但抽查时部分标题未匹配（可能标题差异或不在 OpenReview）

#### 4. NeurIPS → Proceedings / OpenReview

- **官方搜索**: `https://papers.nips.cc/cgi-bin/search.py?search={title}`
- **OpenReview**: 近年 NeurIPS 也在 OpenReview 上
- **状态**: 未充分测试

---

## 三、通用 Fallback（当官方平台找不到时）

### Tier 1: 通用搜索引擎

| 引擎 | 可用性 | 问题 |
|------|--------|------|
| **Bing 国内版** (`cn.bing.com`) | ⚠️ 部分可用 | IP 在中国大陆会被强制跳转国内版，前几条常是词典/百科 |
| **Bing 国际版** | 用户手动测试可用 | 脚本难以模拟（需点击"国际版"标签或特定 cookie）|
| **DuckDuckGo HTML** | 待测试 | 服务端渲染，无 IP 跳转，理论上更稳 |
| **Google** | ❌ 不可用 | JS 渲染 + 反爬严格 |

### Tier 2: 学术聚合平台

- **ResearchGate**: 常有作者上传的 PDF
- **Semantic Scholar**: 提供 PDF 链接（部分开放）
- **DBLP**: 聚合所有官方外链，终极 fallback

### Tier 3: 手动处理

- 生成 missing 列表 → 人工逐一查找
- 联系作者索取 preprint
- 机构图书馆 / 馆际互借

---

## 四、决策建议

### 当前（用户选择）

- **先不处理 107 篇 missing**
- **优先下载 216 篇 ready**（已有 arxiv_id 或本地 PDF）
- 进入 Phase 3 关键词提取

### 后续如需补全 107 篇

推荐按以下优先级批量处理：

1. **ACL/EMNLP/NAACL (32 篇)** → 从 DBLP 页面提取 ACL Anthology 链接 → 100% 可拿到
2. **ICLR/ICML/NeurIPS (32 篇)** → OpenReview API → 大概率可拿到
3. **AAAI (43 篇)** → OJS 搜索 + citation_pdf_url 提取 → 已验证可行

预计 **107 篇中 80-100 篇可通过官方平台补全**，真正完全找不到的应该 < 20 篇。

---

## 五、代码入口

- **主逻辑**: `src/agent_survey/stages/s03_survey_mining/__init__.py`
- **arXiv 搜索**: `src/agent_survey/services/arxiv.py`（多 variant 标题匹配）
- **OpenReview**: `src/agent_survey/services/openreview.py`
- **CLI**: `src/agent_survey/cli.py` → `survey_mining()`
- **策略文档**: `devdocs/pdf-download-strategy.md`
