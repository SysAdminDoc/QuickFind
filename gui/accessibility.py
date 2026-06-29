"""Small helpers for assistive technology metadata."""


def describe_widget(widget, name: str, description: str = ""):
    """Apply narrator-friendly name and optional description to a Qt widget."""
    widget._quickfind_accessible_name = name
    widget._quickfind_accessible_description = description
    widget.setAccessibleName(name)
    if description:
        widget.setAccessibleDescription(description)
    return widget
