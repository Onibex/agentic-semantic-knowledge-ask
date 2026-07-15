# ASK Chat · Using the Chat

> **The end-user manual for ASK Chat.** Everything the admin authored and published now pays
> off here: you ask a question in plain language and the agent answers from your governed
> semantic layer — a written answer, a results table, and (when the data supports it) a chart.
> You can also turn those answers into a shareable document.

| | |
|---|---|
| **Who** | Business user — anyone who needs an answer from the data |
| **Time** | Seconds per question |
| **Prerequisites** | You can sign in to **ASK Chat**; a **Workspace** exists with at least one Data Product **published** to the environment you pick (an admin does this in [Publish & Deploy](../ask-admin/05-publish-deploy.md)). |
| **You'll end with** | Answers to your questions — written text, tables and charts — plus optional Excel documents you can download. |

**Where this fits:** Configure → Author → Publish → **Ask (you are here)**

> The screenshots and sample questions below use an illustrative **SAP Production Planning** example (Production Orders). Substitute your own Data Products — the exact demo names and questions won't exist in your system.

> **Note.** This page describes the chat at the **concept and flow level** — pick a workspace and environment, choose a mode, ask, read the answer, generate artifacts. The interface continues to evolve, so the exact widgets, colours and placement in your deployment may differ from the screenshots.

---

## Concepts (30-second version)

- The **left sidebar** carries the three selectors that scope every question — **Workspace**,
  **Environment** and **Mode** — plus the navigation (**Home**, **Chat**, **Artifacts**) and,
  at the bottom, your signed-in identity.
- A **Workspace** scopes what the agent can see. You must pick one before you can ask anything —
  it is the same workspace an admin created in
  [Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md).
- An **Environment** (**dev** or **prod**) chooses *which published snapshot* the agent queries.
  A Data Product only answers in an environment it was actually published to.
- A **Mode** (**Flash** / **Precise** / **Smart**) decides *how* the agent turns your question
  into SQL. **Precise is the default** — leave it there unless you have a reason to switch.
- You ask in **natural language**, in any language. The agent classifies what you're really
  asking — retrieve data, describe the model's structure, or explain a definition — and answers
  accordingly.
- Your selections and your conversations **persist** across sessions, so you return to where you
  left off.

---

## 1. Pick a Workspace (required)

In the sidebar, under **Workspace**, open the dropdown (it opens on **Select workspace…**) and
choose the workspace you want to query. This is a hard requirement: until a workspace is selected,
the chat shows a reminder and the agent will not answer.

![Chat left sidebar with the Workspace dropdown, the demo workspace selected](../images/chat-sidebar-workspace.png)

Each workspace appears by its name. Your choice is remembered for next time.

> **Warning —** if the dropdown offers only **Select workspace…** with no entries, no workspace
> has been created yet, or your sign-in didn't carry through. Ask an admin to create one in
> [Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md).

> **Tip —** the bottom of the sidebar shows the signed-in user with a small role chip
> (for example **ask-admin** or **ask-user**) and a **Sign out** control. The role reflects
> what you are permitted to do across the platform.

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

## 3. Choose a Mode

Under **Mode**, pick how the agent should resolve **data questions**. The mode changes how the
question is turned into SQL; it does not change what you can ask.

| Mode | When to use it |
|---|---|
| **Flash** | Fastest. A broad, retrieval-based pass over the published model — good for a quick look. |
| **Precise** *(default)* | Deterministic resolution through the semantic layer. The dependable choice for everyday questions; leave it here unless you have a reason to switch. |
| **Smart** | A catalog-driven, graph-based approach suited to exploratory questions over a larger model. |

![The Mode selector in the sidebar showing Flash, Precise and Smart, with Precise selected](../images/chat-mode-selector.png)

> **Tip —** if a data answer looks incomplete or the agent struggles with an unusual phrasing,
> re-ask the same question in a different mode. For everyday questions, **Precise** is the right
> default.

## 4. Ask a question

Type your question in the box at the bottom of the chat — in any language, in business terms.
You don't need to know table or column names; the agent maps your words to the governed semantic
layer. Press **Enter** to send (**Shift+Enter** starts a new line).

When a chat is empty, the agent greets you with **What would you like to know?** and a few
suggested-prompt chips you can click to get started.

Using the demo's **Production Orders** model, try:

