"""
BM25 轻量检索器
- 将文档切分为小块
- 用 BM25 计算相似度
- 取 Top-K 块送入 LLM
- 无需向量数据库，纯文本检索
"""

import os
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

# jieba 分词
try:
    import jieba
except ImportError:
    print("请安装: pip install jieba")
    sys.exit(1)

from common.text_utils import clean_content, count_tokens, to_traditional
from common.table_utils import find_table_ranges


class BM25Retriever:
    """BM25 轻量检索器 - 无需向量数据库"""

    # 类级别词典加载标记
    _dict_loaded = False

    # 表格处理配置参数（可被子类覆盖）
    TABLE_TITLE_SEARCH_RANGE = 200      # 表格前搜索标题的字符范围
    TABLE_TITLE_MIN_LEN = 5             # 标题最小长度
    TABLE_TITLE_MAX_LEN = 30            # 标题最大长度
    TABLE_TITLE_MAX_COMMA = 1           # 标题最大逗号数（排除 CSV 行）
    TABLE_TITLE_MAX_DISTANCE = 50       # 标题距离表格的最大距离
    TABLE_CONTEXT_AFTER = 100           # 表格后上下文长度
    PARAGRAPH_SEARCH_RANGE = 100        # 段落边界搜索范围

    @classmethod
    def _load_finance_dict(cls):
        """加载财务领域词典（只加载一次），转换为繁体中文"""
        if cls._dict_loaded:
            return
        dict_path = os.path.join(
            os.path.dirname(__file__), 'common', 'finance_dict.txt'
        )
        if os.path.exists(dict_path):
            # 读取词典并转换为繁体
            with open(dict_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    word = to_traditional(parts[0])  # 转换为繁体
                    freq = parts[1] if len(parts) > 1 else '5'
                    tag = parts[2] if len(parts) > 2 else 'n'
                    jieba.add_word(word, int(freq), tag)
        cls._dict_loaded = True

    def __init__(
        self,
        filepath: str,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        clean_content_flag: bool = True,
        use_cache: bool = False
    ):
        """
        初始化检索器

        Args:
            filepath: MD 文件路径
            chunk_size: 块大小（字符数）
            chunk_overlap: 块重叠
            clean_content_flag: 是否清理内容（转换表格、移除图片）
            use_cache: 是否使用索引缓存（默认 False）
        """
        self.filepath = filepath
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.clean_content_flag = clean_content_flag

        # 加载财务词典
        self._load_finance_dict()

        # 加载同义词映射
        self.synonym_map = self._load_synonyms()

        # 尝试加载已保存的索引
        if use_cache and self.load_index(filepath):
            # 索引已加载，跳过文档处理
            self.raw_content = ''
            self.raw_lines = []
            self.content = ''
            self.lines = []
            return

        # 索引不存在，需要从头处理文档
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

        # 保存索引到文件
        if use_cache:
            self.save_index(filepath)

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

    def _generate_table_label(self, table_text: str, title: str) -> str:
        """
        生成表格的简短标签（用于 Parent-Child 策略）

        业务逻辑：
        1. 优先使用具体的章节标题
        2. 如果标题宽泛，纵向提取表格第一列（科目列）的前 3~4 个核心科目进行拼接

        Args:
            table_text: 完整表格内容
            title: 表格前的标题

        Returns:
            简短标签（~100字）
        """
        # 1. 优先使用具体的章节标题
        generic_titles = {"附注", "续表", "重要项目", "表格", "说明", "明细"}
        if title and len(title) >= 5 and not any(gt in title for gt in generic_titles):
            return title[:100]

        # 2. 纵向提取第一列（科目定义列）
        lines = table_text.strip().split('\n')
        extracted_accounts = []

        for line in lines:
            # 过滤掉 MD 表格的对齐线（如 |---|---|）或空行
            if '---' in line or not line.strip():
                continue

            # 兼容 Markdown 的 | 和 CSV 的 , 进行切分
            cells = [c.strip() for c in re.split(r'[\|,]', line) if c.strip()]

            if cells:
                first_column_cell = cells[0]
                # 过滤掉"项目/科目/名称"等无意义的通用表头字眼（简繁体）
                generic_headers = ["项目", "科目", "名称", "资产", "负债", "权益", "指标",
                                   "項目", "科目", "名稱", "資產", "負債", "權益", "指標"]
                if first_column_cell in generic_headers:
                    continue

                # 只提取包含中文字符的实质性科目（防止抓到乱码或纯数字）
                if re.search(r'[\u4e00-\u9fa5]', first_column_cell):
                    extracted_accounts.append(first_column_cell)

            # 提取 3-4 个核心科目即可，保证标签的高浓度
            if len(extracted_accounts) >= 4:
                break

        # 3. 组装成高浓度的 Child Label
        if extracted_accounts:
            # 格式如: "附注_销售商品收现/收到税费返还/购买商品付现"
            account_path = "/".join(extracted_accounts)
            return f"{title}_{account_path}"[:100]

        # 4. 终极兜底
        return f"{title}_{table_text[:30]}".replace('\n', ' ')

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

                # 查找表格前的标题
                context_start = max(0, table_start - self.TABLE_TITLE_SEARCH_RANGE)
                title_start = table_start
                search_text = content[context_start:table_start]
                lines = search_text.split('\n')

                # 表格标题（优先使用"独立短行"，其次使用 # 标题）
                table_title = ""

                # 从后往前找，找到第一个标题行
                # 优先匹配 # 开头的行，其次匹配"独立短行"（可能是无 # 前缀的标题）
                for i in range(len(lines) - 1, -1, -1):
                    line_stripped = lines[i].strip()

                    # 1. 检查是否以 # 开头（标准 Markdown 标题）
                    if line_stripped.startswith('#'):
                        title_start = context_start + sum(len(lines[j]) + 1 for j in range(i))
                        table_title = line_stripped.lstrip('#').strip()
                        break

                    # 2. 检查是否是"独立短行"（可能是表格标题）
                    if (
                        len(line_stripped) >= self.TABLE_TITLE_MIN_LEN and
                        len(line_stripped) <= self.TABLE_TITLE_MAX_LEN and
                        line_stripped.count(',') <= self.TABLE_TITLE_MAX_COMMA and
                        not line_stripped.startswith('http')
                    ):
                        # 检查这行前后是否是空行（独立行特征）
                        prev_empty = (i == 0) or not lines[i-1].strip()
                        next_empty = (i == len(lines) - 1) or not lines[i+1].strip()
                        if prev_empty or next_empty:
                            title_start = context_start + sum(len(lines[j]) + 1 for j in range(i))
                            table_title = line_stripped
                            break

                # 如果没找到标题，或者标题距离表格太远，就从表格前一个换行开始
                if title_start == table_start or table_start - title_start > self.TABLE_TITLE_MAX_DISTANCE:
                    temp_start = table_start
                    while temp_start > 0 and content[temp_start - 1] != '\n':
                        temp_start -= 1
                    title_start = max(0, temp_start)

                # 包含表格后的上下文
                context_end = min(content_len, table_end + self.TABLE_CONTEXT_AFTER)
                while context_end < content_len and content[context_end] != '\n':
                    context_end += 1

                chunk_text = content[title_start:context_end].strip()
                line_num = content[:title_start].count('\n') + 1

                # 优先使用表格前的"独立短行"标题，否则使用 # 标题
                if table_title:
                    heading = table_title
                else:
                    heading = self._find_heading_for_line(line_num - 1)

                # 生成表格标签（Parent-Child 策略）
                table_label = self._generate_table_label(chunk_text, heading)

                chunks.append({
                    'text': chunk_text,
                    'metadata': {
                        'line': line_num,
                        'heading': heading,
                        'has_table': True,
                        'child_label': table_label  # Child: 检索用标签
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
                    for offset in range(0, min(self.PARAGRAPH_SEARCH_RANGE, chunk_end - pos)):
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

        # 添加重叠（跳过表格块，避免表格内容被污染）
        if self.chunk_overlap > 0 and len(chunks) > 1:
            for i in range(1, len(chunks)):
                # 跳过表格块，不添加重叠
                if chunks[i]['metadata'].get('has_table', False):
                    continue
                prev_text = chunks[i-1]['text']
                overlap_len = min(self.chunk_overlap, len(prev_text))
                if overlap_len > 0:
                    overlap_text = prev_text[-overlap_len:]
                    if not chunks[i]['text'].startswith(overlap_text):
                        chunks[i]['text'] = overlap_text + '\n' + chunks[i]['text']

        return chunks

    def _load_synonyms(self) -> dict:
        """加载同义词映射"""
        synonym_map = {}
        synonym_path = os.path.join(
            os.path.dirname(__file__), 'common', 'synonyms.txt'
        )
        if os.path.exists(synonym_path):
            with open(synonym_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, values = line.split('=', 1)
                        key_trad = to_traditional(key.strip())
                        values_trad = [to_traditional(v.strip()) for v in values.split(',')]
                        synonym_map[key_trad] = values_trad
        return synonym_map

    def _tokenize(self, text: str, expand_synonyms: bool = False) -> list[str]:
        """
        使用 jieba 进行中文分词

        Args:
            text: 输入文本
            expand_synonyms: 是否扩展同义词（用于查询）

        Returns:
            token 列表
        """
        # 简繁转换（文档是繁体）
        text = to_traditional(text)

        # jieba 分词
        tokens = list(jieba.cut(text))

        # 过滤空白和单字符标点
        tokens = [t.strip() for t in tokens if t.strip() and len(t.strip()) > 0]

        # 同义词扩展（仅用于查询）
        if expand_synonyms:
            expanded = []
            for t in tokens:
                expanded.append(t)
                # 添加同义词
                if t in self.synonym_map:
                    expanded.extend(self.synonym_map[t])
            tokens = expanded

        return tokens

    def _build_index(self) -> BM25Okapi:
        """
        构建 BM25 索引（Parent-Child 混合索引）

        对于表格块：
        - 将标签重复 3 次注入开头，人为拉高标题关键词的 TF 权重
        - 同时保留表身内容，确保科目检索不漏失

        对于非表格块：
        - 直接使用完整文本
        """
        tokenized_corpus = []
        for chunk in self.chunks:
            if chunk['metadata'].get('has_table') and chunk['metadata'].get('child_label'):
                # 权重增强型混合索引：标签重复 3 次 + 完整表身
                enriched_text = (chunk['metadata']['child_label'] + " ") * 3 + chunk['text']
                tokenized_corpus.append(self._tokenize(enriched_text))
            else:
                tokenized_corpus.append(self._tokenize(chunk['text']))

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
        # 分词（内部已包含简繁转换），启用同义词扩展
        tokenized_query = self._tokenize(query, expand_synonyms=True)
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

    def save_index(self, filepath: str) -> str:
        """
        保存索引到文件（持久化）

        Args:
            filepath: 原始文档路径

        Returns:
            索引文件路径
        """
        import json
        index_path = filepath + '.index.json'

        index_data = {
            'chunks': self.chunks,
            'table_ranges': self.table_ranges,
            'stats': self.get_stats()
        }

        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)

        return index_path

    def load_index(self, filepath: str) -> bool:
        """
        加载已保存的索引

        Args:
            filepath: 原始文档路径

        Returns:
            是否成功加载
        """
        import json
        index_path = filepath + '.index.json'

        if not os.path.exists(index_path):
            return False

        with open(index_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)

        self.chunks = index_data['chunks']
        self.table_ranges = [tuple(r) for r in index_data['table_ranges']]
        self.bm25 = self._build_index()

        # 加载保存的统计信息
        if 'stats' in index_data:
            self._cached_stats = index_data['stats']

        return True

    def get_stats(self) -> dict:
        """返回索引统计信息"""
        # 如果有缓存的统计信息，直接返回
        if hasattr(self, '_cached_stats') and self._cached_stats:
            return self._cached_stats

        total_chars = sum(len(chunk['text']) for chunk in self.chunks)
        avg_chunk_size = total_chars / len(self.chunks) if self.chunks else 0

        raw_tokens = self._count_tokens(self.raw_content) if self.raw_content else 0
        cleaned_tokens = self._count_tokens(self.content) if self.content else 0

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
                    'score': 0.0,
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
        print("  python bm25_retriever.py output/report.md '现金流分析'")
        print("  python bm25_retriever.py output/report.md '现金流量表' 8000")
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
