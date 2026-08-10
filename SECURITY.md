# Security Policy

The Onibex ASK Platform connects to enterprise systems (SAP, databases, identity
providers). We take vulnerability reports seriously and appreciate responsible
disclosure.

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Use GitHub's private vulnerability reporting: go to the repository's **Security**
tab → **Report a vulnerability**. Reports go directly and privately to the
maintainers.

Please include: the affected component (package, SPA, endpoint), reproduction
steps, and the impact you believe it has. Proof-of-concept code is welcome.

## Scope

- `platform/**` — the ASK Platform code (orchestrator, admin API, SPAs, deploy
  tooling).
- `definition/**` — specification documents; content issues there are normal
  issues, not security reports.

Out of scope: vulnerabilities in third-party dependencies with no exploitable
path through this project (report those upstream), and issues that require a
misconfigured deployment explicitly warned against in the documentation.

## Response

We aim to acknowledge reports within 5 business days. Confirmed vulnerabilities
are fixed on `main` and noted in the advisory; credit is given unless you prefer
otherwise.