| What you want | Question to type |
|---|---|
| Data with a chart | `What is the total confirmed yield versus scrap quantity by plant for production orders finished this year?` |
| Data | `Show me the top 10 materials by total planned order quantity in plant 1000 this quarter.` |
| Data | `Which production orders have a basic finish date in the past but are not yet flagged as delivery complete?` |
| Schema | `What tables and fields make up the production_order entity, and how are AFKO and AFPO joined?` |
| Documentation | `How is the yield rate defined in this model, and which SAP fields does it use?` |

The agent decides what kind of question you asked and answers accordingly — you don't pick the
type, the wording does.

## 5. Read the answer

For a **data question**, the agent's written answer **streams in** progressively, in plain
language. Once it finishes, a small **mode badge** shows which mode produced the answer, and a
results block appears beneath it with two tabs:

| Tab | What it shows |
|---|---|
| **Table** *(shown by default)* | The rows the query returned, with a count. Large results preview the first 100 rows. |
| **Chart** | A chart of the same data. This tab appears **only** when the result has at least two rows and a numeric column to plot — click it to switch from the table. |

A grouped question like the first demo question above (confirmed yield vs. scrap **by plant**)
returns several rows with numeric columns, so the **Chart** tab is offered and draws a bar chart.

![A chat turn: the confirmed-yield-vs-scrap-by-plant question, the written answer, the mode badge, and the Table/Chart results block with the Chart tab open](../images/chat-answer-with-chart.png)

Two more controls sit with the results:

- **Copy answer** — beside the Table/Chart tabs; copies the written answer to your clipboard.
- **SQL Query** — a collapsible block below the results. Expand it to read the exact SQL the
  agent ran, and use **Copy SQL** to reuse or verify it.

For a **schema** question the agent describes the entity's structure (tables, fields, joins); for
a **documentation** question it explains the definition and the SAP fields behind it. Neither runs
a query, so those answers are written text with no results table or chart.

> **Tip —** each answer is part of a conversation. Ask a follow-up in the same chat
> ("now break that down by month") and the agent keeps the earlier context.

## 6. Manage your chats

The **Chat** page keeps a history rail on the left, scoped to the selected workspace.

- **+ New Chat** starts a clean thread.
- Each conversation is listed by an **automatically generated title** derived from your first
  question (until then it reads *New Chat*).
- Click a conversation to reopen it; hover a conversation and use its **delete** control to
  remove it.

Your conversations are saved per workspace and persist across sessions, so switching workspaces
swaps the visible history.

---

## Artifacts — generate documents

The **Artifacts** page turns your data into a shareable, formatted document — without you writing
anything but a few short answers. It uses the same **Workspace**, **Environment** and **Mode** you
set in the sidebar, so the document is built from the data you'd get by asking.

From the **Artifacts** gallery, click **New artifact** to open a short guided conversation that
asks you, one question at a time:

1. **Name** — how you'd like to name the artifact.
2. **Purpose** — who the audience is and what the document should support.
3. **Data focus** — what data it should cover, in plain language (this drives the queries).
4. **Format** — pick a chip: **Detailed Report**, **Executive Brief**, **Data Tables**, or
   **Proposal Format**.

The agent then generates the document. You land on the finished artifact, which offers a
**Document** tab (the written report) and — when queries returned rows — a **Data** tab with the
underlying results.

![The Artifacts gallery with the New artifact button and saved document cards](../images/chat-artifacts.png)

From the open artifact you can:

- **Copy** the document text, or **Download Excel** to save it as a spreadsheet (report,
  data tables and the SQL used, on separate sheets).
- **Regenerate** — re-run it against the current data.
- **Edit** — adjust the **Name**, **Format**, **Purpose / Audience** and **Data Focus**, or paste
  a **SQL Override**, then click **Apply & Regenerate** to rebuild the document with your changes.

> **Note —** export is **Excel** only, and artifacts are kept in the gallery for reuse; there is
> no separate download format and no delete action in the current interface.

---

## What's next

→ **[Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md)** — where the
workspace you pick in the sidebar comes from.
→ **[Publish & Deploy](../ask-admin/05-publish-deploy.md)** — how content reaches the **dev** and
**prod** environments you choose between.
→ **[Add Data Products](../ask-admin/02-add-data-products.md)** — the entities the agent maps your
questions to.
