# 论文调研方法论

## 整体流程

```
Step 1: 确定分析目标
  └── 每轮调研前明确要回答什么问题

Step 2: 从 DB 筛选候选论文
  ├── 条件：有 PDF、relevance=core、2024-2026 优先、顶会优先
  ├── **过滤非 research paper**：页数 < 6 的标记排除（talk/abstract/demo/poster）
  └── 工具：SQLite 直接查询 papers + paper_topics 联表

Step 3: 批量提取 PDF 文本
  ├── 工具：pdfplumber
  ├── 精读：前 12 页
  ├── 全量扫描：实验页（4-8 页）
  └── 输出：/tmp/paper_{paper_id}.txt

Step 4: 分析
  ├── 粗判（读摘要）：判断分类是否值得切分
  ├── 精读（读 PDF 全文）：提取实验配置、超参、评估协议
  └── 批量扫描（关键词统计）：benchmark/模型/指标分布

Step 5: 构建/更新分类树
  ├── 粗分 3-4 个方向，每方向 1-2 篇代表作
  ├── 代表作筛选条件：安全相关（abstract + eval 双重验证）、≥6 页正规 paper
  └── 树结构 + 具体例子 → 持久化到 MD + JSON

Step 6: 汇总发现
  ├── 什么在文献中是标准做法
  ├── 什么在文献中缺失（= 贡献点）
  └── 什么需要进一步调研
```

## 核心原则

1. **不无中生有**：指标名、公式、来源标注必须从论文原文中提取。先定性描述"想度量什么"，具体定义后续扫文章补
2. **分析单位 = 论文**：每篇论文提取所有相关信息，不预设领域。一篇攻击论文可能也测试了防御
3. **过滤非 research paper**：页数 < 6 的排除（talk abstract、poster、demo、tutorial 提案）
4. **代表作安全取向**：选入分类树的论文必须（a）abstract 提到安全关键词（b）实验测了安全指标。不能选只用 MMLU/win rate 的性能取向论文
5. **先粗判后精读**：读摘要判断分类是否值得切分 → 如果值得，读 PDF 全文确定子方向和代表作
6. **subagent 分层使用**：批量 PDF 扫描用 subagent（读摘要够判粗分类），精读代表作时亲自读 PDF

## 分类树构建方法

### 判断是否值得切分

- 论文量 ≥ 30 篇：大概率值得切
- 抽样 10-12 篇摘要，人工判断是否有 3+ 个明显不同的机制/方向
- 如果 10 篇摘要做的是同一件事（仅参数不同），不切

### 切分粒度

- 粗分 3-4 个方向，每方向 1-2 篇代表作
- 描述格式：`子方向名  一句话问题 → 代表作 (一句话方法)`
- 代表作需标注是"诊断"还是"方法"还是"理论"

### 代表作选取

1. 安全相关（abstract + eval 双重验证）
2. ≥ 6 页正规 research paper
3. 优先 2025-2026 顶会
4. 每子方向 1-2 篇，避免同一篇出现在多个子方向

## 分析层次对照

| 层次 | 数据来源 | 产出 | 耗时/篇 |
|------|---------|------|---------|
| 粗判 | 摘要（abstract 字段） | 是否值得切分、大致方向 | 1 秒 |
| 关键词扫描 | PDF 实验页（4-8 页） | benchmark/模型/指标统计 | 10-20 秒 |
| 精读 | PDF 全文（前 12 页） | 实验配置、超参、评估协议 | 2-5 分钟 |

## 批量分析命令

### 筛选论文
```python
db.execute("""
    SELECT p.paper_id, p.title, p.venue, p.year, p.pdf_path
    FROM papers p JOIN paper_topics pt ON p.paper_id = pt.paper_id
    WHERE pt.topic_name = 'llm-safety-alignment-sok' AND pt.relevance = 'core'
    AND pt.taxonomy_json LIKE '%target-leaf%'
    AND p.pdf_path IS NOT NULL AND p.pdf_path != ''
    ORDER BY p.year DESC
""")
```

### 检查是否 research paper
```python
with pdfplumber.open(pdf_path) as pdf:
    if len(pdf.pages) < 6:  # talk/abstract/demo
        skip()
```

### 多 subagent 并行扫描
```bash
# 按分类树分支分 agent，每个 agent 处理一个子类
# 读摘要 → 判断是否值得切分 → 返回子方向建议
# 每 agent 处理 10-12 篇摘要
```

### 关键词定位
```bash
grep -niE '(benchmark|dataset|ASR|MMLU|harmful|safety)' /tmp/paper_*.txt
```
