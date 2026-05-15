# Fin-RAG - 财务报告智能检索系统

基于 BM25 + LLM 的轻量级财务报告检索工具，通过 LLM 查询扩展和 Parent-Child 策略，从大型 Markdown 文档中精准抽取相关章节。

## 功能特性

| 特性 | 说明 |
|------|------|
| **表格感知分块** | 自动识别表格边界，确保表格不被切断 |
| **LLM 查询扩展** | 自动关联相关财务报表（损益表、资产负债表、现金流量表） |
| **Parent-Child 策略** | 表格标签生成 + 权重增强型混合索引，提升大表格检索效果 |
| **Token 预算控制** | 精确控制输出 Token 数量，适配 64K 上下文限制 |
| **RESTful API** | 提供 `/fin-rag` 接口，支持 Markdown 文件上传检索 |

## 快速开始

### 方式一：Docker 部署（推荐）

```bash
# 1. 构建镜像
docker build -t fin-rag .

# 2. 设置环境变量
export QWEN_API_KEY="your-api-key"

# 3. 启动服务
./start_fin_rag.sh
```

服务启动后访问：
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

### 方式二：本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 设置环境变量
export QWEN_API_KEY="your-api-key"

# 3. 运行检索
python financial_retriever.py output/report.md "现金流分析"
```

## API 使用

### 财务检索接口

**POST /fin-rag**

```bash
curl -X POST "http://localhost:8000/fin-rag" \
  -F "file=@report.md" \
  -F "query=现金流分析" \
  -F "max_tokens=8000"
```

**参数说明**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | Markdown 文件（.md） |
| `query` | string | 是 | 查询语句，如"现金流分析" |
| `max_tokens` | int | 否 | 最大返回 Token 数，默认 12000 |

**响应示例**：

```json
{
  "context": "拼接后的上下文内容...",
  "tokens": 8500,
  "expanded_keywords": ["現金流量表", "經營活動", "投資活動"],
  "stats": {
    "total_chunks": 150,
    "keywords_used": 8,
    "selected": 12,
    "max_tokens": 8000
  },
  "chunks": [
    {
      "text": "块内容...",
      "score": 2.5,
      "metadata": {"line": 100, "heading": "現金流量表", "has_table": true}
    }
  ]
}
```

### 其他接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/file_parse` | POST | 解析 PDF/图片/Office 文件 |
| `/convert2markdown` | POST | Base64 文件解析 |
| `/health` | GET | 健康检查 |

## 配置

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `QWEN_API_KEY` | 通义千问 API Key（必需） | - |
| `QWEN_CHAT_URL` | Chat API URL | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` |
| `QWEN_CHAT_MODEL` | 模型名称 | `qwen-plus-2025-12-01` |
| `MAX_TOKENS` | 最大输出 Token | `32768` |

### 检索参数

```python
# BM25Retriever
TABLE_TITLE_SEARCH_RANGE = 200      # 表格前搜索标题的字符范围
TABLE_TITLE_MIN_LEN = 5             # 标题最小长度
TABLE_TITLE_MAX_LEN = 30            # 标题最大长度

# FinancialRetriever
TABLE_SCORE_MULTIPLIER = 2.0        # 表格分数权重
```

## 项目结构

```
fin-rag/
├── Dockerfile              # Docker 构建文件
├── start_fin_rag.sh        # 启动脚本
├── requirements.txt        # Python 依赖
├── fast_api.py             # FastAPI 服务（覆盖 mineru 原版）
├── bm25_retriever.py       # 通用 BM25 检索器
├── financial_retriever.py  # 财务分析检索器
├── smart_analyzer.py       # 智能信息抽取器
├── md_parser.py            # Markdown AST 解析器
├── common/
│   ├── text_utils.py       # 文本处理工具
│   ├── table_utils.py      # 表格处理工具
│   └── finance_dict.txt    # 财务领域词典
└── llm_services/
    └── qwen_engine.py      # LLM 服务封装
```

## 技术架构

### 检索流程

```
用户查询 → LLM 扩展关键词 → 多关键词 BM25 检索 → 表格权重增强 → Token 预算控制 → 输出上下文
```

### Parent-Child 策略

解决大表格 BM25 分数偏低的问题：

| 组件 | 说明 |
|------|------|
| **Child（标签）** | 纵向提取表格第一列科目，提升宏观检索分数 |
| **Parent（完整内容）** | 保留完整表格内容，保证科目检索不漏失 |
| **混合索引** | 标签重复 3 次 + 完整表身，兼顾两者优势 |

## 文档

- [经验教训](lessons.md) - 开发过程中遇到的问题和解决方案
- [技术决策记录](docs/architecture_decisions.md) - Rerank、摘要分块等技术分析
- [编程规范](docs/programmer_skill.md) - 开发流程和代码质量要求

## 依赖

本项目基于 [MinerU](https://github.com/opendatalab/MinerU) 构建，提供 PDF 解析和 API 服务框架。
