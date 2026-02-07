#!/usr/bin/env python3
"""Build unsigned onefile ContribNote artifacts for macOS and Windows."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


DEFAULT_APP_NAME = "ContribNote"
DEFAULT_ENTRYPOINT = "run_app.py"
DEFAULT_VERSION = "0.0.0"
SUPPORTED_TARGETS = ("auto", "macos", "windows")


def phase(message: str) -> None:
    """Print a high-visibility phase marker."""
    print(f"\n== {message} ==")


def resolve_repo_root() -> Path:
    """Return repository root relative to this script location."""
    return Path(__file__).resolve().parent.parent


def run_command(command: list[str], cwd: Path | None = None) -> None:
    """Run a subprocess command and surface the failing command on error."""
    cmd_text = " ".join(command)
    print(f"$ {cmd_text}")
    try:
        subprocess.run(command, check=True, cwd=str(cwd) if cwd else None)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Command failed with exit code {exc.returncode}: {cmd_text}"
        ) from exc


def detect_host_target() -> str:
    """Map the host platform to a supported build target."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    raise RuntimeError(
        f"Unsupported host OS '{sys.platform}'. This script supports macOS and Windows only."
    )


def resolve_target(requested_target: str, host_target: str) -> str:
    """Resolve requested build target and enforce native-only builds."""
    if requested_target == "auto":
        return host_target
    if requested_target != host_target:
        raise RuntimeError(
            "Native-only builds are enforced. "
            f"Host is '{host_target}' but --target was '{requested_target}'."
        )
    return requested_target


def resolve_venv_python(venv_path: Path, target: str) -> Path:
    """Return venv Python executable path for the selected platform."""
    if target == "windows":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def assert_file_exists(path: Path, label: str) -> None:
    """Validate required input files with actionable error messaging."""
    if not path.exists():
        raise RuntimeError(f"Required {label} not found: {path}")


def ensure_venv_exists(repo_root: Path, venv_path: Path) -> None:
    """Create the virtual environment when it is missing."""
    if venv_path.exists():
        return
    phase(f"Creating virtual environment at {venv_path}")
    run_command([sys.executable, "-m", "venv", str(venv_path)], cwd=repo_root)


