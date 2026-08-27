#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Keep every version string in the repository on the same number.

    python scripts/versions.py                 report what each manifest says
    python scripts/versions.py --check         fail if they disagree (CI gate)
    python scripts/versions.py --set 1.1.0     move all of them at once

One number for the whole repository. None of these packages is published to
PyPI or npm — they are built from source — so a per-package version would only
be a second clock to keep, and a clock nobody winds always drifts. What the
field does carry, in a public repository, is a signal to whoever reads it: a
manifest saying 0.1.0 next to a v1.0.0 release reads as an unstable component
inside a stable product.

Covered: CITATION.cff, every pyproject.toml with a [project] table, every
package.json outside node_modules, and the version badge on the front page --
a number a reader sees before anything else, and the one most likely to be
forgotten. On a tag build the gate also checks the tag itself, so a release
cannot go out describing a version the code does not claim.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
# The shields.io badge on the front page: .../badge/platform-1.1.0-2f6feb.svg
BADGE = re.compile(r"(badge/platform-)([0-9A-Za-z.\-]+?)(-[0-9a-fA-F]{6}\.svg)")


def tracked(pattern: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", pattern], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return [REPO / line for line in out if line.strip()]


def manifests() -> list[Path]:
    files = [REPO / "CITATION.cff"]
    files += [p for p in tracked("*pyproject.toml") if "[project]" in p.read_text(encoding="utf-8")]
    files += [p for p in tracked("*package.json") if "node_modules" not in p.parts]
    files.append(REPO / "README.md")
    return [p for p in files if p.is_file()]


def read_version(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    if path.name == "README.md":
        match = BADGE.search(text)
        return match.group(2) if match else None
    if path.suffix == ".json":
        return json.loads(text).get("version")
    match = re.search(r'^version\s*[:=]\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def write_version(path: Path, version: str) -> bool:
    # newline="" on both sides: read the file as it is on disk and write it
    # back the same way. Without it a release bump silently rewrites CRLF to
    # LF across every manifest, and the diff of the bump is fifteen files of
    # line endings with the version change buried in them.
    text = path.read_text(encoding="utf-8", newline="")
    if path.name == "README.md":
        updated = BADGE.sub(rf"\g<1>{version}\g<3>", text, count=1)
        if updated == text:
            return False
        path.write_text(updated, encoding="utf-8", newline="")
        return True
    if path.suffix == ".json":
        # Rewritten as text, not via json.dump, so formatting and key order survive.
        updated = re.sub(r'("version"\s*:\s*)"[^"]+"', rf'\1"{version}"', text, count=1)
    else:
        updated = re.sub(r'^(version\s*[:=]\s*)"[^"]+"', rf'\1"{version}"', text, count=1, flags=re.MULTILINE)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8", newline="")
    return True


def tag_version() -> str | None:
    """The tag being built, when this runs in CI on a tag push."""
    ref = os.environ.get("GITHUB_REF", "")
    if ref.startswith("refs/tags/"):
        return ref.removeprefix("refs/tags/").lstrip("v")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the versions disagree")
    parser.add_argument("--set", dest="new", metavar="X.Y.Z", help="set every manifest to this version")
    args = parser.parse_args()

    if args.new:
        if not SEMVER.match(args.new):
            print(f"'{args.new}' is not a semantic version (X.Y.Z, optionally -rc.1)")
            return 1
        changed = [p for p in manifests() if write_version(p, args.new)]
        for path in changed:
            print(f"  {path.relative_to(REPO)} -> {args.new}")
        print(f"\n{len(changed)} manifest(s) set to {args.new}.")
        print("Remember the tag, the CITATION date-released, the CHANGELOG and the release notes.")
        return 0

    found: dict[str, list[str]] = {}
    for path in manifests():
        version = read_version(path) or "(none)"
        found.setdefault(version, []).append(str(path.relative_to(REPO)).replace("\\", "/"))

    for version, paths in sorted(found.items()):
        print(f"{version}  ({len(paths)})")
        for path in paths:
            print(f"    {path}")

    if not args.check:
        return 0

    if len(found) > 1:
        print("\nManifests disagree. One repository, one version.")
        print("Fix with: python scripts/versions.py --set X.Y.Z")
        return 1

    declared = next(iter(found))
    tag = tag_version()
    if tag and tag != declared:
        print(f"\nTag v{tag} does not match the version the code declares ({declared}).")
        return 1

    print(f"\nversions OK — everything says {declared}" + (f", matching tag v{tag}" if tag else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
