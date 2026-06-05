# Venue 质量清理 + 摘要补全计划

**日期:** 2026-06-03
**状态:** 规划中

---

## 问题一：Technical Paper 质量审计

### 4 大 SE + 4 大 Security 审计结果

| 会议 | 总数 | 非技术 | 污染率 | 主要污染物 |
|------|------|--------|--------|-----------|
| **ICSE** | 1,398 | 44 | 3.1% | proceedings + industry(SEIP) + workshop |
| **FSE** | 575 | 22 | 3.8% | industry + student + tutorial |
| **ASE** | 990 | 19 | 1.9% | industry + proceedings + workshop |
| **ISSTA** | 346 | 3 | 0.9% | proceedings volume |
| **SP** | 845 | 15 | 1.8% | demo + poster + industry |
| **CCS** | 1,137 | 196 | **17.2%** | poster(131) + workshop(47) + demo(11) |
| **USS** | 1,279 | 3 | 0.2% | industry track |
| **NDSS** | 714 | 5 | 0.7% | proceedings key + industry |

**结论:**
- **CCS 是重灾区** — 17% 是 poster/workshop，需要重新 harvest
- **ICSE/FSE** — 3-4%，主要混入了 industry track 和 proceedings
- **ASE/ISSTA/SP/USS/NDSS** — <2%，可接受

### CCS 根因分析

DBLP `venue:CCS` 搜索会匹配到并置 workshop。CCS 每年有 10+ 个
co-located workshops（CCSW、AISec、MTD、WPES 等），它们的 DBLP
key 也以 `conf/ccs/` 开头，`key_prefixes` 无法区分。

**已修复:** `_is_proceedings_or_workshop()` 会在 harvest 阶段根据
title 过滤掉 workshop/demo/poster/industry/student/tutorial 条目。
但已有数据需要清理。

### 修复方案

| 步骤 | 操作 | 状态 |
|------|------|------|
| 1 | 标记 CCS 中 196 篇非技术论文（`enrich_source = 'non_tech'`） | ⏳ |
| 2 | 标记 ICSE 中 44 篇非技术论文 | ⏳ |
| 3 | 标记 FSE 中 22 篇非技术论文 | ⏳ |
| 4 | 标记 ASE/ISSTA/SP/USS/NDSS 非技术论文 | ⏳ |
| 5 | 重新 harvest 问题 venue（CCS 必须，ICSE/FSE/ASE 可选） | ⏳ |

### 验证标准

Re-harvest 后每个 venue 的非技术论文应 <2%。

---

## 问题二：缺失 Abstract 的论文

### 当前状态

总计 5,635 篇论文缺少 abstract（已标记 proceedings 后）。

三大根因：

| 根因类别 | 受影响 Venue | 论文数 | 解决方案 |
|---------|-------------|--------|---------|
| **Publisher extractor 缺失** | ACL, EMNLP, NAACL (aclanthology.org) | ~4,000+ | ✅ 已添加 `_extract_aclanthology` |
| | USS (usenix.org) | ~4 | ✅ 已添加 `_extract_usenix` |
| | NDSS (ndss-symposium.org) | ~1 | ✅ 已添加 `_extract_ndss` |
| **ACM Cloudflare 拦截** | ICSE, FSE, CHI, CCS (DOI → dl.acm.org) | ~200 | 需 Playwright 或 enrich-web |
| **S2 覆盖不全** | ICML, NeurIPS, COLM | ~2,000 | S2 对新论文覆盖慢；靠 harvest 爬 MLR/NeurIPS proceedings |
| **无可用 URL** | 各 venue 零星 | 138 | 无可爬取链接，只能靠 S2 标题搜索 |

### 各 Venue 策略表

| Venue | 剩余缺摘要 | 推荐策略 | 优先级 |
|-------|----------|---------|--------|
| **ACL** | ~1,050 | 1) harvest with --fetch-abstracts → aclanthology.org, 2) S2 enrich | 1 |
| **EMNLP** | ~1,666 | 同 ACL | 1 |
| **NAACL** | ~251 | 同 ACL | 1 |
| **ICML** | ~1,570 | 1) harvest DOI → PMLR proceedings, 2) S2 enrich | 1 |
| **NeurIPS** | ~649 | 1) harvest DOI → papers.nips.cc, 2) S2 enrich | 2 |
| **COLM** | ~138 | S2 enrich（新会议，可能需要时间） | 2 |
| **CHI** | ~188 | DOI → ACM DL（Cloudflare），需 enrich-web Playwright | 3 |
| **AAAI** | ~68 | 1) harvest DOI → ojs.aaai.org, 2) S2 enrich | 3 |
| **UIST** | ~30 | DOI → ACM DL（Cloudflare），需 enrich-web | 3 |
| **TOSEM** | ~26 | DOI → Crossref API（已在 enrich 中） | 3 |
| **ICSE** | ~11 | DOI → IEEE/ACM，harvest publisher + S2 | 3 |
| **NDSS** | ~5 | 1) harvest DOI → ndss-symposium.org, 2) S2 enrich | 3 |
| **SP** | ~5 | DOI → IEEE，harvest publisher | 3 |
| **TSE** | ~5 | DOI → IEEE，harvest publisher | 3 |
| **USS** | ~4 | 1) harvest DOI → usenix.org, 2) venue fetcher | 3 |
| **CCS** | ~3 | DOI → ACM DL（Cloudflare），S2 enrich | 3 |
| **FSE** | ~3 | DOI → ACM DL（Cloudflare），S2 enrich | 3 |
| **ICLR** | ~5 | OpenReview API（已在 harvest 中） | 3 |
| **ISSTA** | ~1 | DOI → ACM DL（Cloudflare），S2 enrich | 3 |

### 执行顺序

**Phase 1 — NLP 三大会（ACL/EMNLP/NAACL）：**
1. Re-harvest 这三个 venue（新的 aclanthology extractor 生效）
2. 运行 `harvest --fetch-abstracts`
3. 剩余缺口用 `enrich` 补

**Phase 2 — ICML/NeurIPS/COLM：**
1. Re-harvest（新的 proceedings filter + publisher extractor）
2. `harvest --fetch-abstracts`
3. S2 enrich

**Phase 3 — ACM/IEEE venue（CHI/ICSE/FSE/CCS/UIST/TOSEM）：**
1. ACM DL 被 Cloudflare 拦截，需要 enrich-web（Playwright）
2. 这些 venue 的覆盖已经不错（95%+），剩余不多

**Phase 4 — 小 venue 扫尾（NDSS/USS/SP/TSE/ICLR/ISSTA）：**
1. 各自用 venue-specific 策略
2. 数量少，逐个解决

---

## 下一步

1. ⏳ 标记非技术论文
2. ⏳ 对 CCS 重新 harvest
3. ⏳ 对 ACL/EMNLP/NAACL 重新 harvest + fetch-abstracts
4. ⏳ 对 ICML/NeurIPS 重新 harvest + fetch-abstracts
5. ⏳ 重跑 enrich（5s timeout 已生效）
