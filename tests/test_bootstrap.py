"""Tests for application startup dependency handling."""

import pytest

import quickfind


def test_missing_dependency_message_points_source_runs_to_requirements(monkeypatch):
    monkeypatch.delattr(quickfind.sys, "frozen", raising=False)

    message = quickfind._missing_dependency_message("PyQt6")

    assert "PyQt6" in message
    assert "python -m pip install -r requirements.txt" in message


def test_missing_dependency_message_guards_frozen_builds(monkeypatch):
    monkeypatch.setattr(quickfind.sys, "frozen", True, raising=False)

    message = quickfind._missing_dependency_message("PyQt6")

    assert "missing bundled dependency PyQt6" in message
    assert "requirements.txt is installed" in message


def test_load_qt_modules_exits_cleanly_when_pyqt_is_missing(monkeypatch, capsys):
    monkeypatch.delattr(quickfind.sys, "frozen", raising=False)

    def missing_pyqt(_name):
        raise ModuleNotFoundError("No module named 'PyQt6'", name="PyQt6")

    with pytest.raises(SystemExit) as exc_info:
        quickfind._load_qt_modules(missing_pyqt)

    assert exc_info.value.code == 1
    assert "python -m pip install -r requirements.txt" in capsys.readouterr().err


def test_load_qt_modules_reraises_unrelated_missing_modules():
    def missing_other(_name):
        raise ModuleNotFoundError("No module named 'other_dependency'", name="other_dependency")

    with pytest.raises(ModuleNotFoundError):
        quickfind._load_qt_modules(missing_other)
