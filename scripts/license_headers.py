#!/usr/bin/env python3
"""Apply — or verify — the Onibex license header on every source file.

Two modes:

    python scripts/license_headers.py            apply the header where missing
    python scripts/license_headers.py --check    fail if any file lacks it (CI gate)

With no paths, it walks what git tracks, so untracked scratch files, vendored
code and build output never get a header they have no business carrying.

The header is written once and left alone afterwards: a file that already has
the SPDX line is skipped, and the short legacy header (copyright + prose, no
SPDX tag) is replaced in place rather than duplicated.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

HEADER = [
    "SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0",
    "Copyright (c) 2026 Onibex, LLC. All rights reserved.",
    "",
    "Part of Onibex ASK — Agentic Semantic Knowledge.",
    "Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.",
    "Commercial licenses: contact@onibex.com — see LICENSE.",
]

MARKER = "SPDX-License-Identifier: LicenseRef-PolyForm"

# How each family of files carries a comment. `hash` and `block` cover
# everything; `html` exists because an HTML comment may not contain "--".
HASH = "hash"
BLOCK = "block"
HTML = "html"

BY_SUFFIX = {
    ".py": HASH, ".yaml": HASH, ".yml": HASH, ".sh": HASH, ".conf": HASH,
    ".ts": BLOCK, ".tsx": BLOCK, ".js": BLOCK, ".mjs": BLOCK, ".css": BLOCK,
    ".html": HTML,
}

# Files whose name carries the type instead of the suffix.
BY_STEM = {"dockerfile": HASH}

# Not ours to sign, or meaningless to sign.
EXCLUDED_DIRS = {
    "node_modules", "dist", "build", ".venv", "venv", "__pycache__",
    "_internal", "public",
}
EXCLUDED_NAMES = {"package-lock.json"}


def kind_of(path: Path) -> str | None:
    if path.name in EXCLUDED_NAMES:
        return None
    if any(part in EXCLUDED_DIRS for part in path.parts):
        return None
    if path.name.lower().startswith("dockerfile"):
        return BY_STEM["dockerfile"]
    return BY_SUFFIX.get(path.suffix)


def render(kind: str) -> list[str]:
    if kind == HASH:
        return [f"# {line}".rstrip() for line in HEADER]
    if kind == BLOCK:
        return ["/*"] + [f" * {line}".rstrip() for line in HEADER] + [" */"]
    return ["<!--"] + [f"  {line}".rstrip() for line in HEADER] + ["-->"]


def insertion_point(lines: list[str], kind: str, path: Path) -> int:
    """Index at which the header may be inserted without breaking the file.

    Some first lines are load-bearing and must stay first: a shebang, a Python
    encoding cookie, a Dockerfile parser directive, the HTML doctype.
    """
    i = 0
    if lines and lines[0].startswith("#!"):
        i = 1
        if path.suffix == ".py" and i < len(lines) and "coding" in lines[i] and lines[i].startswith("#"):
            i += 1
    elif path.name.lower().startswith("dockerfile"):
        while i < len(lines) and lines[i].lstrip().startswith("# syntax="):
            i += 1
    elif path.suffix == ".html":
        while i < len(lines) and not lines[i].lstrip().lower().startswith("<!doctype"):
            i += 1
        i = i + 1 if i < len(lines) else 0
    return i


def strip_legacy(lines: list[str], start: int, kind: str) -> list[str]:
    """Drop the pre-SPDX header (copyright + prose) if this file carries one."""
    opener = {HASH: "#", BLOCK: "/*", HTML: "<!--"}[kind]
    closer = {BLOCK: "*/", HTML: "-->"}.get(kind)
    j = start
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines) or not lines[j].lstrip().startswith(opener):
        return lines
    end = j
    if closer:
        while end < len(lines) and closer not in lines[end]:
            end += 1
        end = min(end + 1, len(lines))
    else:
        while end < len(lines) and lines[end].lstrip().startswith("#"):
            end += 1
    block = "\n".join(lines[j:end])
    if "Copyright (c)" in block and ("PolyForm" in block or "rights reserved" in block):
        rest = lines[end:]
        while rest and not rest[0].strip():
            rest.pop(0)
        return lines[:j] + rest
    return lines


def process(path: Path, apply: bool) -> str:
    kind = kind_of(path)
    if kind is None:
        return "skipped"
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return "unreadable"
    if MARKER in text[:2000]:
        return "present"
    if not apply:
        return "missing"

    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")
    at = insertion_point(lines, kind, path)
    lines = strip_legacy(lines, at, kind)
    block = render(kind)
    if at < len(lines) and lines[at].strip():
        block = block + [""]
    lines[at:at] = block
    if lines and lines[-1].strip():
        lines.append("")  # every file ends with a newline
    path.write_text(newline.join(lines), encoding="utf-8", newline="")
    return "added"


def tracked_files(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p).resolve() for p in paths]
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return [REPO / p for p in out if p.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="report, change nothing, fail if any file lacks the header")
    ap.add_argument("paths", nargs="*", help="explicit files (default: everything git tracks)")
    args = ap.parse_args()

    counts = {"added": 0, "present": 0, "missing": 0, "skipped": 0, "unreadable": 0}
    missing: list[Path] = []
    for path in tracked_files(args.paths):
        if not path.is_file():
            continue
        result = process(path, apply=not args.check)
        counts[result] += 1
        if result == "missing":
            missing.append(path)

    if args.check:
        if missing:
            print(f"{len(missing)} file(s) without a license header:")
            for path in missing[:50]:
                print(f"  {path.relative_to(REPO)}")
            if len(missing) > 50:
                print(f"  ... and {len(missing) - 50} more")
            print("\nRun: python scripts/license_headers.py")
            return 1
        print(f"license headers OK — {counts['present']} covered, {counts['skipped']} not applicable")
        return 0

    print(f"added {counts['added']} · already present {counts['present']} · not applicable {counts['skipped']}")
    if counts["unreadable"]:
        print(f"unreadable (left untouched): {counts['unreadable']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
