"""
Preview pane for text, images, and media files.
"""

import os
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPlainTextEdit, QScrollArea,
    QStackedWidget, QHBoxLayout, QTextEdit, QDialog, QApplication
)
from PyQt6.QtCore import Qt, QSize, QRect, QThread, pyqtSignal
from PyQt6.QtGui import (
    QPixmap, QImage, QFont, QColor, QPalette, QTextCharFormat,
    QTextFormat,
)

from core.index import FileEntry, FileIndex
from core.content import matched_line_context
from gui.accessibility import describe_widget
from gui.theme import MOCHA
from gui.results_view import format_size, format_datetime, format_attributes, format_reparse_tag

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
QUICK_PREVIEW_MIN_SIZE = QSize(520, 360)
QUICK_PREVIEW_MAX_SCREEN_RATIO = 0.82


def _matched_context_line_numbers(content: str) -> list[int]:
    return [
        index for index, line in enumerate(content.splitlines())
        if line.startswith("> ")
    ]


def quick_preview_geometry(anchor_rect: QRect, available_rect: QRect,
                           preferred_size: QSize) -> QRect:
    """Return an on-screen geometry for a floating quick preview."""
    max_width = max(QUICK_PREVIEW_MIN_SIZE.width(),
                    int(available_rect.width() * QUICK_PREVIEW_MAX_SCREEN_RATIO))
    max_height = max(QUICK_PREVIEW_MIN_SIZE.height(),
                     int(available_rect.height() * QUICK_PREVIEW_MAX_SCREEN_RATIO))
    width = min(max(preferred_size.width(), QUICK_PREVIEW_MIN_SIZE.width()), max_width)
    height = min(max(preferred_size.height(), QUICK_PREVIEW_MIN_SIZE.height()), max_height)

    center = anchor_rect.center() if anchor_rect.isValid() else available_rect.center()
    x = center.x() - width // 2
    y = center.y() - height // 2
    margin = 12

    above = anchor_rect.top() - height - margin
    below = anchor_rect.bottom() + margin
    if anchor_rect.isValid() and above >= available_rect.top():
        y = above
    elif anchor_rect.isValid() and below + height <= available_rect.bottom():
        y = below

    x = max(available_rect.left(), min(x, available_rect.right() - width + 1))
    y = max(available_rect.top(), min(y, available_rect.bottom() - height + 1))
    return QRect(x, y, width, height)


