"""
Markdown AST 解析器
提取标题层级、表格数据、代码块、标题间内容
"""

import re
from typing import Optional
from markdown_it import MarkdownIt
from mdit_py_plugins.gfm import gfm_plugin


class MDParser:
    """Markdown 文档解析器"""

    def __init__(self, filepath: str):
        with open(filepath, 'r', encoding='utf-8') as f:
            self.content = f.read()
        self.lines = self.content.split('\n')
        self.md = MarkdownIt().use(gfm_plugin)
        self.tokens = self.md.parse(self.content)

    def get_headings(self) -> list[dict]:
        """
        提取所有标题，返回层级树结构

        Returns:
            [{'level': 1, 'text': '标题', 'line': 1, 'children': [...]}, ...]
        """
        headings = []
        for i, token in enumerate(self.tokens):
            if token.type == 'heading_open':
                level = int(token.tag[1])  # h1 -> 1
                # 下一个 token 是 inline，包含标题文本
                inline_token = self.tokens[i + 1]
                text = inline_token.content
                headings.append({
                    'level': level,
                    'text': text,
                    'line': token.map[0] + 1 if token.map else None,
                    'children': []
                })

        # 构建层级树
        return self._build_heading_tree(headings)

    def _build_heading_tree(self, headings: list[dict]) -> list[dict]:
        """将扁平标题列表转为树结构"""
        if not headings:
            return []

        root = {'level': 0, 'children': []}
        stack = [root]

        for heading in headings:
            # 弹出栈直到找到父节点
            while stack[-1]['level'] >= heading['level']:
                stack.pop()
            stack[-1]['children'].append(heading)
            stack.append(heading)

        return root['children']

    def get_tables(self) -> list[dict]:
        """
        提取所有表格数据（包括 Markdown 表格和 HTML 表格）

        Returns:
            [{'headers': ['列1', '列2'], 'rows': [['A', 'B'], ...], 'line': 10}, ...]
        """
        tables = []

        # 1. 解析 Markdown 表格
        i = 0
        while i < len(self.tokens):
            token = self.tokens[i]
            if token.type == 'table_open':
                table_data = self._parse_table(i)
                table_data['type'] = 'markdown'
                tables.append(table_data)
                i = table_data['end_index'] + 1
            else:
                i += 1

        # 2. 解析 HTML 表格
        html_tables = self._parse_html_tables()
        tables.extend(html_tables)

        return tables

    def _parse_html_tables(self) -> list[dict]:
        """解析 HTML <table> 标签"""
        tables = []
        pattern = r'<table[^>]*>(.*?)</table>'
        matches = re.finditer(pattern, self.content, re.DOTALL | re.IGNORECASE)

        for match in matches:
            table_html = match.group(1)
            line_num = self.content[:match.start()].count('\n') + 1

            # 解析表格内容
            rows = []
            headers = []

            # 提取所有行
            row_pattern = r'<tr[^>]*>(.*?)</tr>'
            row_matches = re.findall(row_pattern, table_html, re.DOTALL | re.IGNORECASE)

            for row_idx, row_content in enumerate(row_matches):
                # 提取单元格
                cells = []
                # td 和 th
                cell_pattern = r'<t[dh][^>]*>(.*?)</t[dh]>'
                cell_matches = re.findall(cell_pattern, row_content, re.DOTALL | re.IGNORECASE)

                for cell_content in cell_matches:
                    # 清理 HTML 标签
                    clean_text = re.sub(r'<[^>]+>', '', cell_content)
                    clean_text = clean_text.strip().replace('\n', ' ')
                    cells.append(clean_text)

                if cells:
                    # 判断是否为表头行（第一行包含 th 或第一个非空行）
                    if row_idx == 0 and '<th' in row_content.lower():
                        headers = cells
                    else:
                        rows.append(cells)

            # 如果没有明确的表头，使用第一行作为表头
            if not headers and rows:
                headers = rows.pop(0)

            if headers or rows:
                tables.append({
                    'headers': headers,
                    'rows': rows,
                    'line': line_num,
                    'type': 'html'
                })

        return tables

    def _parse_table(self, start_index: int) -> dict:
        """解析单个表格"""
        headers = []
        rows = []
        current_row = []
        in_thead = False
        in_tbody = False
        end_index = start_index

        for i in range(start_index, len(self.tokens)):
            token = self.tokens[i]
            end_index = i

            if token.type == 'thead_open':
                in_thead = True
            elif token.type == 'thead_close':
                in_thead = False
            elif token.type == 'tbody_open':
                in_tbody = True
            elif token.type == 'tbody_close':
                in_tbody = False
            elif token.type == 'table_close':
                break
            elif token.type == 'tr_open':
                current_row = []
            elif token.type == 'tr_close':
                if in_thead:
                    headers = current_row
                elif in_tbody:
                    rows.append(current_row)
            elif token.type == 'inline' and (in_thead or in_tbody):
                current_row.append(token.content)

        return {
            'headers': headers,
            'rows': rows,
            'line': self.tokens[start_index].map[0] + 1 if self.tokens[start_index].map else None,
            'end_index': end_index
        }

    def get_code_blocks(self) -> list[dict]:
        """
        提取所有代码块

        Returns:
            [{'language': 'python', 'code': '...', 'line': 10}, ...]
        """
        code_blocks = []
        i = 0
        while i < len(self.tokens):
            token = self.tokens[i]
            if token.type == 'fence':
                code_blocks.append({
                    'language': token.info.strip() if token.info else '',
                    'code': token.content.rstrip('\n'),
                    'line': token.map[0] + 1 if token.map else None
                })
            elif token.type == 'code_block':
                code_blocks.append({
                    'language': '',
                    'code': token.content.rstrip('\n'),
                    'line': token.map[0] + 1 if token.map else None
                })
            i += 1
        return code_blocks

    def get_content_between_headings(
        self,
        start_heading: str,
        end_heading: Optional[str] = None
    ) -> dict:
        """
        获取两个标题之间的内容

        Args:
            start_heading: 起始标题文本（支持部分匹配）
            end_heading: 结束标题文本（可选，默认为下一个同级或更高级标题）

        Returns:
            {'heading': '标题', 'level': 2, 'content': '...', 'line': 10}
        """
        # 找到起始标题位置
        start_idx = None
        start_level = None
        heading_info = None

        for i, token in enumerate(self.tokens):
            if token.type == 'heading_open':
                inline_token = self.tokens[i + 1]
                if start_heading in inline_token.content:
                    start_idx = token.map[0] if token.map else None
                    start_level = int(token.tag[1])
                    heading_info = {
                        'heading': inline_token.content,
                        'level': start_level,
                        'line': token.map[0] + 1 if token.map else None
                    }
                    break

        if start_idx is None:
            return {'error': f'未找到标题: {start_heading}'}

        # 找到结束标题位置
        end_idx = len(self.lines)
        if end_heading:
            for i, token in enumerate(self.tokens):
                if token.type == 'heading_open':
                    inline_token = self.tokens[i + 1]
                    if end_heading in inline_token.content:
                        end_idx = token.map[0] if token.map else end_idx
                        break
        else:
            # 找下一个同级或更高级标题
            found_start = False
            for i, token in enumerate(self.tokens):
                if token.type == 'heading_open':
                    if not found_start:
                        if token.map and token.map[0] == start_idx:
                            found_start = True
                    else:
                        level = int(token.tag[1])
                        if level <= start_level:
                            end_idx = token.map[0] if token.map else end_idx
                            break

        # 提取内容（去掉标题本身）
        content_lines = self.lines[start_idx + 1:end_idx]
        content = '\n'.join(content_lines).strip()

        return {
            **heading_info,
            'content': content
        }

    def get_sections(self) -> dict:
        """
        按一级标题切分文档

        Returns:
            {'标题名': {'level': 1, 'content': '...', 'subsections': {...}}, ...}
        """
        sections = {}
        current_section = None
        current_content = []
        current_subsections = {}

        def save_section():
            if current_section:
                sections[current_section['text']] = {
                    'level': current_section['level'],
                    'line': current_section['line'],
                    'content': '\n'.join(current_content).strip(),
                    'subsections': current_subsections
                }

        for i, token in enumerate(self.tokens):
            if token.type == 'heading_open':
                level = int(token.tag[1])
                inline_token = self.tokens[i + 1]
                text = inline_token.content
                line = token.map[0] + 1 if token.map else None

                if level == 1:
                    save_section()
                    current_section = {'level': level, 'text': text, 'line': line}
                    current_content = []
                    current_subsections = {}
                elif level == 2 and current_section:
                    # 保存之前的二级标题内容
                    if current_subsections:
                        last_key = list(current_subsections.keys())[-1]
                        current_subsections[last_key]['content'] = '\n'.join(
                            current_subsections[last_key]['content_lines']
                        ).strip()
                        del current_subsections[last_key]['content_lines']

                    current_subsections[text] = {
                        'level': level,
                        'line': line,
                        'content_lines': []
                    }
                elif level > 2 and current_section:
                    # 三级及以下标题内容归入当前二级标题
                    if current_subsections:
                        last_key = list(current_subsections.keys())[-1]
                        current_subsections[last_key]['content_lines'].append(
                            f"{'#' * level} {text}"
                        )
            else:
                # 收集内容
                if token.type == 'inline':
                    content = token.content
                    if current_subsections:
                        last_key = list(current_subsections.keys())[-1]
                        current_subsections[last_key]['content_lines'].append(content)
                    elif current_section:
                        current_content.append(content)

        save_section()
        return sections

    # ==================== 常用便捷方法 ====================

    def print_headings(self, limit: Optional[int] = None) -> None:
        """
        打印所有标题列表

        Args:
            limit: 最大显示数量，None 表示全部显示
        """
        headings = self.get_headings()
        total = len(headings)
        display = headings[:limit] if limit else headings

        print(f'共 {total} 个标题\n')
        for h in display:
            print(f"H{h['level']}: {h['text']} (line {h['line']})")

        if limit and total > limit:
            print(f'\n... 还有 {total - limit} 个标题')

    def search_headings(self, keyword: str) -> list[dict]:
        """
        搜索包含关键词的标题

        Args:
            keyword: 搜索关键词

        Returns:
            匹配的标题列表
        """
        results = []
        headings = self.get_headings()
        for h in headings:
            if keyword in h['text']:
                results.append(h)
        return results

    def get_sections_by_titles(self, titles: list[str]) -> dict[str, dict]:
        """
        批量提取多个章节内容

        Args:
            titles: 标题列表

        Returns:
            {'标题名': {'heading': ..., 'content': ..., 'level': ...}, ...}
        """
        results = {}
        for title in titles:
            content = self.get_content_between_headings(title)
            if 'error' not in content:
                results[title] = content
            else:
                results[title] = {'error': content['error']}
        return results

    def get_section_preview(self, title: str, length: int = 500) -> str:
        """
        获取章节内容预览

        Args:
            title: 标题文本
            length: 预览长度（字符数）

        Returns:
            预览文本
        """
        content = self.get_content_between_headings(title)
        if 'error' in content:
            return content['error']

        text = content['content']
        if len(text) <= length:
            return text
        return text[:length] + '\n...'

    def get_images(self) -> list[dict]:
        """
        提取文档中所有图片链接

        Returns:
            [{'alt': '图片说明', 'url': 'https://...', 'line': 10}, ...]
        """
        import re
        pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        images = []

        for i, line in enumerate(self.lines, 1):
            matches = re.findall(pattern, line)
            for alt, url in matches:
                images.append({
                    'alt': alt,
                    'url': url,
                    'line': i
                })
        return images

    def get_links(self) -> list[dict]:
        """
        提取文档中所有链接（不含图片）

        Returns:
            [{'text': '链接文字', 'url': 'https://...', 'line': 10}, ...]
        """
        import re
        pattern = r'(?<!!)\[([^\]]+)\]\(([^)]+)\)'
        links = []

        for i, line in enumerate(self.lines, 1):
            matches = re.findall(pattern, line)
            for text, url in matches:
                links.append({
                    'text': text,
                    'url': url,
                    'line': i
                })
        return links

    def extract_summary(self, title: str) -> dict:
        """
        提取章节摘要（标题、层级、行号、内容预览、字数）

        Args:
            title: 标题文本

        Returns:
            完整的章节摘要信息
        """
        content = self.get_content_between_headings(title)
        if 'error' in content:
            return content

        text = content['content']
        return {
            'heading': content['heading'],
            'level': content['level'],
            'line': content['line'],
            'char_count': len(text),
            'preview': text[:300] + '...' if len(text) > 300 else text
        }

    # ==================== 大模型 Token 计算 ====================

    def count_tokens(self, text: str, model: str = "cl100k_base") -> int:
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

    def get_token_stats(self, model: str = "cl100k_base") -> dict:
        """
        获取文档的 Token 统计信息

        Args:
            model: 编码模型名称

        Returns:
            {'total_tokens': 总token数, 'char_count': 字符数, 'lines': 行数}
        """
        total_tokens = self.count_tokens(self.content, model)
        return {
            'total_tokens': total_tokens,
            'char_count': len(self.content),
            'lines': len(self.lines),
            'model': model
        }

    def count_section_tokens(self, title: str, model: str = "cl100k_base") -> dict:
        """
        计算指定章节的 Token 数量

        Args:
            title: 标题文本
            model: 编码模型名称

        Returns:
            {'title': 标题, 'tokens': token数, 'char_count': 字符数}
        """
        content = self.get_content_between_headings(title)
        if 'error' in content:
            return {'error': content['error']}

        text = content['content']
        tokens = self.count_tokens(text, model)

        return {
            'title': content['heading'],
            'tokens': tokens,
            'char_count': len(text),
            'line': content['line']
        }

    def get_top_token_sections(self, limit: int = 10, model: str = "cl100k_base") -> list[dict]:
        """
        获取 Token 数最多的章节

        Args:
            limit: 返回数量
            model: 编码模型名称

        Returns:
            按 Token 数降序排列的章节列表
        """
        headings = self.get_headings()
        results = []

        for h in headings:
            data = self.count_section_tokens(h['text'], model)
            if 'error' not in data:
                results.append(data)

        # 按 token 数降序排序
        results.sort(key=lambda x: x['tokens'], reverse=True)
        return results[:limit]

    def estimate_cost(
        self,
        input_price: float = 0.005,    # GPT-4o-mini 输入价格 $/1K tokens
        output_price: float = 0.015,   # GPT-4o-mini 输出价格 $/1K tokens
        model: str = "cl100k_base"
    ) -> dict:
        """
        估算 API 调用成本

        Args:
            input_price: 输入 token 价格（美元/1000 tokens）
            output_price: 输出 token 价格（美元/1000 tokens）
            model: 编码模型名称

        Returns:
            {'input_tokens': 输入token数, 'input_cost': 输入成本, ...}
        """
        stats = self.get_token_stats(model)
        input_tokens = stats['total_tokens']

        # 假设输出约为输入的 20%
        estimated_output = int(input_tokens * 0.2)

        input_cost = (input_tokens / 1000) * input_price
        output_cost = (estimated_output / 1000) * output_price

        return {
            'input_tokens': input_tokens,
            'estimated_output_tokens': estimated_output,
            'input_cost_usd': round(input_cost, 4),
            'output_cost_usd': round(output_cost, 4),
            'total_cost_usd': round(input_cost + output_cost, 4),
            'model': model
        }


