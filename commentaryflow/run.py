"""
CommentaryFlow entry point.
Run:  python -m commentaryflow.run
      or:  python commentaryflow/run.py
Opens browser at http://localhost:8000 automatically.
"""

import os
import sys
import time
import threading
import webbrowser
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://localhost:8000")


def main():
    try:
        import uvicorn
    except ImportError:
        print("ERROR: uvicorn not installed. Run:  pip install uvicorn")
        sys.exit(1)

    print("=" * 60)
    print("  CommentaryFlow  —  Portfolio Commentary Pipeline")
    print("=" * 60)
    print()
    print("  Starting server at http://localhost:8000")
    print("  Default users:")
    print("    writer1 / writer123        (Writer role)")
    print("    compliance1 / compliance123 (Reviewer role)")
    print()
    print("  Press Ctrl+C to stop.")
    print()

    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(
        "commentaryflow.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
