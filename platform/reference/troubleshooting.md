# Troubleshooting & FAQ

> **Reference page.** When an answer comes back empty, an environment behaves
> unexpectedly, or the platform won't start from zero, look up the **symptom** below and follow
> the **fix**. Most "it's broken" reports trace back to one rule: the chat only sees Data
> Products that have been **published to the environment it is querying**.

| | |
|---|---|
| **Who** | Business users and administrators |
| **Time** | Look up your symptom — most fixes are one action |
| **Prerequisites** | The platform is deployed and running (see [Installation](../01-installation.md)). |
| **You'll end with** | A resolved symptom, or a clear next step for your administrator or ops team. |

**Where this fits:** Configure → Author → Publish → Ask → **Reference — troubleshooting (you are here)**

> The screenshots and sample values below use an illustrative **SAP Production Planning** example (Production Orders). Substitute your own Data Products — the exact demo names and questions won't exist in your system.

---

## Concepts (30-second version)

- The chat can only answer from Data Products an administrator has **published** to the
  environment being queried (**dev** or **prod**). If nothing is published, answers come back
  empty even though the platform is "working" — this is the single most common cause of "why do
  I get no results?".
- Publishing is **gated dev → prod**: you publish to **dev** first, then promote to **prod**
  once dev is current. So `dev` showing data while `prod` is empty is normal, not a bug.
- Answer *quality* (which column the agent picks) depends on the **descriptions and synonyms**
  in your semantic layer and the **semantic dictionary** — that's how a user's words map to your
  columns.

---

## Symptom → Cause → Fix

Find your symptom in the first column. "You do" fixes are self-serve; "Administrator" / "Ops"
fixes need the person who set up the platform.

| Symptom | Likely cause | What to do |
|---|---|---|
| **"No workspaces configured"** in chat | No workspace exists yet, or none is published. | *Administrator:* create one in **ASK Admin → Workspaces** and publish a business domain into the environment. See [Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md). |
| Chat returns **empty results** | Nothing is published to the selected environment. | Switch the environment selector to **dev**; if still empty, ask the administrator to publish the business domain (e.g. *Production Orders*) to that environment. |
| **`prod` returns nothing, `dev` works** | Data Products are published to **dev** only. | *Administrator:* promote them to **prod** in ASK Admin — the prod publish becomes available only once **dev is current** (the dev → prod gate). |
| Answer uses the **wrong column** (e.g. picks scrap instead of yield) | Missing synonyms, or an ambiguous business term. | *Administrator:* enrich the Data Product's field descriptions/synonyms, or add the term to the **semantic dictionary** (e.g. map *good quantity / yield* → `AFRU.LMNGA`). |
| **404 / "could not reach LLM / embeddings"** | The LLM or embeddings provider is misconfigured or unreachable. | *Administrator:* open the **Configuration app**, re-**Test** the provider, and save. Verify the model id and endpoint. |
| **401 / Unauthorized** | Expired or missing login session, or bad provider credentials. | Sign in again. If it persists, the administrator should verify the provider credentials (and, on cluster deployments, the identity-provider wiring) in the Config app. |
| **First question is slow** | Cold start — the model/provider is warming up. | Expected on the first call after an idle period; subsequent questions are faster. No action needed. |
| **Publish stalls / seems hung** | A per-Data-Product step is still running (large domains stream progress). | Watch the streamed per-Data-Product progress. Let it finish, use **Stop** to halt the run, then **retry** the publish. |
| **OneConnect merge shows a conflict pending** | A merged field differs from the existing Data Product; the platform won't silently overwrite hand-authored content. | *Administrator:* resolve it under the **Conflicts** filter in Semantic Knowledge (see [Add Data Products · From OneConnect](../ask-admin/02-add-data-products.md#mode-d--from-oneconnect)). |
| **Chat / query returns 500** with a `trace_id` | A backend dependency failed (search index or database connection). | *Ops:* note the `trace_id` and check the orchestrator logs for it; common roots are OpenSearch or the target database being unreachable — your platform / ops team checks the orchestrator logs. |

