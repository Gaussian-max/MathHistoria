"""PDF裁剪与拼接工具"""
import re
from pypdf import PdfReader, PdfWriter


def parse_page_range(range_str: str, total_pages: int) -> list[int]:
    """
    解析页数范围字符串，返回页码列表（0-based索引）

    支持格式：
    - "1-5": 第1到5页
    - "1,3,5": 第1、3、5页
    - "1-5,8-10": 混合格式
    - "all" 或 "": 全部页
    """
    range_str = range_str.strip()

    if not range_str or range_str.lower() == "all":
        return list(range(total_pages))

    pages = set()
    parts = range_str.split(",")

    for part in parts:
        part = part.strip()
        if "-" in part:
            # 范围格式: 1-5
            match = re.match(r"(\d+)-(\d+)", part)
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                # 转换为0-based索引，并限制在有效范围内
                for i in range(max(1, start), min(total_pages + 1, end + 1)):
                    pages.add(i - 1)
        else:
            # 单个页码: 3
            if part.isdigit():
                page_num = int(part)
                if 1 <= page_num <= total_pages:
                    pages.add(page_num - 1)

    return sorted(list(pages))


def merge_pdfs(pdf_files_and_ranges: list[tuple[str, str]], output_path: str) -> tuple[bool, str]:
    """
    拼接多个PDF文件

    Args:
        pdf_files_and_ranges: [(pdf_path, page_range_str), ...]
        output_path: 输出文件路径

    Returns:
        (success, message)
    """
    try:
        writer = PdfWriter()
        total_pages_added = 0

        for pdf_path, range_str in pdf_files_and_ranges:
            try:
                reader = PdfReader(pdf_path)
                total_pages = len(reader.pages)

                pages_to_add = parse_page_range(range_str, total_pages)

                if not pages_to_add:
                    continue

                for page_idx in pages_to_add:
                    writer.add_page(reader.pages[page_idx])
                    total_pages_added += 1

            except Exception as e:
                return False, f"处理 {pdf_path} 时出错: {str(e)}"

        if total_pages_added == 0:
            return False, "没有选择任何页面"

        with open(output_path, "wb") as f:
            writer.write(f)

        return True, f"成功拼接 {total_pages_added} 页"

    except Exception as e:
        return False, f"拼接失败: {str(e)}"


def get_pdf_page_count(pdf_path: str) -> int:
    """获取PDF总页数"""
    try:
        reader = PdfReader(pdf_path)
        return len(reader.pages)
    except:
        return 0
