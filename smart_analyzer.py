"""
智能信息抽取工具
- 根据用户问题，从大型 MD 文件中抽取相关章节
- 支持多轮交互，确保抽取足够的信息
- 控制 Token 数量在限制内
- 输出抽取的内容供后续分析使用
"""

import sys
import os
import json
import re

# 添加 llm_services 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'llm_services'))

from md_parser import MDParser
from llm_services.qwen_engine import chat_with_llm


class InfoExtractor:
    """信息抽取器 - 从大型文档中智能抽取相关内容"""

    def __init__(self, filepath: str, max_tokens: int = 50000):
        """
        初始化抽取器

        Args:
            filepath: MD 文件路径
            max_tokens: 最大 Token 限制（默认 50K）
        """
        self.parser = MDParser(filepath)
        self.max_tokens = max_tokens
        self.filepath = filepath
        self.extracted_sections = {}  # 已提取的章节缓存 {title: content}
        self.failed_sections = set()  # 提取失败或内容不足的章节
        self.total_tokens_used = 0    # 累计使用的 Token

    def clean_content(self, content: str) -> str:
        """
        清理内容：转换表格、移除无效内容

        Args:
            content: 原始内容

        Returns:
            清理后的内容
        """
        # 1. 转换 HTML 表格为 CSV 格式
        content = self._convert_html_tables_to_csv(content)

        # 2. 移除图片链接
        content = re.sub(r'!\[([^\]]*)\]\([^)]+\)', '', content)

        # 3. 移除多余的空行
        content = re.sub(r'\n{3,}', '\n\n', content)

        return content.strip()

    def _convert_html_tables_to_csv(self, content: str) -> str:
        """
        将 HTML 表格转换为 CSV 格式

        Args:
            content: 包含 HTML 表格的内容

        Returns:
            转换后的内容
        """
        def table_to_csv(table_html: str) -> str:
            """将单个 HTML 表格转为 CSV"""
            rows = []

            # 提取所有行
            row_pattern = r'<tr[^>]*>(.*?)</tr>'
            row_matches = re.findall(row_pattern, table_html, re.DOTALL | re.IGNORECASE)

            for row_content in row_matches:
                # 提取单元格
                cell_pattern = r'<t[dh][^>]*>(.*?)</t[dh]>'
                cells = re.findall(cell_pattern, row_content, re.DOTALL | re.IGNORECASE)

                # 清理单元格内容
                clean_cells = []
                for cell in cells:
                    # 移除 HTML 标签
                    clean_text = re.sub(r'<[^>]+>', '', cell)
                    # 清理空白
                    clean_text = clean_text.strip().replace('\n', ' ').replace('\t', ' ')
                    # 转义 CSV 特殊字符
                    if ',' in clean_text or '"' in clean_text or '\n' in clean_text:
                        clean_text = '"' + clean_text.replace('"', '""') + '"'
                    clean_cells.append(clean_text)

                if clean_cells:
                    rows.append(','.join(clean_cells))

            return '\n'.join(rows)

        # 查找并替换所有 HTML 表格
        table_pattern = r'<table[^>]*>(.*?)</table>'

        def replace_table(match):
            table_html = match.group(0)
            csv = table_to_csv(table_html)
            if csv:
                return '\n' + csv + '\n'
            return ''

        result = re.sub(table_pattern, replace_table, content, flags=re.DOTALL | re.IGNORECASE)
        return result

    def get_toc(self) -> dict:
        """
        获取文档目录

        Returns:
            {
                'toc_text': 目录文本,
                'toc_tokens': 目录 Token 数,
                'total_tokens': 文件总 Token 数,
                'headings': 标题列表
            }
        """
        headings = self.parser.get_headings()

        toc_lines = []
        heading_details = []

        for i, h in enumerate(headings, 1):
            indent = '  ' * (h['level'] - 1)
            toc_lines.append(f"{i}. {indent}H{h['level']}: {h['text']}")

            token_data = self.parser.count_section_tokens(h['text'])
            heading_details.append({
                'index': i,
                'level': h['level'],
                'text': h['text'],
                'line': h['line'],
                'tokens': token_data.get('tokens', 0) if 'error' not in token_data else 0
            })

        toc_text = '\n'.join(toc_lines)
        toc_tokens = self.parser.count_tokens(toc_text)
        stats = self.parser.get_token_stats()

        return {
            'toc_text': toc_text,
            'toc_tokens': toc_tokens,
            'total_tokens': stats['total_tokens'],
            'headings': heading_details
        }

    def get_titles_by_indices(self, indices: list[int]) -> list[str]:
        """
        根据序号列表获取标题

        Args:
            indices: 序号列表

        Returns:
            标题列表
        """
        toc = self.get_toc()
        headings = toc['headings']
        titles = []

        for idx in indices:
            if 1 <= idx <= len(headings):
                titles.append(headings[idx - 1]['text'])

        return titles

    def extract_sections(self, titles: list[str]) -> dict:
        """
        提取章节内容（增量提取，避免重复）

        Args:
            titles: 章节标题列表

        Returns:
            {
                'content': 新提取的内容,
                'new_tokens': 新增 Token 数,
                'success': 成功提取的章节,
                'failed': 未找到的章节,
                'skipped': 已尝试过但跳过的章节,
                'all_extracted': 所有已提取的章节
            }
        """
        budget = self.max_tokens - 5000 - self.total_tokens_used

        new_extracted = []
        new_tokens = 0
        success = []
        failed = []
        skipped = []

        for title in titles:
            # 跳过已提取的章节
            if title in self.extracted_sections:
                success.append(title)
                continue

            # 跳过已失败的章节
            if title in self.failed_sections:
                skipped.append(title)
                continue

            # 尝试直接匹配
            content = self.parser.get_content_between_headings(title)

            if 'error' in content:
                # 尝试模糊匹配（搜索关键词）
                matches = self.parser.search_headings(title)

                if matches:
                    matched_title = matches[0]['text']
                    if matched_title in self.extracted_sections:
                        success.append(matched_title)
                        continue
                    elif matched_title in self.failed_sections:
                        skipped.append(matched_title)
                        continue
                    content = self.parser.get_content_between_headings(matched_title)
                    title = matched_title
                else:
                    self.failed_sections.add(title)
                    failed.append(title)
                    continue

            section_tokens = self.parser.count_tokens(content['content'])

            # 检查内容是否太少（少于 50 tokens 可能只是标题）
            min_content_tokens = 50
            if section_tokens < min_content_tokens:
                print(f"⚠ 内容太少 ({section_tokens} tokens)，跳过: {title}")
                self.failed_sections.add(title)
                skipped.append(title)
                continue

            # 清理内容（转换表格、移除图片等）
            cleaned_content = self.clean_content(content['content'])
            cleaned_tokens = self.parser.count_tokens(cleaned_content)

            if new_tokens + cleaned_tokens > budget:
                print(f"⚠ Token 预算不足，跳过: {title}")
                continue

            self.extracted_sections[title] = cleaned_content
            new_extracted.append(f"## {content['heading']}\n{cleaned_content}")
            new_tokens += cleaned_tokens
            success.append(title)

        self.total_tokens_used += new_tokens
        result_text = '\n\n---\n\n'.join(new_extracted) if new_extracted else ''

        return {
            'content': result_text,
            'new_tokens': new_tokens,
            'success': success,
            'failed': failed,
            'skipped': skipped,
            'all_extracted': list(self.extracted_sections.keys())
        }

    def get_all_extracted_content(self) -> str:
        """获取所有已提取的内容"""
        parts = []
        for title, content in self.extracted_sections.items():
            parts.append(f"## {title}\n{content}")
        return '\n\n---\n\n'.join(parts)

    def extract(self, question: str, verbose: bool = True) -> dict:
        """
        执行智能抽取

        Args:
            question: 用户问题（用于判断需要哪些章节）
            verbose: 是否打印详细过程

        Returns:
            {
                'content': 抽取的内容,
                'tokens': 总 Token 数,
                'sections': 抽取的章节列表
            }
        """
        toc = self.get_toc()

        if verbose:
            print("=" * 60)
            print("Step 1: 发送目录给大模型，选择相关章节")
            print("=" * 60)
            print(f"文件: {self.filepath}")
            print(f"目录 Token: {toc['toc_tokens']:,}")
            print(f"问题: {question}")

        # Step 1: 发送目录，让大模型选择章节
        step1_prompt = f"""你是一个文档分析助手。用户需要从一份大型文档中抽取信息，但文件太大无法一次性加载。

以下是这份文档的完整目录结构（每行开头是序号，括号内是该章节的 Token 数）：

{toc['toc_text']}

文件总 Token 数: {toc['total_tokens']:,}
Token 限制: {self.max_tokens:,}

用户问题: {question}

请判断需要哪些章节来回答这个问题。

【重要】输出要求:
1. 输出章节序号的 JSON 数组，例如: [1, 5, 10]
2. 只输出 JSON 数组，不要有其他文字
3. 序号必须是目录中存在的有效序号
4. 优先选择最相关的章节，注意 Token 总数不要超过限制
"""

        step1_response = chat_with_llm(step1_prompt, enable_thinking=False)

        if verbose:
            print(f"\n大模型返回: {step1_response}")

        # 解析序号列表
        try:
            if '[' in step1_response:
                start = step1_response.index('[')
                end = step1_response.rindex(']') + 1
                json_match = step1_response[start:end]
            indices = json.loads(json_match)
            titles = self.get_titles_by_indices(indices)
        except (json.JSONDecodeError, ValueError) as e:
            if verbose:
                print(f"解析失败: {e}")
            return {'content': '', 'tokens': 0, 'sections': [], 'error': f"无法解析章节列表: {step1_response}"}

        if verbose:
            print(f"\n选择的章节: {titles}")

        # Step 2: 提取章节内容
        if verbose:
            print("\n" + "=" * 60)
            print("Step 2: 提取章节内容")
            print("=" * 60)

        extracted = self.extract_sections(titles)

        if verbose:
            print(f"成功提取: {extracted['success']}")
            if extracted['failed']:
                print(f"未找到: {extracted['failed']}")
            print(f"新增 Token: {extracted['new_tokens']:,}")
            print(f"累计 Token: {self.total_tokens_used:,}")

        return {
            'content': extracted['content'],
            'tokens': self.total_tokens_used,
            'sections': extracted['success']
        }

    def interactive_extract(self, question: str, verbose: bool = True) -> dict:
        """
        交互式抽取：自动处理多轮请求，确保抽取足够的信息

        Args:
            question: 用户问题
            verbose: 是否打印详细过程

        Returns:
            {
                'content': 抽取的内容,
                'tokens': 总 Token 数,
                'sections': 抽取的章节列表,
                'rounds': 交互轮数
            }
        """
        # 第一轮抽取
        result = self.extract(question, verbose)
        rounds = 1

        # 检查是否需要更多章节
        need_more_keywords = ['需要更多', '不足', '缺少', '还需要', '需要额外', 'insufficient']
        max_rounds = 3

        while rounds < max_rounds:
            # 检查是否还有 Token 预算
            if self.total_tokens_used >= self.max_tokens - 5000:
                if verbose:
                    print("\n已达到 Token 限制")
                break

            # 让大模型判断是否需要更多章节
            toc = self.get_toc()

            # 构建已尝试章节的说明
            tried_info = ""
            if self.extracted_sections:
                extracted_indices = [i for i, h in enumerate(toc['headings'], 1) if h['text'] in self.extracted_sections]
                if extracted_indices:
                    tried_info += f"\n已提取的章节序号: {extracted_indices}"
            if self.failed_sections:
                failed_indices = [i for i, h in enumerate(toc['headings'], 1) if h['text'] in self.failed_sections]
                if failed_indices:
                    tried_info += f"\n已尝试但失败的章节序号: {failed_indices}"

            check_prompt = f"""用户问题: {question}

以下是完整目录（每行开头是序号）：

{toc['toc_text']}

已抽取的内容 Token 数: {self.total_tokens_used:,}
Token 限制: {self.max_tokens:,}
{tried_info}

请判断：已抽取的内容是否足够回答用户问题？

【输出要求】
- 如果足够，输出: {{"enough": true}}
- 如果需要更多章节，从目录中选择序号，输出: {{"enough": false, "needed": [序号列表]}}

例如: {{"enough": false, "needed": [10, 20, 30]}}
"""

            check_response = chat_with_llm(check_prompt)

            try:
                if '{' in check_response:
                    start = check_response.index('{')
                    end = check_response.rindex('}') + 1
                    check_result = json.loads(check_response[start:end])

                    if check_result.get('enough', True):
                        break

                    needed_indices = check_result.get('needed', [])
                    if not needed_indices:
                        break

                    additional_titles = self.get_titles_by_indices(needed_indices)
                else:
                    break
            except:
                break

            # 检查是否所有请求的章节都已尝试过
            all_tried = all(t in self.extracted_sections or t in self.failed_sections for t in additional_titles)
            if all_tried:
                if verbose:
                    print("\n所有请求的章节都已尝试过")
                break

            if verbose:
                print(f"\n第 {rounds + 1} 轮: 请求额外章节 {additional_titles}")

            # 提取额外章节
            extracted = self.extract_sections(additional_titles)

            if verbose:
                print(f"成功提取: {extracted['success']}")
                print(f"累计 Token: {self.total_tokens_used:,}")

            rounds += 1

        # 返回最终结果
        return {
            'content': self.get_all_extracted_content(),
            'tokens': self.total_tokens_used,
            'sections': list(self.extracted_sections.keys()),
            'rounds': rounds
        }


def main():
    """命令行入口"""
    if len(sys.argv) < 3:
        print("用法: python smart_analyzer.py <md_file> <question> [max_tokens]")
        print("\n功能: 根据问题从大型 MD 文件中智能抽取相关章节")
        print("\n示例:")
        print("  python smart_analyzer.py output/MinerU_markdown_*.md '分析现金流状况'")
        print("  python smart_analyzer.py output/MTR_note.md 'What is the cash flow trend?' 30000")
        sys.exit(1)

    filepath = sys.argv[1]
    question = sys.argv[2]
    max_tokens = int(sys.argv[3]) if len(sys.argv) > 3 else 50000

    if not os.path.exists(filepath):
        print(f"错误: 文件不存在 - {filepath}")
        sys.exit(1)

    extractor = InfoExtractor(filepath, max_tokens)
    result = extractor.interactive_extract(question)

    print("\n" + "=" * 60)
    print("抽取结果")
    print("=" * 60)
    print(f"抽取章节: {result['sections']}")
    print(f"总 Token: {result['tokens']:,}")
    print(f"交互轮数: {result['rounds']}")
    print("\n" + "=" * 60)
    print("抽取内容")
    print("=" * 60)
    print(result['content'])


if __name__ == '__main__':
    main()
