#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The three surfaces keep the names the product gives them.

The authoring app was called *ASK Admin* for most of this repository's life.
Renaming it touched 98 mentions and 41 image files, and nothing but habit
stops the old name coming back one page at a time — which is how a manual
ends up describing a product the reader cannot find in the UI.

So this is a **regression guard, not a cleanup pass**. It was written against
a documentation set that already passes, and its job is to keep it that way.
Every rule here has to be mechanically decidable; the interesting terminology
question is not, and pretending otherwise would make this noise:

    *Data Product* is the user-facing noun, not *entity* — but `entity_role`
    is a YAML key, `entity id` and `cross-entity` are load-bearing, and an
    OData `entity set` is somebody else's vocabulary. The manual uses the word
    ~100 times and nearly all of them are correct. No regex separates the few
    that are not, so that rule stays a human one, written down in CONTRIBUTING.md.

Fenced blocks and inline code are exempt: they quote the system, and the
system is allowed to disagree with the style guide.

Matching runs on the prose with its line wrapping removed, because this
repository wraps at about 95 characters and *ASK Admin* survived the rename
by being split across two lines.

    python scripts/docs_terms.py --check
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Working areas nobody reads, and the two files whose job is to talk *about* the
# names rather than use them: the changelog records that the rename happened, and
# the contributing guide has to print the old name in order to forbid it.
SKIP_PARTS = {"_internal", "_authoring", "node_modules"}
SKIP_FILES = {"CHANGELOG.md", "CONTRIBUTING.md"}

FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")

# (label, pattern, what to write instead)
RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "old app name",
        # "ASK Admin API" is the real name of the ask-admin-api package.
        re.compile(r"\bASK Admin\b(?!\s+API)"),
        "ASK Studio (the authoring app was renamed; only the API kept the name)",
    ),
    (
        "the app called by its old role",
        # Not "console": Keycloak's own screen is the admin console, and so is
        # OpenSearch's. Borrowing their names for our app is the drift; describing
        # theirs accurately is not.
        re.compile(r"\b(?:the )?admin (?:app|panel|UI)\b", re.IGNORECASE),
        "ASK Studio",
    ),
    (
        "old manual path",
        re.compile(r"\bask-admin/"),
        "ask-studio/",
    ),
    (
        "old screenshot name",
        re.compile(r"\badmin-[a-z0-9-]+\.png\b"),
        "studio-*.png",
    ),
    (
        "surface name miscased",
        re.compile(r"\b(?:Ask|ask) (?:Chat|Studio|Setup)\b|\bASK (?:chat|studio|setup)\b"),
        "ASK Chat / ASK Studio / ASK Setup",
    ),
    (
        "company name miscased",
        # The env vars (ONIBEX_ENCRYPTION_KEY) are code and already exempt.
        re.compile(r"\bONIBEX\b(?!_)"),
        "Onibex",
    ),
]


# Published prose that is not Markdown. `llms.txt` is the summary AI agents read,
# and filtering on "*.md" left it the one published file where the old surface name
# survived a rename that touched ninety-eight others.
ALSO_CHECKED = ("llms.txt",)


def tracked_markdown() -> list[Path]:
    """Published prose, as git sees it.

    Only tracked files, so a local run and CI agree -- a check that disagrees
    with the build is a check people learn to ignore.
    """
    result = subprocess.run(
        ["git", "ls-files", "*.md", *ALSO_CHECKED],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    paths = []
    for line in result.stdout.splitlines():
        rel = line.strip()
        if not rel:
            continue
        path = ROOT / rel
        parts = set(Path(rel).parts)
        if parts & SKIP_PARTS or Path(rel).name in SKIP_FILES:
            continue
        paths.append(path)
    return sorted(paths)


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Numbered lines with code removed, since code quotes the system."""
    lines: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        lines.append((number, INLINE_CODE.sub("``", line)))
    return lines


def joined(lines: list[tuple[int, str]]) -> tuple[str, list[int]]:
    """One string of prose, plus the source line for every character in it.

    A two-word name broken by a line wrap is still that name to a reader, and
    was how *ASK Admin* survived the rename. Matching a single line at a time
    cannot see it.
    """
    text: list[str] = []
    origin: list[int] = []
    for number, line in lines:
        for char in line + " ":
            text.append(char)
            origin.append(number)
    return "".join(text), origin


def check() -> list[str]:
    problems: list[str] = []
    for path in tracked_markdown():
        rel = path.relative_to(ROOT).as_posix()
        text, origin = joined(prose_lines(path.read_text(encoding="utf-8")))
        for label, pattern, instead in RULES:
            for match in pattern.finditer(text):
                number = origin[match.start()]
                found = " ".join(match.group(0).split())
                problems.append(
                    f"{rel}:{number}: {label} -> {found!r}, write {instead}"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when a name has drifted (the CI mode).",
    )
    args = parser.parse_args()

    problems = check()
    total = len(tracked_markdown())

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"\n{len(problems)} problem(s) across {total} documents.", file=sys.stderr)
        return 1 if args.check else 0

    print(f"The product is called what it is called, across {total} documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
