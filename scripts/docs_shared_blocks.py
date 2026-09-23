#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The steps that are the same on every cloud stay the same on every cloud.

The Kubernetes runbooks are one page per cloud, deliberately, because a reader
is always on exactly one and a page full of "if AKS do this, if EKS do that"
is read at a glance and executed wrong. The cost of that choice is that the
steps which do NOT depend on the cloud — creating the Secret, building the
realm, watching it come up, signing in — are written out in full on each page
instead of being linked, so that the procedure can be followed top to bottom
without leaving it.

Duplication that nothing checks is how documentation rots, and this repository
has already paid for it once: the runbook created four keys of the platform
Secret while the chart had come to need five, because the chart moved and the
page did not. The install failed several steps later, in the MCP server, naming
a variable nobody had connected to the Secret step.

So the repeated passages are fenced:

    <!-- shared:secret start -->
    ...
    <!-- shared:secret end -->

and this checks that every copy of a given name is byte-identical. Editing one
page and not the others stops being an invisible divergence and becomes a red
build that prints the diff.

It deliberately says nothing about WHICH copy is right. There is no source of
truth among them and inventing one would only move the problem: whoever edited
a shared step knows which page they were thinking about, and the diff is what
they need in order to apply it everywhere.

A block name used in only one file is fine and is not an error. That is how a
passage starts life before a second cloud needs it.

    python scripts/docs_shared_blocks.py --check
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections import defaultdict
from pathlib import Path

# Only this tree. The chart README and the deploy notes are prose about one
# thing each and have no repeated procedure in them.
SEARCH_ROOTS = (Path("platform/docs"),)

BLOCK = re.compile(
    r"<!--[ \t]*shared:([a-z0-9][a-z0-9-]*)[ \t]+start[ \t]*-->\n"
    r"(.*?)"
    r"<!--[ \t]*shared:\1[ \t]+end[ \t]*-->",
    re.DOTALL,
)

# A start marker with no matching end, or the two in the wrong order, would
# otherwise make the block simply vanish from the comparison and report green.
LONE_MARKER = re.compile(r"<!--[ \t]*shared:([a-z0-9][a-z0-9-]*)[ \t]+(start|end)[ \t]*-->")


def collect(root: Path) -> tuple[dict[str, list[tuple[Path, str]]], list[str]]:
    """Return {block name: [(file, body)]} and a list of structural complaints."""
    found: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    problems: list[str] = []

    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8")

        paired: list[str] = []
        for name, body in BLOCK.findall(text):
            found[name].append((path, body))
            paired.append(name)

        # Every marker in the file has to belong to a pair this regex matched.
        # Counting rather than parsing is enough: a start and an end for each.
        seen: dict[str, int] = defaultdict(int)
        for name, _which in LONE_MARKER.findall(text):
            seen[name] += 1
        for name, count in seen.items():
            if count != 2 * paired.count(name):
                problems.append(
                    f"{path}: the markers for 'shared:{name}' are not a start "
                    f"followed by an end ({count} marker(s) found)"
                )

    return found, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when copies disagree. This is what CI runs.",
    )
    args = parser.parse_args()

    found: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    problems: list[str] = []
    for root in SEARCH_ROOTS:
        if not root.is_dir():
            print(f"{root} is not a directory. Run this from the repository root.", file=sys.stderr)
            return 2
        part, trouble = collect(root)
        for name, entries in part.items():
            found[name].extend(entries)
        problems.extend(trouble)

    failures = list(problems)

    for name in sorted(found):
        entries = found[name]
        first_path, first_body = entries[0]
        for path, body in entries[1:]:
            if body == first_body:
                continue
            diff = difflib.unified_diff(
                first_body.splitlines(keepends=True),
                body.splitlines(keepends=True),
                fromfile=str(first_path),
                tofile=str(path),
                n=2,
            )
            failures.append(
                f"'shared:{name}' differs between {first_path} and {path}:\n"
                + "".join(diff).rstrip()
            )

    if failures:
        print("Shared documentation blocks disagree.\n", file=sys.stderr)
        for failure in failures:
            print(failure, file=sys.stderr)
            print(file=sys.stderr)
        print(
            "Apply the change to every copy. These passages are repeated so that each\n"
            "runbook can be followed without leaving it, which only works while they agree.",
            file=sys.stderr,
        )
        return 1 if args.check else 0

    total = sum(len(v) for v in found.values())
    print(f"{len(found)} shared block(s), {total} copies, all in agreement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
