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
Every rule here has to be mechanically decidable.

*Data Product* was the long-standing exception, and is no longer one. The
word *entity* had drifted into about a hundred and fifty places across twenty
files, and while that was true no regex could separate the wrong uses from
the right ones. So the prose was cleaned first, and what survived turned out
to be a short closed list: the `entity_` YAML keys, which are code and
already exempt; the OpenSearch objects (`entity registry`, `entity document`)
and OData's `entity set`, which are somebody else's nouns; and the hyphenated
compounds (`cross-entity`, `per-entity`, `entity-level`), which read as one
adjective rather than as the noun. Everything else is a Data Product. That
list is what the rule below encodes, and it only holds because the cleanup
came first.

Fenced blocks and inline code are exempt: they quote the system, and the
system is allowed to disagree with the style guide. A single line may opt out
of one pass with a trailing `<!-- terms-ok: why -->`, which is how the page
that *defines* a synonym is allowed to print it.

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
# Blockquote markers, dropped so a phrase wrapped inside a `>` block still
# joins into the phrase a reader sees.
QUOTE_MARK = re.compile(r"^\s*>+\s?")

# One line's opt-out, written where a reader can see the reason.
TERMS_OK = re.compile(r"<!--\s*terms-ok\b")

# Prose that belongs to somebody else. Exempted per rule rather than per file:
# a whole-file skip would take the other guards with it, and the old app name
# is exactly as wrong in a prompt as it is in a manual.
NOT_OUR_PROSE = (
    # PolyForm's own words. We license under this text; we do not edit it.
    "platform/LICENSE.md",
    # Instructions about the code, where the code's own names are the point.
    "platform/CLAUDE.md",
    # The standards handed to the model at enrichment time. Rewording these
    # changes what the model writes, so it is a product change and not a
    # documentation one.
    "platform/packages/ask-admin-api/src/ask_admin_api/prompts/",
    # The Apache 2.0 text, quoted in full as that license requires.
    "THIRD-PARTY-NOTICES.md",
)

# (label, pattern, what to write instead, paths the rule does not apply to)
RULES: list[tuple[str, re.Pattern[str], str, tuple[str, ...]]] = [
    (
        "old app name",
        # "ASK Admin API" is the real name of the ask-admin-api package.
        re.compile(r"\bASK Admin\b(?!\s+API)"),
        "ASK Studio (the authoring app was renamed; only the API kept the name)",
        (),
    ),
    (
        "the app called by its old role",
        # Not "console": Keycloak's own screen is the admin console, and so is
        # OpenSearch's. Borrowing their names for our app is the drift; describing
        # theirs accurately is not.
        re.compile(r"\b(?:the )?admin (?:app|panel|UI)\b", re.IGNORECASE),
        "ASK Studio",
        (),
    ),
    (
        "Setup called by its old name",
        # ASK Setup was the "Configuration app" before it was a named surface, and
        # the name outlived the rename in a troubleshooting fix that sent a reader
        # looking for an app the UI does not have. Same failure as ASK Admin, so
        # the same guard.
        re.compile(r"\bconfig(?:uration)? app(?:lication)?\b", re.IGNORECASE),
        "ASK Setup",
        (),
    ),
    (
        "old manual path",
        re.compile(r"\bask-admin/"),
        "ask-studio/",
        (),
    ),
    (
        "old screenshot name",
        re.compile(r"\badmin-[a-z0-9-]+\.png\b"),
        "studio-*.png",
        (),
    ),
    (
        "surface name miscased",
        re.compile(r"\b(?:Ask|ask) (?:Chat|Studio|Setup)\b|\bASK (?:chat|studio|setup)\b"),
        "ASK Chat / ASK Studio / ASK Setup",
        (),
    ),
    (
        "company name miscased",
        # The env vars (ONIBEX_ENCRYPTION_KEY) are code and already exempt.
        re.compile(r"\bONIBEX\b(?!_)"),
        "Onibex",
        (),
    ),
    (
        "the queryable unit called an entity",
        # Not preceded by a hyphen or a word character, and not followed by a
        # hyphen: that clears `cross-entity`, `per-entity` and `entity-level`,
        # which are adjectives, in one condition. A slash-joined compound
        # (`entity/field/docs registries`) is a name for the same reason.
        #
        # The nouns that follow are the closed list of things genuinely called
        # an entity by something other than us: two OpenSearch objects, an
        # OData concept, and the four UI or YAML labels that keep the prefix on
        # purpose (see definition/README.md).
        re.compile(
            r"(?<![-\w])[Ee]ntit(?:y|ies)\b(?![-/])"
            r"(?!\s+(?i:sets?|registry|document|lifecycle|role|grain|ids?|resolution))"
        ),
        "Data Product",
        NOT_OUR_PROSE,
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
        if in_fence or TERMS_OK.search(line):
            continue
        lines.append((number, INLINE_CODE.sub("``", QUOTE_MARK.sub("", line))))
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
        for label, pattern, instead, exempt in RULES:
            if any(rel.startswith(prefix) for prefix in exempt):
                continue
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
