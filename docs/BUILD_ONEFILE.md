# Onefile Build Guide

This guide explains how to build unsigned onefile executables for ContribNote on macOS and Windows.

## Overview

- Build script: `scripts/build_onefile.py`
- Output folder: `dist/`
- Artifacts are unsigned (no code signing or notarization).
- Builds are native-only:
  - Build macOS artifact on macOS
  - Build Windows artifact on Windows

## What the Script Does

By default, the script:

1. Creates/uses repo-local `.venv`
2. Installs runtime dependencies from `requirements.txt`
3. Installs build dependencies from `requirements-build.txt`
4. Runs PyInstaller onefile GUI build
5. Produces a zipped deliverable in `dist/` (plus raw artifact)

## Default Usage

### macOS

```bash
python3 scripts/build_onefile.py
```

Expected artifacts:

- `dist/ContribNote.app`
- `dist/ContribNote-macos-<version>.zip`

### Windows (PowerShell)

```powershell
py scripts/build_onefile.py
```

Expected artifacts:

- `dist/ContribNote.exe`
- `dist/ContribNote-windows-<version>.zip`

## CLI Options

```bash
python scripts/build_onefile.py --help
```

- `--target auto|macos|windows` (default: `auto`)
- `--app-name <name>` (default: `ContribNote`)
- `--entrypoint <path>` (default: `run_app.py`)
- `--venv-path <path>` (default: `.venv`)
- `--clean` remove previous app-specific build outputs before building
- `--build-only` install only `requirements-build.txt` (skip `requirements.txt`)
- `--no-zip` skip zip packaging and keep only raw artifact
- `--no-bootstrap` skip venv/dependency setup and fail fast if build deps are missing

## Examples

Build with clean output:

```bash
python scripts/build_onefile.py --clean
```

Build with a custom app name:

```bash
python scripts/build_onefile.py --app-name CommentaryGenerator
```

Skip runtime dependency install (faster repeat build):

```bash
python scripts/build_onefile.py --build-only
```

Disable bootstrap and use an existing `.venv`:

```bash
python scripts/build_onefile.py --no-bootstrap
```

## Notes

- The script enforces native-only builds. Example: `--target windows` on macOS will fail with a clear error.
- If the expected artifact is not created, the script prints the current `dist/` contents to help diagnose issues.
