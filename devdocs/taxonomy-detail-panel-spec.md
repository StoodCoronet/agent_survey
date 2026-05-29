# Taxonomy 页面 — 文章详情侧边栏 Spec

## 背景
在 Taxonomy 页面（taxonomy.html）中，当前右侧边栏只显示文章列表（标题 + 编号）。用户希望在点击某篇文章后，右侧边栏切换为该文章的详情视图，展示 title、abstract、中文描述（placeholder）和 PDF 原文链接。

## 需求摘要
1. 点击文章（无论是中心面板的 paper-card 还是右侧列表的 right-item），右侧边栏变为该文章的详情视图。
2. 详情视图包含：
   - 文章编号 + 标题
   - Venue / Year
   - Abstract（长文本限制最大高度，内部可滚动）
   - 中文描述（当前为 placeholder：`(中文描述待补充)`）
   - PDF 原文链接（可点击，在新标签页打开）
3. 右上角提供关闭/返回按钮（X 图标），点击后回到当前分类的文章列表。
4. 左侧树导航切换节点时，详情视图保持显示（不自动关闭）。

## 技术方案

### 数据层（generate_docs.py）
- data.json 中每篇 paper 新增字段 `pdf_url`，值为 `./pdfs/<paper_id>.pdf`（相对路径）。
- `generate_docs.py` 执行时，将 `output/pdfs/` 下存在的 PDF 同步复制到 `docs/pdfs/`，确保局域网可访问。

### 前端交互（taxonomy.html）
- 新增全局变量 `selectedPaperId = null`。
- 点击 paper-card / right-item 时：
  - `selectedPaperId = p.id`
  - 调用 `renderRight()`
- `renderRight()` 逻辑：
  - 如果 `selectedPaperId` 有值，显示详情视图。
  - 否则，按现有逻辑显示文章列表。
- 详情视图 DOM 结构（简化）：
  ```
  .right-header
    span: 文章标题
    button.close-btn (X) → selectedPaperId = null; renderRight();
  .right-detail
    .detail-meta: venue year
    .detail-abstract (max-height: 300px; overflow-y: auto)
    .detail-cn (浅灰色背景提示卡片): "（中文描述待补充）"
    .detail-pdf: <a href="./pdfs/xxx.pdf" target="_blank">查看 PDF 原文 →</a>
  ```
- 样式：
  - `.right-detail` 内边距 12px 16px，flex: 1，overflow-y: auto。
  - `.detail-abstract` max-height: 300px，overflow-y: auto，line-height: 1.7，font-size: 13px。
  - `.detail-cn` 背景 #f5f5f5，圆角 6px，padding 8px 12px，font-size: 12px，color: #888。
  - `.detail-pdf` 蓝色链接，底部固定或跟随内容。

### PDF 同步
- `generate_docs.py` 中新增 `_sync_pdfs(docs_dir)` 函数：
  - 读取 DB 中所有 `has_pdf = true` 的 paper。
  - 如果 `output/pdfs/<paper_id>.pdf` 存在，则 `shutil.copy2` 到 `docs/pdfs/<paper_id>.pdf`。
  - 不存在的 PDF 跳过（链接仍然会生成，但点击会 404，可接受）。

## 边界情况
- 无 PDF：`pdf_url` 仍然生成，但前端检测后显示 "PDF 不可用" 或隐藏链接。
- 无 abstract：显示 "(abstract not available)"。
- 切换 tree tab：保持 `selectedPaperId`，但 `renderRight()` 会重新渲染；如果新 tree 下该 paper 不在当前选中节点范围内，详情视图仍然保留（按用户要求）。

## 后续扩展
- 中文描述字段填充后，只需替换 placeholder 文本即可，前端结构不变。
- PDF 在线链接：后续可将 `pdf_url` 替换为 arXiv/S2 实际 URL，无需改前端逻辑。
