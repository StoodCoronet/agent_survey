# Missing Abstract 分析：Proceedings 污染

**日期：** 2026-06-03
**状态：** 分析中

## 概述

Enrich 后仍缺失 abstract 的论文总数：**5,789 篇**

根本原因分析发现，相当一部分"缺失 abstract"的条目**根本不是论文**——它们是 **proceedings 卷册、workshop 合集或 tutorial/demo 条目**，被 DBLP harvest 错误地收录了。

这些条目的标题长这样：
- "Proceedings of the 45th IEEE/ACM International Conference on..."
- "45th IEEE/ACM International Conference on Software Engineering, ICSE 2023"
- "IEEE/ACM International Workshop on Cloud Intelligence & AIOps"

## 分类方法

| 类别 | 检测规则 |
|------|---------|
| **Proceedings 卷册** | 标题以数字 + "IEEE/ACM/ACM/IEEE Conference/Symposium" 开头，或以 "Proceedings of the" 开头，或以 "International Conference/Workshop/Symposium on" 开头 |
| **Workshop 轨道** | 标题包含 "Workshop", "Tutorial", "Demo", "Poster", "Industry", "Student" |
| **真实论文** | 以上都不是；DBLP key 以作者名结尾 |

## Missing Abstract 按 Venue × Year

| 会议 | 年份 | 缺失总数 | Proceedings | Workshop | 真实论文 |
|------|------|---------|-------------|----------|----------|
| **EMNLP** | 2023 | 506 | 4 | 1 | 501 |
| | 2024 | 254 | 5 | 2 | 247 |
| | 2025 | 926 | 4 | 4 | 918 |
| **ICML** | 2023 | 269 | 1 | 1 | 267 |
| | 2024 | 521 | 3 | 0 | 518 |
| | 2025 | 783 | 6 | 1 | 776 |
| **ACL** | 2023 | 215 | 6 | 0 | 209 |
| | 2024 | 178 | 5 | 3 | 173 |
| | 2025 | 677 | 7 | 0 | 667 |
| **NeurIPS** | 2023 | 243 | 1 | 1 | 241 |
| | 2024 | 407 | 2 | 0 | 405 |
| **NAACL** | 2024 | 46 | 4 | 0 | 42 |
| | 2025 | 216 | 6 | 1 | 209 |
| **CHI** | 2023 | 37 | 2 | 1 | 34 |
| | 2024 | 53 | 1 | 1 | 51 |
| | 2025 | 47 | 2 | 0 | 45 |
| | 2026 | 61 | 3 | 0 | 58 |
| **COLM** | 2024 | 138 | 0 | 0 | 138 |
| **AAAI** | 2023 | 39 | 2 | 0 | 37 |
| | 2024 | 17 | 3 | 0 | 14 |
| | 2025 | 14 | 1 | 0 | 13 |
| | 2026 | 1 | 1 | 0 | 0 |
| **ICSE** | 2023 | 9 | **7** | 2 | **0** |
| | 2024 | 16 | **6** | 1 | **9** |
| | 2025 | 9 | **6** | 1 | **2** |
| **UIST** | 2023 | 6 | 1 | 0 | 5 |
| | 2024 | 15 | 1 | 0 | 14 |
| | 2025 | 12 | 1 | 0 | 11 |
| **TOSEM** | 2023 | 4 | 0 | 0 | 4 |
| | 2024 | 9 | 0 | 0 | 9 |
| | 2025 | 10 | 0 | 0 | 10 |
| | 2026 | 3 | 0 | 0 | 3 |
| **CCS** | 2023 | 4 | **3** | 0 | 1 |
| | 2024 | 3 | 1 | 0 | 2 |
| | 2025 | 1 | 1 | 0 | 0 |
| **ASE** | 2023 | 2 | **2** | 0 | **0** |
| | 2024 | 2 | **2** | 0 | **0** |
| | 2025 | 2 | **2** | 0 | **0** |
| **SP** | 2023 | 2 | 1 | 0 | 1 |
| | 2024 | 2 | 1 | 0 | 1 |
| | 2025 | 2 | 1 | 0 | 1 |
| **FSE** | 2023 | 2 | 1 | 0 | 1 |
| | 2024 | 1 | 0 | 0 | 1 |
| | 2025 | 2 | 1 | 0 | 1 |
| **ICLR** | 2023 | 2 | 1 | 0 | 1 |
| | 2024 | 2 | 1 | 0 | 1 |
| | 2025 | 1 | 1 | 0 | 0 |
| **NDSS** | 2023 | 1 | **1** | 0 | **0** |
| | 2024 | 1 | **1** | 0 | **0** |
| | 2025 | 1 | **1** | 0 | **0** |
| | 2026 | 2 | **1** | 0 | **1** |
| **TSE** | 2024 | 1 | 0 | 0 | 1 |
| | 2025 | 3 | 0 | 0 | 3 |
| | 2026 | 1 | 0 | 0 | 1 |
| **ISSTA** | 2023 | 1 | **1** | 0 | **0** |
| | 2024 | 2 | 1 | 0 | 1 |
| | 2025 | 1 | 1 | 0 | 0 |
| **USS** | 2023 | 2 | 0 | 0 | 2 |
| | 2024 | 1 | 0 | 0 | 1 |
| | 2025 | 1 | 0 | 0 | 1 |

