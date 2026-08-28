# Getting Started

[Manual](README.md) › [Foundations](README.md#foundations) › **Getting Started**

> **Tutorial.** One path, end to end: bring the platform up, describe a slice of your data,
> publish it, and ask a question in plain language. Roughly 45 minutes on a clean machine.

| | |
|---|---|
| **Who** | Anyone seeing ASK for the first time. No prior setup assumed. |
| **Prerequisites** | Docker with Compose v2, a clone of this repository, and credentials for one database and one LLM provider. |
| **You'll end with** | A running stack, one published Data Product, and a real answer with the SQL behind it. |

This page makes the choices for you. Where a step has options worth understanding, it links
to the page that covers them. Follow those **after** you have an answer on screen, not
during.

**Not the same page as [Install and run the platform](01-installation.md).** That one is the
reference for the stack itself: every environment variable, the startup order, the health
checks, what to do when a service will not come up, and it stops once the stack is running.
This one walks past all of that with the choices already made, and does not stop until a
question has been answered.

---

## Step 1: Bring the stack up

The stack lives in `platform/`, next to its `docker-compose.yml`. From your clone:

```bash
cd platform
cp .env.example .env
docker compose up -d
```

Two values in `.env` must be set before that second command will get you anywhere:

- **`ONIBEX_ENCRYPTION_KEY`.** Encrypts the credentials you are about to enter. Generate it
  with the one-liner in the file. **Save it somewhere safe**: lose it and every stored
  credential becomes unreadable.
- **`SEMANTIC_LAYER_HOST_PATH`.** An absolute path to a git repository where your semantic
  layer will live. It must already contain a `.git`, or publishing silently does nothing.
  `git init` an empty directory if you have none.

First boot builds images and bootstraps OpenSearch, so it takes a few minutes. Watch until
every service reports healthy:

```bash
docker compose ps
```

→ [Install and run the platform](01-installation.md). Every variable, the startup
order, and what to do when a service stays unhealthy.

## Step 2: Point ASK at a database and a model

Open **ASK Setup** at `http://localhost:5175` and sign in.

Configure two things, in this order, testing each before you save:

1. **A database connection** for the **dev** environment. This is the database ASK will
   query. It is your data, wherever it already lives.
2. **An LLM provider**. Either a direct provider through LiteLLM (OpenAI, Anthropic, Bedrock,
   and others) or SAP AI Core if you run managed models. The same page configures the
   embedder that powers semantic search.

Saving reloads the affected services. The ASK Setup home page should now show both as active.

→ [Sign in to ASK](guides/sign-in.md) · [Connect a database](ask-setup/02-database-connections.md) · [Connect an LLM provider](ask-setup/03-llm-providers.md)

## Step 3: Create somewhere to put your data products

Open **ASK Studio** at `http://localhost:5173`. Two containers come before any content:

```
Workspace  ─►  Business Domain  ─►  Data Products
```

A **workspace** is what the chat scopes to. It decides what a question can reach at all.
A **business domain** groups the Data Products that get queried together.

Create one of each. Names are yours; *Sales* is a fine first domain.

→ [Create workspaces and business domains](ask-studio/01-workspaces-domains.md)

## Step 4: Describe one table

Add a single Data Product. Do not model your whole landscape yet. One table you know well is
enough to reach an answer, and the shape of the work will be obvious once you have.

The fastest route from nothing is **DDL + AI**: paste a `CREATE TABLE` statement and let the
platform derive a Data Product from it. Three other routes exist: a manual form, uploading
YAML you already have, and importing SAP metadata from OneConnect, and the page below covers
when each fits.

Whatever you use, the result lands in **In Review**. Open it and read the field descriptions:
**they are how the agent maps a user's words to your columns**, so they matter more than
anything else on the page. The **Enrich** action drafts them with AI and shows you a diff
before anything is applied.

→ [Add Data Products](ask-studio/02-add-data-products.md) · [Edit and enrich Data Products](ask-studio/03-edit-enrich.md)

## Step 5: Publish it to dev

Nothing you author is visible to the chat until it is published, and publishing is gated:
**dev first, then prod**. That gate is deliberate. It is what stops an untested definition
reaching the environment your business reads.

Publish your Data Product, or the whole business domain at once, to **dev**.

→ [Publish and deploy](ask-studio/05-publish-deploy.md)

## Step 6: Ask something

Open **ASK Chat** at `http://localhost:5174`.

Three controls in the sidebar scope every question, and all three must be set before the
agent will answer:

| Control | Set it to |
|---|---|
| **Workspace** | The one you created in Step 3. |
| **Environment** | **dev**. That is where you published. |
| **Mode** | **Smart**, the default. |

Now ask a question about the table you described, in ordinary language. Any language works.

You should get a written answer, the rows behind it, an automatic chart when the result has
more than one row, and, if you expand it, **the SQL that produced the number**. Read that
SQL. It is the whole argument of the product: the model chose among fields you defined, it
did not invent a table name.

→ [Scope a question](ask-chat/01-workspace-environment-mode.md) · [Using the Chat](ask-chat/02-chat.md)

---

## When something does not work

Two failures account for most first runs:

- **"No workspaces configured"** in the Chat, the workspace exists but nothing is published
  to the environment you selected. Go back to Step 5, or switch the environment to `dev`.
- **An answer that finds no data.** The Data Product is published, but the underlying table
  is empty or the connection points at the wrong schema. Check the connection in ASK Setup.

→ [Troubleshooting & FAQ](reference/troubleshooting.md). Symptoms, causes and fixes.

## What to read next

You now have the whole loop working on one table. Where to go depends on what you want next:

| You want to… | Read |
|---|---|
| Understand what just happened | [Concepts and architecture](02-concepts.md) |
| Know why the answer is trustworthy | [The three chat engines](explain/engines.md) |
| Author a real semantic layer | [The ASK specification](../../definition/README.md) |
| Look up a term | [Glossary](reference/glossary.md) |

---

[← Back to the manual](README.md)
