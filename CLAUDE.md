# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

智能信息抽取工具，用于从大型 Markdown 文档中抽取相关章节。主要解决 64K 上下文限制问题，通过 LLM 智能选择章节并控制 Token 数量。

## 目录结构

```
raw/          # PDF 原始文件
output/       # MD 输出文件
llm_services/ # LLM API 封装
```

## 依赖安装

```bash
pip install -r requirements.txt
```

## 核心模块

### md_parser.py - Markdown AST 解析器

基于 `markdown-it-py` + GFM 插件，支持：
- 标题层级树提取
- 表格数据提取（支持 HTML 表格的 rowspan/colspan）
- 代码块提取
- 章节内容提取
- Token 统计（使用 tiktoken）

运行测试：
```bash
python test_md_parser.py
```

### smart_analyzer.py - 智能信息抽取器

核心类 `InfoExtractor`，工作流程：
1. 发送目录给 LLM，返回章节序号（避免编码问题）
2. 提取章节内容，清理后计算 Token
3. 多轮交互确保信息充足
4. 输出清理后的内容

使用方法：
```bash
source set_key.sh && python smart_analyzer.py <md_file> <问题> [max_tokens]
```

### llm_services/qwen_engine.py - LLM API 封装

通义千问 API 封装，通过环境变量配置：
- `QWEN_API_KEY` - API 密钥
- `QWEN_CHAT_URL` - API 端点
- `QWEN_CHAT_MODEL` - 模型名称

## 内容清理

`clean_content()` 方法处理：
- HTML 表格 → CSV 格式（节省 Token）
- 移除图片链接
- 移除多余空行

## 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_tokens` | 50,000 | Token 总限制 |
| `min_content_tokens` | 100 | 最小章节 Token 数 |
| `max_rounds` | 3 | 最大交互轮数 |
