# ASK Chat · Using the Chat

> **The end-user manual for the ASK Chat.** Everything the admin authored and published now
> pays off here: you ask a question in plain language and the agent answers from your governed
> semantic layer — a written answer, a results table, a chart, and (if you want) the SQL and
> the trace behind it.

| | |
|---|---|
| **Who** | Business user / analyst — anyone who needs an answer from the data |
| **Time** | Seconds per question |
| **Prerequisites** | You can sign in to **ASK Chat**; a **Workspace** exists with at least one Data Product **published** to the environment you pick (an admin does this in [Publish & Deploy](../ask-admin/05-publish-deploy.md)). |
| **You'll end with** | Answers to your questions — text, tables and charts — plus optional documents you can download. |

**Where this fits:** Configure → Author → Publish → **Ask (you are here)**

> The screenshots and sample values below use an illustrative **SAP Production Planning** example (Production Orders). Substitute your own Data Products — the exact demo names and questions won't exist in your system.

> **Note.** This page describes the chat at the **concept and flow level** — the ideas below
> (pick a workspace and environment, choose an agent mode, ask, read the answer, generate
> artifacts) are what matter. The interface continues to evolve, so the exact widgets, colours
> and placement in your deployment may differ from the screenshots.

---

## Concepts (30-second version)

- A **Workspace** scopes what the agent can see. You must pick one before you can ask anything —
  it is the same workspace an admin created in
  [Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md).
- An **Environment** (**dev** or **prod**) chooses *which published snapshot* the agent queries.
  A Data Product only answers in an environment it was actually published to.
- An **Agent Mode** (**Flash** / **Precise** / **Smart**) decides *how hard the agent works* to
  turn your question into SQL. It only affects data questions — see the guidance below.
- You ask in **natural language**, in any language. The agent classifies what you're really
  asking (get data, describe the schema, or explain the documentation) and answers accordingly.

---

## 1. Pick a Workspace (required)

In the sidebar, under **Workspace**, choose the workspace you want to query. This is a hard
requirement: until a workspace is selected, the agent has nothing to scope to and will refuse
the question.

![Chat sidebar with the Workspace picker, the demo workspace selected](../images/chat-sidebar-workspace.png)

| Control | Behavior |
|---|---|
| **Workspace** (dropdown) | The workspace the agent scopes to. Shows each workspace as *Name (slug)*. Your choice persists for the session. |
| **Reload workspaces** | Re-fetches the list — click it if an admin just created a workspace and it isn't showing yet. |

> **Warning —** if the sidebar says *No workspaces configured*, no workspace has been created
> yet, or your sign-in didn't carry through. Ask an admin to create one in
> [Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md), then click
> **Reload workspaces**.

## 2. Pick an Environment (dev / prod)

Under **Environment**, choose which published snapshot to query:

| Option | What it targets |
|---|---|
| **dev** *(default)* | The development snapshot. Everything an admin publishes goes to **dev** first, so this is the safe default. |
| **prod** | The promoted, production snapshot. Only content that was promoted from dev to prod lives here. |

If you pick an environment a Data Product was never published to, the agent simply finds nothing
to answer from — so if a question comes back empty, confirm the entity is published to *this*
environment.

> **Tip —** start in **dev** while a model is being built and reviewed; switch to **prod** once
> the admin has promoted it. See [Publish & Deploy](../ask-admin/05-publish-deploy.md) for how
> content moves between the two.

## 3. Choose an Agent Mode

Under **Agent Mode**, pick how the agent should resolve **data questions**. The mode only
changes the SQL path — schema questions, documentation questions and SAP actions are unaffected.

| Mode | Plain-English guidance |
|---|---|
| **Flash** | Free-form search across the data product. Fast, broad coverage — good for a quick look. |
| **Precise** | Calculated and thorough; handles the "messy" data where exact resolution matters. |
| **Smart** *(default)* | The intuitive, all-rounder. Balances speed and accuracy — leave it here unless you have a reason to switch. |

![Agent Mode selector showing Flash, Precise and Smart with Smart selected](../images/chat-mode-selector.png)

> **Tip —** if a data answer looks incomplete or the agent struggles to map an unusual phrasing,
> re-ask the same question in **Precise**. For everyday questions, **Smart** is the right default.

## 4. Ask a question

