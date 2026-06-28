"""Content extraction adapters for content: searches."""

from .adapters import (
    AdapterDiagnostic,
    ExtractedContent,
    SUPPORTED_CONTENT_EXTENSIONS,
    adapter_diagnostics,
    adapter_for_path,
    extract_text,
    is_supported_content_path,
    matched_line_context,
)

__all__ = [
    'AdapterDiagnostic',
    'ExtractedContent',
    'SUPPORTED_CONTENT_EXTENSIONS',
    'adapter_diagnostics',
    'adapter_for_path',
    'extract_text',
    'is_supported_content_path',
    'matched_line_context',
]