class TextPreviewLoader(QThread):
    """Background thread for loading text file previews."""
    loaded = pyqtSignal(str, str)  # (path, content)
    error = pyqtSignal(str, str)  # (path, error_message)

    def __init__(self, path: str, max_size: int = MAX_TEXT_PREVIEW_SIZE,
                 highlight_text: str = "", case_sensitive: bool = False):
        super().__init__()
        self._path = path
        self._max_size = max_size
        self._highlight_text = highlight_text
        self._case_sensitive = case_sensitive

    def run(self):
        try:
            size = os.path.getsize(self._path)
            truncated = size > self._max_size

            with open(self._path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(self._max_size)

            if truncated:
                content += f"\n\n--- Truncated ({size:,} bytes total) ---"

            if self._highlight_text:
                content = matched_line_context(
                    content,
                    self._highlight_text,
                    case_sensitive=self._case_sensitive,
                )

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
        describe_widget(
            self,
            "Preview pane",
            "Shows a text, image, or metadata preview for the selected file.",
        )
        self._file_index = file_index
        self._current_path: Optional[str] = None
        self._loader_thread: Optional[QThread] = None
        self._highlight_preview_lines = False

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self._header = QLabel("Preview")
        describe_widget(self._header, "Preview header")
        self._header.setStyleSheet(f"""
            QLabel {{
                background-color: {MOCHA['mantle']};
                color: {MOCHA['subtext1']};
                padding: 7px 14px;
                font-weight: 600;
                font-size: 11px;
                border-bottom: 1px solid {MOCHA['surface0']};
                letter-spacing: 0.3px;
            }}
        """)
        layout.addWidget(self._header)

        # Stacked content area
        self._stack = QStackedWidget()
        describe_widget(self._stack, "Preview content")
        layout.addWidget(self._stack)

        # Page 0: No selection / info
        self._info_label = QLabel("Select a file to preview")
        describe_widget(self._info_label, "Preview empty state")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_label.setStyleSheet(f"color: {MOCHA['overlay0']}; font-size: 12px; padding: 24px;")
        self._info_label.setWordWrap(True)
        self._stack.addWidget(self._info_label)

        # Page 1: Text preview
        self._text_edit = QPlainTextEdit()
        describe_widget(
            self._text_edit,
            "Text preview",
            "Read-only text preview for the selected file.",
        )
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont(QFont("Cascadia Code", 10))
        self._text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._text_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {MOCHA['base']};
                color: {MOCHA['text']};
                border: 0;
                selection-background-color: {MOCHA['surface2']};
            }}
        """)
        self._stack.addWidget(self._text_edit)

        # Page 2: Image preview
        self._image_scroll = QScrollArea()
        describe_widget(self._image_scroll, "Image preview scroll area")
        self._image_scroll.setWidgetResizable(False)
        self._image_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label = QLabel()
        describe_widget(self._image_label, "Image preview")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setScaledContents(False)
        self._image_scroll.setWidget(self._image_label)
        self._stack.addWidget(self._image_scroll)

        # Page 3: File info panel
        self._file_info = QLabel()
        describe_widget(self._file_info, "File metadata preview")
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

    def preview_entry(self, entry: Optional[FileEntry],
                      content_query: str = "",
                      case_sensitive: bool = False):
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
            self._load_text_preview(path, content_query, case_sensitive)
        else:
            self._show_file_info(entry, path)

    def _load_text_preview(self, path: str,
                           content_query: str = "",
                           case_sensitive: bool = False):
        """Load text file preview in background."""
        self._text_edit.clear()
        self._text_edit.setExtraSelections([])
        self._stack.setCurrentIndex(1)
        self._highlight_preview_lines = bool(content_query)

        loader = TextPreviewLoader(
            path,
            highlight_text=content_query,
            case_sensitive=case_sensitive,
        )
        loader.loaded.connect(self._on_text_loaded)
        loader.error.connect(self._on_preview_error)
        loader.finished.connect(self._on_loader_finished)
        self._loader_thread = loader
        loader.start()

    def _on_text_loaded(self, path: str, content: str):
        if path == self._current_path:
            self._text_edit.setPlainText(content)
            self._apply_match_line_highlighting(content)

    def _apply_match_line_highlighting(self, content: str):
        if not self._highlight_preview_lines:
            self._text_edit.setExtraSelections([])
            return

        line_numbers = _matched_context_line_numbers(content)
        if not line_numbers:
            self._text_edit.setExtraSelections([])
            return

        highlight_format = QTextCharFormat()
        highlight_format.setBackground(QColor(MOCHA['surface1']))
        highlight_format.setForeground(QColor(MOCHA['peach']))
        highlight_format.setProperty(
            QTextFormat.Property.FullWidthSelection,
            True,
        )

        selections = []
        document = self._text_edit.document()
        for line_number in line_numbers:
            block = document.findBlockByLineNumber(line_number)
            if not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            cursor = self._text_edit.textCursor()
            cursor.setPosition(block.position())
            selection.cursor = cursor
            selection.format = highlight_format
            selections.append(selection)

        self._text_edit.setExtraSelections(selections)

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

        file_type = f'{entry.extension.upper()} File' if entry.extension else 'File'
        info_html = f"""
        <div style="font-family: Segoe UI; line-height: 2.0;">
            <p><span style="color: {MOCHA['subtext0']};">Name</span><br>
               <span style="color: {MOCHA['text']};">{entry.name}</span></p>
            <p><span style="color: {MOCHA['subtext0']};">Type</span><br>
               <span style="color: {MOCHA['text']};">{file_type}</span></p>
            <p><span style="color: {MOCHA['subtext0']};">Location</span><br>
               <span style="color: {MOCHA['text']}; font-size: 12px;">{path}</span></p>
        """

        if stat:
            info_html += f"""
            <p><span style="color: {MOCHA['subtext0']};">Size</span><br>
               <span style="color: {MOCHA['text']};">{format_size(stat.st_size)}  <span style="color: {MOCHA['overlay0']};">({stat.st_size:,} bytes)</span></span></p>
            <p><span style="color: {MOCHA['subtext0']};">Modified</span><br>
               <span style="color: {MOCHA['text']};">{format_datetime(entry.date_modified)}</span></p>
            <p><span style="color: {MOCHA['subtext0']};">Created</span><br>
               <span style="color: {MOCHA['text']};">{format_datetime(entry.date_created)}</span></p>
            """

        attrs = format_attributes(entry.attributes)
        if attrs:
            info_html += f"""
            <p><span style="color: {MOCHA['subtext0']};">Attributes</span><br>
               <span style="color: {MOCHA['text']};">{attrs}</span></p>
            """
        reparse_tag = format_reparse_tag(entry.reparse_tag)
        if reparse_tag:
            info_html += f"""
            <p><span style="color: {MOCHA['subtext0']};">Reparse Tag</span><br>
               <span style="color: {MOCHA['text']};">{reparse_tag}</span></p>
            """
        if entry.has_extended_attributes:
            info_html += f"""
            <p><span style="color: {MOCHA['subtext0']};">Extended Attributes</span><br>
               <span style="color: {MOCHA['text']};">Present</span></p>
            """

        info_html += "</div>"

        self._file_info.setText(info_html)
        self._stack.setCurrentIndex(3)

    def _show_dir_info(self, entry: FileEntry, path: str):
        """Show directory info."""
        info_html = f"""
        <div style="font-family: Segoe UI; line-height: 2.0;">
            <p><span style="color: {MOCHA['subtext0']};">Folder</span><br>
               <span style="color: {MOCHA['text']};">{entry.name}</span></p>
            <p><span style="color: {MOCHA['subtext0']};">Location</span><br>
               <span style="color: {MOCHA['text']}; font-size: 12px;">{path}</span></p>
            <p><span style="color: {MOCHA['subtext0']};">Modified</span><br>
               <span style="color: {MOCHA['text']};">{format_datetime(entry.date_modified)}</span></p>
        """
        attrs = format_attributes(entry.attributes)
        if attrs:
            info_html += f"""
            <p><span style="color: {MOCHA['subtext0']};">Attributes</span><br>
               <span style="color: {MOCHA['text']};">{attrs}</span></p>
            """
        reparse_tag = format_reparse_tag(entry.reparse_tag)
        if reparse_tag:
            info_html += f"""
            <p><span style="color: {MOCHA['subtext0']};">Reparse Tag</span><br>
               <span style="color: {MOCHA['text']};">{reparse_tag}</span></p>
            """
        if entry.has_extended_attributes:
            info_html += f"""
            <p><span style="color: {MOCHA['subtext0']};">Extended Attributes</span><br>
               <span style="color: {MOCHA['text']};">Present</span></p>
            """
        info_html += "</div>"
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


class QuickPreviewPopover(QDialog):
    """Floating preview popup for the currently selected result."""

    def __init__(self, file_index: FileIndex, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self.setObjectName("quickPreviewPopover")
        self.setWindowTitle("Quick Preview")
        describe_widget(
            self,
            "Quick preview popover",
            "Floating preview for the selected search result.",
        )
        self.setModal(False)
        self.setMinimumSize(QUICK_PREVIEW_MIN_SIZE)
        self.resize(760, 520)
        self.setStyleSheet(f"""
            #quickPreviewPopover {{
                background-color: {MOCHA['base']};
                border: 1px solid {MOCHA['surface2']};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self._preview_pane = PreviewPane(file_index, self)
        layout.addWidget(self._preview_pane)

    def preview_entry(self, entry: Optional[FileEntry],
                      content_query: str = "",
                      case_sensitive: bool = False):
        self._preview_pane.preview_entry(entry, content_query, case_sensitive)

    def show_for_anchor(self, anchor: QWidget):
        screen = anchor.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QRect(0, 0, 1280, 720)
        anchor_rect = QRect(
            anchor.mapToGlobal(anchor.rect().topLeft()),
            anchor.rect().size(),
        )
        self.setGeometry(quick_preview_geometry(anchor_rect, available, self.size()))
        self.show()
        self.raise_()
        self.activateWindow()

    def hideEvent(self, event):
        self._preview_pane.clear()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.hide()
            return
        super().keyPressEvent(event)
