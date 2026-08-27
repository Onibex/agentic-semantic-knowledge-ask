# Getting help

Where to go depends on what you need. Picking the right one saves you a round trip.

| You want to… | Go to |
|---|---|
| **Understand how something works** | The [platform manual](platform/docs/README.md), starting with [Getting Started](platform/docs/GETTING_STARTED.md) |
| **Fix something that is not working** | [Troubleshooting & FAQ](platform/docs/reference/troubleshooting.md) — symptom, cause, fix |
| **Report a bug** | A [Bug issue](https://github.com/Onibex/agentic-semantic-knowledge-ask/issues/new?template=bug.yml) |
| **Report something wrong in the documentation** | A [Documentation issue](https://github.com/Onibex/agentic-semantic-knowledge-ask/issues/new?template=documentation.yml) — this counts as a bug, and we treat it as one |
| **Propose a change to the specification** | An [RFC issue](https://github.com/Onibex/agentic-semantic-knowledge-ask/issues/new?template=rfc.yml) |
| **Report a vulnerability** | **Not** a public issue — see [`SECURITY.md`](SECURITY.md) |
| **Use ASK in production, or ask about licensing** | contact@onibex.com |

## Before opening an issue

Two things make a report actionable, and their absence is the usual reason one stalls:

- **What you expected, and what happened instead.** A description of the broken thing
  is worth more than a description of the fix you had in mind.
- **Enough to reproduce it.** The engine mode, the environment (`dev` / `prod`), and the
  generated SQL if the problem is an answer. Redact credentials and business data.

## What this repository is not

ASK is **source-available, not open source** — see [`LICENSE`](LICENSE). There is no
community support commitment: issues are read by the maintainers and answered as
capacity allows. Production use requires a
[commercial licence](COMMERCIAL-LICENSE.md), and that comes with a support channel
that does not depend on this tracker.

Being explicit about that is more useful than implying a promise nobody is on the hook
for.
