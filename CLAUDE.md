# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **⚠️ 经验教训**：关键警告和最佳实践请参阅 [lessons.md](lessons.md)
> **🔧 编程规范**：开发流程、系统设计决策请遵守 [docs/programmer_skill.md](docs/programmer_skill.md)
> **📐 技术决策**：架构设计决策请参阅 [docs/architecture_decisions.md](docs/architecture_decisions.md)

## 项目概述

Fin-RAG - 财务报告智能检索系统。基于 BM25 + LLM，从大型 Markdown 文档中精准抽取相关章节，解决 64K 上下文限制问题。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 设置 API 密钥
export QWEN_API_KEY="your-key"

# 检索（通用 BM25）
python bm25_retriever.py <md_file> <query> [max_tokens]

# 检索（财务分析，带 LLM 扩展）
python financial_retriever.py <md_file> <query> [max_tokens]

# 测试 Markdown 解析器
python test_md_parser.py

# 清除 jieba 缓存（修改词典后必须执行）
rm -f /tmp/jieba.cache

# Docker 部署
docker build -t fin-rag .
./start_fin_rag.sh
```

## 架构

### 核心模块

| 模块 | 职责 | 关键点 |
|------|------|--------|
| `bm25_retriever.py` | 通用 BM25 检索器 | 表格感知分块、jieba 分词、Parent-Child 策略。类常量可被子类覆盖 |
| `financial_retriever.py` | 财务检索器 | 继承 BM25Retriever，添加 LLM 查询扩展、表格分数权重（2.0x） |
| `fast_api.py` | API 服务 | `/fin-rag` 接口，覆盖 mineru 原版。需设置 `sys.path.insert(0, '/app')` |
| `smart_analyzer.py` | 智能抽取器 | 目录导航 + 多轮交互 |
| `md_parser.py` | Markdown 解析 | AST 解析、表格提取 |

### 公共组件

```
common/
├── text_utils.py      # to_traditional() 简繁转换、clean_content()、count_tokens()
├── table_utils.py     # find_table_ranges() 表格边界识别
├── finance_dict.txt   # 财务词典（简体→繁体，格式: 词 频率 标签）
└── synonyms.txt       # 同义词映射

llm_services/
└── qwen_engine.py     # chat_with_llm() 通义千问 API
```

### 设计原则

**通用 vs 领域分离**：
- `bm25_retriever.py` - 通用逻辑，适用于任何 Markdown
- `financial_retriever.py` - 领域逻辑，财务特定功能（LLM 扩展、三大报表强制包含）

**继承机制**：FinancialRetriever 覆盖父类常量（如 `TABLE_SCORE_MULTIPLIER`）实现差异化配置。

## 核心策略

### Parent-Child 策略

解决大表格 BM25 分数偏低问题：

```
Child（标签）: 纵向提取第一列科目 → 用于检索匹配
Parent（内容）: 完整表格内容 → 命中后返回

混合索引: (child_label × 3) + parent_text
```

**实现位置**：`bm25_retriever.py` 的 `_enrich_table_chunk()` 方法。

### 简繁体处理

统一转换为繁体中文（香港/台湾财务报告通用）：

```
文档 → to_traditional() → jieba → BM25
词典 → to_traditional() → jieba
查询 → to_traditional() → BM25
```

**注意**：词典用简体编写，加载时自动转繁体。

### 表格分数权重

表格标题只出现一次，BM25 分数偏低。FinancialRetriever 对表格块分数翻倍：

```python
if chunk['metadata'].get('has_table'):
    chunk['score'] *= TABLE_SCORE_MULTIPLIER  # 默认 2.0
```

## 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `QWEN_API_KEY` | API 密钥（必需） | - |
| `QWEN_CHAT_URL` | API 地址 | dashscope |
| `QWEN_CHAT_MODEL` | 模型 | qwen-plus |

### 检索参数（类常量，可被子类覆盖）

```python
# BM25Retriever
TABLE_TITLE_SEARCH_RANGE = 200   # 表格标题搜索范围
TABLE_TITLE_MAX_DISTANCE = 50    # 标题距离表格最大距离

# FinancialRetriever
TABLE_SCORE_MULTIPLIER = 2.0     # 表格分数权重
```

## 相关文档

- [检索流程详解](docs/retrieval_flow.md) - 完整流程图解
- [技术决策记录](docs/architecture_decisions.md) - Rerank、摘要分块分析
- [编程规范](docs/programmer_skill.md) - 开发流程、代码质量要求
- [经验教训](lessons.md) - 常见问题与解决方案