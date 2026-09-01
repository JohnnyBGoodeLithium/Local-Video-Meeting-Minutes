#!/usr/bin/env python3
"""Install and smoke-test an extracted bundle without its source Git repository."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(root: Path) -> None:
    root = root.resolve()
    if (root / ".git").exists():
        raise RuntimeError("bundle smoke requires an extracted directory without .git")
    manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("archive_root") != root.name:
        raise RuntimeError("extracted root does not match release manifest")
    if not any(shutil.which(name) for name in ("google-chrome", "chromium", "chromium-browser")):
        raise RuntimeError("Headless Chromium is required for release bundle smoke")

    venv = root / ".venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], cwd=root, check=True)
    python = venv / "bin" / "python"
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", "requirements/ci.lock"],
        cwd=root, check=True,
    )
    subprocess.run(
        [str(python), "-m", "pip", "install", "-e", ".", "--no-deps"],
        cwd=root, check=True,
    )

    env = os.environ.copy()
    env["PATH"] = f"{venv / 'bin'}:{env.get('PATH', '')}"
    env["MEETING_RESOURCE_GUARD"] = "0"
    env.pop("PYTHONPATH", None)
    for name in list(env):
        if name.startswith("MM_TEST_"):
            env.pop(name, None)
    subprocess.run(["make", "package-check"], cwd=root, env=env, check=True)
    subprocess.run(["make", "smoke"], cwd=root, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    run(args.root)
    print("release bundle: clean extraction package-check and smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
