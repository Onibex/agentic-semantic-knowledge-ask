#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Audit the licenses of every third-party dependency this repository pulls in.

THIRD-PARTY-NOTICES.md says "re-audit before a release". This is that audit,
so the instruction is a command rather than a reminder.

    python scripts/dependency_licenses.py            report
    python scripts/dependency_licenses.py --strict   exit 1 on a blocking license

Two passes, over what git actually publishes:

  * npm — every package-lock.json. Lockfile v3 records a `license` per resolved
    package, so this is the real transitive closure, not the declared surface.
  * Python — requirements.txt plus every pyproject.toml, expanded through the
    interpreter's installed metadata; anything not installed locally is looked
    up on PyPI so the audit does not silently skip it.

What matters here is a license that would force a change before publishing:
AGPL, SSPL, Elastic, BUSL, Confluent Community, strong GPL. Weak copyleft
(LGPL, MPL) is reported separately — normally fine when the component is used
unmodified, which is the case throughout, but it belongs in the notices file.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

BLOCKING = re.compile(
    r"\b(AGPL|GNU Affero|SSPL|Server Side Public|Elastic License|BUSL|"
    r"Business Source|Confluent Community|Commons Clause|CC-BY-NC|"
    r"Prosperity|Redis Source Available|RSAL)\b",
    re.I,
)
STRONG_COPYLEFT = re.compile(r"(?<!L)\bGPL(?!-compatible)|GNU General Public", re.I)
WEAK_COPYLEFT = re.compile(r"\bLGPL|MPL|Mozilla Public|EPL|CDDL\b", re.I)

# Not open source at all. These do not block use, but they carry their own
# redistribution terms and have to be named explicitly in the notices file.
PROPRIETARY = re.compile(
    r"SAP DEVELOPER LICENSE|SEE LICENSE IN|UNLICENSED|proprietary|all rights reserved", re.I
)

BLOCKED, STRONG, PROPRIETARY_V = "BLOCKING", "COPYLEFT", "PROPRIETARY"
WEAK, DUAL, UNKNOWN, OK = "WEAK-COPYLEFT", "DUAL", "UNKNOWN", "OK"

# Worst first, so a dual expression can be reduced to its least severe option.
SEVERITY = [BLOCKED, STRONG, PROPRIETARY_V, WEAK, UNKNOWN, OK]


def classify_one(license_text: str) -> str:
    if not license_text or license_text.lower() in {"unknown", "none", "null"}:
        return UNKNOWN
    if BLOCKING.search(license_text):
        return BLOCKED
    if STRONG_COPYLEFT.search(license_text):
        return STRONG
    if PROPRIETARY.search(license_text):
        return PROPRIETARY_V
    if WEAK_COPYLEFT.search(license_text):
        return WEAK
    return OK


def classify(license_text: str) -> str:
    """Classify a license expression, reading OR as the choice it is.

    "BSD-3-Clause OR GPL-2.0" is not a GPL obligation: the licensor offers both
    and the licensee elects one. Reporting that as copyleft is a false alarm,
    and false alarms train people to skip the report. AND is different - both
    apply - so only OR gets this treatment.
    """
    if not license_text:
        return UNKNOWN
    alternatives = [part for part in license_text.strip().strip("()").split(" OR ")]
    if len(alternatives) > 1:
        verdicts = [classify_one(alt.strip().strip("()")) for alt in alternatives]
        if OK in verdicts:
            return DUAL  # a permissive option is on the table; elect it
        return min(verdicts, key=SEVERITY.index)
    return classify_one(license_text)