## 关键发现

### 🔴 高 Proceedings 污染 (>50% 缺失不是真实论文)

| 会议 | 缺失总数 | Proceedings+Workshop | 真实论文 | 污染率 |
|------|---------|---------------------|----------|--------|
| **ASE** | 6 | 6 | 0 | **100%** |
| **ICSE** | 34 | 23 | 11 | **68%** |
| **CCS** | 8 | 5 | 3 | **63%** |
| **NDSS** | 5 | 4 | 1 | **80%** |
| **ISSTA** | 4 | 3 | 1 | **75%** |

### 🟡 中度污染 (10-50%)

| 会议 | 缺失总数 | Proceedings+Workshop | 真实论文 | 污染率 |
|------|---------|---------------------|----------|--------|
| **AAAI** | 71 | 7 | 64 | **10%** |
| **CHI** | 198 | 10 | 188 | **5%** |
| **ICLR** | 5 | 3 | 2 | **60%** |

### 🟢 低污染 (<5%)

| 会议 | 缺失总数 | Proceedings+Workshop | 真实论文 | 污染率 |
|------|---------|---------------------|----------|--------|
| **EMNLP** | 1686 | 20 | 1666 | **1.2%** |
| **ICML** | 1573 | 12 | 1561 | **0.8%** |
| **ACL** | 1070 | 21 | 1049 | **2.0%** |
| **NeurIPS** | 650 | 4 | 646 | **0.6%** |
| **NAACL** | 262 | 11 | 251 | **4.2%** |
| **COLM** | 138 | 0 | 138 | **0%** |
| **TOSEM** | 26 | 0 | 26 | **0%** |
| **TSE** | 5 | 0 | 5 | **0%** |
| **USS** | 4 | 0 | 4 | **0%** |

## 根本原因

DBLP `venue:` 搜索返回所有匹配该 venue 的条目，包括：
1. **Proceedings 卷册** (conf/venue/year) — 整个会议的 proceedings 元数据
2. **Workshop proceedings** (conf/venue/year-workshopname) — 并置 workshop
3. **真实论文** (conf/venue/yearauthor) — 带作者后缀的单篇论文

当前 `key_prefixes` 只检查前缀（如 `conf/icse/`），不检查后缀模式。
Proceedings 卷册和 workshop 轨道因为 key 也以 `conf/icse/` 开头，所以通过了过滤。

## 修复策略

### 立即：处理现有数据库
1. 标记所有 proceedings/workshop 条目为 `enrich_source = 'proceedings'`
2. 将它们从 enrich 队列中永久移除
3. 重新统计真实的缺失论文数

**执行结果：** 标记 111 个条目，剩余真实论文 **5,678 篇**

### 长期：修复 harvest 过滤 ✅ 已完成

在 `services/dblp.py` 的 `_normalize_hit` 中增加了三重过滤：

**过滤 1 — Title 匹配 proceedings 模式：**
- 以数字 + "IEEE/ACM/ACM/IEEE Conference/Workshop/Symposium" 开头
- 以 "Proceedings of the" 开头
- 以 "International Conference/Workshop/Symposium on" 开头

**过滤 2 — Title 包含非技术轨道标记：**
- 包含 "Workshop", "Tutorial", "Demo", "Poster", "Industry", "Student", "Competition"

**过滤 3 — DBLP key 后缀为纯年份：**
- key 以纯数字结尾（如 `conf/icse/2023`）→ proceedings 卷册
- key 以数字+单字母结尾（如 `conf/icse/2023c`）→ supplement
- 真实论文 key 以年份+作者名结尾（如 `conf/icse/2023zhang`）→ 保留

代码：`src/agent_survey/services/dblp.py`，已语法验证通过。

## 下一步

1. ✅ 执行 proceedings 分类脚本
2. ✅ 标记 proceedings 条目（`enrich_source = 'proceedings'`）
3. ⏳ 修复 harvest 代码防止未来污染
4. ⏳ 对剩余 5,678 篇真实论文重新跑 enrich
5. ⏳ 优先处理 EMNLP/ICML/ACL/NeurIPS 等大头
