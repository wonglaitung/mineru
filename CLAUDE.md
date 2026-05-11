# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

本项目用于处理 Markdown 文档，主要包含一个自定义的 Markdown AST 解析器。

## 依赖安装

```bash
pip install -r requirements.txt
```

## 核心模块

### md_parser.py - Markdown AST 解析器

基于 `markdown-it-py` + GFM 插件实现，提供以下 API：

```python
from md_parser import MDParser

parser = MDParser('your_file.md')

# 提取标题层级树
headings = parser.get_headings()  # [{'level': 1, 'text': '标题', 'children': [...]}, ...]

# 提取表格数据
tables = parser.get_tables()  # [{'headers': [...], 'rows': [[...], ...]}, ...]

# 提取代码块
code_blocks = parser.get_code_blocks()  # [{'language': 'python', 'code': '...'}, ...]

# 获取两个标题间的内容
content = parser.get_content_between_headings("起始标题", "结束标题")

# 按一级标题切分文档
sections = parser.get_sections()
```

运行测试：
```bash
python md_parser.py
```

## Docker 环境

Dockerfile 基于 vLLM 镜像，预装 MinerU（PDF 解析工具）：
```bash
docker build -t mineru .
```
