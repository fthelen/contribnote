"""
UI Styles and Constants for Commentary Generator

Centralized styling definitions for consistent appearance.
"""


class Spacing:
    """Standard spacing values for consistent layout."""

    # Section margins (space between major sections)
    SECTION_MARGIN = 12

    # Inner padding for LabelFrames and containers
    FRAME_PADDING = 12

    # Gap between label and control
    LABEL_GAP = 10

    # Between related controls (e.g., stacked buttons)
    CONTROL_GAP_SMALL = 4

    # Between control groups
    CONTROL_GAP = 8

    # Standard button padding
    BUTTON_PAD = 8


class Typography:
    """Font definitions for visual hierarchy."""

    # Help/hint text
    HELP_FONT = ("TkDefaultFont", 9)
    HELP_COLOR = "#666666"

    # Error message font
    ERROR_COLOR = "#cc0000"

    # Primary action button
    PRIMARY_BUTTON_FONT = ("TkDefaultFont", 10, "bold")


class Dimensions:
    """Standard window and widget dimensions."""

    # Main window
    MAIN_WIDTH = 980
    MAIN_HEIGHT = 780
    MAIN_MIN_WIDTH = 750
    MAIN_MIN_HEIGHT = 600

    # Settings modal
    SETTINGS_WIDTH = 550
    SETTINGS_HEIGHT = 240

    # Prompt Editor modal
    PROMPT_EDITOR_WIDTH = 700
    PROMPT_EDITOR_HEIGHT = 750

    # Attribution Workflow modal
    ATTRIBUTION_EDITOR_WIDTH = 700
    ATTRIBUTION_EDITOR_HEIGHT = 720

    # File list height (lines)
    FILE_LIST_HEIGHT = 5

    # Text area heights
    PROMPT_TEXT_HEIGHT = 14
