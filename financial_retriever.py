"""
财务分析检索器
- 继承 BM25Retriever
- 添加 LLM 查询扩展功能
- 表格分数权重调整
"""

from bm25_retriever import BM25Retriever
from llm_services.qwen_engine import chat_with_llm, log_message


def expand_query_for_financial_analysis(query: str) -> list[str]:
    """
    使用 LLM 扩展财务分析查询

    Args:
        query: 用户原始查询

    Returns:
        扩展后的关键词列表（繁体中文）
    """
    prompt = f"""你是一个财务分析专家。用户想要查询：{query}

请分析这个查询需要哪些财务报表数据？返回需要检索的关键词列表。

要求：
1. 返回繁体中文关键词
2. 每个关键词用逗号分隔
3. 关键词要简短，避免组合词（如"總資產"改为"資產"）
4. 只返回关键词，不要解释

财务报告常用词汇示例：
- 綜合損益表、財務狀況表、現金流量表
- 營業收入、營業成本、淨利潤
- 資產、負債、淨資產
- 現金流、經營活動、投資活動

查询：{query}
返回："""

    response = chat_with_llm(prompt, enable_thinking=False)

    # 解析关键词
    keywords = [k.strip() for k in response.split(',') if k.strip()]

    # 确保三大报表始终在关键词列表中
    required_tables = ['綜合損益表', '財務狀況表', '現金流量表']
    for table in required_tables:
        if table not in keywords:
            keywords.append(table)

    # 添加损益表相关关键词（现金流分析需要收入、利润数据）
    income_keywords = ['營業收入', '淨利潤', '利息支出']
    for kw in income_keywords:
        if kw not in keywords:
            keywords.append(kw)

    return keywords


class FinancialRetriever(BM25Retriever):
    """财务分析检索器 - 基于 BM25Retriever，添加财务特定功能"""

    # 表格分数权重（表格标题通常只出现一次，BM25 分数偏低）
    TABLE_SCORE_MULTIPLIER = 2.0

    def retrieve_with_expansion(
        self,
        query: str,
        max_tokens: int = 12000,
        top_k_per_keyword: int = 10
    ) -> dict:
        """
        使用 LLM 扩展查询后检索

        Args:
            query: 用户原始查询
            max_tokens: 最大 Token 数
            top_k_per_keyword: 每个关键词检索的块数

        Returns:
            {
                'context': 拼接后的上下文,
                'tokens': 总 Token 数,
                'chunks': 选中的块信息,
                'expanded_keywords': 扩展的关键词,
                'stats': 统计信息
            }
        """
        # 1. LLM 扩展查询
        expanded_keywords = expand_query_for_financial_analysis(query)

        # 记录到日志文件
        log_message(f"[LLM 查询扩展] 原始查询: {query}")
        log_message(f"[LLM 查询扩展] 扩展关键词: {expanded_keywords}")

        print(f"\n扩展关键词: {expanded_keywords}")

        # 2. 多关键词检索
        all_results = []
        for keyword in expanded_keywords:
            results = self.retrieve(keyword, top_k=top_k_per_keyword)
            all_results.extend(results)

        # 3. 为表格块增加分数权重
        for r in all_results:
            if r['metadata'].get('has_table', False):
                r['score'] *= self.TABLE_SCORE_MULTIPLIER

        # 4. 合并去重（按行号去重，保留最高分数）
        merged = {}
        for r in all_results:
            line = r['metadata']['line']
            if line not in merged or r['score'] > merged[line]['score']:
                merged[line] = r

        # 5. 按分数排序
        sorted_results = sorted(merged.values(), key=lambda x: x['score'], reverse=True)

        # 6. Token 预算控制
        selected = []
        total_tokens = 0

        for chunk in sorted_results:
            chunk_tokens = self._count_tokens(chunk['text'])
            if total_tokens + chunk_tokens <= max_tokens:
                selected.append(chunk)
                total_tokens += chunk_tokens
            else:
                break

        # 7. 按原始顺序重排
        selected.sort(key=lambda x: x['metadata']['line'])

        # 8. 拼接上下文
        context_parts = []
        for chunk in selected:
            source = f"[来源: 行 {chunk['metadata']['line']}"
            if chunk['metadata']['heading']:
                source += f", 章节: {chunk['metadata']['heading']}"
            source += "]"

            context_parts.append(f"{source}\n{chunk['text']}")

        context = '\n\n---\n\n'.join(context_parts)

        return {
            'context': context,
            'tokens': total_tokens,
            'chunks': selected,
            'expanded_keywords': expanded_keywords,
            'stats': {
                'total_chunks': len(self.chunks),
                'keywords_used': len(expanded_keywords),
                'total_retrieved': len(all_results),
                'merged_unique': len(merged),
                'selected': len(selected),
                'max_tokens': max_tokens
            }
        }


def main():
    """命令行入口"""
    import sys

    if len(sys.argv) < 3:
        print("用法: python financial_retriever.py <md_file> <query> [max_tokens]")
        print("\n功能: 使用 LLM 扩展查询，从财务报告中检索相关内容")
        print("\n示例:")
        print("  python financial_retriever.py output/report.md '现金流分析'")
        print("  python financial_retriever.py output/report.md '现金流分析' 8000")
        sys.exit(1)

    filepath = sys.argv[1]
    query = sys.argv[2]
    max_tokens = int(sys.argv[3]) if len(sys.argv) > 3 else 12000

    print("=" * 60)
    print("财务分析检索器")
    print("=" * 60)
    print(f"文件: {filepath}")
    print(f"问题: {query}")
    print(f"Token 限制: {max_tokens:,}")

    # 初始化检索器
    retriever = FinancialRetriever(filepath)
    stats = retriever.get_stats()

    print(f"\n文档统计:")
    print(f"  总块数: {stats['total_chunks']}")
    print(f"  原始 Token: {stats['raw_tokens']:,}")
    if stats['clean_content']:
        print(f"  清理后 Token: {stats['cleaned_tokens']:,}")
        print(f"  节省 Token: {stats['tokens_saved']:,} ({stats['tokens_saved']*100//stats['raw_tokens']}%)")

    # 检索
    print("\n" + "=" * 60)
    print("检索结果")
    print("=" * 60)

    result = retriever.retrieve_with_expansion(query, max_tokens=max_tokens)

    print(f"扩展关键词数: {result['stats']['keywords_used']}")
    print(f"总检索块数: {result['stats']['total_retrieved']}")
    print(f"合并后唯一块: {result['stats']['merged_unique']}")
    print(f"选中块数: {result['stats']['selected']}")
    print(f"总 Token: {result['tokens']:,}")

    print("\n选中的块:")
    for i, chunk in enumerate(result['chunks'], 1):
        preview = chunk['text'][:100] + '...' if len(chunk['text']) > 100 else chunk['text']
        print(f"\n{i}. [行 {chunk['metadata']['line']}] 分数: {chunk['score']:.3f}")
        print(f"   {preview}")

    print("\n" + "=" * 60)
    print("上下文内容")
    print("=" * 60)
    print(result['context'])


if __name__ == '__main__':
    main()
