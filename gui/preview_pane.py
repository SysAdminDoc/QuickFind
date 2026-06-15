"""
Preview pane for text, images, and media files.
"""

import os
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPlainTextEdit, QScrollArea,
    QStackedWidget, QHBoxLayout
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor, QPalette

from core.index import FileEntry, FileIndex
from gui.theme import MOCHA
from gui.results_view import format_size, format_datetime, format_attributes

logger = logging.getLogger('QuickFind.PreviewPane')

# File types that can be previewed
TEXT_EXTENSIONS = {
    'txt', 'md', 'log', 'ini', 'cfg', 'conf', 'json', 'xml', 'yaml', 'yml',
    'csv', 'tsv', 'html', 'htm', 'css', 'js', 'ts', 'py', 'ps1', 'bat',
    'cmd', 'sh', 'bash', 'c', 'cpp', 'h', 'hpp', 'cs', 'java', 'rs',
    'go', 'rb', 'php', 'sql', 'r', 'lua', 'pl', 'swift', 'kt',
    'toml', 'env', 'gitignore', 'dockerfile', 'makefile',
}
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'ico', 'webp', 'svg'}
AUDIO_EXTENSIONS = {'mp3', 'flac', 'wav', 'aac', 'ogg', 'wma', 'm4a', 'opus'}
VIDEO_EXTENSIONS = {'mp4', 'mkv', 'avi', 'mov', 'wmv', 'webm', 'flv'}

MAX_TEXT_PREVIEW_SIZE = 512 * 1024  # 512KB
MAX_IMAGE_PREVIEW_SIZE = 50 * 1024 * 1024  # 50MB


