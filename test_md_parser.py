"""
MDParser 测试脚本
"""

import os
from md_parser import MDParser

# 目录配置
OUTPUT_DIR = 'output'
# 测试文件（使用第一个找到的 MD 文件）
import glob
md_files = glob.glob(f'{OUTPUT_DIR}/MinerU_markdown_*.md')
MAIN_TEST_FILE = md_files[0] if md_files else f'{OUTPUT_DIR}/report.md'
# 备用测试文件（有表格和代码块）
BACKUP_TEST_FILE = f'{OUTPUT_DIR}/CLASSIC_TRADING_THEORIES.md'


def test_main_file():
    """测试主力文件"""

    print("=" * 60)
    print(f"主力测试: {MAIN_TEST_FILE}")
    print("=" * 60)

    parser = MDParser(MAIN_TEST_FILE)

    # 1. 文件统计
    print("\n【1. 文件统计】")
    headings = parser.get_headings()
    tables = parser.get_tables()
    code_blocks = parser.get_code_blocks()
    images = parser.get_images()
    links = parser.get_links()

    print(f"   标题数: {len(headings)}")
    print(f"   表格数: {len(tables)}")
    print(f"   代码块: {len(code_blocks)}")
    print(f"   图片数: {len(images)}")
    print(f"   链接数: {len(links)}")
    print(f"   文件行数: {len(parser.lines)}")
    print(f"   Token数: {len(parser.tokens)}")

    # 2. 标题功能
    print("\n【2. 标题功能】")
    print("   print_headings(limit=10):")
    parser.print_headings(limit=10)

    # 3. 搜索标题
    print("\n【3. 搜索标题】")
    keywords = ['財務', '收入', '利潤', '香港']
    for kw in keywords:
        results = parser.search_headings(kw)
        print(f"   search_headings('{kw}'): {len(results)} 个匹配")
        if results:
            print(f"      示例: {results[0]['text'][:30]}...")

    # 4. 章节内容提取
    print("\n【4. 章节内容提取】")
    test_titles = [
        '總收入',
        '經常性業務利潤',
        '公司股東應佔淨利潤',
        '物業發展利潤',
        '投資物業公允價值計量',
    ]
    for title in test_titles:
        content = parser.get_content_between_headings(title)
        if 'error' not in content:
            preview = content['content'][:60].replace('\n', ' ')
            print(f"   【{title}】")
            print(f"      行号: {content['line']}, 字数: {len(content['content'])}")
            print(f"      预览: {preview}...")
        else:
            print(f"   【{title}】: {content['error']}")

    # 5. 批量提取章节
    print("\n【5. 批量提取章节】")
    sections = parser.get_sections_by_titles(test_titles)
    success = sum(1 for v in sections.values() if 'error' not in v)
    print(f"   get_sections_by_titles(): {success}/{len(test_titles)} 成功")

    # 6. 章节摘要
    print("\n【6. 章节摘要】")
    summary = parser.extract_summary('總收入')
    if 'error' not in summary:
        print(f"   标题: {summary['heading']}")
        print(f"   层级: H{summary['level']}, 行号: {summary['line']}")
        print(f"   字数: {summary['char_count']}")

    # 7. 图片提取
    print("\n【7. 图片提取】")
    print(f"   共 {len(images)} 个图片")
    if images:
        for i, img in enumerate(images[:3]):
            print(f"   图片 {i+1}: line {img['line']}")
            print(f"      URL: {img['url'][:50]}...")

    # 8. 文档分区
    print("\n【8. 文档分区】")
    doc_sections = parser.get_sections()
    print(f"   共 {len(doc_sections)} 个一级分区")
    section_names = list(doc_sections.keys())[:5]
    for name in section_names:
        print(f"   - {name[:30]}...")

    # 9. 边界测试
    print("\n【9. 边界测试】")
    result = parser.get_content_between_headings('不存在的标题xyz123')
    print(f"   不存在的标题: {result.get('error', '成功')}")

    results = parser.search_headings('xyz不存在abc')
    print(f"   搜索不存在的关键词: {len(results)} 个结果")

    # 10. 大模型 Token 统计
    print("\n【10. 大模型 Token 统计】")
    token_stats = parser.get_token_stats()
    print(f"   字符数: {token_stats['char_count']:,}")
    print(f"   行数: {token_stats['lines']}")
    print(f"   Token数: {token_stats['total_tokens']:,}")

    # 11. 章节 Token 统计
    print("\n【11. 章节 Token 统计】")
    section_tokens = parser.count_section_tokens('總收入')
    if 'error' not in section_tokens:
        print(f"   總收入: {section_tokens['tokens']} tokens")

    # 12. Token 最多的章节
    print("\n【12. Token 最多的 TOP 5 章节】")
    top_sections = parser.get_top_token_sections(limit=5)
    for i, s in enumerate(top_sections, 1):
        print(f"   {i}. {s['title'][:25]}... : {s['tokens']} tokens")

    # 13. 成本估算
    print("\n【13. API 成本估算】")
    cost = parser.estimate_cost()
    print(f"   输入成本: ${cost['input_cost_usd']}")
    print(f"   输出成本: ${cost['output_cost_usd']}")
    print(f"   总成本: ${cost['total_cost_usd']}")


def test_backup_file():
    """测试备用文件（有表格和代码块）"""

    if not os.path.exists(BACKUP_TEST_FILE):
        print(f"\n跳过: {BACKUP_TEST_FILE} 不存在")
        return

    print("\n" + "=" * 60)
    print(f"备用测试: {BACKUP_TEST_FILE}")
    print("=" * 60)

    parser = MDParser(BACKUP_TEST_FILE)

    # 统计
    print("\n【文件统计】")
    print(f"   标题: {len(parser.get_headings())}")
    print(f"   表格: {len(parser.get_tables())}")
    print(f"   代码块: {len(parser.get_code_blocks())}")
    print(f"   图片: {len(parser.get_images())}")

    # 表格测试
    tables = parser.get_tables()
    if tables:
        print("\n【表格示例】")
        for i, t in enumerate(tables[:2]):
            print(f"   表格 {i+1}: {t['headers']}")
            if t['rows']:
                print(f"      首行: {t['rows'][0]}")

    # 代码块测试
    code_blocks = parser.get_code_blocks()
    if code_blocks:
        print("\n【代码块示例】")
        for i, b in enumerate(code_blocks[:2]):
            print(f"   代码块 {i+1}: 语言={b['language'] or '(无)'}")
            print(f"      预览: {b['code'][:40]}...")


if __name__ == '__main__':
    if not os.path.exists(MAIN_TEST_FILE):
        print(f"错误: 主力测试文件 {MAIN_TEST_FILE} 不存在")
        exit(1)

    test_main_file()
    test_backup_file()

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
