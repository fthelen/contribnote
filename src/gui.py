"""
Commentary Generator GUI

Simple tkinter-based GUI for non-technical users.
"""

import asyncio
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.excel_parser import (
    parse_multiple_files,
    format_attribution_table_markdown,
)
from src.selection_engine import (
    SelectionMode, process_portfolios
)
from src.prompt_manager import (
    PromptManager,
    PromptConfig,
    AttributionPromptManager,
    AttributionPromptConfig,
    get_default_preferred_sources,
    DEFAULT_PROMPT_TEMPLATE,
    DEFAULT_ATTRIBUTION_PROMPT_TEMPLATE,
    DEFAULT_ATTRIBUTION_DEVELOPER_PROMPT,
)
from src.openai_client import (
    OpenAIClient,
    CommentaryResult,
    AttributionOverviewResult,
    DEFAULT_DEVELOPER_PROMPT,
)
from src.output_generator import create_output_workbook, create_log_file
from src.ui_styles import Spacing, Typography, Dimensions
from src import keystore

AVAILABLE_MODELS = [
    "gpt-5-nano-2025-08-07",
    "gpt-5.2-pro-2025-12-11",
    "gpt-5.2-2025-12-11",
]
DEFAULT_MODEL = "gpt-5.2-2025-12-11"


def get_reasoning_levels_for_model(model_id: str) -> list[str]:
    """Return supported reasoning effort levels for a model."""
    if model_id.startswith("gpt-5.2-pro"):
        return ["medium", "high", "xhigh"]
    if model_id.startswith("gpt-5.2"):
        return ["none", "low", "medium", "high", "xhigh"]
    return ["low", "medium", "high"]


def validate_and_clean_domains(domains_str: str) -> tuple[list[str], list[str]]:
    """
    Validate and clean domain inputs for web search.
    
    Removes common URL prefixes (http://, https://, www.) and validates domain format.
    
    Args:
        domains_str: Comma-separated domain string
        
    Returns:
        tuple: (list of valid cleaned domains, list of validation error messages)
    """
    errors = []
    valid_domains = []
    
    if not domains_str.strip():
        return [], []
    
    for domain in domains_str.split(","):
        domain = domain.strip()
        if not domain:
            continue
        
        # Remove common URL prefixes
        cleaned = domain.lower()
        for prefix in ["https://", "http://", "www."]:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
        
        # Remove trailing slashes
        cleaned = cleaned.rstrip("/")
        
        # Basic domain validation: should contain at least one dot and alphanumeric chars
        if not cleaned:
            errors.append(f"'{domain}' results in empty domain after cleanup")
            continue
        
        if "." not in cleaned:
            errors.append(f"'{domain}' is not a valid domain (missing top-level domain)")
            continue
        
        # Check for invalid characters (allow alphanumeric, dots, hyphens)
        if not re.match(r"^[a-z0-9\-\.]+$", cleaned):
            errors.append(f"'{domain}' contains invalid characters")
            continue
        
        # Check that it doesn't start or end with a hyphen or dot
        if cleaned.startswith("-") or cleaned.startswith(".") or cleaned.endswith("-") or cleaned.endswith("."):
            errors.append(f"'{domain}' has invalid format (starts/ends with invalid character)")
            continue
        
        valid_domains.append(cleaned)
    
    return valid_domains, errors


def _organize_commentary_results_by_request(
    requests: list[dict[str, str]],
    results: list[CommentaryResult],
) -> tuple[dict[str, dict[str, CommentaryResult]], dict[str, list[str]]]:
    """
    Organize commentary results by originating request order.

    Args:
        requests: Commentary requests in submission order.
        results: Commentary results returned in corresponding order.

    Returns:
        Tuple containing:
            - Nested commentary dict keyed by portcode then ticker
            - Error dict keyed as "PORTCODE|TICKER"
    """
    commentary_results: dict[str, dict[str, CommentaryResult]] = {}
    errors: dict[str, list[str]] = {}

    for request, result in zip(requests, results):
        portcode = request.get("portcode", "unknown")
        ticker = request.get("ticker", result.ticker)

        if portcode not in commentary_results:
            commentary_results[portcode] = {}
        commentary_results[portcode][ticker] = result

        if not result.success:
            key = f"{portcode}|{ticker}"
            errors.setdefault(key, []).append(result.error_message)

    return commentary_results, errors


def _compute_overall_progress(
    completed: int,
    offset: int,
    overall_total: int
) -> tuple[int, int]:
    """
    Translate phase-local progress into run-level progress.

    Args:
        completed: Completed count in the current phase.
        offset: Number of items completed before this phase.
        overall_total: Total requests across all phases in this run.

    Returns:
        Tuple of (overall_completed, overall_total).
    """
    if overall_total <= 0:
        return 0, 0

    normalized_completed = max(0, completed)
    overall_completed = min(overall_total, offset + normalized_completed)
    return overall_completed, overall_total


def _make_overall_progress_callback(
    update_progress_fn: Callable[[str, int, int], None],
    offset: int,
    overall_total: int
) -> Callable[[str, int, int], None]:
    """
    Create a phase progress callback that reports run-level totals.

    Args:
        update_progress_fn: App progress callback target.
        offset: Number of already-completed requests before this phase.
        overall_total: Total requests in the run.

    Returns:
        Callback compatible with OpenAIClient progress callback signature.
    """
    def _callback(item_id: str, completed: int, _phase_total: int) -> None:
        overall_completed, total = _compute_overall_progress(
            completed=completed,
            offset=offset,
            overall_total=overall_total
        )
        if total > 0:
            update_progress_fn(item_id, overall_completed, total)

    return _callback


class ToolTip:
    """Simple hover tooltip for tkinter widgets."""

    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.tip_window: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None

        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_leave, add="+")
        self.widget.bind("<Destroy>", self._on_destroy, add="+")

    def _on_enter(self, _event=None):
        if self._after_id is None:
            self._after_id = self.widget.after(500, self._show)

    def _on_leave(self, _event=None):
        self._cancel_pending_show()
        self._hide()

    def _on_destroy(self, _event=None):
        self._cancel_pending_show()
        self._hide()

    def _cancel_pending_show(self):
        if self._after_id is None:
            return
        try:
            self.widget.after_cancel(self._after_id)
        except tk.TclError:
            pass
        finally:
            self._after_id = None

    def _show(self):
        if self.tip_window is not None:
            return
        try:
            if not self.widget.winfo_exists():
                self._after_id = None
                return
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            self._after_id = None
            return
        self._after_id = None
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self.text,
            justify="left",
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=4,
            background="#f8f8f8",
            foreground="#222222",
            font=Typography.HELP_FONT,
            wraplength=360,
        )
        label.pack()

    def _hide(self):
        if self.tip_window is not None:
            try:
                self.tip_window.destroy()
            except tk.TclError:
                # The tooltip window may already have been destroyed or the Tcl interpreter
                # may be shutting down; ignore errors during best-effort cleanup.
                pass
            self.tip_window = None


def _make_info_icon(parent: tk.Widget) -> ttk.Label:
    """Create a small info indicator label for tooltip affordance."""
    return ttk.Label(parent, text="(i)", cursor="hand2")


