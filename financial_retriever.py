"""
财务分析检索器
- 继承 BM25Retriever
- 添加 LLM 查询扩展功能
- 表格分数权重调整
- 多轮迭代检索 + LLM 质检闭环
"""

import json
import re
from bm25_retriever import BM25Retriever
from llm_services.qwen_engine import chat_with_llm, log_message


# 质检提示词
EVALUATOR_PROMPT = """# 角色
你是一名银行风险合规部的【财报资料核对员】。你的唯一任务是检查现有的财报原文片段是否已经收集完整。

# 任务背景
下游系统需要回答用户针对这份财报提出的技术问题：
"{user_query}"

# 当前你手里已持有的原始片段
{current_financial_data}

# 核对及穿透规范
1. 检查数据勾稽与嵌套：
   - 若当前片段包含利润表中的"投资收益"大幅波动，但缺失"附注中关于投资收益的明细表"，判定为【资料不齐】
   - 若表身文本中明确写有"详见附注五、（十四）"，而当前片段中找不到这个附注，判定为【资料不齐】
2. 严禁越权：不要尝试分析或回答用户问题，只关心"原文齐不齐"

# 输出格式约束
你必须、且只能输出一个标准的 JSON 结构，不要包含任何前言、后记或 Markdown 代码块包裹。

格式 1：资料不齐，需要继续补充
{{"status": "INCOMPLETE", "reason": "缺失了哪个附注、哪张主表或哪个科目的明细", "next_query": "下一步检索关键词"}}

格式 2：资料已齐备
{{"status": "COMPLETE", "reason": "涉及的报表及附注已全部集齐，无缺失的嵌套索引"}}"""


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
        top_k_per_keyword: int = 10,
        max_loops: int = 3,
        enable_validation: bool = True
    ) -> dict:
        """
        使用 LLM 扩展查询后检索，支持多轮迭代 + LLM 质检闭环

        Args:
            query: 用户原始查询
            max_tokens: 最大 Token 数
            top_k_per_keyword: 每个关键词检索的块数
            max_loops: 最大迭代次数（安全阀 A，防止死循环）
            enable_validation: 是否启用 LLM 质检

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

        # 2. 多关键词检索（第一轮）
        all_results = []
        for keyword in expanded_keywords:
            results = self.retrieve(keyword, top_k=top_k_per_keyword)
            all_results.extend(results)

        # 3. 物理去重（安全阀 B，按行号去重，保留最高分数）
        merged = {}
        for r in all_results:
            line = r['metadata']['line']
            if line not in merged or r['score'] > merged[line]['score']:
                merged[line] = r

        log_message(f"[第一轮检索] 总检索块数: {len(all_results)}, 去重后: {len(merged)}")

        # 4. 多轮迭代检索（如果启用质检）
        loops_used = 0
        if enable_validation:
            for loop_idx in range(max_loops):
                loops_used = loop_idx + 1
                print(f"\n--- 第 {loops_used} / {max_loops} 轮质检 ---")

                # 拼接当前上下文
                context_str = self._build_context_str(merged.values())

                # LLM 质检
                eval_result = self._evaluate_completeness(query, context_str)

                log_message(f"[质检结果] 第 {loops_used} 轮: {eval_result}")

                if eval_result['status'] == 'COMPLETE':
                    print(f"✅ 资料已齐备: {eval_result['reason']}")
                    break

                print(f"❌ 资料不齐: {eval_result['reason']}")
                print(f"   下一轮检索词: {eval_result.get('next_query', 'N/A')}")

                # 用 next_query 进行下一轮检索
                next_query = eval_result.get('next_query', '')
                if not next_query:
                    log_message("[WARN] next_query 为空，终止迭代")
                    break

                new_results = self.retrieve(next_query, top_k=top_k_per_keyword)

                # 物理去重，加入 merged
                new_count = 0
                for r in new_results:
                    line = r['metadata']['line']
                    if line not in merged or r['score'] > merged[line]['score']:
                        merged[line] = r
                        new_count += 1

                log_message(f"[第 {loops_used + 1} 轮检索] 新增块数: {new_count}")

                # 如果本轮没有新数据，提前终止
                if new_count == 0:
                    print("⚠️ 本轮未发现新数据，自动终止")
                    break
            else:
                # 达到最大迭代次数
                print(f"⚠️ 达到最大迭代次数 ({max_loops})，强制终止")
                log_message(f"[安全阀 A] 达到最大迭代次数 {max_loops}")

        # 5. 为表格块增加分数权重
        for r in merged.values():
            if r['metadata'].get('has_table', False):
                r['score'] *= self.TABLE_SCORE_MULTIPLIER

        # 6. 按分数排序
        sorted_results = sorted(merged.values(), key=lambda x: x['score'], reverse=True)

        # 7. Token 预算控制
        selected = []
        total_tokens = 0

        for chunk in sorted_results:
            chunk_tokens = self._count_tokens(chunk['text'])
            if total_tokens + chunk_tokens <= max_tokens:
                selected.append(chunk)
                total_tokens += chunk_tokens
            else:
                break

        # 8. 按原始顺序重排
        selected.sort(key=lambda x: x['metadata']['line'])

        # 9. 拼接上下文
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
                'max_tokens': max_tokens,
                'loops_used': loops_used,
                'validation_enabled': enable_validation
            }
        }

    def _build_context_str(self, chunks: list) -> str:
        """构建用于质检的上下文字符串"""
        parts = []
        for chunk in chunks:
            source = f"【来源章节：{chunk['metadata']['heading']} | 起始行号：{chunk['metadata']['line']}】"
            parts.append(f"{source}\n{chunk['text']}")
        return "\n\n".join(parts)

    def _evaluate_completeness(self, user_query: str, context_str: str) -> dict:
        """
        调用 LLM 判断资料是否齐备

        Args:
            user_query: 用户原始查询
            context_str: 当前上下文字符串

        Returns:
            {'status': 'COMPLETE' | 'INCOMPLETE', 'reason': str, 'next_query': str}
        """
        prompt = EVALUATOR_PROMPT.format(
            user_query=user_query,
            current_financial_data=context_str
        )

        try:
            response = chat_with_llm(prompt, enable_thinking=False)
            return self._parse_eval_response(response)
        except Exception as e:
            log_message(f"[ERROR] LLM 质检失败: {e}")
            # 出错时返回 COMPLETE 终止循环，保护系统
            return {
                'status': 'COMPLETE',
                'reason': f'LLM 质检出错，强制终止: {str(e)}'
            }

    def _parse_eval_response(self, raw_response: str) -> dict:
        """
        解析 LLM 响应，带三层降级策略（安全阀 C）

        Args:
            raw_response: LLM 原始响应

        Returns:
            {'status': 'COMPLETE' | 'INCOMPLETE', 'reason': str, 'next_query': str}
        """
        # 第一层：尝试标准 JSON 解析
        try:
            # 清理可能存在的 markdown 代码块包裹
            clean_json = re.sub(r'```json\s*|\s*```', '', raw_response.strip())
            result = json.loads(clean_json)
            # 确保必要字段存在
            if 'status' not in result:
                result['status'] = 'COMPLETE'
            if 'reason' not in result:
                result['reason'] = '解析成功但缺少 reason 字段'
            if result['status'] == 'INCOMPLETE' and 'next_query' not in result:
                result['next_query'] = ''
            return result
        except json.JSONDecodeError as e:
            log_message(f"[WARN] JSON 解析失败，启动正则降级: {e}")

        # 第二层：正则捕获关键字段
        if "COMPLETE" in raw_response:
            return {
                'status': 'COMPLETE',
                'reason': '模型意图判定为齐备（正则捕获）'
            }

        # 尝试提取 next_query
        next_query_match = re.search(r'["\']next_query["\']\s*:\s*["\']([^"\']+)["\']', raw_response)
        if next_query_match:
            return {
                'status': 'INCOMPLETE',
                'reason': '格式解析失败，但成功捕获检索词',
                'next_query': next_query_match.group(1)
            }

        # 第三层：终极兜底，强制终止
        log_message("[WARN] 模型输出格式严重解析失败，强制终止")
        return {
            'status': 'COMPLETE',
            'reason': '模型输出格式严重解析失败，强制终止以保护系统'
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