---

## From-zero footguns (first Docker boot)

These bite a **fresh deployment** the first time you bring it up. They are configuration/boot
issues, not usage issues — hand them to whoever installed the platform.

| Symptom | Likely cause | What to do |
|---|---|---|
| First query fails / search never returns | `opensearch.host` is set to `localhost` | Inside Docker Compose the search service is reachable as **`opensearch`**, not `localhost`. Set the search host to `opensearch` (port `9200`). |
| Platform **won't start** / fails closed at boot | `ONIBEX_ENCRYPTION_KEY` is missing | This key encrypts stored provider secrets and is **required** — the platform deliberately fails to boot without it. *Ops:* generate a valid key and set the environment variable, then restart. |
| **Publish to an environment fails** on a from-zero deploy | The semantic-layer repo has no `.git` → no `dev` / `prod` branches exist | Publishing writes to per-environment branches. On a from-zero deploy the semantic-layer repo must be **git-initialized** (a `main` branch + seed commit) before publish works. *Ops:* initialize the repo, then retry the publish. |

> **Warning —** the from-zero footguns above block the platform from ever answering a question,
> so they can look like a broken product. They are almost always one missing setting. Check the
> installer's runbook and the boot logs first.

---

## FAQ

**Why do I get empty answers when the platform is clearly running?**
Because the chat only sees Data Products **published to the environment you selected**. Confirm
your administrator has published the relevant business domain to that environment (dev or prod),
and that your environment selector matches.

**Why does `dev` have data but `prod` is empty?**
Publishing is gated **dev → prod**. New content is published to **dev** first and only promoted
to **prod** once dev is current. An empty `prod` usually just means the promotion hasn't happened
yet — ask your administrator to promote it.

**The agent answered with the wrong field. How do I fix it going forward?**
That's a semantic-layer signal, not a one-off. Have the administrator improve the Data Product's
field **descriptions and synonyms**, or add the business term to the **semantic dictionary** so
the mapping is pinned (for example, *good quantity* / *yield* → `AFRU.LMNGA`, and *scrap* →
`AFRU.XMNGA`).

**Which agent mode should I use if answers look off?**
Start with **Smart** (the balanced default). If you need a more rigorously validated,
reproducible result — or you want the agent to justify exactly which tables and joins it used —
switch to **Precise**.

**The first question of the day is slow — is something wrong?**
No. That's a normal **cold start** while the provider warms up. Subsequent questions are faster.

**Publishing seems stuck. Should I refresh?**
No — watch the streamed per-Data-Product progress. Large domains take a moment. If it truly
stalls, use **Stop** to halt the run and then **retry** the publish; don't reload mid-publish.

**I merged a OneConnect export and nothing changed — why the "conflict"?**
When a merged field differs from what already exists, the platform surfaces a **conflict** rather
than overwrite hand-authored content. Resolve it under the **Conflicts** filter in Semantic
Knowledge; auto-applied (non-conflicting) changes land immediately.

**I get 401 Unauthorized even after logging in.**
Your session likely expired — sign in again. If it recurs, the provider credentials or the
identity-provider wiring may be off; that's an administrator/ops check in the Config app
(orchestrator logs and auth wiring).

> **Tip —** when reporting a data-question failure to your administrator, include the exact
> question you typed, the **workspace** and **environment** you had selected, and the agent
> **mode**. If the UI can reveal the generated SQL or a trace, include that too — it turns a vague
> "it didn't work" into a one-look fix.

---

## What's next

→ **[Flow 1 · Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md)** — create and
publish the containers the chat scopes to.
→ **[Flow 2 · Add Data Products](../ask-admin/02-add-data-products.md)** — author and enrich the
entities the agent maps questions to.
→ **Deep ops diagnostics** — handled by your platform / ops team (health checks, auth wiring,
`trace_id` lookups in the orchestrator logs).

---

*Found something inaccurate or confusing? That's a documentation bug — open an issue or ping the
platform team so the next person doesn't hit it.*
