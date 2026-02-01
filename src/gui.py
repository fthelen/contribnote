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
from src.prompt_manager import PromptManager, PromptConfig, get_default_preferred_sources, DEFAULT_PROMPT_TEMPLATE
from src.openai_client import OpenAIClient, CommentaryResult, RateLimitConfig, DEFAULT_DEVELOPER_PROMPT
from src.output_generator import create_output_workbook, create_log_file


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
    
    def __init__(self, parent: tk.Tk, api_key: str):
        """
        Initialize the settings modal window.
        
        Args:
            parent: Parent window
            api_key: Current OpenAI API key
        """
        self.result = None  # Will be set to dict if user saves
        
        self.window = tk.Toplevel(parent)
        self.window.title("Settings")
        self.window.geometry("500x200")
        self.window.transient(parent)
        self.window.grab_set()
        
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(1, weight=1)
        
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        
        # API Key section
        ttk.Label(main_frame, text="OpenAI API Key:").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.api_key_var = tk.StringVar(value=api_key)
        self.api_key_entry = ttk.Entry(main_frame, textvariable=self.api_key_var, show="*")
        self.api_key_entry.grid(row=0, column=1, sticky="ew", pady=(0, 5))
        
        self.show_key_var = tk.BooleanVar()
        ttk.Checkbutton(main_frame, text="Show", variable=self.show_key_var, 
                        command=self.toggle_key_visibility).grid(row=0, column=2, padx=(10, 0))
        
        # Help text for API key
        help_text = ttk.Label(
            main_frame,
            text="Your API key is stored locally and never shared.",
            font=("TkDefaultFont", 8),
            foreground="gray"
        )
        help_text.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))
        
        # Button frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=2, column=0, columnspan=3, sticky="e", pady=(10, 0))
        
        ttk.Button(btn_frame, text="Cancel", command=self.on_cancel).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Save", command=self.on_save).pack(side="left", padx=5)
        
        self.window.focus()
    
    def toggle_key_visibility(self):
        """Toggle API key visibility."""
        if self.show_key_var.get():
            self.api_key_entry.configure(show="")
        else:
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
    """Modal window for editing prompt template, system prompt, thinking level, and preferred sources."""
    
    def __init__(self, parent: tk.Tk, current_prompt: str, current_developer_prompt: str, current_thinking_level: str, current_sources: str):
        """
        Initialize the modal window.
        
        Args:
            parent: Parent window
            current_prompt: Current prompt template text
            current_developer_prompt: Current system/developer prompt text
            current_thinking_level: Current thinking level ("low", "medium", "high")
            current_sources: Current preferred sources (comma-separated domains)
        """
        self.result = None  # Will be set to dict if user saves
        
        self.window = tk.Toplevel(parent)
        self.window.title("Edit Prompts, Sources & Thinking Level")
        self.window.geometry("700x750")
        self.window.transient(parent)
        self.window.grab_set()
        
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        
        # Thinking level section
        level_frame = ttk.LabelFrame(main_frame, text="Thinking Level (Reasoning Effort)", padding="10")
        level_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        level_frame.columnconfigure(1, weight=1)
        
        ttk.Label(level_frame, text="Select reasoning effort level:").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.thinking_var = tk.StringVar(value=current_thinking_level)
        
        thinking_combo = ttk.Combobox(
            level_frame,
            textvariable=self.thinking_var,
            values=["low", "medium", "high"],
            state="readonly",
            width=15
        )
        thinking_combo.grid(row=0, column=1, sticky="w")
        
        # Help text for thinking levels
        help_text = ttk.Label(
            level_frame,
            text="low: Faster, economical | medium: Balanced (default) | high: More thorough",
            font=("TkDefaultFont", 8),
            foreground="gray"
        )
        help_text.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))
        
        # Preferred sources section
        sources_frame = ttk.LabelFrame(main_frame, text="Preferred Sources for Web Search", padding="10")
        sources_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        sources_frame.columnconfigure(0, weight=1)
        
        ttk.Label(sources_frame, text="Domain names (comma-separated):").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.sources_var = tk.StringVar(value=current_sources)
        sources_entry = ttk.Entry(sources_frame, textvariable=self.sources_var)
        sources_entry.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        
        # Help text for sources
        sources_help = ttk.Label(
            sources_frame,
            text="Examples: reuters.com, bloomberg.com, cnbc.com\nWill automatically clean URLs (removes http://, www., etc.)",
            font=("TkDefaultFont", 8),
            foreground="gray"
        )
        sources_help.grid(row=2, column=0, sticky="w", pady=(5, 0))
        
        # Error message label for sources validation
        self.sources_error_var = tk.StringVar()
        self.sources_error_label = ttk.Label(
            sources_frame,
            textvariable=self.sources_error_var,
            font=("TkDefaultFont", 8),
            foreground="red"
        )
        self.sources_error_label.grid(row=3, column=0, sticky="w", pady=(3, 0))
        
        # Prompts tabs section
        prompt_frame = ttk.LabelFrame(main_frame, text="Prompts", padding="10")
        prompt_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
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
        
        self.prompt_text = scrolledtext.ScrolledText(user_prompt_tab, height=12, wrap=tk.WORD)
        self.prompt_text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.prompt_text.insert("1.0", current_prompt)
        
        # Variables helper for user prompt
        help_label = ttk.Label(
            user_prompt_tab,
            text="Variables: {ticker}, {security_name}, {period}, {source_instructions}",
            font=("TkDefaultFont", 8),
            foreground="gray"
        )
        help_label.grid(row=1, column=0, sticky="w", padx=10, pady=(5, 10))
        
        # Tab 2: System/Developer Prompt
        dev_prompt_tab = ttk.Frame(self.notebook)
        self.notebook.add(dev_prompt_tab, text="System Prompt (Instructions)")
        dev_prompt_tab.columnconfigure(0, weight=1)
        dev_prompt_tab.rowconfigure(0, weight=1)
        
        self.dev_prompt_text = scrolledtext.ScrolledText(dev_prompt_tab, height=12, wrap=tk.WORD)
        self.dev_prompt_text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.dev_prompt_text.insert("1.0", current_developer_prompt)
        
        # Help text for system prompt
        dev_help_label = ttk.Label(
            dev_prompt_tab,
            text="System prompt controls the LLM's behavior and tone for all requests.",
            font=("TkDefaultFont", 8),
            foreground="gray"
        )
        dev_help_label.grid(row=1, column=0, sticky="w", padx=10, pady=(5, 10))
        
        # Button frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=3, column=0, sticky="e", pady=(10, 0))
        
        ttk.Button(btn_frame, text="Reset User Prompt", command=self.reset_user_prompt).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Reset System Prompt", command=self.reset_system_prompt).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.on_cancel).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Save", command=self.on_save).pack(side="left", padx=5)
        
        self.window.focus()
    
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
        # Validate and clean sources
        valid_domains, errors = validate_and_clean_domains(self.sources_var.get())
        
        if errors:
            self.sources_error_var.set("Errors: " + "; ".join(errors))
            return
        
        self.result = {
            "prompt_template": self.prompt_text.get("1.0", tk.END).strip(),
            "developer_prompt": self.dev_prompt_text.get("1.0", tk.END).strip(),
            "thinking_level": self.thinking_var.get(),
            "preferred_sources": ", ".join(valid_domains)  # Return cleaned domains
        }
        self.window.destroy()