class TextPreviewLoader(QThread):
    """Background thread for loading text file previews."""
    loaded = pyqtSignal(str, str)  # (path, content)
    error = pyqtSignal(str, str)  # (path, error_message)

    def __init__(self, path: str, max_size: int = MAX_TEXT_PREVIEW_SIZE):
        super().__init__()
        self._path = path
        self._max_size = max_size

    def run(self):
        try:
            size = os.path.getsize(self._path)
            truncated = size > self._max_size

            with open(self._path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(self._max_size)

            if truncated:
                content += f"\n\n--- Truncated ({size:,} bytes total) ---"

            self.loaded.emit(self._path, content)
        except Exception as e:
            self.error.emit(self._path, str(e))


class ImagePreviewLoader(QThread):
    """Background thread for loading image previews."""
    loaded = pyqtSignal(str, QImage)
    error = pyqtSignal(str, str)

    def __init__(self, path: str, max_width: int = 800, max_height: int = 800):
        super().__init__()
        self._path = path
        self._max_width = max_width
        self._max_height = max_height

    def run(self):
        try:
            try:
                if os.path.getsize(self._path) > MAX_IMAGE_PREVIEW_SIZE:
                    self.error.emit(self._path, "Image too large for preview")
                    return
            except OSError:
                pass
            image = QImage(self._path)
            if image.isNull():
                self.error.emit(self._path, "Failed to load image")
                return

            # Scale to fit
            if image.width() > self._max_width or image.height() > self._max_height:
                image = image.scaled(
                    self._max_width, self._max_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )

            self.loaded.emit(self._path, image)
        except Exception as e:
            self.error.emit(self._path, str(e))


class PreviewPane(QWidget):
    """
    Preview pane that shows text, image, or info preview for selected files.
    """

    def __init__(self, file_index: FileIndex, parent=None):
        super().__init__(parent)
        self._file_index = file_index
        self._current_path: Optional[str] = None
        self._loader_thread: Optional[QThread] = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self._header = QLabel("Preview")
        self._header.setStyleSheet(f"""
            QLabel {{
                background-color: {MOCHA['mantle']};
                color: {MOCHA['subtext0']};
                padding: 6px 12px;
                font-weight: 600;
                font-size: 12px;
                border-bottom: 1px solid {MOCHA['surface0']};
            }}
        """)
        layout.addWidget(self._header)

        # Stacked content area
        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # Page 0: No selection / info
        self._info_label = QLabel("Select a file to preview")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_label.setStyleSheet(f"color: {MOCHA['overlay0']}; font-size: 13px;")
        self._info_label.setWordWrap(True)
        self._stack.addWidget(self._info_label)

        # Page 1: Text preview
        self._text_edit = QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont(QFont("Cascadia Code", 10))
        self._text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._stack.addWidget(self._text_edit)

        # Page 2: Image preview
        self._image_scroll = QScrollArea()
        self._image_scroll.setWidgetResizable(False)
        self._image_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setScaledContents(False)
        self._image_scroll.setWidget(self._image_label)
        self._stack.addWidget(self._image_scroll)

        # Page 3: File info panel
        self._file_info = QLabel()
        self._file_info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._file_info.setWordWrap(True)
        self._file_info.setStyleSheet(f"padding: 12px; color: {MOCHA['text']}; font-size: 13px;")
        self._file_info.setTextFormat(Qt.TextFormat.RichText)
        self._stack.addWidget(self._file_info)

        self._stack.setCurrentIndex(0)

    def _cleanup_loader(self):
        """Safely clean up any previous loader thread."""
        if self._loader_thread is not None:
            try:
                if self._loader_thread.isRunning():
                    self._loader_thread.requestInterruption()
                    self._loader_thread.wait(2000)
            except RuntimeError:
                # C++ object already deleted
                pass
            self._loader_thread = None

    def preview_entry(self, entry: Optional[FileEntry]):
        """Preview a file entry."""
        self._cleanup_loader()

        if entry is None:
            self._stack.setCurrentIndex(0)
            self._header.setText("Preview")
            self._current_path = None
            return

        path = entry.get_path(self._file_index)
        self._current_path = path
        self._header.setText(entry.name)

        ext = entry.extension
        logger.debug(f"Preview: {entry.name} ext='{ext}' is_dir={entry.is_dir} path={path}")

        if entry.is_dir:
            self._show_dir_info(entry, path)
        elif ext in IMAGE_EXTENSIONS:
            self._load_image_preview(path)
        elif ext in TEXT_EXTENSIONS:
            self._load_text_preview(path)
        else:
            self._show_file_info(entry, path)

    def _load_text_preview(self, path: str):
        """Load text file preview in background."""
        self._text_edit.clear()
        self._stack.setCurrentIndex(1)

        loader = TextPreviewLoader(path)
        loader.loaded.connect(self._on_text_loaded)
        loader.error.connect(self._on_preview_error)
        loader.finished.connect(self._on_loader_finished)
        self._loader_thread = loader
        loader.start()

    def _on_text_loaded(self, path: str, content: str):
        if path == self._current_path:
            self._text_edit.setPlainText(content)

    def _load_image_preview(self, path: str):
        """Load image preview in background."""
        self._image_label.clear()
        self._image_label.setText("Loading...")
        self._stack.setCurrentIndex(2)

        loader = ImagePreviewLoader(path)
        loader.loaded.connect(self._on_image_loaded)
        loader.error.connect(self._on_preview_error)
        loader.finished.connect(self._on_loader_finished)
        self._loader_thread = loader
        loader.start()

    def _on_loader_finished(self):
        """Called when a loader thread finishes — safe to release reference."""
        # Don't deleteLater here; just let _cleanup_loader handle it next time
        pass

    def _on_image_loaded(self, path: str, image: QImage):
        logger.debug(f"Image loaded: {path} ({image.width()}x{image.height()}, null={image.isNull()})")
        if path == self._current_path:
            pixmap = QPixmap.fromImage(image)
            # Scale to fit the scroll area width while preserving aspect ratio
            available_width = self._image_scroll.viewport().width() - 20
            if available_width > 0 and pixmap.width() > available_width:
                pixmap = pixmap.scaledToWidth(
                    available_width, Qt.TransformationMode.SmoothTransformation
                )
            self._image_label.setPixmap(pixmap)
            self._image_label.adjustSize()
            logger.debug(f"Preview pixmap set: {pixmap.width()}x{pixmap.height()}")

    def _on_preview_error(self, path: str, error: str):
        logger.warning(f"Preview error for {path}: {error}")
        if path == self._current_path:
            self._info_label.setText(f"Cannot preview:\n{error}")
            self._stack.setCurrentIndex(0)

    def _show_file_info(self, entry: FileEntry, path: str):
        """Show file info panel."""
        try:
            stat = os.stat(path) if os.path.exists(path) else None
        except OSError:
            stat = None

        info_html = f"""
        <div style="font-family: Segoe UI; line-height: 1.8;">
            <p><b style="color: {MOCHA['blue']};">Name:</b> {entry.name}</p>
            <p><b style="color: {MOCHA['blue']};">Type:</b> {entry.extension.upper() + ' File' if entry.extension else 'File'}</p>
            <p><b style="color: {MOCHA['blue']};">Path:</b> {path}</p>
        """

        if stat:
            info_html += f"""
            <p><b style="color: {MOCHA['blue']};">Size:</b> {format_size(stat.st_size)} ({stat.st_size:,} bytes)</p>
            <p><b style="color: {MOCHA['blue']};">Modified:</b> {format_datetime(entry.date_modified)}</p>
            <p><b style="color: {MOCHA['blue']};">Created:</b> {format_datetime(entry.date_created)}</p>
            """

        info_html += f"""
            <p><b style="color: {MOCHA['blue']};">Attributes:</b> {format_attributes(entry.attributes)}</p>
        </div>
        """

        self._file_info.setText(info_html)
        self._stack.setCurrentIndex(3)

    def _show_dir_info(self, entry: FileEntry, path: str):
        """Show directory info."""
        info_html = f"""
        <div style="font-family: Segoe UI; line-height: 1.8;">
            <p><b style="color: {MOCHA['blue']};">Folder:</b> {entry.name}</p>
            <p><b style="color: {MOCHA['blue']};">Path:</b> {path}</p>
            <p><b style="color: {MOCHA['blue']};">Modified:</b> {format_datetime(entry.date_modified)}</p>
            <p><b style="color: {MOCHA['blue']};">Attributes:</b> {format_attributes(entry.attributes)}</p>
        </div>
        """
        self._file_info.setText(info_html)
        self._stack.setCurrentIndex(3)

    def clear(self):
        """Clear the preview."""
        self._current_path = None
        self._text_edit.clear()
        self._image_label.clear()
        self._info_label.setText("Select a file to preview")
        self._stack.setCurrentIndex(0)
        self._header.setText("Preview")
