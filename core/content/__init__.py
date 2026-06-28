"""Content extraction adapters for content: searches."""

from .adapters import (
    ExtractedContent,
    SUPPORTED_CONTENT_EXTENSIONS,
    extract_text,
    is_supported_content_path,
    matched_line_context,
)

__all__ = [
    'ExtractedContent',
    'SUPPORTED_CONTENT_EXTENSIONS',
    'extract_text',
    'is_supported_content_path',
    'matched_line_context',
]
