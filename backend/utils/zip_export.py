"""
带媒体的 ZIP 导出工具
生成包含 CSV 和媒体文件的 ZIP 包
"""

import csv
import io
from pathlib import Path


def generate_csv_with_media_paths(cards: list[dict]) -> str:
    """生成带相对媒体路径的 CSV 内容"""
    output = io.StringIO()
    # 写入 BOM 以确保 Excel 兼容性
    output.write('﻿')

    writer = csv.writer(output)
    writer.writerow(['sentence', 'translation', 'notes', 'word', 'definition', 'audio', 'screenshot'])

    for card in cards:
        audio_path = card.get('audio_path', '') or ''
        screenshot_path = card.get('screenshot_path', '') or ''

        # 将 HTTP URL 转换为相对路径：
        # "/output/{task_id}/audio/card_0001.mp3" -> "audio/card_0001.mp3"
        audio_rel = _to_relative_path(audio_path, 'audio')
        screenshot_rel = _to_relative_path(screenshot_path, 'screenshots')

        writer.writerow([
            card.get('sentence', ''),
            card.get('translation', ''),
            card.get('notes', ''),
            card.get('word', ''),
            card.get('definition', ''),
            audio_rel,
            screenshot_rel,
        ])

    return output.getvalue()


def _to_relative_path(url: str, folder: str) -> str:
    """将 /output/{task_id}/{folder}/file.ext 转换为 {folder}/file.ext"""
    if not url:
        return ''
    # URL 格式: /output/{task_id}/audio/card_0001.mp3
    parts = url.strip('/').split('/')
    # 查找 folder 部分并从那里开始
    try:
        idx = parts.index(folder)
        return '/'.join(parts[idx:])
    except ValueError:
        # 回退：只返回文件名
        return f"{folder}/{parts[-1]}" if parts else ''
