"""
BM25 轻量检索器
- 将文档切分为小块
- 用 BM25 计算相似度
- 取 Top-K 块送入 LLM
- 无需向量数据库，纯文本检索
"""

import re
import sys
from typing import Optional

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    print("请安装: pip install rank_bm25")
    sys.exit(1)

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    print("请安装: pip install langchain-text-splitters")
    sys.exit(1)

# 简繁转换
try:
    import opencc
    _converter = opencc.OpenCC('s2t.json')  # 简体转繁体
    def to_traditional(text: str) -> str:
        return _converter.convert(text)
except ImportError:
    try:
        import zhconv
        def to_traditional(text: str) -> str:
            return zhconv.convert(text, 'zh-hant')
    except ImportError:
        def to_traditional(text: str) -> str:
            return text  # 无转换库时保持原样

from common.text_utils import clean_content, count_tokens
from common.table_utils import find_table_ranges


class BM25Retriever:
    """BM25 轻量检索器 - 无需向量数据库"""

    def __init__(
        self,
        filepath: str,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        clean_content_flag: bool = True
    ):
        """
        初始化检索器

        Args:
            filepath: MD 文件路径
            chunk_size: 块大小（字符数）
            chunk_overlap: 块重叠
            clean_content_flag: 是否清理内容（转换表格、移除图片）
        """
        self.filepath = filepath
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.clean_content_flag = clean_content_flag

        with open(filepath, 'r', encoding='utf-8') as f:
            self.raw_content = f.read()
        self.raw_lines = self.raw_content.split('\n')

        # 清理内容（用于检索和输出）
        if clean_content_flag:
            self.content = clean_content(self.raw_content)
        else:
            self.content = self.raw_content
        self.lines = self.content.split('\n')

        # 识别内容中的表格位置（使用公共组件）
        self.table_ranges = find_table_ranges(self.content)

        # 切分文档（表格感知）
        self.chunks = self._split_document_table_aware()

        # 构建 BM25 索引
        self.bm25 = self._build_index()

    def _is_in_table(self, pos: int) -> bool:
        """检查位置是否在表格内"""
        for start, end in self.table_ranges:
            if start <= pos < end:
                return True
        return False

    def _find_table_for_pos(self, pos: int) -> Optional[tuple]:
        """找到包含该位置的表格范围"""
        for start, end in self.table_ranges:
            if start <= pos < end:
                return (start, end)
        return None

    def _find_heading_for_line(self, line_num: int) -> str:
        """找到某行所属的最近标题"""
        heading = ""
        # 使用原始行来查找标题（标题结构不变）
        for i, line in enumerate(self.raw_lines[:line_num + 1], 1):
            if line.startswith('#'):
                # 提取标题文本
                heading = line.lstrip('#').strip()
        return heading

    def _split_document_table_aware(self) -> list[dict]:
        """
        表格感知的文档切分
        - 确保表格不被切断
        - 保留表格上下文

        Returns:
            [{'text': '...', 'metadata': {'line': 10, 'heading': '...'}}, ...]
        """
        chunks = []
        content = self.content
        content_len = len(content)
        pos = 0

        while pos < content_len:
            # 检查当前位置是否在表格内
            table_range = self._find_table_for_pos(pos)

            if table_range:
                # 当前位置在表格内，将整个表格作为一个块
                table_start, table_end = table_range

                # 包含表格前的上下文（前一个换行到表格结束）
                context_start = max(0, table_start - 200)  # 前200字符上下文
                # 找到上下文的段落边界
                while context_start > 0 and content[context_start] != '\n':
                    context_start -= 1

                # 包含表格后的上下文
                context_end = min(content_len, table_end + 100)
                while context_end < content_len and content[context_end] != '\n':
                    context_end += 1

                chunk_text = content[context_start:context_end].strip()
                line_num = content[:context_start].count('\n') + 1
                heading = self._find_heading_for_line(line_num - 1)

                chunks.append({
                    'text': chunk_text,
                    'metadata': {
                        'line': line_num,
                        'heading': heading,
                        'has_table': True
                    }
                })

                pos = context_end
            else:
                # 不在表格内，正常分块
                chunk_end = min(pos + self.chunk_size, content_len)

                # 检查块结束位置是否在表格内
                if self._is_in_table(chunk_end):
                    # 找到表格开始位置，在那之前截断
                    for start, end in self.table_ranges:
                        if start < chunk_end < end:
                            chunk_end = start
                            break

                # 找到合适的分割点（段落边界优先）
                if chunk_end < content_len:
                    # 尝试在段落边界分割
                    for offset in range(0, min(100, chunk_end - pos)):
                        if chunk_end - offset > pos and content[chunk_end - offset] == '\n':
                            chunk_end = chunk_end - offset
                            break

                chunk_text = content[pos:chunk_end].strip()
                if chunk_text:
                    line_num = content[:pos].count('\n') + 1
                    heading = self._find_heading_for_line(line_num - 1)

                    chunks.append({
                        'text': chunk_text,
                        'metadata': {
                            'line': line_num,
                            'heading': heading,
                            'has_table': False
                        }
                    })

                pos = chunk_end

        # 添加重叠
        if self.chunk_overlap > 0 and len(chunks) > 1:
            for i in range(1, len(chunks)):
                prev_text = chunks[i-1]['text']
                overlap_len = min(self.chunk_overlap, len(prev_text))
                if overlap_len > 0:
                    overlap_text = prev_text[-overlap_len:]
                    if not chunks[i]['text'].startswith(overlap_text):
                        chunks[i]['text'] = overlap_text + '\n' + chunks[i]['text']

        return chunks

    def _tokenize(self, text: str) -> list[str]:
        """
        中文分词：字符 + 二元语法（bigram）+ 英文单词

        Args:
            text: 输入文本

        Returns:
            token 列表
        """
        tokens = []
        word = ""
        chinese_chars = []

        for char in text:
            # 中文字符
            if '\u4e00' <= char <= '\u9fff':
                if word:
                    tokens.append(word.lower())
                    word = ""
                chinese_chars.append(char)
            # 英文/数字累积成词
            elif char.isalnum():
                if chinese_chars:
                    # 处理累积的中文
                    tokens.extend(chinese_chars)  # 单字符
                    # 添加二元语法
                    for i in range(len(chinese_chars) - 1):
                        tokens.append(''.join(chinese_chars[i:i+2]))
                    chinese_chars = []
                word += char
            # 其他字符作为分隔
            else:
                if word:
                    tokens.append(word.lower())
                    word = ""
                if chinese_chars:
                    tokens.extend(chinese_chars)
                    for i in range(len(chinese_chars) - 1):
                        tokens.append(''.join(chinese_chars[i:i+2]))
                    chinese_chars = []

        # 处理末尾
        if word:
            tokens.append(word.lower())
        if chinese_chars:
            tokens.extend(chinese_chars)
            for i in range(len(chinese_chars) - 1):
                tokens.append(''.join(chinese_chars[i:i+2]))

        return tokens

    def _build_index(self) -> BM25Okapi:
        """构建 BM25 索引"""
        tokenized_corpus = [self._tokenize(chunk['text']) for chunk in self.chunks]
        return BM25Okapi(tokenized_corpus)

    def retrieve(self, query: str, top_k: int = 15) -> list[dict]:
        """
        检索相关块

        Args:
            query: 用户问题
            top_k: 返回块数

        Returns:
            [{'text': '...', 'score': 0.85, 'metadata': {...}}, ...]
        """
        # 转换为繁体中文（文档是繁体）
        query_traditional = to_traditional(query)
        tokenized_query = self._tokenize(query_traditional)
        scores = self.bm25.get_scores(tokenized_query)

        # 获取 top_k 索引
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        for idx in top_indices:
            chunk = self.chunks[idx]
            results.append({
                'text': chunk['text'],
                'score': float(scores[idx]),
                'metadata': chunk['metadata']
            })

        return results

    def get_context(
        self,
        query: str,
        max_tokens: int = 12000,
        top_k: int = 30
    ) -> dict:
        """
        获取适合 LLM 输入的上下文

        Args:
            query: 用户问题
            max_tokens: 最大 Token 数
            top_k: 初始检索块数

        Returns:
            {
                'context': 拼接后的上下文,
                'tokens': 总 Token 数,
                'chunks': 选中的块信息,
                'stats': 统计信息
            }
        """
        # 检索相关块
        chunks = self.retrieve(query, top_k=top_k)

        # Token 预算控制
        selected = []
        total_tokens = 0

        for chunk in chunks:
            chunk_tokens = self._count_tokens(chunk['text'])
            if total_tokens + chunk_tokens <= max_tokens:
                selected.append(chunk)
                total_tokens += chunk_tokens
            else:
                break

        # 按原始顺序重排
        selected.sort(key=lambda x: x['metadata']['line'])

        # 拼接上下文
        context_parts = []
        for chunk in selected:
            # 添加来源标记
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
            'stats': {
                'total_chunks': len(self.chunks),
                'retrieved': len(chunks),
                'selected': len(selected),
                'max_tokens': max_tokens
            }
        }

    def _count_tokens(self, text: str, model: str = "cl100k_base") -> int:
        """计算文本的 Token 数量（使用公共组件）"""
        return count_tokens(text, model)

    def get_stats(self) -> dict:
        """返回索引统计信息"""
        total_chars = sum(len(chunk['text']) for chunk in self.chunks)
        avg_chunk_size = total_chars / len(self.chunks) if self.chunks else 0

        raw_tokens = self._count_tokens(self.raw_content)
        cleaned_tokens = self._count_tokens(self.content)

        return {
            'total_chunks': len(self.chunks),
            'total_chars': total_chars,
            'avg_chunk_size': int(avg_chunk_size),
            'chunk_size': self.chunk_size,
            'chunk_overlap': self.chunk_overlap,
            'raw_tokens': raw_tokens,
            'cleaned_tokens': cleaned_tokens,
            'tokens_saved': raw_tokens - cleaned_tokens,
            'clean_content': self.clean_content_flag
        }

    def search_by_keyword(self, keyword: str, top_k: int = 10) -> list[dict]:
        """
        精确关键词搜索（不使用 BM25）

        Args:
            keyword: 关键词
            top_k: 返回块数

        Returns:
            匹配的块列表
        """
        results = []
        for chunk in self.chunks:
            if keyword.lower() in chunk['text'].lower():
                results.append({
                    'text': chunk['text'],
                    'metadata': chunk['metadata']
                })
                if len(results) >= top_k:
                    break

        return results


def main():
    """命令行入口"""
    if len(sys.argv) < 3:
        print("用法: python bm25_retriever.py <md_file> <query> [max_tokens]")
        print("\n功能: 使用 BM25 从大型 MD 文件中检索相关内容")
        print("\n示例:")
        print("  python bm25_retriever.py output/MinerU_markdown_*.md '分析现金流状况'")
        print("  python bm25_retriever.py output/MTR_note.md '现金流量表' 8000")
        sys.exit(1)

    filepath = sys.argv[1]
    query = sys.argv[2]
    max_tokens = int(sys.argv[3]) if len(sys.argv) > 3 else 12000

    print("=" * 60)
    print("BM25 轻量检索")
    print("=" * 60)
    print(f"文件: {filepath}")
    print(f"问题: {query}")
    print(f"Token 限制: {max_tokens:,}")

    # 初始化检索器
    retriever = BM25Retriever(filepath)
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

    result = retriever.get_context(query, max_tokens=max_tokens)

    print(f"选中块数: {result['stats']['selected']}/{result['stats']['retrieved']}")
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
