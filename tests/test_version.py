"""Tests for application version metadata."""

import build
from core.version import APP_NAME, APP_TITLE, VERSION


def test_version_metadata_is_consistent():
    assert APP_NAME == "QuickFind"
    assert APP_TITLE == f"{APP_NAME} v{VERSION}"
    assert build.APP_NAME == APP_NAME
    assert build.VERSION == VERSION
