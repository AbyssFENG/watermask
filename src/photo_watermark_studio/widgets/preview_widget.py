# -*- coding: utf-8 -*-
"""中间预览区（2.0 画布）。导出不会使用预览图。"""
from __future__ import annotations

from photo_watermark_studio.ui.canvas_view import PLACEHOLDER_TEXT, CanvasPanel

# 兼容旧导入名
PreviewPanel = CanvasPanel

__all__ = ["PLACEHOLDER_TEXT", "PreviewPanel", "CanvasPanel"]
