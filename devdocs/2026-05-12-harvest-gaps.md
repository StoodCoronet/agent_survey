# 2026-05-12 — harvest 覆盖缺口诊断与修复

**状态**：TOSEM/TSE 已修复并回填；NAACL 2023 / COLM / NeurIPS 2025 已处理。

**进度**：总 papers 73,703（含 COLM 2024 687 篇）

## 背景

第一轮 `agent-survey harvest` 跑完后（80/80 tasks，total=71,507 papers），用 sqlite 查 `harvest_runs` 发现若干 venue/year 被标记为 `empty`，表面看是"DBLP 上没数据"，但人工交叉验证后确认**其中一部分是我们爬法不对，不是 DBLP 真没有**。

## 缺口分类

### A. 预期中的 empty（无需处理）

全部 venue 的 **2026** 年份（会议还没办或 DBLP 还没编目）：ACL, ASE, CCS, EMNLP, FSE, ICLR, ICML, ICSE, ISSTA, NAACL, SP, UIST, USS。

**COLM 2023**：COLM 第一届是 2024 年，2023 年不存在。

### B. 真缺口 — 已修复并回填（2026-05-12）

| venue/year | 缺失原因 | 修复方式 | 回填结果 |
|---|---|---|---|
| TOSEM 2023-2026 | DBLP 对 journal 没有按 year 的 `venue:` index；`venue:TOSEM year:2024` → 0 hits | 新增 journal volume 直读路径：`dblp.org/db/journals/tosem/tosem<vol>.xml`，按 year→volume 映射枚举 | 2023=159, 2024=219, 2025=239, 2026=115 |
| TSE 2023-2026 | 同上 | 同上，`dblp.org/db/journals/tse/tse<vol>.xml` | 2023=278, 2024=182, 2025=228, 2026=89 |

**Volume 映射（截至 2026-05，已探测 DBLP 确认 year 字段）**：
- TOSEM：vol 32 = 2023 (161 articles), vol 33 = 2024 (223), vol 34 = 2025, vol 35 = 2026（每年 1 卷）
- TSE：vol 49 = 2023 (278), vol 50 = 2024, vol 51 = 2025, vol 52 = 2026（每年 1 卷）

注：DB 中 TOSEM 2023 = 159 vs vol32 XML 161 篇，diff=2，可能是 `<article>` 内有非 regular 条目（editorial/correction）被 filter 掉，或有 `year` 字段缺失的条目 — 不影响结论。

### C. 真缺口 — 已处理（截至 2026-05-13）

| venue/year | 结论 | 处理方式 |
|---|---|---|
| NAACL 2023 | 会议不存在（NAACL 2022 → 2024，无 2023） | `skip_years: [2023]`，直接跳过 |
| NAACL 2024/2025 | DBLP `venue:NAACL` 搜索正常 | 保留原路径 |
| COLM 2024 | DBLP 无编目；COLM 官网 mini-conf 有完整数据 | 走 `json_source_url: https://colmweb.org/2024/serve_papers.json`，拿到 687 篇 |
| COLM 2025 | 官网数据尚未更新（serve_papers.json 仍是 2024 副本） | 运行时检测 `serve_config.json` date 字段，不匹配则跳过 |
| COLM 2023/2026 | 官网 404 | `external.py` 内 404 转 empty，不报 error |
| NeurIPS 2025 | DBLP 未编目，OpenReview 无公开 notes，proceedings 网站只有标题无作者 | `skip_years: [2025]`，等 DBLP 编目后解除 |

### D. 数量可疑但状态=done（不是 0 的)

| venue/year | 现有 | 预期 | 备注 |
|---|---|---|---|
| ISSTA 2025 | 36 | ~130 | DBLP 当下只有 36；可能是编目中途。后续 `--force` 重爬观察 |
| FSE 2024 | 109 | ~150 | `venue:FSE year:2024` 返回 125，filter `conf/fse/` + `conf/sigsoft/` 后 109。可能需要加更多 key_prefixes（如 `conf/esec/`），或 FSE 2024 在 DBLP 上也分多 volume |

---

## 代码改动清单（已落地）

- `src/agent_survey/config.py`：`VenueCfg` 新增字段
  - `journal_stream: str | None` + `journal_volumes: dict[int, list[int]]`
  - `json_source_url: str | None` — 外部 JSON 源（如 COLM mini-conf）
  - `skip_years: list[int]` — 跳过的年份
- `src/agent_survey/sources/external.py`：新增 `fetch_json_papers()`，支持 mini-conf JSON 格式（title/authors/abstract/UID），含 COLM 年份校验和 404 静默处理
- `src/agent_survey/sources/dblp.py`：新增 `fetch_journal_volumes()`
- `src/agent_survey/pipeline/harvest.py`：`_worker` dispatch 顺序
  `skip_years > json_source_url > journal_stream > toc_stream > venue:` 搜索
- `config.yaml`：
  - TOSEM / TSE 加 `journal_stream` + `journal_volumes`
  - NAACL 加 `skip_years: [2023]`
  - COLM 加 `json_source_url`
  - NeurIPS 加 `skip_years: [2025]`

## 已执行

```bash
# TOSEM/TSE 回填
sqlite3 output/db/papers.sqlite "DELETE FROM harvest_runs WHERE venue_name IN ('TOSEM','TSE')"
agent-survey harvest -w 1

# NAACL/COLM/NeurIPS 清理错误数据
sqlite3 output/db/papers.sqlite "
DELETE FROM harvest_runs WHERE venue_name IN ('NAACL','COLM','NeurIPS');
DELETE FROM papers WHERE venue IN ('NAACL','COLM','NeurIPS') AND year IN (2023,2024,2025,2026);
"
```

## 下一步

1. 等 DBLP 编目 NeurIPS 2025 后，去掉 `skip_years: [2025]`，删 harvest_runs 重跑
2. FSE 2024 (109) / ISSTA 2025 (36) 数量可疑，用 `--force` 或单独删行后复查
