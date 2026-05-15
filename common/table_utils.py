"""
表格处理公共组件
- HTML 表格解析（支持 rowspan/colspan 合并单元格）
- HTML 表格转 CSV
"""

import re
from typing import Optional


def parse_html_cells(row_content: str) -> list[tuple]:
    """
    解析 HTML 行中的单元格

    Args:
        row_content: <tr>...</tr> 内的内容

    Returns:
        [(内容, colspan, rowspan), ...]
    """
    cells = []
    # 匹配 td 或 th 及其属性
    cell_pattern = r'<(t[dh])([^>]*)>(.*?)</\1>'
    matches = re.findall(cell_pattern, row_content, re.DOTALL | re.IGNORECASE)

    for tag, attrs, content in matches:
        # 提取 colspan
        colspan_match = re.search(r'colspan\s*=\s*["\']?(\d+)', attrs, re.IGNORECASE)
        colspan = int(colspan_match.group(1)) if colspan_match else 1

        # 提取 rowspan
        rowspan_match = re.search(r'rowspan\s*=\s*["\']?(\d+)', attrs, re.IGNORECASE)
        rowspan = int(rowspan_match.group(1)) if rowspan_match else 1

        # 清理 HTML 标签
        clean_text = re.sub(r'<[^>]+>', '', content)
        clean_text = clean_text.strip().replace('\n', ' ')

        cells.append((clean_text, colspan, rowspan))

    return cells


def expand_html_table_to_matrix(table_html: str) -> list[list[str]]:
    """
    将 HTML 表格展开为二维矩阵（处理 rowspan/colspan 合并单元格）

    Args:
        table_html: <table>...</table> 完整 HTML

    Returns:
        二维矩阵，每个单元格都有对应位置
        例如: [['A', 'B'], ['A', 'C']] 表示 A 单元格跨两行
    """
    # 提取所有行
    row_pattern = r'<tr[^>]*>(.*?)</tr>'
    row_matches = re.findall(row_pattern, table_html, re.DOTALL | re.IGNORECASE)

    matrix = []
    rowspan_tracker = {}  # {col_index: (content, remaining_rows)}

    for row_content in row_matches:
        cells_data = parse_html_cells(row_content)

        if not cells_data:
            continue

        current_row = []
        col_index = 0
        cell_idx = 0

        while col_index < len(cells_data) + len(rowspan_tracker):
            # 优先处理 rowspan 占位
            if col_index in rowspan_tracker:
                content, remaining = rowspan_tracker[col_index]
                current_row.append(content)
                if remaining > 1:
                    rowspan_tracker[col_index] = (content, remaining - 1)
                else:
                    del rowspan_tracker[col_index]
                col_index += 1
            elif cell_idx < len(cells_data):
                cell_content, colspan, rowspan = cells_data[cell_idx]

                # colspan: 重复内容填入多列
                for _ in range(colspan):
                    current_row.append(cell_content)

                # rowspan: 记录跨行占位
                if rowspan > 1:
                    for offset in range(colspan):
                        rowspan_tracker[col_index + offset] = (cell_content, rowspan - 1)

                col_index += colspan
                cell_idx += 1
            else:
                break

        if current_row:
            matrix.append(current_row)

    # 规范化：确保所有行长度一致
    if matrix:
        max_cols = max(len(row) for row in matrix)
        for row in matrix:
            while len(row) < max_cols:
                row.append('')

    return matrix


def html_table_to_csv(table_html: str) -> str:
    """
    将 HTML 表格转换为 CSV 格式（支持合并单元格）

    Args:
        table_html: <table>...</table> 完整 HTML

    Returns:
        CSV 格式字符串，每行一行，逗号分隔
    """
    matrix = expand_html_table_to_matrix(table_html)

    if not matrix:
        return ''

    rows = []
    for row in matrix:
        # 转义 CSV 特殊字符
        clean_cells = []
        for cell in row:
            if ',' in cell or '"' in cell or '\n' in cell:
                cell = '"' + cell.replace('"', '""') + '"'
            clean_cells.append(cell)
        rows.append(','.join(clean_cells))

    return '\n'.join(rows)


