#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The published documentation must resolve, and the manual must navigate.

A dead link is the cheapest possible signal that documentation is not
maintained, and it is the one a reader hits before any of the prose. This
checks the two kinds a repository can verify without a network: a link to a
path that does not exist, and a link to a `#heading-anchor` that no heading
produces.

It also checks that the manual can be walked: every page listed in the index,
every page carrying a way back to it, and every page called by one name. On a
forge there is no sidebar to supply any of the three, so all of them live in
the pages themselves and decay in silence.

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
import functools
import re
import subprocess
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


MANUAL = ROOT / "platform" / "docs"
MANUAL_INDEX = MANUAL / "README.md"


@functools.lru_cache(maxsize=1)
def tracked_files() -> frozenset[str] | None:
    """Paths git is tracking, or None when that cannot be determined."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", "platform/docs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return frozenset(line.strip() for line in result.stdout.splitlines() if line.strip())


def check_navigation() -> list[str]:
    """Every manual page is reachable from the index, and can get back.

    Plain Markdown on a forge has no chrome: no sidebar, no breadcrumb bar,
    nothing that says where you are. Whatever navigation exists is written into
    the pages, so it decays silently unless something watches it. Readers arrive
    in the middle — from a search result or a shared link — far more often than
    they arrive at the index, which is what makes the way *back* matter as much
    as the way in.
    """
    if not MANUAL_INDEX.exists():
        return [f"{MANUAL_INDEX.relative_to(ROOT).as_posix()}: the manual index is missing"]

    index_text = MANUAL_INDEX.read_text(encoding="utf-8")
    listed = {
        (MANUAL / target.partition("#")[0]).resolve()
        for _, target in LINK.findall(index_text)
        if not target.startswith(("http://", "https://", "mailto:", "#")) and target.partition("#")[0]
    }

    problems: list[str] = []
    for path in sorted(MANUAL.rglob("*.md")):
        if "_authoring" in path.relative_to(ROOT).parts or path == MANUAL_INDEX:
            continue
        rel = path.relative_to(ROOT).as_posix()
        # Only what the repository actually publishes. A file someone has not
        # committed yet is their business, and flagging it would make a local
        # run disagree with CI -- which is how a check earns its way into being
        # ignored.
        if tracked_files() is not None and rel not in tracked_files():
            continue
        if path.resolve() not in listed:
            problems.append(f"{rel}: not linked from the manual index")
        if "Back to the manual" not in path.read_text(encoding="utf-8"):
            problems.append(f"{rel}: no way back to the index")
    return problems


NAME_LINK = re.compile(
    r"\[(?P<label>[^\]\[]+)\]\((?P<target>[^)\s]+\.md)(?P<anchor>#[^)]*)?\)"
)


def index_titles() -> dict[Path, str]:
    """The name the index gives each page, which is the page's only name."""
    titles: dict[Path, str] = {}
    if not MANUAL_INDEX.exists():
        return titles
    for match in NAME_LINK.finditer(MANUAL_INDEX.read_text(encoding="utf-8")):
        target = match.group("target")
        if target.startswith(("http", "../../")):
            continue
        destination = (MANUAL / target).resolve()
        if destination.exists() and MANUAL.resolve() in destination.parents:
            titles[destination] = match.group("label").strip()
    return titles


def check_names() -> list[str]:
    """A page is called the same thing everywhere it is referred to.

    The manual accumulated four naming schemes at once -- an abandoned "Flow N"
    sequence, superseded titles, path-shaped labels and the index's own
    wording -- and one page answered to six names. Nothing about that breaks a
    link, so nothing caught it; the reader is simply left unsure whether the
    page they landed on is the page they were sent to.

    A link into a specific section keeps its own label: it names the section,
    not the page.
    """
    titles = index_titles()
    if not titles:
        return []

    problems: list[str] = []
    for path in sorted(ROOT.rglob("*.md")):
        parts = set(path.relative_to(ROOT).parts)
        if parts & SKIP_PARTS or path == MANUAL_INDEX:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if tracked_files() is not None and rel not in tracked_files() and rel.startswith("platform/docs/"):
            continue
        for match in NAME_LINK.finditer(path.read_text(encoding="utf-8")):
            destination = (path.parent / match.group("target")).resolve()
            label = match.group("label").strip()
            if destination not in titles or match.group("anchor"):
                continue
            if label.startswith("\u2190"):  # the way back, which names the index
                continue
            if label != titles[destination]:
                problems.append(
                    f"{rel}: {label!r} is not what this page is called -- "
                    f"the index calls it {titles[destination]!r}"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when a link does not resolve (the CI mode).",
    )
    args = parser.parse_args()

    problems = check() + check_navigation() + check_names()
    total = len(markdown_files())

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(
            f"\n{len(problems)} problem(s) across {total} documents.",
            file=sys.stderr,
        )
        return 1 if args.check else 0

    print(f"Links resolve, the manual navigates and every page has one name, across {total} documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
