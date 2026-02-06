"""
Commentary Generator GUI

Simple tkinter-based GUI for non-technical users.
"""

import asyncio
import json
import os
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.excel_parser import parse_multiple_files, PortfolioData
from src.selection_engine import (
    SelectionMode, process_portfolios, SelectionResult
)
from src.prompt_manager import PromptManager, PromptConfig, get_default_preferred_sources, DEFAULT_PROMPT_TEMPLATE, SOURCE_INSTRUCTIONS_DEFAULT
from src.openai_client import OpenAIClient, CommentaryResult, RateLimitConfig, DEFAULT_DEVELOPER_PROMPT
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


class SettingsModal:
    """Modal window for application settings including API key."""

    def __init__(self, parent: tk.Tk, api_key: str, api_key_source: str, keyring_available: bool, require_citations: bool = True):
        """
        Initialize the settings modal window.

        Args:
            parent: Parent window
            api_key: Current OpenAI API key
            api_key_source: Where the API key was loaded from ("env", "keyring", "config", "session", "none")
            keyring_available: Whether system keychain storage is available
            require_citations: Whether citations are required in responses
        """
        self.result = None  # Will be set to dict if user saves

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
        help_text = ttk.Label(
            api_frame,
            text="\n".join(help_lines),
            font=Typography.HELP_FONT,
            foreground=Typography.HELP_COLOR
        )
        help_text.grid(row=1, column=0, sticky="w", pady=(Spacing.CONTROL_GAP, 0))

        source_note = ""
        if api_key_source == "env":
            source_note = "OPENAI_API_KEY is set and will be used by default."
        elif api_key_source == "keyring":
            source_note = "Using key stored in your system keychain."
        elif api_key_source == "config":
            source_note = "Using key from legacy config; it will be migrated."
        elif api_key_source == "session":
            source_note = "Key will be used for this session only."
        if source_note:
            ttk.Label(
                api_frame,
                text=source_note,
                font=Typography.HELP_FONT,
                foreground=Typography.HELP_COLOR
            ).grid(row=2, column=0, sticky="w", pady=(Spacing.CONTROL_GAP, 0))

        # Citation Settings section
        citation_frame = ttk.LabelFrame(main_frame, text="Citation Settings", padding=Spacing.FRAME_PADDING)
        citation_frame.grid(row=1, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        citation_frame.columnconfigure(0, weight=1)

        self.require_citations_var = tk.BooleanVar(value=require_citations)
        ttk.Checkbutton(
            citation_frame,
            text="Require Citations",
            variable=self.require_citations_var
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            citation_frame,
            text="When enabled, commentary without citations will be marked as failed.",
            font=Typography.HELP_FONT,
            foreground=Typography.HELP_COLOR
        ).grid(row=1, column=0, sticky="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))

        # Button frame - right aligned at bottom
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=2, column=0, sticky="e", pady=(Spacing.SECTION_MARGIN, 0))

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
            "api_key": self.api_key_var.get(),
            "require_citations": self.require_citations_var.get()
        }
        self.window.destroy()


