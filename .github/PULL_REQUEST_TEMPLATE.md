## What changes, and why

<!-- The diff already says what. Say why, and what it changes for a reader or a caller. -->

## Which track

<!-- Delete the ones that do not apply. -->

- [ ] `definition/`, the **specification**. A rule that changes meaning invalidates YAML
      somebody has already authored. Link the `[RFC]` issue, or say why none was needed.
- [ ] `platform/`, the runtime or its manual.

## Documentation

- [ ] **This change alters something a reader was told.** The docs are updated in this PR.
- [ ] It does not. Nothing documented behaves differently.

<!--
Not a formality. The audit that produced the current manual found 34 dead links, a
specification forked in two places, and AI enrichment running with no rules at all in
every container: none of it noticed, because each change was individually reasonable
and nobody checked what it made untrue.
-->

## Checks

<!-- Say what you ran, not what you assume. Untested is a fine answer; silent is not. -->

- [ ] `ruff check .` from `platform/`
- [ ] `pytest tests/boundary/` and the tests of any package touched
- [ ] `python scripts/docs_links.py --check` if documentation changed
- [ ] Ran it against a live stack

## Anything a reviewer should look at first

<!-- The part you are least sure about. Saying so gets it reviewed properly. -->
