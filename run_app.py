#!/usr/bin/env python3
"""
Commentary Generator

Main entry point for the LLM-powered financial commentary generator.
Processes FactSet Excel reports to generate AI-written commentary
for portfolio contributors and detractors.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.gui import main

if __name__ == "__main__":
    main()
