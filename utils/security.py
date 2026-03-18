"""安全工具函数"""
import os
from pathlib import Path


def is_safe_path(base_dir: str, user_path: str) -> bool:
    """验证路径是否在允许的目录范围内"""
    try:
        base = Path(base_dir).resolve()
        target = Path(user_path).resolve()
        return target.is_relative_to(base)
    except (ValueError, OSError):
        return False


def validate_pdf_path(pdf_path: str, allowed_dirs: list[str] = None) -> tuple[bool, str]:
    """验证 PDF 文件路径的安全性"""
    if not pdf_path or not pdf_path.strip():
        return False, "路径不能为空"

    pdf_path = pdf_path.strip()

    if not os.path.isfile(pdf_path):
        return False, f"文件不存在: {pdf_path}"

    if not pdf_path.lower().endswith('.pdf'):
        return False, "只允许 PDF 文件"

    try:
        file_size = os.path.getsize(pdf_path)
        if file_size > 100 * 1024 * 1024:
            return False, "文件过大（最大 100MB）"
    except OSError:
        return False, "无法读取文件大小"

    if allowed_dirs:
        path_safe = False
        for allowed_dir in allowed_dirs:
            if is_safe_path(allowed_dir, pdf_path):
                path_safe = True
                break
        if not path_safe:
            return False, "文件路径不在允许的目录范围内"

    return True, ""


def safe_filename(name: str, max_length: int = 200) -> str:
    """清理文件名，移除危险字符"""
    import re
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip('. ')
    if len(name) > max_length:
        name = name[:max_length]
    if not name:
        name = "untitled"
    return name
