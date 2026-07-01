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
from .sandbox import (
    DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
    ExtractionOutcome,
    extract_text_sandboxed,
    extract_text_with_diagnostics,
)

__all__ = [
    'AdapterDiagnostic',
    'DEFAULT_EXTRACTION_TIMEOUT_SECONDS',
    'ExtractedContent',
    'ExtractionOutcome',
    'SUPPORTED_CONTENT_EXTENSIONS',
    'adapter_diagnostics',
    'adapter_for_path',
    'extract_text',
    'extract_text_sandboxed',
    'extract_text_with_diagnostics',
    'is_supported_content_path',
    'matched_line_context',
]
