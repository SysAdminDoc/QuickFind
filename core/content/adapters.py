"""Pluggable text extraction adapters for content search."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


logger = logging.getLogger('QuickFind.Content')

MAX_EXTRACT_CHARS = 1_000_000
MAX_TEXT_BYTES = 10 * 1024 * 1024

TEXT_EXTENSIONS = {
    'txt', 'md', 'log', 'ini', 'cfg', 'conf', 'json', 'xml', 'yaml', 'yml',
    'csv', 'tsv', 'html', 'htm', 'css', 'js', 'ts', 'py', 'ps1', 'bat',
    'cmd', 'sh', 'bash', 'c', 'cpp', 'h', 'hpp', 'cs', 'java', 'rs',
    'go', 'rb', 'php', 'sql', 'r', 'lua', 'pl', 'swift', 'kt',
    'toml', 'env', 'gitignore', 'dockerfile', 'makefile',
}


@dataclass(frozen=True)
class ExtractedContent:
    text: str
    extractor: str


class ContentAdapter(Protocol):
    name: str
    extensions: set[str]

    def extract(self, path: str, max_chars: int = MAX_EXTRACT_CHARS) -> str:
        ...


class PlainTextAdapter:
    name = 'text'
    extensions = TEXT_EXTENSIONS

    def extract(self, path: str, max_chars: int = MAX_EXTRACT_CHARS) -> str:
        if os.path.getsize(path) > MAX_TEXT_BYTES:
            max_chars = min(max_chars, MAX_TEXT_BYTES)
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read(max_chars)


class PdfAdapter:
    name = 'pdfplumber'
    extensions = {'pdf'}

    def extract(self, path: str, max_chars: int = MAX_EXTRACT_CHARS) -> str:
        import pdfplumber

        chunks = []
        total = 0
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ''
                if not text:
                    continue
                remaining = max_chars - total
                if remaining <= 0:
                    break
                chunks.append(text[:remaining])
                total += len(chunks[-1])
        return '\n'.join(chunks)


class DocxAdapter:
    name = 'python-docx'
    extensions = {'docx'}

    def extract(self, path: str, max_chars: int = MAX_EXTRACT_CHARS) -> str:
        from docx import Document

        doc = Document(path)
        chunks = []
        total = 0
        for paragraph in doc.paragraphs:
            text = paragraph.text
            if not text:
                continue
            remaining = max_chars - total
            if remaining <= 0:
                break
            chunks.append(text[:remaining])
            total += len(chunks[-1])
        return '\n'.join(chunks)


class PptxAdapter:
    name = 'python-pptx'
    extensions = {'pptx'}

    def extract(self, path: str, max_chars: int = MAX_EXTRACT_CHARS) -> str:
        from pptx import Presentation

        deck = Presentation(path)
        chunks = []
        total = 0
        for slide in deck.slides:
            for shape in slide.shapes:
                text = getattr(shape, 'text', '')
                if not text:
                    continue
                remaining = max_chars - total
                if remaining <= 0:
                    return '\n'.join(chunks)
                chunks.append(text[:remaining])
                total += len(chunks[-1])
        return '\n'.join(chunks)


ADAPTERS: tuple[ContentAdapter, ...] = (
    PlainTextAdapter(),
    PdfAdapter(),
    DocxAdapter(),
    PptxAdapter(),
)

_ADAPTER_BY_EXTENSION = {
    ext: adapter
    for adapter in ADAPTERS
    for ext in adapter.extensions
}

SUPPORTED_CONTENT_EXTENSIONS = set(_ADAPTER_BY_EXTENSION)


def is_supported_content_path(path: str) -> bool:
    return _extension(path) in SUPPORTED_CONTENT_EXTENSIONS


def extract_text(path: str, max_chars: int = MAX_EXTRACT_CHARS) -> ExtractedContent | None:
    adapter = _ADAPTER_BY_EXTENSION.get(_extension(path))
    if adapter is None:
        return None
    try:
        text = adapter.extract(path, max_chars=max_chars)
    except (OSError, PermissionError, UnicodeError, ImportError) as exc:
        logger.debug(f"Content extraction failed for {path}: {exc}")
        return None
    except Exception as exc:
        logger.debug(f"Content extraction failed for {path}: {exc}")
        return None
    return ExtractedContent(text=text, extractor=adapter.name)


def matched_line_context(content: str, search_text: str,
                         case_sensitive: bool = False,
                         context_lines: int = 3,
                         max_matches: int = 5) -> str:
    if not content or not search_text:
        return content

    needle = search_text if case_sensitive else search_text.lower()
    lines = content.splitlines()

    matches = []
    for idx, line in enumerate(lines):
        segment = line if case_sensitive else line.lower()
        if needle in segment:
            matches.append(idx)
            if len(matches) >= max_matches:
                break

    if not matches:
        return content

    ranges = []
    for idx in matches:
        start = max(0, idx - context_lines)
        end = min(len(lines), idx + context_lines + 1)
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))

    output = []
    for range_index, (start, end) in enumerate(ranges):
        if range_index:
            output.append("...")
        for line_number in range(start, end):
            prefix = ">" if line_number in matches else " "
            output.append(f"{prefix} {line_number + 1}: {lines[line_number]}")
    return '\n'.join(output)


def _extension(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip('.')
    if suffix:
        return suffix
    return Path(path).name.lower()