class CommentaryGeneratorApp:
    """Main GUI application for the commentary generator."""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Commentary Generator")
        self.root.geometry("900x750")
        self.root.minsize(800, 650)
        
        # State variables
        self.input_files: list[Path] = []
        self.output_folder: Optional[Path] = None
        self.is_running = False
        self.thinking_level: str = "medium"  # Default thinking level
        self.api_key: str = ""  # API key storage
        self.sources_var = tk.StringVar(value=", ".join(get_default_preferred_sources()))
        
        # Prompt template and system prompt variables
        self.prompt_text_content: str = DEFAULT_PROMPT_TEMPLATE
        self.developer_prompt_content: str = DEFAULT_DEVELOPER_PROMPT
        
        # Configure grid weights for resizing
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        self.setup_ui()
        self.load_api_key()
        self.load_config()
    
    def _get_config_path(self) -> Path:
        """Get the configuration directory path (platform-aware)."""
        if sys.platform == "win32":
            # Windows: use APPDATA environment variable
            config_dir = Path(os.getenv("APPDATA", str(Path.home()))) / "Commentary"
        else:
            # macOS/Linux: use ~/.commentary
            config_dir = Path.home() / ".commentary"
        
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
            
            # Load API key
            if "api_key" in config:
                self.api_key = config["api_key"]
            
            # Load prompt template
            if "prompt_template" in config:
                self.prompt_text_content = config["prompt_template"]
            
            # Load developer prompt
            if "developer_prompt" in config:
                self.developer_prompt_content = config["developer_prompt"]
            
            # Load thinking level
            if "thinking_level" in config:
                self.thinking_level = config["thinking_level"]
            
            # Load preferred sources
            if "preferred_sources" in config:
                self.sources_var.set(", ".join(config["preferred_sources"]))
            
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
                "api_key": self.api_key,
                "prompt_template": self.prompt_text_content,
                "developer_prompt": self.developer_prompt_content,
                "thinking_level": self.thinking_level,
                "preferred_sources": [s.strip() for s in self.sources_var.get().split(",") if s.strip()],
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
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(1, weight=1)
        
        current_row = 0
        
        # ====== File Selection Section ======
        file_frame = ttk.LabelFrame(main_frame, text="File Selection", padding="10")
        file_frame.grid(row=current_row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        file_frame.columnconfigure(1, weight=1)
        
        # Input files
        ttk.Label(file_frame, text="Input Files:").grid(row=0, column=0, sticky="nw", padx=(0, 10))
        
        input_list_frame = ttk.Frame(file_frame)
        input_list_frame.grid(row=0, column=1, sticky="ew")
        input_list_frame.columnconfigure(0, weight=1)
        
        self.input_listbox = tk.Listbox(input_list_frame, height=4, selectmode=tk.EXTENDED)
        self.input_listbox.grid(row=0, column=0, sticky="ew")
        
        input_scroll = ttk.Scrollbar(input_list_frame, orient="vertical", command=self.input_listbox.yview)
        input_scroll.grid(row=0, column=1, sticky="ns")
        self.input_listbox.configure(yscrollcommand=input_scroll.set)
        
        input_btn_frame = ttk.Frame(file_frame)
        input_btn_frame.grid(row=0, column=2, padx=(10, 0))
        ttk.Button(input_btn_frame, text="Add Files", command=self.add_input_files).pack(pady=2)
        ttk.Button(input_btn_frame, text="Remove", command=self.remove_input_files).pack(pady=2)
        ttk.Button(input_btn_frame, text="Clear All", command=self.clear_input_files).pack(pady=2)
        
        # Output folder
        ttk.Label(file_frame, text="Output Folder:").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(10, 0))
        
        self.output_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.output_var, state="readonly").grid(
            row=1, column=1, sticky="ew", pady=(10, 0))
        ttk.Button(file_frame, text="Browse", command=self.select_output_folder).grid(
            row=1, column=2, padx=(10, 0), pady=(10, 0))
        
        current_row += 1
        
        # ====== Settings Section ======
        settings_frame = ttk.LabelFrame(main_frame, text="Settings", padding="10")
        settings_frame.grid(row=current_row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        settings_frame.columnconfigure(1, weight=1)
        
        # Holdings mode
        ttk.Label(settings_frame, text="Holdings Mode:").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.mode_var = tk.StringVar(value="top_bottom")
        mode_frame = ttk.Frame(settings_frame)
        mode_frame.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(mode_frame, text="Top/Bottom N", variable=self.mode_var, 
                        value="top_bottom", command=self.on_mode_change).pack(side="left")
        ttk.Radiobutton(mode_frame, text="All Holdings", variable=self.mode_var, 
                        value="all_holdings", command=self.on_mode_change).pack(side="left", padx=(20, 0))
        
        # Top/Bottom count
        ttk.Label(settings_frame, text="Top/Bottom Count:").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(5, 0))
        self.count_var = tk.StringVar(value="5")
        self.count_combo = ttk.Combobox(settings_frame, textvariable=self.count_var, 
                                         values=["5", "10"], state="readonly", width=10)
        self.count_combo.grid(row=1, column=1, sticky="w", pady=(5, 0))
        
        current_row += 1
        
        # ====== Configuration Section ======
        config_frame = ttk.Frame(main_frame)
        config_frame.grid(row=current_row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)
        
        ttk.Label(config_frame, text="Configuration:").pack(side="left")
        ttk.Button(config_frame, text="Settings", command=self.open_settings).pack(side="left", padx=(10, 0))
        
        current_row += 1
        
        # ====== Prompt Section ======
        prompt_frame = ttk.LabelFrame(main_frame, text="Prompts, Sources & Thinking Level", padding="10")
        prompt_frame.grid(row=current_row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        prompt_frame.columnconfigure(0, weight=1)
        
        ttk.Label(prompt_frame, text="Click 'Edit' to modify prompts, preferred sources, and configure thinking level.").pack(side="left", padx=(0, 10))
        ttk.Button(prompt_frame, text="Edit", command=self.open_prompt_editor).pack(side="left")
        
        current_row += 1
        
        # ====== Progress Section ======
        progress_frame = ttk.LabelFrame(main_frame, text="Progress", padding="10")
        progress_frame.grid(row=current_row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, 
                                             maximum=100, mode="determinate")
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(progress_frame, textvariable=self.status_var).grid(row=1, column=0, sticky="w", pady=(5, 0))
        
        current_row += 1
        
        # ====== Action Buttons ======
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=current_row, column=0, columnspan=3, pady=(0, 10))
        
        self.run_btn = ttk.Button(btn_frame, text="Generate Commentary", command=self.run_generation)
        self.run_btn.pack(side="left", padx=5)
        
        ttk.Button(btn_frame, text="Exit", command=self.root.quit).pack(side="left", padx=5)
    
    def load_api_key(self):
        """Load API key from environment variable if available."""
        api_key = os.environ.get("OPENAI_API_KEY", "")
        self.api_key = api_key
    
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
        modal = PromptEditorModal(self.root, self.prompt_text_content, self.developer_prompt_content, self.thinking_level, self.sources_var.get())
        self.root.wait_window(modal.window)
        
        # Apply changes if user clicked Save
        if modal.result:
            self.prompt_text_content = modal.result["prompt_template"]
            self.developer_prompt_content = modal.result["developer_prompt"]
            self.thinking_level = modal.result["thinking_level"]
            self.sources_var.set(modal.result["preferred_sources"])
    
    def open_settings(self):
        """Open the settings modal window."""
        modal = SettingsModal(self.root, self.api_key)
        self.root.wait_window(modal.window)
        
        # Apply changes if user clicked Save
        if modal.result:
            self.api_key = modal.result["api_key"]
    
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
            
            result = loop.run_until_complete(self._async_generate())
            
            # Update UI on main thread
            self.root.after(0, lambda: self._on_generation_complete(result))
            
        except Exception as e:
            self.root.after(0, lambda: self._on_generation_error(str(e)))
        finally:
            self.is_running = False
            self.root.after(0, lambda: self.run_btn.configure(state="normal"))
    
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
            thinking_level=self.thinking_level
        )
        prompt_manager = PromptManager(prompt_config)
        
        # Set up OpenAI client
        client = OpenAIClient(
            api_key=self.api_key.strip(),
            progress_callback=self.update_progress,
            developer_prompt=self.developer_prompt_content
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
            thinking_level=self.thinking_level
        )
        
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
