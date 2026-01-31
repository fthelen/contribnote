"""
Commentary Generator GUI

Simple tkinter-based GUI for non-technical users.
"""

import asyncio
import os
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
        
        # Configure grid weights for resizing
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        self.setup_ui()
        self.load_api_key()
    
    def setup_ui(self):
        """Set up the user interface."""
        # Main frame with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(1, weight=1)
        
        current_row = 0
        
        # ====== API Key Section ======
        api_frame = ttk.LabelFrame(main_frame, text="OpenAI API Key", padding="10")
        api_frame.grid(row=current_row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        api_frame.columnconfigure(1, weight=1)
        
        ttk.Label(api_frame, text="API Key:").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.api_key_var = tk.StringVar()
        self.api_key_entry = ttk.Entry(api_frame, textvariable=self.api_key_var, show="*", width=50)
        self.api_key_entry.grid(row=0, column=1, sticky="ew")
        
        self.show_key_var = tk.BooleanVar()
        ttk.Checkbutton(api_frame, text="Show", variable=self.show_key_var, 
                        command=self.toggle_key_visibility).grid(row=0, column=2, padx=(10, 0))
        
        current_row += 1
        
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
        
        # Citations mode
        ttk.Label(settings_frame, text="Require Citations:").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=(5, 0))
        self.citations_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(settings_frame, variable=self.citations_var).grid(row=2, column=1, sticky="w", pady=(5, 0))
        
        # Preferred sources
        ttk.Label(settings_frame, text="Preferred Sources:").grid(row=3, column=0, sticky="nw", padx=(0, 10), pady=(5, 0))
        self.sources_var = tk.StringVar(value=", ".join(get_default_preferred_sources()))
        sources_entry = ttk.Entry(settings_frame, textvariable=self.sources_var)
        sources_entry.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(5, 0))
        
        ttk.Label(settings_frame, text="(comma-separated domains)", 
                  font=("TkDefaultFont", 9)).grid(row=4, column=1, sticky="w")
        
        current_row += 1
        
        # ====== Developer Prompt Section ======
        dev_prompt_frame = ttk.LabelFrame(main_frame, text="Developer Prompt (System Instructions)", padding="10")
        dev_prompt_frame.grid(row=current_row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        dev_prompt_frame.columnconfigure(0, weight=1)
        
        self.dev_prompt_text = scrolledtext.ScrolledText(dev_prompt_frame, height=4, wrap=tk.WORD)
        self.dev_prompt_text.grid(row=0, column=0, sticky="ew")
        self.dev_prompt_text.insert("1.0", DEFAULT_DEVELOPER_PROMPT)
        
        dev_prompt_btn_frame = ttk.Frame(dev_prompt_frame)
        dev_prompt_btn_frame.grid(row=1, column=0, sticky="e", pady=(5, 0))
        ttk.Button(dev_prompt_btn_frame, text="Reset to Default", command=self.reset_dev_prompt).pack(side="right")
        
        current_row += 1
        
        # ====== Prompt Section ======
        prompt_frame = ttk.LabelFrame(main_frame, text="Prompt Template", padding="10")
        prompt_frame.grid(row=current_row, column=0, columnspan=3, sticky="nsew", pady=(0, 10))
        prompt_frame.columnconfigure(0, weight=1)
        prompt_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(current_row, weight=1)
        
        self.prompt_text = scrolledtext.ScrolledText(prompt_frame, height=8, wrap=tk.WORD)
        self.prompt_text.grid(row=0, column=0, sticky="nsew")
        self.prompt_text.insert("1.0", DEFAULT_PROMPT_TEMPLATE)
        
        prompt_btn_frame = ttk.Frame(prompt_frame)
        prompt_btn_frame.grid(row=1, column=0, sticky="e", pady=(5, 0))
        ttk.Button(prompt_btn_frame, text="Reset to Default", command=self.reset_prompt).pack(side="right")
        
        ttk.Label(prompt_frame, 
                  text="Variables: {ticker}, {security_name}, {period}, {source_instructions}",
                  font=("TkDefaultFont", 9)).grid(row=2, column=0, sticky="w")
        
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
        if api_key:
            self.api_key_var.set(api_key)
    
    def toggle_key_visibility(self):
        """Toggle API key visibility."""
        if self.show_key_var.get():
            self.api_key_entry.configure(show="")
        else:
            self.api_key_entry.configure(show="*")
    
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
    
    def reset_prompt(self):
        """Reset prompt to default."""
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", DEFAULT_PROMPT_TEMPLATE)
    
    def reset_dev_prompt(self):
        """Reset developer prompt to default."""
        self.dev_prompt_text.delete("1.0", tk.END)
        self.dev_prompt_text.insert("1.0", DEFAULT_DEVELOPER_PROMPT)
    
    def update_progress(self, ticker: str, completed: int, total: int):
        """Update progress bar (called from async thread)."""
        def update():
            progress = (completed / total) * 100 if total > 0 else 0
            self.progress_var.set(progress)
            self.status_var.set(f"Processing: {ticker} ({completed}/{total})")
        self.root.after(0, update)
    
    def validate_inputs(self) -> bool:
        """Validate user inputs before running."""
        if not self.api_key_var.get().strip():
            messagebox.showerror("Error", "Please enter your OpenAI API key.")
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
            template=self.prompt_text.get("1.0", tk.END).strip(),
            preferred_sources=sources,
            require_citations=self.citations_var.get()
        )
        prompt_manager = PromptManager(prompt_config)
        
        # Set up OpenAI client
        client = OpenAIClient(
            api_key=self.api_key_var.get().strip(),
            progress_callback=self.update_progress,
            developer_prompt=self.dev_prompt_text.get("1.0", tk.END).strip()
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
            require_citations=self.citations_var.get()
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
