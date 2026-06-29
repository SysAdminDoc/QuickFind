"""Tests for accessibility helper behavior."""

from gui.accessibility import describe_widget


class FakeWidget:
    def __init__(self):
        self.name = ""
        self.description = ""

    def setAccessibleName(self, name: str):
        self.name = name

    def setAccessibleDescription(self, description: str):
        self.description = description


def test_describe_widget_sets_qt_and_testable_metadata():
    widget = FakeWidget()

    assert describe_widget(widget, "Search input", "Type a query.") is widget

    assert widget.name == "Search input"
    assert widget.description == "Type a query."
    assert widget._quickfind_accessible_name == "Search input"
    assert widget._quickfind_accessible_description == "Type a query."


def test_describe_widget_allows_name_only_labels():
    widget = FakeWidget()

    describe_widget(widget, "Preview header")

    assert widget.name == "Preview header"
    assert widget.description == ""
    assert widget._quickfind_accessible_description == ""
