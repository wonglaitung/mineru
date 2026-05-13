# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 提供项目指导。

## 项目概述

智能信息抽取工具，用于从大型 Markdown 文档中抽取相关章节。主要解决 64K 上下文限制问题，通过 LLM 智能选择章节并控制 Token 数量。

## 依赖安装

```bash
pip install -r requirements.txt
```

## 核心模块

### md_parser.py - Markdown AST 解析器

基于 `markdown-it-py` + GFM 插件，提供文档解析能力：
- 标题层级树提取、搜索
- 表格数据提取（支持 HTML 表格的 rowspan/colspan）
- 章节内容提取
- Token 统计（使用 tiktoken）

### smart_analyzer.py - 智能信息抽取器

核心类 `InfoExtractor`，工作流程：
1. 发送目录给 LLM，返回章节序号（避免编码问题）
2. 提取章节内容，清理后计算 Token
3. 多轮交互确保信息充足
4. 输出清理后的内容

### bm25_retriever.py - BM25 轻量检索器

无需向量数据库的纯文本检索：
- 文档切分（表格感知，不切断表格）
- BM25 相似度计算
- 简繁转换支持（opencc/zhconv）

### llm_services/qwen_engine.py - LLM API 封装

通义千问 API 封装，通过环境变量配置：
- `QWEN_API_KEY` - API 密钥
- `QWEN_CHAT_URL` - API 端点
- `QWEN_CHAT_MODEL` - 模型名称

## 常用命令

```bash
# 运行解析器测试
python test_md_parser.py

# 智能信息抽取
source set_key.sh && python smart_analyzer.py <md_file> <问题> [max_tokens]

# BM25 检索
python bm25_retriever.py <md_file> <query> [max_tokens]
```

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
| `chunk_size` | 500 | BM25 块大小（字符数） |

## 会话工作流

- 会话开始时：读取 `progress.txt` 了解项目进展，审查 `lessons.md` 检查错误
- 功能更新后：更新 `progress.txt` 记录进展，如有新学习心得更新 `lessons.md`

> **⚠️ 经验教训**：关键警告和最佳实践请参阅 [lessons.md](lessons.md)
> **🔧 编程规范**：开发流程、系统设计决策请遵守 [docs/programmer_skill.md](docs/programmer_skill.md)
