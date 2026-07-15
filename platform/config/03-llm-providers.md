# ASK Setup · LLM Providers

> **Configuration flow.** Register the language models the agent may use. The page holds a
> **registry** of LLM connections, of which exactly **one is active** at any time, plus the
> single **shared embedder** that builds the platform's vector space.

| | |
|---|---|
| **Who** | Administrator |
| **Time** | ~2 minutes to add and activate a model |
| **Prerequisites** | You can sign in to **ASK Setup** (see [Installation](../01-installation.md)), and you have the provider's credentials to hand (API key, or cloud access keys). |
| **You'll end with** | One **active** LLM the agent uses for chat and SQL generation, and a configured **embedder** shared with ASK Admin. |

**Where this fits:** **Configure — LLM Providers (you are here)** → Author → Publish → Ask

> The screenshots and sample values below use illustrative, non-secret settings (an **AWS Bedrock**
> model). Substitute your own provider and model — and never type or screenshot a real API key,
> access key, or secret.

---

## Concepts (30-second version)

- The page is a **registry**: you can store many LLM connections (one per provider/model/account),
  but **exactly one is active** at a time. The active model is what chat and SQL generation call.
- The active model is **global — not per environment**. This is deliberately different from
  [Database Connections](02-database-connections.md), where one connection is active *per* dev and
  prod. There is one LLM for the whole deployment.
- **Secrets are encrypted at rest.** Every credential field marked **encrypted** is stored
  encrypted in the platform's secret store, never in `settings.json`. When you edit a connection,
  leaving a secret field blank **keeps** the stored value.
- The **first** connection you add is **activated automatically**, so the agent always has a model
  once you begin.
- The **embedder** is a separate, **single, org-wide** setting — the *same* configuration ASK Admin
  uses. It has no dev/prod split, and changing its provider or model is a disruptive operation
  (see step 6).
- The old **"Stack Mode"** control has been **removed** — you no longer pick a managed/direct stack;
  you register concrete provider connections directly.

---

## 1. Open the LLM Providers page

In the ASK Setup sidebar, open **LLM Providers**. The header describes the page — *"Register the
models the agent can use. One connection is active at a time (global — not per environment).
Secrets are encrypted at rest."* — with a **Refresh** button and a blue **Add LLM** button on the
right.

Below the header you'll see three areas: the **Active model** card, the **All LLM connections**
list, and the **Embedder** card.

![ASK Setup LLM Providers page: Active model card, the list of registered connections, and the shared Embedder card](../images/config-llm-providers.png)

If nothing is registered yet, the list shows an empty state — **"No LLM connections yet"** — with
an **Add LLM** button.

## 2. Add an LLM connection