class PromptEditorModal:
    """Modal window for editing prompt template, system prompt, thinking level, and preferred sources."""

    def __init__(
        self,
        parent: tk.Tk,
        current_prompt: str,
        current_developer_prompt: str,
        current_thinking_level: str,
        current_model: str,
        available_models: list[str],
        current_sources: str,
        current_text_verbosity: str,
        prioritize_sources: bool = True
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
            current_sources: Current preferred sources (comma-separated domains)
            current_text_verbosity: Current text verbosity ("low", "medium", "high")
            prioritize_sources: Whether to inject source prioritization into prompts
        """
        self.result = None  # Will be set to dict if user saves
        self._prioritize_sources = prioritize_sources

        self.window = tk.Toplevel(parent)
        self.window.title("Prompts & Sources")
        self.window.transient(parent)
        self.window.grab_set()

        # Center on parent
        self._center_on_parent(parent, Dimensions.PROMPT_EDITOR_WIDTH, Dimensions.PROMPT_EDITOR_HEIGHT)

        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        main_frame = ttk.Frame(self.window, padding=Spacing.FRAME_PADDING)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)  # Prompts section expands

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

        # Help text for thinking levels
        self.reasoning_help_label = ttk.Label(
            level_frame,
            text="",
            font=Typography.HELP_FONT,
            foreground=Typography.HELP_COLOR
        )
        self.reasoning_help_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(Spacing.CONTROL_GAP, 0))
        self._update_reasoning_levels()

        verbosity_help = ttk.Label(
            level_frame,
            text="Verbosity controls response length and detail.",
            font=Typography.HELP_FONT,
            foreground=Typography.HELP_COLOR
        )
        verbosity_help.grid(row=4, column=0, columnspan=2, sticky="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))

        # Preferred sources section
        sources_frame = ttk.LabelFrame(main_frame, text="Preferred Sources for Web Search", padding=Spacing.FRAME_PADDING)
        sources_frame.grid(row=1, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        sources_frame.columnconfigure(0, weight=1)

        # Prioritize sources checkbox
        self.prioritize_sources_var = tk.BooleanVar(value=self._prioritize_sources)
        ttk.Checkbutton(
            sources_frame,
            text="Prioritize Sources",
            variable=self.prioritize_sources_var,
            command=self._refresh_source_preview
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            sources_frame,
            text="When enabled, the model will be instructed to prioritize the listed sources.",
            font=Typography.HELP_FONT,
            foreground=Typography.HELP_COLOR
        ).grid(row=1, column=0, sticky="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))

        ttk.Label(sources_frame, text="Domain names (comma-separated):").grid(row=2, column=0, sticky="w", pady=(Spacing.CONTROL_GAP, 0))
        self.sources_var = tk.StringVar(value=current_sources)
        sources_entry = ttk.Entry(sources_frame, textvariable=self.sources_var)
        sources_entry.grid(row=3, column=0, sticky="ew", pady=(Spacing.CONTROL_GAP_SMALL, 0))

        # Help text for sources
        sources_help = ttk.Label(
            sources_frame,
            text="Examples: reuters.com, bloomberg.com, cnbc.com\nURLs are cleaned automatically (removes http://, www., etc.)",
            font=Typography.HELP_FONT,
            foreground=Typography.HELP_COLOR
        )
        sources_help.grid(row=4, column=0, sticky="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))

        # Error message label for sources validation
        self.sources_error_var = tk.StringVar()
        self.sources_error_label = ttk.Label(
            sources_frame,
            textvariable=self.sources_error_var,
            font=Typography.HELP_FONT,
            foreground=Typography.ERROR_COLOR
        )
        self.sources_error_label.grid(row=5, column=0, sticky="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))

        # Source instructions preview
        preview_frame = ttk.LabelFrame(main_frame, text="Source Instructions Preview", padding=Spacing.FRAME_PADDING)
        preview_frame.grid(row=2, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        preview_frame.columnconfigure(0, weight=1)

        self.source_preview_text = tk.Text(preview_frame, height=3, wrap=tk.WORD, state="disabled")
        self.source_preview_text.grid(row=0, column=0, sticky="ew")

        # Prompts tabs section
        prompt_frame = ttk.LabelFrame(main_frame, text="Prompts", padding=Spacing.FRAME_PADDING)
        prompt_frame.grid(row=3, column=0, sticky="nsew", pady=(0, Spacing.SECTION_MARGIN))
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

        # Variables helper for user prompt
        help_label = ttk.Label(
            user_prompt_tab,
            text="Variables: {ticker}, {security_name}, {period}, {source_instructions}",
            font=Typography.HELP_FONT,
            foreground=Typography.HELP_COLOR
        )
        help_label.grid(row=1, column=0, sticky="w", padx=Spacing.CONTROL_GAP, pady=(Spacing.CONTROL_GAP_SMALL, Spacing.CONTROL_GAP))

        # Tab 2: System/Developer Prompt
        dev_prompt_tab = ttk.Frame(self.notebook)
        self.notebook.add(dev_prompt_tab, text="System Prompt (Instructions)")
        dev_prompt_tab.columnconfigure(0, weight=1)
        dev_prompt_tab.rowconfigure(0, weight=1)

        self.dev_prompt_text = scrolledtext.ScrolledText(dev_prompt_tab, height=Dimensions.PROMPT_TEXT_HEIGHT, wrap=tk.WORD)
        self.dev_prompt_text.grid(row=0, column=0, sticky="nsew", padx=Spacing.CONTROL_GAP, pady=Spacing.CONTROL_GAP)
        self.dev_prompt_text.insert("1.0", current_developer_prompt)

        # Help text for system prompt
        dev_help_label = ttk.Label(
            dev_prompt_tab,
            text="System prompt controls the LLM's behavior and tone for all requests.",
            font=Typography.HELP_FONT,
            foreground=Typography.HELP_COLOR
        )
        dev_help_label.grid(row=1, column=0, sticky="w", padx=Spacing.CONTROL_GAP, pady=(Spacing.CONTROL_GAP_SMALL, Spacing.CONTROL_GAP))

        # Button frame - Reset buttons left, Cancel/Save right
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=4, column=0, sticky="ew")
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

        self.sources_var.trace_add("write", self._on_sources_change)
        self._refresh_source_preview()
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

        self.reasoning_help_label.configure(text=self._build_reasoning_help_text(levels))
    
    def reset_user_prompt(self):
        """Reset user prompt to default template."""
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", DEFAULT_PROMPT_TEMPLATE)
    
    def reset_system_prompt(self):
        """Reset system/developer prompt to default."""
        self.dev_prompt_text.delete("1.0", tk.END)
        self.dev_prompt_text.insert("1.0", DEFAULT_DEVELOPER_PROMPT)

    def _on_sources_change(self, *_args):
        self._refresh_source_preview()

    def _refresh_source_preview(self):
        valid_domains, errors = validate_and_clean_domains(self.sources_var.get())
        if errors and self.sources_var.get().strip():
            self.sources_error_var.set("Errors: " + "; ".join(errors))
        else:
            self.sources_error_var.set("")

        # Show preview based on prioritize_sources setting
        if self.prioritize_sources_var.get() and valid_domains:
            preview_config = PromptConfig(preferred_sources=valid_domains)
            preview_manager = PromptManager(preview_config)
            preview_text = preview_manager.get_source_instructions()
        elif self.prioritize_sources_var.get():
            preview_text = SOURCE_INSTRUCTIONS_DEFAULT
        else:
            preview_text = "(Source prioritization disabled - no instructions will be added to prompt)"

        self.source_preview_text.configure(state="normal")
        self.source_preview_text.delete("1.0", tk.END)
        self.source_preview_text.insert("1.0", preview_text)
        self.source_preview_text.configure(state="disabled")
    
    def on_cancel(self):
        """Cancel button clicked - discard changes."""
        self.result = None
        self.window.destroy()
    
    def on_save(self):
        """Save button clicked - apply changes."""
        # Validate and clean sources
        valid_domains, errors = validate_and_clean_domains(self.sources_var.get())
        
        if errors:
            self.sources_error_var.set("Errors: " + "; ".join(errors))
            return
        
        self.result = {
            "prompt_template": self.prompt_text.get("1.0", tk.END).strip(),
            "developer_prompt": self.dev_prompt_text.get("1.0", tk.END).strip(),
            "thinking_level": self.thinking_var.get(),
            "model": self.model_var.get(),
            "text_verbosity": self.text_verbosity_var.get(),
            "preferred_sources": ", ".join(valid_domains),  # Return cleaned domains
            "prioritize_sources": self.prioritize_sources_var.get()
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

        # Prompt template and system prompt variables
        self.prompt_text_content: str = DEFAULT_PROMPT_TEMPLATE
        self.developer_prompt_content: str = DEFAULT_DEVELOPER_PROMPT
        
        # Citation and source settings
        self.require_citations: bool = True  # Default: require citations
        self.prioritize_sources: bool = True  # Default: inject source instructions into prompt

        # Configure grid weights for resizing
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self._configure_styles()
        self.setup_ui()
        self.load_api_key()
        self.load_config()

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
            
            # Load preferred sources
            if "preferred_sources" in config:
                self.sources_var.set(", ".join(config["preferred_sources"]))
            
            # Load require_citations setting
            if "require_citations" in config:
                self.require_citations = config["require_citations"]
            
            # Load prioritize_sources setting
            if "prioritize_sources" in config:
                self.prioritize_sources = config["prioritize_sources"]
            
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

        current_row += 1

        # ====== Configuration Section (merged API Settings + Prompts & Sources) ======
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding=Spacing.FRAME_PADDING)
        config_frame.grid(row=current_row, column=0, sticky="ew", pady=(0, Spacing.SECTION_MARGIN))
        config_frame.columnconfigure(0, weight=1)
        config_frame.columnconfigure(1, weight=1)

        # API Settings button with description
        api_container = ttk.Frame(config_frame)
        api_container.grid(row=0, column=0, sticky="w", padx=(0, Spacing.SECTION_MARGIN))
        ttk.Button(api_container, text="API Settings", command=self.open_settings).pack(anchor="w")
        ttk.Label(api_container, text="Configure your OpenAI API key",
                  font=Typography.HELP_FONT, foreground=Typography.HELP_COLOR).pack(anchor="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))

        # Prompts & Sources button with description
        prompts_container = ttk.Frame(config_frame)
        prompts_container.grid(row=0, column=1, sticky="w")
        ttk.Button(prompts_container, text="Prompts & Sources", command=self.open_prompt_editor).pack(anchor="w")
        ttk.Label(prompts_container, text="Edit prompts, sources, reasoning, and verbosity",
                  font=Typography.HELP_FONT, foreground=Typography.HELP_COLOR).pack(anchor="w", pady=(Spacing.CONTROL_GAP_SMALL, 0))

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

        # ====== Action Buttons (right-aligned with primary emphasis) ======
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=current_row, column=0, sticky="e", pady=(0, Spacing.SECTION_MARGIN))

        ttk.Button(btn_frame, text="Exit", command=self.on_exit_requested).pack(side="left", padx=(0, Spacing.BUTTON_PAD))
        self.run_btn = ttk.Button(btn_frame, text="Generate Commentary", command=self.run_generation, style="Primary.TButton")
        self.run_btn.pack(side="left")
    
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
    
    def open_prompt_editor(self):
        """Open the prompt editor modal window."""
        modal = PromptEditorModal(
            self.root,
            self.prompt_text_content,
            self.developer_prompt_content,
            self.thinking_level,
            self.model_id,
            AVAILABLE_MODELS,
            self.sources_var.get(),
            self.text_verbosity,
            self.prioritize_sources
        )
        self.root.wait_window(modal.window)
        
        # Apply changes if user clicked Save
        if modal.result:
            self.prompt_text_content = modal.result["prompt_template"]
            self.developer_prompt_content = modal.result["developer_prompt"]
            self.thinking_level = modal.result["thinking_level"]
            self.model_id = modal.result["model"]
            self.text_verbosity = modal.result["text_verbosity"]
            self.sources_var.set(modal.result["preferred_sources"])
            self.prioritize_sources = modal.result["prioritize_sources"]
    
    def open_settings(self):
        """Open the settings modal window."""
        modal = SettingsModal(self.root, self.api_key, self.api_key_source, self.keyring_available, self.require_citations)
        self.root.wait_window(modal.window)
        
        # Apply changes if user clicked Save
        if modal.result:
            # Handle require_citations setting
            self.require_citations = modal.result.get("require_citations", True)
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
        """Update progress bar (called from async thread)."""
        def update():
            progress = (completed / total) * 100 if total > 0 else 0
            self.progress_var.set(progress)
            self.status_var.set(f"Processing: {ticker} ({completed}/{total})")
        self.root.after(0, update)
    
    def validate_inputs(self) -> bool:
        """Validate user inputs before running."""
        if not self.api_key.strip():
            messagebox.showerror("Error", "Please configure your OpenAI API key in Settings.")
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
            self.root.after(0, lambda: self._on_generation_complete(result))
            
        except asyncio.CancelledError:
            self.root.after(0, self._on_generation_cancelled)
        except Exception as e:
            self.root.after(0, lambda: self._on_generation_error(str(e)))
        finally:
            self.is_running = False
            self.root.after(0, lambda: self.run_btn.configure(state="normal"))
            self._generation_loop = None
            self._cancel_event = None
    
    async def _async_generate(self) -> dict:
        """Async generation logic."""
        start_time = datetime.now()
        errors: dict[str, list[str]] = {}
        
        # Update status
        self.root.after(0, lambda: self.status_var.set("Parsing Excel files..."))
        
        # Parse input files
        portfolios = parse_multiple_files(self.input_files)
        
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
        
        # Set up OpenAI client
        client = OpenAIClient(
            api_key=self.api_key.strip(),
            progress_callback=self.update_progress,
            developer_prompt=self.developer_prompt_content,
            model=self.model_id
        )
        
        # Build all API requests
        all_requests = []
        request_mapping = {}  # Map ticker to (portcode, period)
        
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
                request_mapping[ranked_sec.ticker] = selection.portcode
        
        # Update status
        total = len(all_requests)
        self.root.after(0, lambda: self.status_var.set(f"Generating commentary for {total} securities..."))
        
        # Generate commentary (batch)
        results = await client.generate_commentary_batch(
            all_requests,
            use_web_search=True,
            thinking_level=self.thinking_level,
            text_verbosity=self.text_verbosity,
            require_citations=self.require_citations,
            cancel_event=self._cancel_event
        )

        if self._cancel_event and self._cancel_event.is_set():
            raise asyncio.CancelledError()
        
        # Organize results by portfolio
        commentary_results: dict[str, dict[str, CommentaryResult]] = {}
        for result in results:
            portcode = request_mapping.get(result.ticker, "unknown")
            if portcode not in commentary_results:
                commentary_results[portcode] = {}
            commentary_results[portcode][result.ticker] = result
            
            # Track errors
            if not result.success:
                key = f"{portcode}|{result.ticker}"
                if key not in errors:
                    errors[key] = []
                errors[key].append(result.error_message)
        
        # Update status
        self.root.after(0, lambda: self.status_var.set("Creating output workbook..."))
        
        # Create output workbook (output_folder validated in validate_inputs)
        assert self.output_folder is not None
        output_path = create_output_workbook(
            selections,
            commentary_results,
            self.output_folder
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
            "total_securities": total,
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
        # Save configuration after successful generation
        self.save_config()
        
        self.progress_var.set(100)
        self.status_var.set("Complete!")
        
        message = (
            f"Commentary generation complete!\n\n"
            f"Securities processed: {result['total_securities']}\n"
            f"Errors: {result['errors']}\n"
            f"Duration: {result['duration']:.1f} seconds\n\n"
            f"Output file:\n{result['output_path']}\n\n"
            f"Log file:\n{result['log_path']}"
        )
        messagebox.showinfo("Success", message)
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