class SettingsModal:
    """Modal window for API key settings."""

    def __init__(self, parent: tk.Tk, api_key: str, api_key_source: str, keyring_available: bool):
        """
        Initialize the settings modal window.

        Args:
            parent: Parent window
            api_key: Current OpenAI API key
            api_key_source: Where the API key was loaded from ("env", "keyring", "config", "session", "none")
            keyring_available: Whether system keychain storage is available
        """
        self.result = None  # Will be set to dict if user saves
        self._tooltips: list[ToolTip] = []

        self.window = tk.Toplevel(parent)
        self.window.title("API Settings")
        self.window.transient(parent)
        self.window.grab_set()

        # Center on parent
        self._center_on_parent(parent, Dimensions.SETTINGS_WIDTH, Dimensions.SETTINGS_HEIGHT)

        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        main_frame = ttk.Frame(self.window, padding=Spacing.FRAME_PADDING)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)

        # API Key section
        api_frame = ttk.LabelFrame(main_frame, text="OpenAI API Key", padding=Spacing.FRAME_PADDING)
        api_frame.grid(row=0, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        api_frame.columnconfigure(0, weight=1)

        # Entry row
        entry_frame = ttk.Frame(api_frame)
        entry_frame.grid(row=0, column=0, sticky="ew")
        entry_frame.columnconfigure(0, weight=1)

        self.api_key_var = tk.StringVar(value=api_key)
        self.api_key_entry = ttk.Entry(entry_frame, textvariable=self.api_key_var, show="*")
        self.api_key_entry.grid(row=0, column=0, sticky="ew")

        self.show_button = ttk.Button(entry_frame, text="Hold to show")
        self.show_button.grid(row=0, column=1, padx=(Spacing.CONTROL_GAP, 0))
        self.show_button.bind("<ButtonPress-1>", self._show_key)
        self.show_button.bind("<ButtonRelease-1>", self._hide_key)
        self.show_button.bind("<Leave>", self._hide_key)
        self.window.bind("<FocusOut>", self._hide_key)
        api_help_icon = _make_info_icon(entry_frame)
        api_help_icon.grid(row=0, column=2, padx=(Spacing.CONTROL_GAP_SMALL, 0))

        # Help text for API key
        if keyring_available:
            storage_line = "Stored securely in your system keychain."
        else:
            storage_line = "Secure storage unavailable; use OPENAI_API_KEY."
        help_lines = [
            storage_line,
            "Hold the button to reveal the key.",
            "Get your key from platform.openai.com or set OPENAI_API_KEY."
        ]
        source_note = ""
        if api_key_source == "env":
            source_note = "OPENAI_API_KEY is set and will be used by default."
        elif api_key_source == "keyring":
            source_note = "Using key stored in your system keychain."
        elif api_key_source == "config":
            source_note = "Using key from legacy config; it will be migrated."
        elif api_key_source == "session":
            source_note = "Key will be used for this session only."

        tooltip_lines = help_lines[:]
        if source_note:
            tooltip_lines.append(source_note)
        self._tooltips.extend([
            ToolTip(self.api_key_entry, "\n".join(tooltip_lines)),
            ToolTip(self.show_button, "Hold while pressed to temporarily reveal the API key."),
            ToolTip(api_help_icon, "\n".join(tooltip_lines)),
        ])

        # Button frame - right aligned at bottom
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=1, column=0, sticky="e", pady=(Spacing.SECTION_MARGIN, 0))

        ttk.Button(btn_frame, text="Cancel", command=self.on_cancel).pack(side="left", padx=(0, Spacing.BUTTON_PAD))
        ttk.Button(btn_frame, text="Save", command=self.on_save).pack(side="left")

        self.window.focus()

    def _center_on_parent(self, parent: tk.Tk, width: int, height: int):
        """Center the modal window on its parent."""
        parent.update_idletasks()
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2

        # Ensure window stays on screen
        x = max(0, x)
        y = max(0, y)

        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _show_key(self, _event=None):
        """Show the API key while the button is held."""
        self.api_key_entry.configure(show="")

    def _hide_key(self, _event=None):
        """Hide the API key when the hold is released or focus changes."""
        self.api_key_entry.configure(show="*")
    
    def on_cancel(self):
        """Cancel button clicked - discard changes."""
        self.result = None
        self.window.destroy()
    
    def on_save(self):
        """Save button clicked - apply changes."""
        self.result = {
            "api_key": self.api_key_var.get()
        }
        self.window.destroy()


