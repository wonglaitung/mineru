# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

智能信息抽取工具，用于从大型 Markdown 文档中抽取相关章节。主要解决 64K 上下文限制问题，通过 LLM 智能选择章节并控制 Token 数量。

## 依赖安装

```bash
pip install -r requirements.txt
```

## 架构设计

### 通用检索器 vs 领域检索器

**设计原则**：分离通用逻辑和领域特定逻辑。

```
bm25_retriever.py       # 通用 BM25 检索器（适用于任何 Markdown 文档）
financial_retriever.py  # 财务分析检索器（继承 BM25Retriever，添加 LLM 查询扩展）
```

### 核心模块

**bm25_retriever.py** - 通用 BM25 检索器
- 文档切分（表格感知，不切断表格）
- BM25 相似度计算
- jieba 中文分词 + 可配置词典
- 简繁转换支持
- **Parent-Child 策略**：表格标签生成 + 权重增强型混合索引
- 索引持久化（可选）

**financial_retriever.py** - 财务分析检索器
- 继承 BM25Retriever
- LLM 查询扩展（自动关联相关财务报表）
- 表格分数权重调整

**smart_analyzer.py** - 智能信息抽取器
- 发送目录给 LLM，返回章节序号
- 多轮交互确保信息充足

**md_parser.py** - Markdown AST 解析器
- 基于 `markdown-it-py` + GFM 插件
- 标题层级树提取、表格数据提取

### 公共组件 (common/)

- `text_utils.py` - 文本清理、Token 计算、简繁转换
- `table_utils.py` - HTML 表格解析（支持合并单元格）、CSV 转换
- `finance_dict.txt` - 财务领域词典（简体中文，加载时转繁体）
- `synonyms.txt` - 同义词映射

### LLM 服务 (llm_services/)

- `qwen_engine.py` - 通义千问 API 封装
- 环境变量：`QWEN_API_KEY`, `QWEN_CHAT_URL`, `QWEN_CHAT_MODEL`

## 常用命令

```bash
# 通用 BM25 检索（任何 Markdown 文档）
python bm25_retriever.py <md_file> <query> [max_tokens]

# 财务分析检索（带 LLM 扩展）
source set_key.sh && python financial_retriever.py <md_file> <query> [max_tokens]

# 智能信息抽取
source set_key.sh && python smart_analyzer.py <md_file> <问题> [max_tokens]

# 运行测试
python test_md_parser.py

# 清除 jieba 缓存（修改词典后需要）
rm -f /tmp/jieba.cache
```

## 配置参数

BM25Retriever 类常量（可被子类覆盖）：

```python
TABLE_TITLE_SEARCH_RANGE = 200      # 表格前搜索标题的字符范围
TABLE_TITLE_MIN_LEN = 5             # 标题最小长度
TABLE_TITLE_MAX_LEN = 30            # 标题最大长度
TABLE_TITLE_MAX_COMMA = 1           # 标题最大逗号数
TABLE_TITLE_MAX_DISTANCE = 50       # 标题距离表格的最大距离
TABLE_CONTEXT_AFTER = 100           # 表格后上下文长度
PARAGRAPH_SEARCH_RANGE = 100        # 段落边界搜索范围
```

FinancialRetriever 类常量：

```python
TABLE_SCORE_MULTIPLIER = 2.0        # 表格分数权重
```

## Parent-Child 策略

用于提升大表格的 BM25 检索效果：

**核心思想**：
- **Child（标签）**：表格的简短标签，用于检索匹配
- **Parent（完整内容）**：完整表格内容，命中后返回

**实现方式**：
1. **标签生成**：纵向提取表格第一列的核心科目（如"經營活動現金流量"）
2. **混合索引**：标签重复 3 次 + 完整表身内容，兼顾宏观检索和科目检索
3. **表格标题识别**：优先使用"独立短行"（无 `#` 前缀的标题）

**效果**：
- 大表格检索分数提升
- 科目检索不漏失（混合索引保留完整表身）

## 简繁体处理流程

所有文本统一转换为繁体中文进行索引和匹配：

```
文档(繁体) → to_traditional() → jieba分词 → BM25索引
词典(简体) → to_traditional() → 加入jieba
用户查询 → to_traditional() → jieba分词 → BM25匹配
```

## 内容清理

`clean_content()` 方法处理：
- HTML 表格 → CSV 格式（节省 Token）
- 移除图片链接
- 移除多余空行

## 开发规范

> **⚠️ 经验教训**：关键警告和最佳实践请参阅 [lessons.md](lessons.md)
> **🔧 编程规范**：开发流程、系统设计决策请遵守 [docs/programmer_skill.md](docs/programmer_skill.md)
> **📐 技术决策**：架构设计决策请参阅 [docs/architecture_decisions.md](docs/architecture_decisions.md)
