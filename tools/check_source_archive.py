#!/usr/bin/env python3
"""Check that the source release does not contain generated or imported data."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {"__pycache__", "dist", "node_modules", "data"}
FORBIDDEN_SUFFIXES = {
    ".3mf",
    ".db",
    ".glb",
    ".gltf",
    ".obj",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".stl",
}
MEDIA_SUFFIXES = {".gif", ".jpg", ".jpeg", ".mp4", ".png", ".webm", ".webp"}


def candidate_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        text=True,
    )
    return [Path(line) for line in output.splitlines() if line]


def main() -> int:
    errors = []
    media_manifest = (ROOT / "docs/media/PROVENANCE.md").read_text()
    for path in candidate_files():
        if FORBIDDEN_PARTS.intersection(path.parts) or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"Generated or data file is not allowed in the source archive: {path}")
        if path.suffix.lower() in MEDIA_SUFFIXES:
            if path.parts[:2] != ("docs", "media"):
                errors.append(f"Media must be stored under docs/media: {path}")
            elif path.name not in media_manifest:
                errors.append(f"Media is missing from docs/media/PROVENANCE.md: {path}")
    if errors:
        print("\n".join(errors))
        return 1
    print("Source archive contains no generated, imported or unreviewed media files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