def convert_html_tables_to_csv(content: str) -> str:
    """
    将内容中的所有 HTML 表格转换为 CSV 格式

    Args:
        content: 包含 HTML 表格的内容

    Returns:
        转换后的内容
    """
    table_pattern = r'<table[^>]*>(.*?)</table>'

    def replace_table(match):
        table_html = match.group(0)
        csv = html_table_to_csv(table_html)
        if csv:
            return '\n' + csv + '\n'
        return ''

    result = re.sub(table_pattern, replace_table, content, flags=re.DOTALL | re.IGNORECASE)
    return result


def parse_html_table(table_html: str, line_num: int = 0) -> dict:
    """
    解析 HTML 表格为结构化数据

    Args:
        table_html: <table>...</table> 完整 HTML
        line_num: 表格所在行号

    Returns:
        {
            'headers': ['列1', '列2', ...],
            'rows': [['A', 'B'], ...],
            'line': 行号,
            'type': 'html',
            'has_merged_cells': bool
        }
    """
    matrix = expand_html_table_to_matrix(table_html)

    if not matrix:
        return {
            'headers': [],
            'rows': [],
            'line': line_num,
            'type': 'html',
            'has_merged_cells': False
        }

    # 检测是否有合并单元格（通过比较原始单元格数和矩阵单元格数）
    row_pattern = r'<tr[^>]*>(.*?)</tr>'
    row_matches = re.findall(row_pattern, table_html, re.DOTALL | re.IGNORECASE)
    original_cell_count = sum(len(parse_html_cells(row)) for row in row_matches)
    matrix_cell_count = sum(len(row) for row in matrix)
    has_merged_cells = matrix_cell_count > original_cell_count

    return {
        'headers': matrix[0] if matrix else [],
        'rows': matrix[1:] if len(matrix) > 1 else [],
        'line': line_num,
        'type': 'html',
        'has_merged_cells': has_merged_cells
    }


def find_table_ranges(content: str) -> list[tuple[int, int]]:
    """
    找出内容中所有表格的位置范围

    支持：
    - CSV 格式表格（多行逗号分隔）
    - HTML 表格
    - Markdown 表格

    Args:
        content: 文档内容

    Returns:
        [(start_pos, end_pos), ...] 表格在内容中的字符位置
    """
    ranges = []

    # 1. 匹配 CSV 格式表格
    lines = content.split('\n')
    csv_start = None
    csv_comma_count = 0

    for i, line in enumerate(lines):
        comma_count = line.count(',')

        # CSV 行条件：至少 2 个逗号，不是 URL，长度足够或有多个逗号
        # 放宽长度限制：财务报表中有些行很短但确实是表格的一部分
        is_csv_line = (
            comma_count >= 2 and
            not line.strip().startswith('http') and
            (len(line.strip()) > 5 or comma_count >= 3)  # 短行但有多于3个逗号也认为是表格
        )

        if is_csv_line:
            if csv_start is None:
                csv_start = i
                csv_comma_count = comma_count
            # 放宽容忍度：逗号数量差异超过 5 才认为表格结束
            # 财务报表表格常有空单元格，导致逗号数量变化
            elif abs(comma_count - csv_comma_count) > 5:
                # CSV 块结束
                end_pos = content.find('\n', sum(len(l) + 1 for l in lines[:i]))
                start_pos = sum(len(l) + 1 for l in lines[:csv_start])
                if end_pos - start_pos > 50:
                    ranges.append((start_pos, end_pos))
                csv_start = i
                csv_comma_count = comma_count
        else:
            if csv_start is not None:
                end_pos = content.find('\n', sum(len(l) + 1 for l in lines[:i]))
                start_pos = sum(len(l) + 1 for l in lines[:csv_start])
                if end_pos - start_pos > 50:
                    ranges.append((start_pos, end_pos))
                csv_start = None

    # 处理末尾的 CSV 块
    if csv_start is not None:
        start_pos = sum(len(l) + 1 for l in lines[:csv_start])
        ranges.append((start_pos, len(content)))

    # 2. 匹配 HTML 表格
    pattern = r'<table[^>]*>.*?</table>'
    for match in re.finditer(pattern, content, re.DOTALL | re.IGNORECASE):
        ranges.append((match.start(), match.end()))

    # 3. 匹配 Markdown 表格
    md_table_pattern = r'(\|[^\n]+\|\n)+(\|[-:| ]+\|\n)(\|[^\n]+\|\n?)+'
    for match in re.finditer(md_table_pattern, content):
        ranges.append((match.start(), match.end()))

    # 合并重叠的范围并排序
    if not ranges:
        return []

    ranges = sorted(ranges, key=lambda x: x[0])
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    return merged