def tracked(pattern: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", pattern], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return [REPO / line for line in out if line.strip()]


def scan_npm() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for lock in tracked("*package-lock.json"):
        data = json.loads(lock.read_text(encoding="utf-8"))
        packages: dict[str, str] = {}
        for path, meta in data.get("packages", {}).items():
            if not path:  # the root project itself
                continue
            name = meta.get("name") or path.split("node_modules/")[-1]
            license_text = meta.get("license")
            if isinstance(license_text, dict):
                license_text = license_text.get("type", "")
            if isinstance(license_text, list):
                license_text = " OR ".join(str(item) for item in license_text)
            packages[name] = license_text or "UNKNOWN"
        result[str(lock.relative_to(REPO)).replace("\\", "/")] = packages
    return result


def declared_python() -> set[str]:
    names: set[str] = set()
    requirements = REPO / "platform" / "requirements.txt"
    if requirements.exists():
        for line in requirements.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if line and not line.startswith("-"):
                names.add(re.split(r"[<>=!~\[; ]", line)[0].strip().lower())
    for pyproject in tracked("*pyproject.toml"):
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        for dep in data.get("project", {}).get("dependencies", []) or []:
            names.add(re.split(r"[<>=!~\[; ]", dep)[0].strip().lower())
    return {name for name in names if name and not name.startswith("ask-")}


def license_of_installed(dist) -> str:
    metadata = dist.metadata
    expression = metadata.get("License-Expression")
    if expression:
        return expression
    classifiers = [c for c in metadata.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return "; ".join(c.split("::")[-1].strip() for c in classifiers)
    declared = metadata.get("License")
    if declared and len(declared) < 120:
        return declared.replace("\n", " ")
    return "UNKNOWN"


def license_from_pypi(name: str) -> str:
    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=20) as response:
            info = json.load(response)["info"]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        return "UNKNOWN"
    declared = info.get("license_expression") or info.get("license") or ""
    if not declared or len(declared) > 80:
        classifiers = [
            c.split("::")[-1].strip()
            for c in info.get("classifiers", [])
            if c.startswith("License ::")
        ]
        declared = "; ".join(classifiers) or "UNKNOWN"
    return declared.replace("\n", " ")


def scan_python(offline: bool) -> dict[str, str]:
    from importlib import metadata as importlib_metadata

    installed = {
        dist.metadata["Name"].lower(): dist
        for dist in importlib_metadata.distributions()
        if dist.metadata["Name"]
    }
    direct = declared_python()
    found: dict[str, str] = {}

    queue = list(direct & installed.keys())
    while queue:
        name = queue.pop()
        if name in found:
            continue
        dist = installed[name]
        found[name] = license_of_installed(dist)
        for requirement in dist.requires or []:
            if "extra ==" in requirement:  # optional extras are not installed by default
                continue
            child = re.split(r"[<>=!~\[; (]", requirement)[0].strip().lower()
            if child in installed and child not in found:
                queue.append(child)

    for name in sorted(direct - installed.keys()):
        found[name] = "UNKNOWN (not installed)" if offline else license_from_pypi(name)
    return found


def report(title: str, packages: dict[str, str]) -> list[tuple[str, str, str]]:
    findings: list[tuple[str, str, str]] = []
    buckets: dict[str, list[str]] = defaultdict(list)
    for name, license_text in sorted(packages.items()):
        verdict = classify(license_text)
        buckets[verdict].append(f"{name} -> {license_text}")
        if verdict != OK:
            findings.append((verdict, name, license_text))

    print(f"\n### {title}  ({len(packages)} packages)")
    for verdict in (BLOCKED, STRONG, PROPRIETARY_V, WEAK, DUAL, UNKNOWN):
        rows = buckets.get(verdict)
        if not rows:
            continue
        print(f"  [{verdict}] {len(rows)}")
        for row in rows[:15]:
            print(f"      - {row}")
        if len(rows) > 15:
            print(f"      ... and {len(rows) - 15} more")
    print(f"  [OK] {len(buckets.get(OK, []))}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit 1 if a blocking license appears")
    parser.add_argument("--offline", action="store_true", help="skip the PyPI lookup for uninstalled packages")
    args = parser.parse_args()

    findings: list[tuple[str, str, str]] = []

    print("=" * 78)
    print("npm — from the lockfiles (real transitive closure)")
    print("=" * 78)
    for lock, packages in scan_npm().items():
        findings += report(lock, packages)

    print()
    print("=" * 78)
    print("Python — requirements.txt + pyproject.toml, expanded transitively")
    print("=" * 78)
    findings += report("Python closure", scan_python(args.offline))

    blocking = [f for f in findings if f[0] in (BLOCKED, STRONG)]
    proprietary = [f for f in findings if f[0] == PROPRIETARY_V]
    weak = [f for f in findings if f[0] == WEAK]
    dual = [f for f in findings if f[0] == DUAL]
    unknown = [f for f in findings if f[0] == UNKNOWN]

    print()
    print("=" * 78)
    if blocking:
        print(f"{len(blocking)} license(s) require a decision before publishing:")
        for verdict, name, license_text in blocking:
            print(f"  {verdict}: {name} -> {license_text}")
    else:
        print("No AGPL, SSPL, Elastic, BUSL, Confluent Community or strong GPL.")
    if proprietary:
        print(f"\nNot open source - name each one in THIRD-PARTY-NOTICES.md ({len(proprietary)}):")
        for _, name, license_text in proprietary:
            print(f"  {name} -> {license_text}")
    print(f"\nWeak copyleft (LGPL/MPL — fine while used unmodified): {len(weak)}")
    print(f"Dual-licensed, permissive option elected: {len(dual)}")
    print(f"License not declared (check by hand): {len(unknown)}")
    print("\nTHIRD-PARTY-NOTICES.md must reflect anything listed above.")

    return 1 if (blocking and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