def install_dependencies(
    repo_root: Path,
    venv_python: Path,
    build_only: bool,
) -> None:
    """Install runtime and build dependencies into the venv."""
    requirements_txt = repo_root / "requirements.txt"
    requirements_build_txt = repo_root / "requirements-build.txt"

    assert_file_exists(requirements_build_txt, "build requirements file")
    if not build_only:
        assert_file_exists(requirements_txt, "runtime requirements file")

    phase("Installing dependencies into virtual environment")
    run_command(
        [str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        cwd=repo_root,
    )
    if not build_only:
        run_command(
            [str(venv_python), "-m", "pip", "install", "-r", str(requirements_txt)],
            cwd=repo_root,
        )
    run_command(
        [str(venv_python), "-m", "pip", "install", "-r", str(requirements_build_txt)],
        cwd=repo_root,
    )


def verify_pyinstaller_available(venv_python: Path, repo_root: Path) -> None:
    """Fail fast when PyInstaller is not available in the selected venv."""
    try:
        run_command([str(venv_python), "-m", "PyInstaller", "--version"], cwd=repo_root)
    except RuntimeError as exc:
        raise RuntimeError(
            "PyInstaller is not available in the selected virtual environment. "
            "Run without --no-bootstrap or install build dependencies manually."
        ) from exc


def clean_outputs(repo_root: Path, app_name: str) -> None:
    """Remove prior build outputs relevant to this application."""
    phase("Cleaning previous build artifacts")
    build_pyinstaller = repo_root / "build" / "pyinstaller"
    build_spec = repo_root / "build" / "spec"
    dist_dir = repo_root / "dist"

    for path in (build_pyinstaller, build_spec):
        if path.exists():
            print(f"Removing {path}")
            shutil.rmtree(path)

    candidates = [
        dist_dir / app_name,
        dist_dir / f"{app_name}.exe",
        dist_dir / f"{app_name}.app",
    ]
    candidates.extend(dist_dir.glob(f"{app_name}-windows-*.zip"))
    candidates.extend(dist_dir.glob(f"{app_name}-macos-*.zip"))

    for path in candidates:
        if not path.exists():
            continue
        print(f"Removing {path}")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def build_artifact(
    repo_root: Path,
    venv_python: Path,
    app_name: str,
    entrypoint: Path,
    clean: bool,
) -> None:
    """Run PyInstaller onefile build."""
    dist_dir = repo_root / "dist"
    work_dir = repo_root / "build" / "pyinstaller"
    spec_dir = repo_root / "build" / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    phase("Building onefile artifact with PyInstaller")
    command = [
        str(venv_python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        app_name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
    ]
    if clean:
        command.append("--clean")
    command.append(str(entrypoint))
    run_command(command, cwd=repo_root)


def detect_artifact(repo_root: Path, app_name: str, target: str) -> Path:
    """Return expected raw artifact for the target platform."""
    dist_dir = repo_root / "dist"
    expected = dist_dir / (f"{app_name}.exe" if target == "windows" else f"{app_name}.app")
    if expected.exists():
        return expected

    dist_contents = sorted(path.name for path in dist_dir.glob("*")) if dist_dir.exists() else []
    raise RuntimeError(
        f"Expected build artifact not found: {expected}\n"
        f"Current dist contents: {dist_contents}"
    )


def read_version(repo_root: Path) -> str:
    """Read package version from src/__init__.py with fallback."""
    init_file = repo_root / "src" / "__init__.py"
    if not init_file.exists():
        return DEFAULT_VERSION

    try:
        content = init_file.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_VERSION

    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
    return match.group(1).strip() if match else DEFAULT_VERSION


def write_zip(artifact_path: Path, zip_path: Path) -> None:
    """Create a zip archive containing the built artifact."""
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if artifact_path.is_file():
            archive.write(artifact_path, arcname=artifact_path.name)
            return
        for child in sorted(artifact_path.rglob("*")):
            if child.is_dir():
                continue
            archive.write(child, arcname=str(child.relative_to(artifact_path.parent)))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for build automation."""
    parser = argparse.ArgumentParser(
        description=(
            "Build unsigned onefile ContribNote artifacts for macOS and Windows "
            "using a repo-local virtual environment."
        )
    )
    parser.add_argument("--target", default="auto", choices=SUPPORTED_TARGETS)
    parser.add_argument("--app-name", default=DEFAULT_APP_NAME)
    parser.add_argument("--entrypoint", default=DEFAULT_ENTRYPOINT)
    parser.add_argument("--venv-path", default=".venv")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--no-zip", action="store_true")
    parser.add_argument("--no-bootstrap", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Program entrypoint."""
    args = parse_args()
    repo_root = resolve_repo_root()
    host_target = detect_host_target()
    target = resolve_target(args.target, host_target)
    venv_path = (repo_root / args.venv_path).resolve()
    venv_python = resolve_venv_python(venv_path, target)
    entrypoint = (repo_root / args.entrypoint).resolve()

    print("Artifacts are UNSIGNED.")
    print(f"Repository root: {repo_root}")
    print(f"Host target: {host_target}")
    print(f"Build target: {target}")
    print(f"Virtual environment: {venv_path}")

    assert_file_exists(entrypoint, "entrypoint file")

    if args.clean:
        clean_outputs(repo_root, args.app_name)

    if args.no_bootstrap:
        phase("Bootstrap skipped by --no-bootstrap")
        if not venv_path.exists():
            raise RuntimeError(
                f"Virtual environment not found at {venv_path}. "
                "Create it first or run without --no-bootstrap."
            )
    else:
        ensure_venv_exists(repo_root, venv_path)

    if not venv_python.exists():
        raise RuntimeError(
            f"Virtual environment Python executable not found: {venv_python}\n"
            "Ensure the venv path is correct for this platform."
        )

    if not args.no_bootstrap:
        install_dependencies(repo_root=repo_root, venv_python=venv_python, build_only=args.build_only)

    phase("Verifying PyInstaller availability")
    verify_pyinstaller_available(venv_python=venv_python, repo_root=repo_root)

    build_artifact(
        repo_root=repo_root,
        venv_python=venv_python,
        app_name=args.app_name,
        entrypoint=entrypoint,
        clean=args.clean,
    )

    raw_artifact = detect_artifact(repo_root=repo_root, app_name=args.app_name, target=target)
    version = read_version(repo_root)
    zip_artifact: Path | None = None

    if not args.no_zip:
        phase("Packaging artifact into zip")
        zip_artifact = repo_root / "dist" / f"{args.app_name}-{target}-{version}.zip"
        write_zip(raw_artifact, zip_artifact)

    phase("Build complete")
    print(f"Raw artifact: {raw_artifact.resolve()}")
    if zip_artifact is not None:
        print(f"Zip artifact: {zip_artifact.resolve()}")
    print("Artifacts are UNSIGNED.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
