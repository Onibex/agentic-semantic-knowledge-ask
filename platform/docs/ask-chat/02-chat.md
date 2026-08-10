# ASK Chat · Using the Chat

> **Flow 2 of the ASK Chat manual.** Ask questions in plain language and read governed SQL
> answers — written summaries, results tables, auto-generated charts, and optionally the SQL
> and token trace behind each answer.

| | |
|---|---|
| **Who** | Business user / analyst |
| **Time** | Seconds per question |
| **Prerequisites** | A workspace is selected, an environment chosen, and a mode set (see [Flow 1](01-workspace-environment-mode.md)). |
| **You'll end with** | Answers to your questions — text, tables, charts — in one or more named conversations you can return to. |

**Where this fits:** Configure → Author → Publish → Set controls → **Ask — chat (you are here)**

> The screenshots and sample values below use an illustrative **SAP Sales & Distribution**
> example (Sales Orders). Substitute your own Data Products — the exact demo names and
> questions won't exist in your system.

---

## Concepts (30-second version)

- Each conversation is an independent **chat session** with its own history. You can have
  multiple sessions per workspace and switch between them freely.
- You type in **natural language** — any language, business terms only. The agent maps your
  words to the governed semantic layer; you never need to know table or column names.
- The agent classifies every question as one of four types: **data** (runs SQL), **schema**
  (describes structure), **documentation** (explains definitions), or **action** (writes to
  SAP via MCP). The type is determined by your wording — you don't pick it.
- For data questions, a **chart is drawn automatically** whenever the result has more than
  one row.

---

## 1. Manage sessions

The **Chat history sidebar** sits on the left side of the Chat page — separate from the
main navigation sidebar. It lists all sessions for the currently selected workspace.

| Action | How |
|---|---|
| **New session** | Click **New Chat** at the top of the history sidebar. |
| **Switch session** | Click any session title in the list. |
| **Delete session** | Hover a session and click the trash icon. If deleting leaves no sessions, one is created automatically. |

Session titles start as *"New Chat"* and are automatically renamed by the LLM after the
first exchange — derived from the content of your opening question.

> **Tip —** each session forwards its last 10 messages as context with every new question.
> Use **New Chat** to start a clean thread rather than appending unrelated questions to an
> existing one.

> **Warning —** If no workspace is selected, **New Chat** is disabled and an amber banner
> appears at the top of the page. Select a workspace first (see [Flow 1](01-workspace-environment-mode.md)).

---

## 2. Ask a question

Type your question in the **composer** at the bottom of the chat and press **Enter** (or
click the send button). **Shift + Enter** inserts a line break without sending.

The composer expands automatically as you type (up to a maximum height) and disables while
a response is in progress.

Using the demo's Sales & Distribution model, try:

| What you want | Question to type |
|---|---|
| Data with a chart | `What were the top 10 materials by net sales value last quarter?` |
| Data over time | `Show me total revenue by month for the current year, broken down by sales organization.` |
| Schema | `What tables and fields make up the sales order entity, and how are VBAK and VBAP joined?` |
| Documentation | `How is net value defined in this model, and which SAP field does it map to?` |

**Quick-start chips** appear on the empty-state screen before the first message: "Top 10
customers by revenue", "Sales orders this month", and "Pending purchase orders". Clicking
any chip sends it as a message immediately.

---

## 3. Read the answer

### Data questions

For a data question the agent replies with a **written answer** streamed word by word. Once
streaming completes, the full response is rendered with markdown formatting and three tabs
below the text:

**Table tab** (default)

The raw query results in a striped, scrollable table — up to 100 rows displayed. If the
result exceeds 100 rows, a note shows the total count. Columns are auto-detected from the
result set; all values are rendered as strings. A **Copy answer** button copies the written
answer text to the clipboard.

**Chart tab**

Appears only when the result has **at least 2 rows** and at least one numeric column. Click
**Chart** to switch. The chart type is chosen automatically:

| Result shape | Chart type |
|---|---|
| Date or timestamp X axis | Line chart |
| Categorical X, ≤ 8 rows | Vertical bar chart |
| Categorical X, > 8 rows | Horizontal bar chart (sorted ascending) |

Bar charts use a blue gradient scale; line charts use Onibex blue (`#2563eb`). The Y axis
picks the numeric column with the highest maximum value.

**SQL tab**

Collapsed by default. Click **SQL** to expand the raw SQL the agent sent to the database.
A **Copy SQL** button copies it to the clipboard — useful for reuse in an external tool or
for verifying the query logic.

> **Tip —** the mode badge (e.g. *precise*) shown next to the answer tells you which engine
> produced it, in case you switch modes between questions.

### Schema questions

The agent describes the entity's structure — tables, fields, their types and roles, and the
exact join predicates — without running a query or drawing a chart.

### Documentation questions

The agent retrieves and summarises the answer from ingested documentation (KPI catalogs,
process descriptions, field definitions). No query is executed.

### Action questions *(requires MCP)*

If the MCP server is configured, the agent extracts the action parameters from your question,
calls the MCP tool on SAP S/4HANA, and confirms whether the write-back succeeded. Action
questions require explicit action-oriented wording ("create", "update", "submit").

---

## 4. Follow up

Each session retains the previous 10 messages as context. You can ask follow-ups naturally:

> *"Now break that down by month."*
> *"Filter to sales organization 1000 only."*
> *"What does the top material sell in the EMEA region?"*

The agent carries the context forward — you do not need to repeat the subject of the
original question.

---

## 5. The thinking indicator

While the backend is processing, a **thinking bubble** appears — a pulsing indicator with
rotating status messages ("Translating your question into SQL…", "Querying the database…",
etc.). The indicator disappears as soon as streaming begins.

---

## 6. Scroll behaviour

The chat auto-scrolls to new content while you are near the bottom of the thread. If you
scroll up to review earlier messages, auto-scroll pauses. A floating **↓ Scroll to bottom**
button appears when you are more than 100 px above the latest message — click it to jump
back down and re-enable auto-scroll.

---

## What's next

→ **[Flow 3 · Artifacts](03-artifacts.md)** — turn your data into shareable reports, executive
briefs, and data tables.
→ **[Flow 1 · Workspace, Environment & Mode](01-workspace-environment-mode.md)** — change the
workspace or switch to the `prod` environment.
