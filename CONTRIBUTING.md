# Contributing to Onibex ASK

Thank you for looking. Before anything else, one thing worth being direct about:

**ASK is source-available, not open source.** You can read it, evaluate it, study it
and build against it, and Onibex stewards both tracks of this repository. See
[`LICENSE`](LICENSE) for the map and [`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md)
for production use. Contributions are welcome on that footing.

## The two tracks

This repository holds two things with different licences and different review bars.
Which one you are touching decides how a change is handled:

| You are changing | Track | Reviewed as |
|---|---|---|
| `definition/` | The **ASK specification** (`ask-spec 1.0`): a published, vendor-neutral contract | A change to a contract other people have already implemented against. Slower, and deliberately so. |
| `platform/` | The **Onibex Agentic Semantic Knowledge Platform**, the runtime and its manual | An ordinary code or documentation change. |

## Before you open a pull request

**Discuss substantial changes first.** Open an issue and let us agree on the shape
before you spend time on the implementation. This is not bureaucracy: the
specification is the harder case, because a rule that changes meaning invalidates
YAML somebody has already authored.

**One concern per pull request.** A branch that fixes a bug and also renames things
is two reviews wearing one hat, and the second one gets less attention than it
deserves.

**Say what changes for a reader or a caller.** A commit message that explains why is
worth more than one that lists what, the diff already lists what.

## Changing the specification

`definition/` is the normative contract. The platform's AI-enrichment prompts are
rendered from these rules; they are never a second authority. So:

- **The code decides questions of fact.** Where the specification and the platform's
  behaviour disagree, one of them is defective. Say which, in the issue.
- **Open an RFC issue.** Put `[RFC]` in the title: for anything that changes a rule,
  a type, or whether a key is required.
- **New examples are especially welcome**, and non-SAP sources most of all. A PR adding
  a YAML under `definition/examples/` needs no RFC.
- The specification version is `MAJOR.MINOR`, no patch level, and moves more slowly
  than the platform. See the version policy in [`definition/README.md`](definition/README.md).

## Changing the platform

Run the checks the CI runs, from `platform/`:

```bash
ruff check .
pytest tests/boundary/
lint-imports
```

Package tests live with their package, `cd packages/ask-admin-api && pytest`.

House rules that reviewers will hold you to:

- **User-facing output is in English.** UI strings, documentation, commit messages.
- **ASK YAML goes through ruamel** (`load_yaml_text` / `dump_yaml`), never `import yaml`.
- **Documentation declares what is**, and never narrates what changed. The changelog is
  where change belongs.
- **Package boundaries are enforced**, not conventional, `.importlinter` contracts fail
  the build.

## Changing the documentation

The manual is `platform/docs/`, and it follows [Diátaxis](https://diataxis.fr):
**no page belongs to two genres.** A page that explains and also instructs is two pages.

| Genre | Job | Lives in |
|---|---|---|
| Tutorial | One guided path, learner chooses nothing | `GETTING_STARTED.md`. There is exactly one |
| How-to | One task, titled with a verb | `ask-setup/`, `ask-studio/`, `ask-chat/`, `guides/` |
| Reference | Look-up, no narrative | `reference/`, and `definition/` for the contract |
| Explanation | Why it works this way | `explain/` |

**One exception, taken deliberately.** A how-to page may carry a short **What you need to know
first** section. It is explanation on a task page, and it stays: the alternative is sending a
reader who is mid-task to another page for four sentences they need in order to follow the
next one. Keep it dense and decision-shaped: *"a registry, not a single connection"*, *"no
active connection blocks the chat"*, and keep it short. Anything longer belongs in `explain/`.

### The names

The three surfaces are **ASK Studio**, **ASK Chat** and **ASK Setup**. Studio was called *ASK
Admin* for most of this repository's life; only the `ask-admin-api` package kept that name. The
queryable unit is a **Data Product**, not an *entity*.

That last one is a judgement call, not a rule a build can apply: `entity_role` is a YAML key,
`entity id` and `cross-entity` are load-bearing, and an OData `entity set` belongs to OData. The
manual uses the word about a hundred times and nearly all of them are right. When you mean the
thing a reader creates in Studio, write **Data Product**.

### What the build enforces

- **Every page is listed in `platform/docs/README.md`** and carries a link back to it.
- **Every relative link resolves**, including `#heading-anchors`.
- **The surface names have not drifted back** to *ASK Admin*, `ask-admin/` or `admin-*.png`.

Check all three locally with:

```bash
python scripts/docs_links.py --check
python scripts/docs_terms.py --check
```

Both read only what git tracks, so run them **after** `git add` -- otherwise a new file passes
locally and fails in CI.

Found something inaccurate or confusing in the docs? That is a bug. Open a
**Documentation** issue. Reporting it is a contribution.

## Security

Do not open a public issue for a vulnerability. See [`SECURITY.md`](SECURITY.md).

## The terms

By submitting a contribution you confirm that it is yours to give, and you grant
Onibex, LLC permission to include it in this repository and distribute it under the
terms of the applicable licence, [`definition/LICENSE`](definition/LICENSE) or
[`platform/LICENSE.md`](platform/LICENSE.md).

Tooling you build *around* the specification is yours. The licence covers this
repository's own material, not what you write against the contract.