class PromptEditorModal:
    """Modal window for editing contribution prompts and model settings."""

    def __init__(
        self,
        parent: tk.Tk,
        current_prompt: str,
        current_developer_prompt: str,
        current_thinking_level: str,
        current_model: str,
        available_models: list[str],
        current_text_verbosity: str,
    ):
        """
        Initialize the modal window.

        Args:
            parent: Parent window
            current_prompt: Current prompt template text
            current_developer_prompt: Current system/developer prompt text
            current_thinking_level: Current thinking level ("none", "low", "medium", "high", "xhigh")
            current_model: Current model ID
            available_models: List of available model IDs
            current_text_verbosity: Current text verbosity ("low", "medium", "high")
        """
        self.result = None  # Will be set to dict if user saves
        self._tooltips: list[ToolTip] = []

        self.window = tk.Toplevel(parent)
        self.window.title("Contribution Settings")
        self.window.transient(parent)
        self.window.grab_set()

        # Center on parent
        self._center_on_parent(parent, Dimensions.PROMPT_EDITOR_WIDTH, Dimensions.PROMPT_EDITOR_HEIGHT)

        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        main_frame = ttk.Frame(self.window, padding=Spacing.FRAME_PADDING)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)  # Prompts section expands

        # Thinking level section
        level_frame = ttk.LabelFrame(main_frame, text="Reasoning & Verbosity", padding=Spacing.FRAME_PADDING)
        level_frame.grid(row=0, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        level_frame.columnconfigure(1, weight=1)

        ttk.Label(level_frame, text="Reasoning effort:").grid(row=0, column=0, sticky="w", padx=(0, Spacing.LABEL_GAP))
        self.thinking_var = tk.StringVar(value=current_thinking_level)

        self.thinking_combo = ttk.Combobox(
            level_frame,
            textvariable=self.thinking_var,
            values=[],
            state="readonly",
            width=12
        )
        self.thinking_combo.grid(row=0, column=1, sticky="w")
        reasoning_icon = _make_info_icon(level_frame)
        reasoning_icon.grid(row=0, column=2, padx=(Spacing.CONTROL_GAP_SMALL, 0), sticky="w")

        ttk.Label(level_frame, text="Model:").grid(row=1, column=0, sticky="w", padx=(0, Spacing.LABEL_GAP), pady=(Spacing.CONTROL_GAP_SMALL, 0))
        model_value = current_model if current_model in available_models else DEFAULT_MODEL
        self.model_var = tk.StringVar(value=model_value)
        model_combo = ttk.Combobox(
            level_frame,
            textvariable=self.model_var,
            values=available_models,
            state="readonly",
            width=28
        )
        model_combo.grid(row=1, column=1, sticky="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))
        model_icon = _make_info_icon(level_frame)
        model_icon.grid(row=1, column=2, padx=(Spacing.CONTROL_GAP_SMALL, 0), pady=(Spacing.CONTROL_GAP_SMALL, 0), sticky="w")
        model_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_reasoning_levels())

        ttk.Label(level_frame, text="Text verbosity:").grid(row=2, column=0, sticky="w", padx=(0, Spacing.LABEL_GAP), pady=(Spacing.CONTROL_GAP_SMALL, 0))
        self.text_verbosity_var = tk.StringVar(value=current_text_verbosity)

        verbosity_combo = ttk.Combobox(
            level_frame,
            textvariable=self.text_verbosity_var,
            values=["low", "medium", "high"],
            state="readonly",
            width=12
        )
        verbosity_combo.grid(row=2, column=1, sticky="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))
        verbosity_icon = _make_info_icon(level_frame)
        verbosity_icon.grid(row=2, column=2, padx=(Spacing.CONTROL_GAP_SMALL, 0), pady=(Spacing.CONTROL_GAP_SMALL, 0), sticky="w")

        # Prompts tabs section
        prompt_frame = ttk.LabelFrame(main_frame, text="Prompts", padding=Spacing.FRAME_PADDING)
        prompt_frame.grid(row=1, column=0, sticky="nsew", pady=(0, Spacing.SECTION_MARGIN))
        prompt_frame.columnconfigure(0, weight=1)
        prompt_frame.rowconfigure(0, weight=1)

        # Create notebook (tabs)
        self.notebook = ttk.Notebook(prompt_frame)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        # Tab 1: User Prompt
        user_prompt_tab = ttk.Frame(self.notebook)
        self.notebook.add(user_prompt_tab, text="User Prompt (Template)")
        user_prompt_tab.columnconfigure(0, weight=1)
        user_prompt_tab.rowconfigure(0, weight=1)

        self.prompt_text = scrolledtext.ScrolledText(user_prompt_tab, height=Dimensions.PROMPT_TEXT_HEIGHT, wrap=tk.WORD)
        self.prompt_text.grid(row=0, column=0, sticky="nsew", padx=Spacing.CONTROL_GAP, pady=Spacing.CONTROL_GAP)
        self.prompt_text.insert("1.0", current_prompt)
        prompt_icon = _make_info_icon(user_prompt_tab)
        prompt_icon.grid(row=1, column=0, sticky="w", padx=Spacing.CONTROL_GAP, pady=(0, Spacing.CONTROL_GAP))

        # Tab 2: System/Developer Prompt
        dev_prompt_tab = ttk.Frame(self.notebook)
        self.notebook.add(dev_prompt_tab, text="System Prompt (Instructions)")
        dev_prompt_tab.columnconfigure(0, weight=1)
        dev_prompt_tab.rowconfigure(0, weight=1)

        self.dev_prompt_text = scrolledtext.ScrolledText(dev_prompt_tab, height=Dimensions.PROMPT_TEXT_HEIGHT, wrap=tk.WORD)
        self.dev_prompt_text.grid(row=0, column=0, sticky="nsew", padx=Spacing.CONTROL_GAP, pady=Spacing.CONTROL_GAP)
        self.dev_prompt_text.insert("1.0", current_developer_prompt)
        dev_prompt_icon = _make_info_icon(dev_prompt_tab)
        dev_prompt_icon.grid(row=1, column=0, sticky="w", padx=Spacing.CONTROL_GAP, pady=(0, Spacing.CONTROL_GAP))

        # Button frame - Reset buttons left, Cancel/Save right
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=2, column=0, sticky="ew")
        btn_frame.columnconfigure(0, weight=1)

        # Left side - Reset buttons
        reset_frame = ttk.Frame(btn_frame)
        reset_frame.grid(row=0, column=0, sticky="w")
        ttk.Button(reset_frame, text="Reset User Prompt", command=self.reset_user_prompt).pack(side="left", padx=(0, Spacing.BUTTON_PAD))
        ttk.Button(reset_frame, text="Reset System Prompt", command=self.reset_system_prompt).pack(side="left")

        # Right side - Cancel/Save
        action_frame = ttk.Frame(btn_frame)
        action_frame.grid(row=0, column=1, sticky="e")
        ttk.Button(action_frame, text="Cancel", command=self.on_cancel).pack(side="left", padx=(0, Spacing.BUTTON_PAD))
        ttk.Button(action_frame, text="Save", command=self.on_save).pack(side="left")

        self.reasoning_tooltip = ToolTip(self.thinking_combo, "")
        self.reasoning_icon_tooltip = ToolTip(reasoning_icon, "")
        self._tooltips.extend([
            self.reasoning_tooltip,
            self.reasoning_icon_tooltip,
            ToolTip(model_combo, "Select the model used for contribution commentary."),
            ToolTip(model_icon, "Select the model used for contribution commentary."),
            ToolTip(verbosity_combo, "Controls response length and detail."),
            ToolTip(verbosity_icon, "Controls response length and detail."),
            ToolTip(
                self.prompt_text,
                "Template variables: {ticker}, {security_name}, {period}, {source_instructions}",
            ),
            ToolTip(
                prompt_icon,
                "Template variables: {ticker}, {security_name}, {period}, {source_instructions}",
            ),
            ToolTip(
                self.dev_prompt_text,
                "System prompt controls the model behavior and tone for all contribution requests.",
            ),
            ToolTip(
                dev_prompt_icon,
                "System prompt controls the model behavior and tone for all contribution requests.",
            ),
        ])
        self._update_reasoning_levels()

        self.window.focus()

    def _center_on_parent(self, parent: tk.Tk, width: int, height: int):
        """Center the modal window on its parent."""
        parent.update_idletasks()
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2

        # Ensure window stays on screen
        x = max(0, x)
        y = max(0, y)

        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _build_reasoning_help_text(self, levels: list[str]) -> str:
        parts = []
        if "none" in levels:
            parts.append("none: No reasoning")
        if "low" in levels:
            parts.append("low: Fastest")
        if "medium" in levels:
            parts.append("medium: Balanced")
        if "high" in levels:
            parts.append("high: Thorough")
        if "xhigh" in levels:
            parts.append("xhigh: Most thorough")
        return " | ".join(parts)

    def _update_reasoning_levels(self) -> None:
        model_id = self.model_var.get()
        levels = get_reasoning_levels_for_model(model_id)
        self.thinking_combo["values"] = levels

        if self.thinking_var.get() not in levels:
            default_level = "none" if "none" in levels else "medium"
            self.thinking_var.set(default_level)

        if hasattr(self, "reasoning_tooltip"):
            help_text = f"Supported levels: {self._build_reasoning_help_text(levels)}"
            self.reasoning_tooltip.text = help_text
            if hasattr(self, "reasoning_icon_tooltip"):
                self.reasoning_icon_tooltip.text = help_text
    
    def reset_user_prompt(self):
        """Reset user prompt to default template."""
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", DEFAULT_PROMPT_TEMPLATE)
    
    def reset_system_prompt(self):
        """Reset system/developer prompt to default."""
        self.dev_prompt_text.delete("1.0", tk.END)
        self.dev_prompt_text.insert("1.0", DEFAULT_DEVELOPER_PROMPT)

    def on_cancel(self):
        """Cancel button clicked - discard changes."""
        self.result = None
        self.window.destroy()
    
    def on_save(self):
        """Save button clicked - apply changes."""
        self.result = {
            "prompt_template": self.prompt_text.get("1.0", tk.END).strip(),
            "developer_prompt": self.dev_prompt_text.get("1.0", tk.END).strip(),
            "thinking_level": self.thinking_var.get(),
            "model": self.model_var.get(),
            "text_verbosity": self.text_verbosity_var.get(),
        }
        self.window.destroy()


class AttributionWorkflowModal:
    """Modal window for attribution workflow prompt and model configuration."""

    def __init__(
        self,
        parent: tk.Tk,
        current_prompt: str,
        current_developer_prompt: str,
        current_thinking_level: str,
        current_model: str,
        available_models: list[str],
        current_text_verbosity: str,
    ):
        self.result = None
        self._tooltips: list[ToolTip] = []

        self.window = tk.Toplevel(parent)
        self.window.title("Attribution Settings")
        self.window.transient(parent)
        self.window.grab_set()

        self._center_on_parent(parent, Dimensions.ATTRIBUTION_EDITOR_WIDTH, Dimensions.ATTRIBUTION_EDITOR_HEIGHT)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        main_frame = ttk.Frame(self.window, padding=Spacing.FRAME_PADDING)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        level_frame = ttk.LabelFrame(main_frame, text="Reasoning & Verbosity", padding=Spacing.FRAME_PADDING)
        level_frame.grid(row=0, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        level_frame.columnconfigure(1, weight=1)

        ttk.Label(level_frame, text="Reasoning effort:").grid(row=0, column=0, sticky="w", padx=(0, Spacing.LABEL_GAP))
        self.thinking_var = tk.StringVar(value=current_thinking_level)
        self.thinking_combo = ttk.Combobox(
            level_frame,
            textvariable=self.thinking_var,
            values=[],
            state="readonly",
            width=12
        )
        self.thinking_combo.grid(row=0, column=1, sticky="w")
        reasoning_icon = _make_info_icon(level_frame)
        reasoning_icon.grid(row=0, column=2, padx=(Spacing.CONTROL_GAP_SMALL, 0), sticky="w")

        ttk.Label(level_frame, text="Model:").grid(
            row=1, column=0, sticky="w", padx=(0, Spacing.LABEL_GAP), pady=(Spacing.CONTROL_GAP_SMALL, 0)
        )
        model_value = current_model if current_model in available_models else DEFAULT_MODEL
        self.model_var = tk.StringVar(value=model_value)
        model_combo = ttk.Combobox(
            level_frame,
            textvariable=self.model_var,
            values=available_models,
            state="readonly",
            width=28
        )
        model_combo.grid(row=1, column=1, sticky="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))
        model_icon = _make_info_icon(level_frame)
        model_icon.grid(row=1, column=2, padx=(Spacing.CONTROL_GAP_SMALL, 0), pady=(Spacing.CONTROL_GAP_SMALL, 0), sticky="w")
        model_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_reasoning_levels())

        ttk.Label(level_frame, text="Text verbosity:").grid(
            row=2, column=0, sticky="w", padx=(0, Spacing.LABEL_GAP), pady=(Spacing.CONTROL_GAP_SMALL, 0)
        )
        self.text_verbosity_var = tk.StringVar(value=current_text_verbosity)
        verbosity_combo = ttk.Combobox(
            level_frame,
            textvariable=self.text_verbosity_var,
            values=["low", "medium", "high"],
            state="readonly",
            width=12
        )
        verbosity_combo.grid(row=2, column=1, sticky="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))
        verbosity_icon = _make_info_icon(level_frame)
        verbosity_icon.grid(row=2, column=2, padx=(Spacing.CONTROL_GAP_SMALL, 0), pady=(Spacing.CONTROL_GAP_SMALL, 0), sticky="w")

        prompt_frame = ttk.LabelFrame(main_frame, text="Attribution Prompts", padding=Spacing.FRAME_PADDING)
        prompt_frame.grid(row=1, column=0, sticky="nsew", pady=(0, Spacing.SECTION_MARGIN))
        prompt_frame.columnconfigure(0, weight=1)
        prompt_frame.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(prompt_frame)
        notebook.grid(row=0, column=0, sticky="nsew")

        user_tab = ttk.Frame(notebook)
        notebook.add(user_tab, text="User Prompt (Template)")
        user_tab.columnconfigure(0, weight=1)
        user_tab.rowconfigure(0, weight=1)

        self.prompt_text = scrolledtext.ScrolledText(user_tab, height=Dimensions.PROMPT_TEXT_HEIGHT, wrap=tk.WORD)
        self.prompt_text.grid(row=0, column=0, sticky="nsew", padx=Spacing.CONTROL_GAP, pady=Spacing.CONTROL_GAP)
        self.prompt_text.insert("1.0", current_prompt)
        prompt_icon = _make_info_icon(user_tab)
        prompt_icon.grid(row=1, column=0, sticky="w", padx=Spacing.CONTROL_GAP, pady=(0, Spacing.CONTROL_GAP))

        dev_tab = ttk.Frame(notebook)
        notebook.add(dev_tab, text="System Prompt (Instructions)")
        dev_tab.columnconfigure(0, weight=1)
        dev_tab.rowconfigure(0, weight=1)

        self.dev_prompt_text = scrolledtext.ScrolledText(dev_tab, height=Dimensions.PROMPT_TEXT_HEIGHT, wrap=tk.WORD)
        self.dev_prompt_text.grid(row=0, column=0, sticky="nsew", padx=Spacing.CONTROL_GAP, pady=Spacing.CONTROL_GAP)
        self.dev_prompt_text.insert("1.0", current_developer_prompt)
        dev_prompt_icon = _make_info_icon(dev_tab)
        dev_prompt_icon.grid(row=1, column=0, sticky="w", padx=Spacing.CONTROL_GAP, pady=(0, Spacing.CONTROL_GAP))

        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=2, column=0, sticky="ew")
        btn_frame.columnconfigure(0, weight=1)

        reset_frame = ttk.Frame(btn_frame)
        reset_frame.grid(row=0, column=0, sticky="w")
        ttk.Button(reset_frame, text="Reset User Prompt", command=self.reset_user_prompt).pack(
            side="left", padx=(0, Spacing.BUTTON_PAD)
        )
        ttk.Button(reset_frame, text="Reset System Prompt", command=self.reset_system_prompt).pack(side="left")

        action_frame = ttk.Frame(btn_frame)
        action_frame.grid(row=0, column=1, sticky="e")
        ttk.Button(action_frame, text="Cancel", command=self.on_cancel).pack(side="left", padx=(0, Spacing.BUTTON_PAD))
        ttk.Button(action_frame, text="Save", command=self.on_save).pack(side="left")

        self.reasoning_tooltip = ToolTip(self.thinking_combo, "")
        self.reasoning_icon_tooltip = ToolTip(reasoning_icon, "")
        self._tooltips.extend([
            self.reasoning_tooltip,
            self.reasoning_icon_tooltip,
            ToolTip(model_combo, "Select the model used for attribution overview output."),
            ToolTip(model_icon, "Select the model used for attribution overview output."),
            ToolTip(verbosity_combo, "Controls response length and detail."),
            ToolTip(verbosity_icon, "Controls response length and detail."),
            ToolTip(
                self.prompt_text,
                "Template variables: {portcode}, {period}, {sector_attrib}, {country_attrib}, {source_instructions}",
            ),
            ToolTip(
                prompt_icon,
                "Template variables: {portcode}, {period}, {sector_attrib}, {country_attrib}, {source_instructions}",
            ),
            ToolTip(
                self.dev_prompt_text,
                "System prompt controls behavior and tone for attribution overview requests.",
            ),
            ToolTip(
                dev_prompt_icon,
                "System prompt controls behavior and tone for attribution overview requests.",
            ),
        ])
        self._update_reasoning_levels()

        self.window.focus()

    def _center_on_parent(self, parent: tk.Tk, width: int, height: int):
        """Center the modal window on its parent."""
        parent.update_idletasks()
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2
        x = max(0, x)
        y = max(0, y)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _build_reasoning_help_text(self, levels: list[str]) -> str:
        parts = []
        if "none" in levels:
            parts.append("none: No reasoning")
        if "low" in levels:
            parts.append("low: Fastest")
        if "medium" in levels:
            parts.append("medium: Balanced")
        if "high" in levels:
            parts.append("high: Thorough")
        if "xhigh" in levels:
            parts.append("xhigh: Most thorough")
        return " | ".join(parts)

    def _update_reasoning_levels(self) -> None:
        model_id = self.model_var.get()
        levels = get_reasoning_levels_for_model(model_id)
        self.thinking_combo["values"] = levels

        if self.thinking_var.get() not in levels:
            default_level = "none" if "none" in levels else "medium"
            self.thinking_var.set(default_level)

        if hasattr(self, "reasoning_tooltip"):
            help_text = f"Supported levels: {self._build_reasoning_help_text(levels)}"
            self.reasoning_tooltip.text = help_text
            if hasattr(self, "reasoning_icon_tooltip"):
                self.reasoning_icon_tooltip.text = help_text

    def reset_user_prompt(self):
        """Reset attribution user prompt to default template."""
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", DEFAULT_ATTRIBUTION_PROMPT_TEMPLATE)

    def reset_system_prompt(self):
        """Reset attribution system prompt to default."""
        self.dev_prompt_text.delete("1.0", tk.END)
        self.dev_prompt_text.insert("1.0", DEFAULT_ATTRIBUTION_DEVELOPER_PROMPT)

    def on_cancel(self):
        """Discard changes."""
        self.result = None
        self.window.destroy()

    def on_save(self):
        """Apply changes."""
        self.result = {
            "prompt_template": self.prompt_text.get("1.0", tk.END).strip(),
            "developer_prompt": self.dev_prompt_text.get("1.0", tk.END).strip(),
            "thinking_level": self.thinking_var.get(),
            "model": self.model_var.get(),
            "text_verbosity": self.text_verbosity_var.get(),
        }
        self.window.destroy()


class CommentaryGeneratorApp:
    """Main GUI application for the commentary generator."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Commentary Generator")
        self.root.geometry(f"{Dimensions.MAIN_WIDTH}x{Dimensions.MAIN_HEIGHT}")
        self.root.minsize(Dimensions.MAIN_MIN_WIDTH, Dimensions.MAIN_MIN_HEIGHT)

        # State variables
        self.input_files: list[Path] = []
        self.output_folder: Optional[Path] = None
        self.is_running = False
        self.thinking_level: str = "medium"  # Default thinking level
        self.text_verbosity: str = "low"  # Default verbosity level
        self.model_id: str = DEFAULT_MODEL
        self.api_key: str = ""  # API key storage
        self.api_key_source: str = "none"
        self.keyring_available: bool = keystore.keyring_available()
        self.sources_var = tk.StringVar(value=", ".join(get_default_preferred_sources()))

        self._generation_loop: Optional[asyncio.AbstractEventLoop] = None
        self._cancel_event: Optional[asyncio.Event] = None
        self._cancel_requested: bool = False
        self._exit_after_cancel: bool = False
        self._progress_queue: queue.SimpleQueue[tuple[str, int, int]] = queue.SimpleQueue()
        self._ui_callback_queue: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()

        # Prompt template and system prompt variables
        self.prompt_text_content: str = DEFAULT_PROMPT_TEMPLATE
        self.developer_prompt_content: str = DEFAULT_DEVELOPER_PROMPT
        self.run_attribution_overview: bool = False
        self.attribution_prompt_text_content: str = DEFAULT_ATTRIBUTION_PROMPT_TEMPLATE
        self.attribution_developer_prompt_content: str = DEFAULT_ATTRIBUTION_DEVELOPER_PROMPT
        self.attribution_thinking_level: str = "medium"
        self.attribution_text_verbosity: str = "low"
        self.attribution_model_id: str = DEFAULT_MODEL
        
        # Citation and source settings
        self.require_citations: bool = True  # Default: require citations
        self.prioritize_sources: bool = True  # Default: inject source instructions into prompt
        self._tooltips: list[ToolTip] = []

        # Configure grid weights for resizing
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self._configure_styles()
        self.setup_ui()
        self.load_api_key()
        self.load_config()
        self._schedule_progress_queue_drain()

        self.root.protocol("WM_DELETE_WINDOW", self.on_exit_requested)

    def _configure_styles(self):
        """Configure custom ttk styles for the application."""
        style = ttk.Style()

        # Primary action button - bold font
        style.configure(
            "Primary.TButton",
            font=Typography.PRIMARY_BUTTON_FONT
        )
    
    def _get_config_path(self) -> Path:
        """Get the configuration directory path (platform-aware)."""
        if sys.platform == "win32":
            # Windows: use APPDATA environment variable
            config_dir = Path(os.getenv("APPDATA", str(Path.home()))) / "ContribNote"
        else:
            # macOS/Linux: use ~/.contribnote
            config_dir = Path.home() / ".contribnote"
        
        return config_dir
    
    def _get_config_file(self) -> Path:
        """Get the full path to the config file."""
        return self._get_config_path() / "config.json"
    
    def load_config(self) -> None:
        """Load configuration from file if it exists."""
        config_file = self._get_config_file()
        
        if not config_file.exists():
            return  # Use defaults if no config file
        
        try:
            with open(config_file, "r") as f:
                config = json.load(f)
            
            # Load API key (legacy config migration)
            if "api_key" in config:
                self._migrate_api_key_from_config(config.get("api_key", ""))
            
            # Load prompt template
            if "prompt_template" in config:
                self.prompt_text_content = config["prompt_template"]
            
            # Load developer prompt
            if "developer_prompt" in config:
                self.developer_prompt_content = config["developer_prompt"]
            
            # Load thinking level
            if "thinking_level" in config:
                self.thinking_level = config["thinking_level"]

            if "text_verbosity" in config:
                self.text_verbosity = config["text_verbosity"]

            if "model" in config and config["model"] in AVAILABLE_MODELS:
                self.model_id = config["model"]
            else:
                self.model_id = DEFAULT_MODEL

            if "run_attribution_overview" in config:
                self.run_attribution_overview = bool(config["run_attribution_overview"])
                if hasattr(self, "run_attribution_var"):
                    self.run_attribution_var.set(self.run_attribution_overview)

            if "attribution_prompt_template" in config:
                self.attribution_prompt_text_content = config["attribution_prompt_template"]

            if "attribution_developer_prompt" in config:
                self.attribution_developer_prompt_content = config["attribution_developer_prompt"]

            if "attribution_thinking_level" in config:
                self.attribution_thinking_level = config["attribution_thinking_level"]

            if "attribution_text_verbosity" in config:
                self.attribution_text_verbosity = config["attribution_text_verbosity"]

            if "attribution_model" in config and config["attribution_model"] in AVAILABLE_MODELS:
                self.attribution_model_id = config["attribution_model"]
            else:
                self.attribution_model_id = DEFAULT_MODEL
            
            # Load preferred sources
            if "preferred_sources" in config:
                self.sources_var.set(", ".join(config["preferred_sources"]))
            
            # Load require_citations setting
            if "require_citations" in config:
                self.require_citations = config["require_citations"]
            
            # Load prioritize_sources setting
            if "prioritize_sources" in config:
                self.prioritize_sources = config["prioritize_sources"]

            if hasattr(self, "require_citations_var"):
                self.require_citations_var.set(self.require_citations)
            if hasattr(self, "prioritize_sources_var"):
                self.prioritize_sources_var.set(self.prioritize_sources)
            self._refresh_global_source_errors()
            
            # Load output folder
            if "output_folder" in config:
                output_folder = config["output_folder"]
                if Path(output_folder).exists():
                    self.output_folder = Path(output_folder)
                    self.output_var.set(output_folder)
        
        except Exception as e:
            # Silently fail if config load fails - use defaults
            print(f"Warning: Could not load config: {e}")
    
    def save_config(self) -> None:
        """Save current configuration to file."""
        try:
            config_dir = self._get_config_path()
            config_dir.mkdir(parents=True, exist_ok=True)
            
            config = {
                "prompt_template": self.prompt_text_content,
                "developer_prompt": self.developer_prompt_content,
                "thinking_level": self.thinking_level,
                "model": self.model_id,
                "text_verbosity": self.text_verbosity,
                "preferred_sources": [s.strip() for s in self.sources_var.get().split(",") if s.strip()],
                "require_citations": self.require_citations,
                "prioritize_sources": self.prioritize_sources,
                "run_attribution_overview": self.run_attribution_overview,
                "attribution_prompt_template": self.attribution_prompt_text_content,
                "attribution_developer_prompt": self.attribution_developer_prompt_content,
                "attribution_thinking_level": self.attribution_thinking_level,
                "attribution_text_verbosity": self.attribution_text_verbosity,
                "attribution_model": self.attribution_model_id,
                "output_folder": str(self.output_folder) if self.output_folder else ""
            }
            
            config_file = self._get_config_file()
            with open(config_file, "w") as f:
                json.dump(config, f, indent=2)
        
        except Exception as e:
            # Silently fail if config save fails
            print(f"Warning: Could not save config: {e}")
    
    
    def setup_ui(self):
        """Set up the user interface."""
        # Main frame with padding
        main_frame = ttk.Frame(self.root, padding=Spacing.FRAME_PADDING)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)

        current_row = 0

        # ====== File Selection Section ======
        file_frame = ttk.LabelFrame(main_frame, text="File Selection", padding=Spacing.FRAME_PADDING)
        file_frame.grid(row=current_row, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        file_frame.columnconfigure(1, weight=1)

        # Input files
        ttk.Label(file_frame, text="Input Files:").grid(row=0, column=0, sticky="nw", padx=(0, Spacing.LABEL_GAP))

        input_list_frame = ttk.Frame(file_frame)
        input_list_frame.grid(row=0, column=1, sticky="ew")
        input_list_frame.columnconfigure(0, weight=1)

        self.input_listbox = tk.Listbox(input_list_frame, height=Dimensions.FILE_LIST_HEIGHT, selectmode=tk.EXTENDED)
        self.input_listbox.grid(row=0, column=0, sticky="ew")

        input_scroll = ttk.Scrollbar(input_list_frame, orient="vertical", command=self.input_listbox.yview)
        input_scroll.grid(row=0, column=1, sticky="ns")
        self.input_listbox.configure(yscrollcommand=input_scroll.set)

        input_btn_frame = ttk.Frame(file_frame)
        input_btn_frame.grid(row=0, column=2, padx=(Spacing.LABEL_GAP, 0))
        ttk.Button(input_btn_frame, text="Add Files", command=self.add_input_files).pack(pady=Spacing.CONTROL_GAP_SMALL)
        ttk.Button(input_btn_frame, text="Remove", command=self.remove_input_files).pack(pady=Spacing.CONTROL_GAP_SMALL)
        ttk.Button(input_btn_frame, text="Clear All", command=self.clear_input_files).pack(pady=Spacing.CONTROL_GAP_SMALL)

        # Output folder
        ttk.Label(file_frame, text="Output Folder:").grid(row=1, column=0, sticky="w", padx=(0, Spacing.LABEL_GAP), pady=(Spacing.CONTROL_GAP, 0))

        self.output_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.output_var, state="readonly").grid(
            row=1, column=1, sticky="ew", pady=(Spacing.CONTROL_GAP, 0))
        ttk.Button(file_frame, text="Browse", command=self.select_output_folder).grid(
            row=1, column=2, padx=(Spacing.LABEL_GAP, 0), pady=(Spacing.CONTROL_GAP, 0))

        current_row += 1

        # ====== Generation Options Section (renamed from Settings) ======
        options_frame = ttk.LabelFrame(main_frame, text="Generation Options", padding=Spacing.FRAME_PADDING)
        options_frame.grid(row=current_row, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        options_frame.columnconfigure(1, weight=1)

        # Holdings mode
        ttk.Label(options_frame, text="Holdings Mode:").grid(row=0, column=0, sticky="w", padx=(0, Spacing.LABEL_GAP))
        self.mode_var = tk.StringVar(value="top_bottom")
        mode_frame = ttk.Frame(options_frame)
        mode_frame.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(mode_frame, text="Top/Bottom N", variable=self.mode_var,
                        value="top_bottom", command=self.on_mode_change).pack(side="left")
        ttk.Radiobutton(mode_frame, text="All Holdings", variable=self.mode_var,
                        value="all_holdings", command=self.on_mode_change).pack(side="left", padx=(Spacing.SECTION_MARGIN, 0))

        # Top/Bottom count
        ttk.Label(options_frame, text="Top/Bottom Count:").grid(row=1, column=0, sticky="w", padx=(0, Spacing.LABEL_GAP), pady=(Spacing.CONTROL_GAP, 0))
        self.count_var = tk.StringVar(value="5")
        self.count_combo = ttk.Combobox(options_frame, textvariable=self.count_var,
                                         values=["5", "10"], state="readonly", width=10)
        self.count_combo.grid(row=1, column=1, sticky="w", pady=(Spacing.CONTROL_GAP, 0))

        # Attribution overview workflow toggle
        ttk.Label(options_frame, text="Attribution Overview:").grid(
            row=2, column=0, sticky="w", padx=(0, Spacing.LABEL_GAP), pady=(Spacing.CONTROL_GAP, 0)
        )
        self.run_attribution_var = tk.BooleanVar(value=self.run_attribution_overview)
        ttk.Checkbutton(
            options_frame,
            text="Run Attribution Overview",
            variable=self.run_attribution_var
        ).grid(row=2, column=1, sticky="w", pady=(Spacing.CONTROL_GAP, 0))

        citation_frame = ttk.LabelFrame(options_frame, text="Citation Preferences", padding=Spacing.FRAME_PADDING)
        citation_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(Spacing.SECTION_MARGIN, 0))
        citation_frame.columnconfigure(0, weight=1)

        self.require_citations_var = tk.BooleanVar(value=self.require_citations)
        require_citations_check = ttk.Checkbutton(
            citation_frame,
            text="Require Citations",
            variable=self.require_citations_var
        )
        require_citations_check.grid(row=0, column=0, sticky="w")
        require_citations_icon = _make_info_icon(citation_frame)
        require_citations_icon.grid(row=0, column=1, sticky="w", padx=(Spacing.CONTROL_GAP_SMALL, 0))

        self.prioritize_sources_var = tk.BooleanVar(value=self.prioritize_sources)
        prioritize_sources_check = ttk.Checkbutton(
            citation_frame,
            text="Prioritize Sources",
            variable=self.prioritize_sources_var,
        )
        prioritize_sources_check.grid(row=1, column=0, sticky="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))
        prioritize_sources_icon = _make_info_icon(citation_frame)
        prioritize_sources_icon.grid(
            row=1, column=1, sticky="w", padx=(Spacing.CONTROL_GAP_SMALL, 0), pady=(Spacing.CONTROL_GAP_SMALL, 0)
        )

        ttk.Label(
            citation_frame,
            text="Preferred Sources (comma-separated domains):"
        ).grid(row=2, column=0, sticky="w", pady=(Spacing.CONTROL_GAP, 0))
        sources_label_icon = _make_info_icon(citation_frame)
        sources_label_icon.grid(row=2, column=1, sticky="w", padx=(Spacing.CONTROL_GAP_SMALL, 0), pady=(Spacing.CONTROL_GAP, 0))
        sources_entry = ttk.Entry(citation_frame, textvariable=self.sources_var)
        sources_entry.grid(
            row=3, column=0, sticky="ew", pady=(Spacing.CONTROL_GAP_SMALL, 0)
        )

        self.global_sources_error_var = tk.StringVar()
        ttk.Label(
            citation_frame,
            textvariable=self.global_sources_error_var,
            font=Typography.HELP_FONT,
            foreground=Typography.ERROR_COLOR
        ).grid(row=4, column=0, sticky="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))
        self.sources_var.trace_add("write", self._on_global_sources_change)
        self._refresh_global_source_errors()

        current_row += 1

        # ====== Configuration Section ======
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding=Spacing.FRAME_PADDING)
        config_frame.grid(row=current_row, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        config_frame.columnconfigure(0, weight=1)
        config_frame.columnconfigure(1, weight=1)

        # Contribution settings button with description
        prompts_container = ttk.Frame(config_frame)
        prompts_container.grid(row=0, column=0, sticky="w", padx=(0, Spacing.SECTION_MARGIN))
        contribution_button_row = ttk.Frame(prompts_container)
        contribution_button_row.pack(anchor="w")
        contribution_settings_btn = ttk.Button(
            contribution_button_row,
            text="Contribution Settings",
            command=self.open_prompt_editor
        )
        contribution_settings_btn.pack(side="left")
        contribution_settings_icon = _make_info_icon(contribution_button_row)
        contribution_settings_icon.pack(side="left", padx=(Spacing.CONTROL_GAP_SMALL, 0))

        # Attribution settings button with description
        attribution_container = ttk.Frame(config_frame)
        attribution_container.grid(row=0, column=1, sticky="w")
        attribution_button_row = ttk.Frame(attribution_container)
        attribution_button_row.pack(anchor="w")
        attribution_settings_btn = ttk.Button(
            attribution_button_row,
            text="Attribution Settings",
            command=self.open_attribution_workflow_editor
        )
        attribution_settings_btn.pack(side="left")
        attribution_settings_icon = _make_info_icon(attribution_button_row)
        attribution_settings_icon.pack(side="left", padx=(Spacing.CONTROL_GAP_SMALL, 0))

        current_row += 1

        # ====== Progress Section ======
        progress_frame = ttk.LabelFrame(main_frame, text="Progress", padding=Spacing.FRAME_PADDING)
        progress_frame.grid(row=current_row, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        progress_frame.columnconfigure(0, weight=1)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var,
                                             maximum=100, mode="determinate")
        self.progress_bar.grid(row=0, column=0, sticky="ew", ipady=2)  # Slightly thicker

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(progress_frame, textvariable=self.status_var).grid(row=1, column=0, sticky="w", pady=(Spacing.CONTROL_GAP, 0))

        current_row += 1

        # ====== Footer Actions ======
        footer_frame = ttk.Frame(main_frame)
        footer_frame.grid(row=current_row, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        footer_frame.columnconfigure(0, weight=1)

        left_actions = ttk.Frame(footer_frame)
        left_actions.grid(row=0, column=0, sticky="w")
        api_settings_btn = ttk.Button(left_actions, text="API Settings", command=self.open_settings)
        api_settings_btn.pack(side="left")
        api_settings_icon = _make_info_icon(left_actions)
        api_settings_icon.pack(side="left", padx=(Spacing.CONTROL_GAP_SMALL, 0))

        right_actions = ttk.Frame(footer_frame)
        right_actions.grid(row=0, column=1, sticky="e")
        ttk.Button(right_actions, text="Exit", command=self.on_exit_requested).pack(side="left", padx=(0, Spacing.BUTTON_PAD))
        self.run_btn = ttk.Button(right_actions, text="Generate Commentary", command=self.run_generation, style="Primary.TButton")
        self.run_btn.pack(side="left")

        self._tooltips.extend([
            ToolTip(require_citations_check, "Mark responses without citations as failed."),
            ToolTip(require_citations_icon, "Mark responses without citations as failed."),
            ToolTip(prioritize_sources_check, "When enabled, prompts ask the model to prioritize your preferred domains."),
            ToolTip(prioritize_sources_icon, "When enabled, prompts ask the model to prioritize your preferred domains."),
            ToolTip(
                sources_entry,
                "Comma-separated domains, e.g. reuters.com, bloomberg.com, cnbc.com. "
                "URLs are cleaned automatically."
            ),
            ToolTip(
                sources_label_icon,
                "Comma-separated domains, e.g. reuters.com, bloomberg.com, cnbc.com. "
                "URLs are cleaned automatically."
            ),
            ToolTip(contribution_settings_btn, "Edit contribution prompts plus model reasoning and verbosity."),
            ToolTip(contribution_settings_icon, "Edit contribution prompts plus model reasoning and verbosity."),
            ToolTip(attribution_settings_btn, "Edit attribution overview prompts plus model reasoning and verbosity."),
            ToolTip(attribution_settings_icon, "Edit attribution overview prompts plus model reasoning and verbosity."),
            ToolTip(api_settings_btn, "Configure your OpenAI API key."),
            ToolTip(api_settings_icon, "Configure your OpenAI API key."),
        ])
    
    def load_api_key(self):
        """Load API key from environment or keychain."""
        env_key = os.environ.get("OPENAI_API_KEY", "")
        if env_key:
            self.api_key = env_key
            self.api_key_source = "env"
            return

        keyring_key = keystore.get_api_key()
        if keyring_key:
            self.api_key = keyring_key
            self.api_key_source = "keyring"
        else:
            self.api_key = ""
            self.api_key_source = "none"

    def _migrate_api_key_from_config(self, config_key: str) -> None:
        """Migrate legacy config API key into keychain when possible."""
        if self.api_key.strip():
            return
        if not config_key.strip():
            return
        if self.keyring_available and keystore.set_api_key(config_key):
            self.api_key = config_key
            self.api_key_source = "keyring"
            return
        self.api_key = config_key
        self.api_key_source = "config"
    
    def add_input_files(self):
        """Add input Excel files."""
        files = filedialog.askopenfilenames(
            title="Select FactSet Excel Files",
            filetypes=[("Excel Files", "*.xlsx"), ("All Files", "*.*")]
        )
        for file in files:
            path = Path(file)
            if path not in self.input_files:
                self.input_files.append(path)
                self.input_listbox.insert(tk.END, path.name)
    
    def remove_input_files(self):
        """Remove selected input files."""
        selection = self.input_listbox.curselection()
        for index in reversed(selection):
            self.input_listbox.delete(index)
            del self.input_files[index]
    
    def clear_input_files(self):
        """Clear all input files."""
        self.input_listbox.delete(0, tk.END)
        self.input_files.clear()
    
    def select_output_folder(self):
        """Select output folder."""
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_folder = Path(folder)
            self.output_var.set(folder)
    
    def on_mode_change(self):
        """Handle holdings mode change."""
        if self.mode_var.get() == "all_holdings":
            self.count_combo.configure(state="disabled")
        else:
            self.count_combo.configure(state="readonly")

    def _on_global_sources_change(self, *_args):
        """Refresh inline domain validation when preferred sources change."""
        self._refresh_global_source_errors()

    def _refresh_global_source_errors(self) -> None:
        """Refresh the inline source validation error text."""
        if not hasattr(self, "global_sources_error_var"):
            return

        _, errors = validate_and_clean_domains(self.sources_var.get())
        if errors and self.sources_var.get().strip():
            self.global_sources_error_var.set("Errors: " + "; ".join(errors))
        else:
            self.global_sources_error_var.set("")

    def _sync_and_validate_global_preferences(self) -> bool:
        """Sync global UI preferences into app state and validate sources."""
        if hasattr(self, "require_citations_var"):
            self.require_citations = self.require_citations_var.get()
        if hasattr(self, "prioritize_sources_var"):
            self.prioritize_sources = self.prioritize_sources_var.get()

        valid_domains, errors = validate_and_clean_domains(self.sources_var.get())
        if errors:
            self._refresh_global_source_errors()
            messagebox.showerror("Error", "Please fix invalid preferred source domains before running.")
            return False

        self.sources_var.set(", ".join(valid_domains))
        self._refresh_global_source_errors()
        return True
    
    def open_prompt_editor(self):
        """Open the contribution settings modal window."""
        modal = PromptEditorModal(
            self.root,
            self.prompt_text_content,
            self.developer_prompt_content,
            self.thinking_level,
            self.model_id,
            AVAILABLE_MODELS,
            self.text_verbosity,
        )
        self.root.wait_window(modal.window)
        
        # Apply changes if user clicked Save
        if modal.result:
            self.prompt_text_content = modal.result["prompt_template"]
            self.developer_prompt_content = modal.result["developer_prompt"]
            self.thinking_level = modal.result["thinking_level"]
            self.model_id = modal.result["model"]
            self.text_verbosity = modal.result["text_verbosity"]

    def open_attribution_workflow_editor(self):
        """Open the attribution settings modal window."""
        modal = AttributionWorkflowModal(
            self.root,
            self.attribution_prompt_text_content,
            self.attribution_developer_prompt_content,
            self.attribution_thinking_level,
            self.attribution_model_id,
            AVAILABLE_MODELS,
            self.attribution_text_verbosity,
        )
        self.root.wait_window(modal.window)

        if modal.result:
            self.attribution_prompt_text_content = modal.result["prompt_template"]
            self.attribution_developer_prompt_content = modal.result["developer_prompt"]
            self.attribution_thinking_level = modal.result["thinking_level"]
            self.attribution_model_id = modal.result["model"]
            self.attribution_text_verbosity = modal.result["text_verbosity"]
    
    def open_settings(self):
        """Open the API settings modal window."""
        modal = SettingsModal(self.root, self.api_key, self.api_key_source, self.keyring_available)
        self.root.wait_window(modal.window)
        
        # Apply changes if user clicked Save
        if modal.result:
            env_key = os.environ.get("OPENAI_API_KEY", "")
            env_present = bool(env_key)
            new_key = modal.result["api_key"].strip()
            if not new_key:
                if self.keyring_available:
                    keystore.delete_api_key()
                if env_present:
                    self.api_key = env_key
                    self.api_key_source = "env"
                else:
                    self.api_key = ""
                    self.api_key_source = "none"
                return

            saved = False
            if self.keyring_available:
                saved = keystore.set_api_key(new_key)

            # Determine final state and show a single consolidated message
            if env_present:
                # Environment variable takes priority regardless of keychain result
                self.api_key = env_key
                self.api_key_source = "env"
                if saved:
                    messagebox.showinfo(
                        "Info",
                        "OPENAI_API_KEY is set and will be used by default. "
                        "The key was also saved to keychain for when the environment variable is unset."
                    )
                else:
                    messagebox.showinfo(
                        "Info",
                        "OPENAI_API_KEY is set and will be used. "
                        "Note: Could not save to keychain, but this won't affect operation while the environment variable is set."
                    )
            elif saved:
                self.api_key = new_key
                self.api_key_source = "keyring"
            else:
                self.api_key = new_key
                self.api_key_source = "session"
                messagebox.showwarning(
                    "Warning",
                    "Could not save API key to system keychain. "
                    "It will be used for this session only. "
                    "Set OPENAI_API_KEY or enable keychain access to persist."
                )
    
    def update_progress(self, ticker: str, completed: int, total: int):
        """Enqueue progress updates from worker threads."""
        self._progress_queue.put((ticker, completed, total))

    def _enqueue_ui_callback(self, callback: Callable[[], None]) -> None:
        """Queue a UI callback to run on the Tk main thread."""
        self._ui_callback_queue.put(callback)

    def _schedule_progress_queue_drain(self) -> None:
        """Drain queued progress/UI updates on the Tk main thread."""
        latest: Optional[tuple[str, int, int]] = None
        while True:
            try:
                latest = self._progress_queue.get_nowait()
            except queue.Empty:
                break

        if latest:
            ticker, completed, total = latest
            progress = (completed / total) * 100 if total > 0 else 0
            self.progress_var.set(progress)
            self.status_var.set(f"Processing: {ticker} ({completed}/{total})")

        while True:
            try:
                callback = self._ui_callback_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception as callback_error:
                print(f"UI callback error: {callback_error}")

        self.root.after(100, self._schedule_progress_queue_drain)
    
    def validate_inputs(self) -> bool:
        """Validate user inputs before running."""
        if not self._sync_and_validate_global_preferences():
            return False

        if not self.api_key.strip():
            messagebox.showerror("Error", "Please configure your OpenAI API key in API Settings.")
            return False
        
        if not self.input_files:
            messagebox.showerror("Error", "Please select at least one input file.")
            return False
        
        if not self.output_folder:
            messagebox.showerror("Error", "Please select an output folder.")
            return False
        
        return True
    
    def run_generation(self):
        """Start the commentary generation process."""
        if self.is_running:
            messagebox.showwarning("Warning", "Generation is already in progress.")
            return
        
        if not self.validate_inputs():
            return

        self.run_attribution_overview = self.run_attribution_var.get()
        
        self.is_running = True
        self._cancel_requested = False
        self._exit_after_cancel = False
        self.run_btn.configure(state="disabled")
        self.progress_var.set(0)
        self.status_var.set("Starting...")
        
        # Run in separate thread to keep UI responsive
        thread = threading.Thread(target=self._run_generation_thread)
        thread.daemon = True
        thread.start()
    
    def _run_generation_thread(self):
        """Run generation in a separate thread."""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._generation_loop = loop
            self._cancel_event = asyncio.Event()
            if self._cancel_requested:
                self._cancel_event.set()
            
            result = loop.run_until_complete(self._async_generate())
            
            # Update UI on main thread
            self._enqueue_ui_callback(lambda: self._on_generation_complete(result))
            
        except asyncio.CancelledError:
            self._enqueue_ui_callback(self._on_generation_cancelled)
        except Exception as e:
            self._enqueue_ui_callback(lambda: self._on_generation_error(str(e)))
        finally:
            self.is_running = False
            self._enqueue_ui_callback(lambda: self.run_btn.configure(state="normal"))
            self._generation_loop = None
            self._cancel_event = None
    
    async def _async_generate(self) -> dict:
        """Async generation logic."""
        start_time = datetime.now()
        errors: dict[str, list[str]] = {}
        attribution_overview_results: Optional[dict[str, AttributionOverviewResult]] = None
        
        # Update status
        self._enqueue_ui_callback(lambda: self.status_var.set("Parsing Excel files..."))
        
        # Parse input files
        portfolios = parse_multiple_files(self.input_files)

        if self.run_attribution_overview:
            # Record parser-level attribution warnings in the run log only when the
            # attribution workflow is enabled for this run.
            for portfolio in portfolios:
                for warning in portfolio.attribution_warnings:
                    key = f"{portfolio.portcode}|ATTRIBUTION_PARSER"
                    errors.setdefault(key, []).append(warning)
        
        # Determine selection mode
        mode = SelectionMode.TOP_BOTTOM if self.mode_var.get() == "top_bottom" else SelectionMode.ALL_HOLDINGS
        n = int(self.count_var.get())
        
        # Process portfolios (selection/ranking)
        selections = process_portfolios(portfolios, mode, n)
        
        # Set up prompt manager
        sources = [s.strip() for s in self.sources_var.get().split(",") if s.strip()]
        prompt_config = PromptConfig(
            template=self.prompt_text_content,
            preferred_sources=sources,
            thinking_level=self.thinking_level,
            prioritize_sources=self.prioritize_sources
        )
        prompt_manager = PromptManager(prompt_config)
        
        # Build all API requests
        all_requests = []
        
        for selection in selections:
            for ranked_sec in selection.ranked_securities:
                prompt = prompt_manager.build_prompt(
                    ticker=ranked_sec.ticker,
                    security_name=ranked_sec.security_name,
                    period=selection.period
                )
                all_requests.append({
                    "ticker": ranked_sec.ticker,
                    "security_name": ranked_sec.security_name,
                    "prompt": prompt,
                    "portcode": selection.portcode
                })

        # Build attribution requests up front so progress can track all requests end-to-end.
        attribution_requests: list[dict[str, str]] = []
        if self.run_attribution_overview:
            attribution_overview_results = {}

            attribution_prompt_config = AttributionPromptConfig(
                template=self.attribution_prompt_text_content,
                preferred_sources=sources,
                thinking_level=self.attribution_thinking_level,
                prioritize_sources=self.prioritize_sources,
            )
            attribution_prompt_manager = AttributionPromptManager(attribution_prompt_config)

            for portfolio in portfolios:
                has_sector_data = (
                    portfolio.sector_attribution is not None
                    and portfolio.sector_attribution.has_data()
                )
                has_country_data = (
                    portfolio.country_attribution is not None
                    and portfolio.country_attribution.has_data()
                )

                if not has_sector_data and not has_country_data:
                    warning_message = (
                        "WARNING: Attribution overview skipped because no sector "
                        "or country attribution data was found."
                    )
                    attribution_overview_results[portfolio.portcode] = AttributionOverviewResult(
                        portcode=portfolio.portcode,
                        output="",
                        citations=[],
                        success=False,
                        error_message=warning_message,
                    )
                    errors.setdefault(f"{portfolio.portcode}|ATTRIBUTION_OVERVIEW", []).append(
                        warning_message
                    )
                    continue

                sector_attrib_markdown = format_attribution_table_markdown(
                    portfolio.sector_attribution,
                    empty_message="No sector attribution data available.",
                )
                country_attrib_markdown = format_attribution_table_markdown(
                    portfolio.country_attribution,
                    empty_message="No country attribution data available.",
                )
                attribution_prompt = attribution_prompt_manager.build_prompt(
                    portcode=portfolio.portcode,
                    period=portfolio.period,
                    sector_attrib=sector_attrib_markdown,
                    country_attrib=country_attrib_markdown,
                )
                attribution_requests.append(
                    {
                        "portcode": portfolio.portcode,
                        "prompt": attribution_prompt,
                    }
                )

        commentary_total = len(all_requests)
        attribution_total = len(attribution_requests)
        overall_total = commentary_total + attribution_total

        # Set up OpenAI client for security-level commentary with run-level progress totals.
        commentary_progress_callback = _make_overall_progress_callback(
            update_progress_fn=self.update_progress,
            offset=0,
            overall_total=overall_total,
        )
        commentary_client = OpenAIClient(
            api_key=self.api_key.strip(),
            progress_callback=commentary_progress_callback,
            developer_prompt=self.developer_prompt_content,
            model=self.model_id
        )
        
        # Update status
        self._enqueue_ui_callback(
            lambda: self.status_var.set(f"Generating commentary for {commentary_total} securities...")
        )
        
        # Generate commentary (batch)
        results = await commentary_client.generate_commentary_batch(
            all_requests,
            use_web_search=True,
            thinking_level=self.thinking_level,
            text_verbosity=self.text_verbosity,
            require_citations=self.require_citations,
            cancel_event=self._cancel_event
        )

        if self._cancel_event and self._cancel_event.is_set():
            raise asyncio.CancelledError()
        
        # Organize results by originating request order to avoid ticker collisions
        commentary_results, commentary_errors = _organize_commentary_results_by_request(
            all_requests,
            results
        )
        for key, error_list in commentary_errors.items():
            errors.setdefault(key, []).extend(error_list)

        if self.run_attribution_overview:
            self._enqueue_ui_callback(lambda: self.status_var.set("Generating attribution overviews..."))
            if attribution_requests:
                attribution_progress_callback = _make_overall_progress_callback(
                    update_progress_fn=self.update_progress,
                    offset=commentary_total,
                    overall_total=overall_total,
                )
                attribution_client = OpenAIClient(
                    api_key=self.api_key.strip(),
                    progress_callback=attribution_progress_callback,
                    developer_prompt=self.attribution_developer_prompt_content,
                    model=self.attribution_model_id,
                )
                attribution_results = await attribution_client.generate_attribution_overview_batch(
                    attribution_requests,
                    use_web_search=True,
                    thinking_level=self.attribution_thinking_level,
                    text_verbosity=self.attribution_text_verbosity,
                    require_citations=self.require_citations,
                    cancel_event=self._cancel_event,
                )

                if self._cancel_event and self._cancel_event.is_set():
                    raise asyncio.CancelledError()

                for overview_result in attribution_results:
                    attribution_overview_results[overview_result.portcode] = overview_result
                    if not overview_result.success:
                        errors.setdefault(
                            f"{overview_result.portcode}|ATTRIBUTION_OVERVIEW",
                            []
                        ).append(overview_result.error_message)
        
        # Update status
        self._enqueue_ui_callback(lambda: self.status_var.set("Creating output workbook..."))
        
        # Create output workbook (output_folder validated in validate_inputs)
        assert self.output_folder is not None
        output_path = create_output_workbook(
            selections,
            commentary_results,
            self.output_folder,
            attribution_overview_results=attribution_overview_results
        )
        
        # Create log file
        end_time = datetime.now()
        log_path = create_log_file(
            self.output_folder,
            self.input_files,
            output_path,
            errors,
            start_time,
            end_time
        )
        
        return {
            "output_path": output_path,
            "log_path": log_path,
            "total_securities": commentary_total,
            "total_commentary_requests": commentary_total,
            "total_attribution_requests": attribution_total,
            "total_requests": overall_total,
            "errors": len(errors),
            "duration": (end_time - start_time).total_seconds()
        }

    def request_cancel(self) -> None:
        """Request cancellation of an in-progress generation."""
        self._cancel_requested = True
        self.status_var.set("Cancellation requested... waiting for in-flight requests to stop")
        self.run_btn.configure(state="disabled")
        if self._generation_loop and self._cancel_event:
            self._generation_loop.call_soon_threadsafe(self._cancel_event.set)

    def on_exit_requested(self) -> None:
        """Handle exit requests, warning if generation is in progress."""
        if not self.is_running:
            self.root.destroy()
            return

        confirm = messagebox.askyesno(
            "Generation in Progress",
            "Generation is running. Cancel now and exit? In-flight requests may still complete server-side."
        )
        if confirm:
            self._exit_after_cancel = True
            self.request_cancel()
    
    def _on_generation_complete(self, result: dict):
        """Handle successful generation completion."""
        self.progress_var.set(100)
        self.status_var.set("Complete!")

        commentary_processed = int(result.get("total_commentary_requests", result.get("total_securities", 0)))
        attribution_processed = int(result.get("total_attribution_requests", 0))
        total_processed = int(result.get("total_requests", commentary_processed + attribution_processed))

        try:
            # Save configuration after successful generation
            self.save_config()

            message = (
                f"Commentary generation complete!\n\n"
                f"Commentary requests processed: {commentary_processed}\n"
                f"Attribution requests processed: {attribution_processed}\n"
                f"Total requests processed: {total_processed}\n"
                f"Errors: {result['errors']}\n"
                f"Duration: {result['duration']:.1f} seconds\n\n"
                f"Output file:\n{result['output_path']}\n\n"
                f"Log file:\n{result['log_path']}"
            )
            messagebox.showinfo("Success", message, parent=self.root)
        except Exception as e:
            messagebox.showerror(
                "Error",
                f"Generation finished but failed to display completion details:\n\n{e}",
                parent=self.root,
            )
        finally:
            self.status_var.set("Ready")
            self.progress_var.set(0)

    def _on_generation_cancelled(self) -> None:
        """Handle generation cancellation."""
        self.progress_var.set(0)
        self.status_var.set("Cancelled")
        if self._exit_after_cancel:
            should_exit = messagebox.askyesno(
                "Cancellation Complete",
                "Cancellation complete. In-flight requests may still finish on the server.\n\nExit the application now?"
            )
            if should_exit:
                self.root.destroy()
                return
            self.status_var.set("Ready")
        else:
            messagebox.showinfo(
                "Cancelled",
                "Generation cancelled. In-flight requests may still finish on the server."
            )
            self.status_var.set("Ready")
    
    def _on_generation_error(self, error: str):
        """Handle generation error."""
        self.progress_var.set(0)
        self.status_var.set("Error occurred")
        messagebox.showerror("Error", f"Generation failed:\n\n{error}")


def main():
    """Main entry point for the GUI application."""
    # Load .env file if python-dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    root = tk.Tk()
    app = CommentaryGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