Click **Add LLM**. A drawer titled **Add LLM connection** opens on the right (*"Pick a provider,
then enter its connection details."*). It has two numbered steps.

**Step 1 — Provider.** Pick a tile from the provider grid. The registry offers:

| Provider tile | Typical use |
|---|---|
| **AWS Bedrock** | Amazon Bedrock models (demo: `us.amazon.nova-pro-v1:0`). |
| **OpenAI** | OpenAI API models. |
| **Anthropic** | Claude models via the Anthropic API. |
| **Azure OpenAI** | OpenAI models hosted on Azure. |
| **Google Gemini** / **Google Vertex AI** | Gemini via the public API or via Vertex AI. |
| **Databricks** | Databricks-served models. |
| **SAP AI Core** | Models brokered through SAP AI Core deployments. |
| **Hugging Face (local)** | Locally served Hugging Face models. |

**Step 2 — Connection details.** The fields adapt to the provider you picked:

| Field | Required | Notes |
|---|---|---|
| **Display name** | Yes | A label you choose to recognise this connection — demo: *Bedrock Nova Pro (prod)*. |
| **Model** | Yes | Just the model id (the provider is already selected) — demo: `us.amazon.nova-pro-v1:0`. A few suggestions appear as you type. |
| Credential fields | Vary | Provider-specific. For Bedrock these include **AWS Access Key ID**, **AWS Secret Access Key**, **AWS Region**, and optional **AWS Session Token**; for OpenAI/Anthropic it's an **API Key**; SAP AI Core adds a **Deployment ID**. Fields marked **encrypted** are stored encrypted. |

Click **Save connection**. The drawer closes and the new connection appears in the list.

> **Tip — one account per connection.** Register a separate connection for each distinct
> model or account you want to switch between (for example a production model and a cheaper
> fallback). Only one is ever active at once, but keeping several ready makes switching instant.

## 3. Activate a model

Only the **active** model is used. Set it in either place:

- The **Active model** card at the top — use its dropdown (labelled *"used by chat"*) and choose a
  connection, or **— none —** to deactivate.
- A connection's **⋯** menu → **Set as active model** (a check mark shows which one is active).

The active connection is marked with a violet **Active** badge in the list, and the top card shows
its provider, name and model. When you activate one, a toast confirms *"<name> is now the active
model."*

> **Warning — no active model blocks the agent.** If no model is active, the Active model card
> shows an amber notice — *"No active model — chat & SQL generation are blocked until you activate
> one."* Always leave one connection active.

## 4. Test a connection

On any connection card, click **Test**. The platform makes a live call with the stored credentials
and reports the result as a toast — success shows the response and latency in milliseconds; failure
shows the error. Use this after adding or editing a connection, and after rotating a key.

## 5. Edit or delete a connection

- **Edit** — click **Edit** on a card. The drawer reopens as **Edit LLM connection** (*"Update
  details. Blank secret fields keep the stored value."*). Change the display name, model or
  credentials. **Leave a secret field blank to keep** the value already stored; type a new value
  only to replace it.
- **Delete** — open the **⋯** menu → **Delete**. A confirmation dialog appears. If you delete the
  **active** model it warns that the agent will have no LLM until you activate another (*"chat will
  be blocked"*). Deletion also removes the connection's encrypted credentials and cannot be undone.

A connection missing required credentials carries an amber **Incomplete** badge — finish it (or its
test will fail) before relying on it.

## 6. Configure the shared embedder

Below the connection list, the **Embedder** section (**single · global**) shows the embedding model
that turns your semantic layer, dictionary and docs into vectors. It carries a **Shared · ASK Admin**
badge because it is the *same* configuration ASK Admin uses — there is one embedder org-wide, with
**no dev/prod split**.

Click **Test** to verify it, or **Edit** to change it. The drawer opens as **Edit embedder**. Pick
the provider and model as in step 2 — demo: **AWS Bedrock** · `amazon.titan-embed-text-v2:0`.

> **Warning — changing the embedder rebuilds the vector space.** Rotating the embedder's
> *credentials* is safe. But changing its **provider or model** redefines the embedding vector
> space: **every** existing embedding — knowledge graph, semantic dictionary and docs, across
> **both dev and prod** — becomes incompatible and returns wrong or empty results until you
> **re-ingest and re-embed everything**. Vector dimensions may differ, so the indices are rebuilt
> from scratch; this is not automatic, and switching back will not restore rebuilt data. The drawer
> makes you tick an acknowledgement checkbox before it will save such a change.

![Edit embedder drawer showing the red "This changes the embedding vector space" warning and its acknowledgement checkbox](../images/config-llm-embedder-warning.png)

---

## What's next

→ **[ASK Setup · Identity Provider](04-identity-provider.md)** — who signs in, and how.
→ **[ASK Setup · Database Connections](02-database-connections.md)** — the peer registry, where the
active connection is chosen **per environment** (contrast the global active model here).
→ **[ASK Admin · Providers & Docs](../ask-admin/09-providers-docs.md)** — the ASK Admin side that
shares this embedder and ingests documents.
