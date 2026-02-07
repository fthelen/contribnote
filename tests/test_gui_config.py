"""
Tests for GUI configuration persistence (without creating a Tk window).
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

import src.gui as gui_module
from src.gui import CommentaryGeneratorApp, DEFAULT_MODEL


class DummyVar:
    """Simple stand-in for tkinter variable objects in tests."""

    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def make_app_stub(config_dir: Path) -> CommentaryGeneratorApp:
    """Create a CommentaryGeneratorApp-like object without tkinter initialization."""
    app = CommentaryGeneratorApp.__new__(CommentaryGeneratorApp)
    app.prompt_text_content = "prompt"
    app.developer_prompt_content = "developer"
    app.thinking_level = "medium"
    app.model_id = DEFAULT_MODEL
    app.text_verbosity = "low"
    app.sources_var = DummyVar("reuters.com, bloomberg.com")
    app.require_citations = True
    app.prioritize_sources = True
    app.output_folder = None

    app.run_attribution_overview = False
    app.attribution_prompt_text_content = "attrib prompt"
    app.attribution_developer_prompt_content = "attrib developer"
    app.attribution_thinking_level = "medium"
    app.attribution_text_verbosity = "low"
    app.attribution_model_id = DEFAULT_MODEL

    app.output_var = DummyVar("")
    app.run_attribution_var = DummyVar(False)

    app._migrate_api_key_from_config = lambda _value: None
    app._get_config_path = lambda: config_dir
    app._get_config_file = lambda: config_dir / "config.json"
    return app


def make_validation_app_stub(tmp_path: Path, sources: str) -> CommentaryGeneratorApp:
    """Create a minimal app stub for validate_inputs tests."""
    app = CommentaryGeneratorApp.__new__(CommentaryGeneratorApp)
    app.api_key = "test-key"
    app.input_files = [Path("input.xlsx")]
    app.output_folder = tmp_path
    app.sources_var = DummyVar(sources)
    app.require_citations = True
    app.prioritize_sources = True
    app.require_citations_var = DummyVar(True)
    app.prioritize_sources_var = DummyVar(True)
    app.global_sources_error_var = DummyVar("")
    return app


def test_save_config_includes_attribution_keys(tmp_path):
    app = make_app_stub(tmp_path)
    app.run_attribution_overview = True
    app.attribution_prompt_text_content = "new attrib prompt"
    app.attribution_developer_prompt_content = "new attrib developer"
    app.attribution_thinking_level = "high"
    app.attribution_text_verbosity = "medium"
    app.attribution_model_id = DEFAULT_MODEL

    app.save_config()

    config_path = tmp_path / "config.json"
    payload = json.loads(config_path.read_text())

    assert payload["run_attribution_overview"] is True
    assert payload["attribution_prompt_template"] == "new attrib prompt"
    assert payload["attribution_developer_prompt"] == "new attrib developer"
    assert payload["attribution_thinking_level"] == "high"
    assert payload["attribution_text_verbosity"] == "medium"
    assert payload["attribution_model"] == DEFAULT_MODEL


def test_load_config_reads_attribution_keys_and_updates_checkbox_var(tmp_path):
    output_folder = tmp_path / "out"
    output_folder.mkdir()

    payload = {
        "prompt_template": "loaded prompt",
        "developer_prompt": "loaded developer",
        "thinking_level": "high",
        "model": DEFAULT_MODEL,
        "text_verbosity": "medium",
        "preferred_sources": ["reuters.com", "ft.com"],
        "require_citations": False,
        "prioritize_sources": False,
        "run_attribution_overview": True,
        "attribution_prompt_template": "loaded attribution prompt",
        "attribution_developer_prompt": "loaded attribution developer",
        "attribution_thinking_level": "xhigh",
        "attribution_text_verbosity": "high",
        "attribution_model": DEFAULT_MODEL,
        "output_folder": str(output_folder),
    }
    (tmp_path / "config.json").write_text(json.dumps(payload))

    app = make_app_stub(tmp_path)
    app.load_config()

    assert app.prompt_text_content == "loaded prompt"
    assert app.developer_prompt_content == "loaded developer"
    assert app.require_citations is False
    assert app.prioritize_sources is False
    assert app.sources_var.get() == "reuters.com, ft.com"

    assert app.run_attribution_overview is True
    assert app.run_attribution_var.get() is True
    assert app.attribution_prompt_text_content == "loaded attribution prompt"
    assert app.attribution_developer_prompt_content == "loaded attribution developer"
    assert app.attribution_thinking_level == "xhigh"
    assert app.attribution_text_verbosity == "high"
    assert app.attribution_model_id == DEFAULT_MODEL


def test_validate_inputs_rejects_invalid_preferred_sources(tmp_path, monkeypatch):
    app = make_validation_app_stub(tmp_path, "invalid_domain")
    error_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        gui_module.messagebox,
        "showerror",
        lambda title, message: error_calls.append((title, message)),
    )

    assert app.validate_inputs() is False
    assert error_calls
    assert app.global_sources_error_var.get().startswith("Errors:")


def test_validate_inputs_normalizes_preferred_sources(tmp_path, monkeypatch):
    app = make_validation_app_stub(tmp_path, "https://www.reuters.com/, bloomberg.com")
    error_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        gui_module.messagebox,
        "showerror",
        lambda title, message: error_calls.append((title, message)),
    )

    assert app.validate_inputs() is True
    assert app.sources_var.get() == "reuters.com, bloomberg.com"
    assert app.global_sources_error_var.get() == ""
    assert error_calls == []
