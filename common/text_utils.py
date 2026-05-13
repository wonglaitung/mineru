"""
文本处理公共组件
- 内容清理
- Token 计算
"""

import re


def clean_content(content: str) -> str:
    """
    清理内容：转换表格、移除无效内容

    Args:
        content: 原始内容

    Returns:
        清理后的内容
    """
    from .table_utils import convert_html_tables_to_csv

    # 1. 转换 HTML 表格为 CSV 格式
    content = convert_html_tables_to_csv(content)

    # 2. 移除图片链接
    content = re.sub(r'!\[([^\]]*)\]\([^)]+\)', '', content)

    # 3. 移除多余的空行
    content = re.sub(r'\n{3,}', '\n\n', content)

    return content.strip()


def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """
    计算文本的大模型 Token 数量

    Args:
        text: 要计算的文本
        model: 编码模型名称
            - "cl100k_base": GPT-4, GPT-3.5-turbo, text-embedding-ada-002
            - "o200k_base": GPT-4o, GPT-4o-mini
            - "p50k_base": Codex 模型

    Returns:
        Token 数量
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding(model)
        return len(enc.encode(text))
    except ImportError:
        # tiktoken 未安装，使用估算
        # 中文约 1.5 token/字，英文约 0.25 token/字符
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars * 0.25)


def estimate_cost(
    tokens: int,
    input_price: float = 0.005,
    output_price: float = 0.015,
    output_ratio: float = 0.2
) -> dict:
    """
    估算 API 调用成本

    Args:
        tokens: 输入 Token 数
        input_price: 输入 token 价格（美元/1000 tokens）
        output_price: 输出 token 价格（美元/1000 tokens）
        output_ratio: 输出/输入比例估算

    Returns:
        {'input_tokens': ..., 'input_cost_usd': ..., 'total_cost_usd': ...}
    """
    estimated_output = int(tokens * output_ratio)
    input_cost = (tokens / 1000) * input_price
    output_cost = (estimated_output / 1000) * output_price

    return {
        'input_tokens': tokens,
        'estimated_output_tokens': estimated_output,
        'input_cost_usd': round(input_cost, 4),
        'output_cost_usd': round(output_cost, 4),
        'total_cost_usd': round(input_cost + output_cost, 4),
    }