if __name__ == '__main__':
    # 测试代码
    parser = MDParser('CLASSIC_TRADING_THEORIES.md')

    print("=" * 60)
    print("1. 标题层级树")
    print("=" * 60)
    headings = parser.get_headings()
    for h in headings[:3]:  # 只显示前3个一级标题
        print(f"H{h['level']}: {h['text']} (line {h['line']})")
        for child in h['children'][:2]:
            print(f"  └─ H{child['level']}: {child['text']}")

    print("\n" + "=" * 60)
    print("2. 表格数据")
    print("=" * 60)
    tables = parser.get_tables()
    for i, table in enumerate(tables[:2]):  # 只显示前2个表格
        print(f"\n表格 {i+1} (line {table['line']}):")
        print(f"  表头: {table['headers']}")
        print(f"  行数: {len(table['rows'])}")
        if table['rows']:
            print(f"  首行: {table['rows'][0]}")

    print("\n" + "=" * 60)
    print("3. 代码块")
    print("=" * 60)
    code_blocks = parser.get_code_blocks()
    for i, block in enumerate(code_blocks):
        print(f"\n代码块 {i+1} (line {block['line']}):")
        print(f"  语言: {block['language'] or '(无)'}")
        print(f"  内容预览: {block['code'][:50]}...")

    print("\n" + "=" * 60)
    print("4. 两个标题间的内容")
    print("=" * 60)
    content = parser.get_content_between_headings("道氏理论", "价值投资")
    print(f"标题: {content['heading']} (H{content['level']}, line {content['line']})")
    print(f"内容预览:\n{content['content'][:200]}...")

    print("\n" + "=" * 60)
    print("5. 文档分区")
    print("=" * 60)
    sections = parser.get_sections()
    for name, section in sections.items():
        print(f"\n{name} (line {section['line']})")
        print(f"  二级标题数: {len(section['subsections'])}")