Type your question in the input at the bottom of the chat — in any language, in business terms.
You don't need to know table or column names; the agent maps your words to the governed semantic
layer.

Using the demo's **Production Orders** model, try:

| What you want | Question to type |
|---|---|
| Data with a chart | `What is the total confirmed yield versus scrap quantity by plant for production orders finished this year?` |
| Data | `Show me the top 10 materials by total planned order quantity in plant 1000 this quarter.` |
| Schema | `What tables and fields make up the production_order entity, and how are AFKO and AFPO joined?` |
| Documentation | `How is the yield rate defined in this model, and which SAP fields does it use?` |

The agent decides what kind of question you asked and answers accordingly: it may run a query,
describe the model's structure, or explain a definition from the documentation — you don't pick
the type, the wording does.

## 5. Read the answer

For a **data question**, the agent replies with a **written answer** in plain language, and — when
the result has more than one row — an **auto-generated chart** underneath it. A grouped question
like the first demo question above (yield vs. scrap **by plant**) returns several rows and draws a
bar chart automatically.

![A chat turn: the confirmed-yield-vs-scrap-by-plant question, the written answer, and an auto-generated bar chart](../images/chat-answer-with-chart.png)

The sidebar's **Display Options** let you decide how much detail to see with each answer:

| Option | What it does |
|---|---|
| **Show SQL queries** | Prints the exact SQL the agent ran, above the answer, so you can verify or reuse it. |
| **Show token usage** | Adds a running **Token Usage (session)** panel in the sidebar and a per-turn breakdown. |
| **Show debug logs** | Tags each answer with the detected question type (its *macro intent*). |
| **Auto-generate charts** | On by default; turns the automatic chart under multi-row results on or off. |

When **Show token usage** is on, each assistant answer carries a collapsible
**Pipeline trace & tokens** section reporting the number of LLM calls and tokens, broken down by
pipeline phase and per call — useful for understanding cost and how the answer was produced.

![The Pipeline trace & tokens panel expanded under an answer, showing per-phase token counts](../images/chat-trace-tokens.png)

For a **schema** question the agent describes the entity's structure (tables, fields, joins); for
a **documentation** question it explains the definition and the SAP fields behind it. Neither runs
a query, so they won't produce a results chart.

> **Tip —** each answer is part of a conversation. You can ask a follow-up in the same chat
> ("now break that down by month") and the agent keeps the earlier context. Use **+ New Chat** in
> the sidebar to start a clean thread.

---

## Artifacts — generate documents

The **Artifacts** page turns your data into a shareable document — a report, an executive brief,
a data-table pack or a dashboard — without you writing anything but a few answers.

From the Artifacts gallery, click **New Artifact** to open a short guided wizard. It walks you
through, one question at a time:

1. **Document type** — **Report**, **Executive Brief**, **Data Tables**, **Dashboard**, or
   **Custom**. Each explains what it produces.
2. **Purpose / audience** — who will read it and what decision it should support.
3. **Data source** — e.g. **SAP S/4HANA**.
4. **Data to include** — describe what you need in plain language.
5. **Name** — accept the suggested name or type your own.
6. **Generate** — review the summary, then click **Generate Document**.

The same **Workspace**, **Environment** and mode selectors from the chat apply here, so the
document is built from the data you'd get by asking. When it's done you can preview it, **Download
Excel** (a dashboard also offers **Download HTML** with an interactive chart), **Edit** it — where
you can tweak the purpose, data focus, or even the underlying **SQL Query** and **Refresh &
Regenerate** — or **Delete** it.

![The Artifacts gallery with the New Artifact button and a few saved document cards](../images/chat-artifacts.png)

---

## User Profile — briefly

The **User Profile** page shows an **AI-generated profile** built from your chat history — your
work context, what's top of mind, and a brief history of what you've been analyzing. Click
**Refresh Profile** to (re)build it from your recent conversations; if you've only just started,
it will tell you there isn't enough history yet. It's a personalization aid — nothing here changes
what the agent can query.

---

## What's next

→ **[Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md)** — where the
workspace you pick in the sidebar comes from.
→ **[Publish & Deploy](../ask-admin/05-publish-deploy.md)** — how content reaches the **dev** and
**prod** environments you choose between.
→ **[Add Data Products](../ask-admin/02-add-data-products.md)** — the entities the agent maps your
questions to.
