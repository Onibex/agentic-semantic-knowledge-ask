#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Every relative link in the published documentation must resolve.

A dead link is the cheapest possible signal that documentation is not
maintained, and it is the one a reader hits before any of the prose. This
checks the two kinds a repository can verify without a network: a link to a
path that does not exist, and a link to a `#heading-anchor` that no heading
produces.

External `http(s)` links are out of scope on purpose — they fail for reasons
that have nothing to do with this commit, and a build that goes red when
somebody else's site is down teaches people to ignore it.

Only *published* documentation is scanned. Locally-ignored working areas
(`_internal/`, `_authoring/`) and vendored tool drops are skipped, since
nothing in them reaches a reader.

    python scripts/docs_links.py --check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories whose contents never reach a reader of this repository.
SKIP_PARTS = {
    ".git",
    ".github",
    ".claude",
    ".databricks",
    ".gemini",
    ".ruff_cache",
    "node_modules",
    "_internal",
    "_authoring",
    "__pycache__",
}

LINK = re.compile(r"\[(?P<label>[^\]]*)\]\((?P<target>[^)\s]+)\)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<text>.*?)\s*#*\s*$", re.MULTILINE)
FENCE = re.compile(r"^\s*(```|~~~)", re.MULTILINE)


def slugify(heading: str) -> str:
    """GitHub's heading-anchor rule, closely enough for link checking.

    Inline code and link syntax collapse to their text, everything that is not
    a word character / whitespace / hyphen is dropped, and each remaining
    whitespace character becomes one hyphen — note *each*, not each run, which
    is why `A · B` yields a double hyphen.
    """
    text = heading.strip().lower()
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text).strip("-")


def headings_of(text: str) -> set[str]:
    """Anchors this document defines, ignoring `#` inside fenced code."""
    anchors: set[str] = set()
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING.match(line)
        if match:
            anchors.add(slugify(match.group("text")))
    return anchors


def markdown_files() -> list[Path]:
    return sorted(
        p
        for p in ROOT.rglob("*.md")
        if not SKIP_PARTS.intersection(p.relative_to(ROOT).parts)
    )


def check() -> list[str]:
    files = markdown_files()
    anchors = {p: headings_of(p.read_text(encoding="utf-8")) for p in files}
    problems: list[str] = []

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        for match in LINK.finditer(path.read_text(encoding="utf-8")):
            target = match.group("target")
            if target.startswith(("http://", "https://", "mailto:", "tel:")):
                continue

            file_part, _, anchor = target.partition("#")
            destination = path
            if file_part:
                destination = (path.parent / file_part).resolve()
                if not destination.exists():
                    problems.append(f"{rel}: no such path -> {target}")
                    continue

            # An anchor is only checkable when the destination is Markdown we
            # actually scanned; a link into a source file's line number is not.
            if anchor and destination in anchors and anchor not in anchors[destination]:
                problems.append(f"{rel}: no such heading -> {target}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when a link does not resolve (the CI mode).",
    )
    args = parser.parse_args()

    problems = check()
    total = len(markdown_files())

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(
            f"\n{len(problems)} unresolved link(s) across {total} documents.",
            file=sys.stderr,
        )
        return 1 if args.check else 0

    print(f"All relative links resolve across {total} documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
