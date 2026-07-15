# ASK Setup · Contracts

> **ASK Setup configuration — Contracts.** Register a SAP OData service — described by an
> **OpenAPI 3.0** specification — so the agent can call it. Each registered contract turns the
> service's entity sets and operations into MCP tools the agent uses for SAP actions.

| | |
|---|---|
| **Who** | Administrator |
| **Time** | ~3 minutes |
| **Prerequisites** | You can sign in to **ASK Setup**; an OpenAPI 3.0 spec **in JSON** for the OData service you want to expose. |
| **You'll end with** | The OData service registered as MCP tools, its entity sets and operations available to the agent. |

**Where this fits:** **Configure — Contracts (you are here)** → Author → Publish → Ask

> The screenshots use a sample OData spec. Register your own service's spec — the exact entity
> sets shown here won't match yours.

---

## Concepts (30-second version)

- A **contract** is an **OpenAPI 3.0 specification** describing a SAP OData service.
  Registering it turns each **entity set** and its **operations** (list, get, create, update,
  delete) into MCP tools the agent can call through the [MCP Server](06-mcp-server.md).
- **JSON only.** The spec is parsed in your browser to preview what it exposes; only JSON is
  accepted. **Convert YAML to JSON first.**
- Registering is **non-destructive to review** — you see a parsed preview of the entity sets
  and operations **before** you commit it.
- The built-in **`salesorder`** contract ships with the platform and **cannot be removed**.
  Your own contracts can be registered, replaced and deleted freely.

---

## 1. Open the Contracts page

In the left sidebar, click **Contracts**. The page header reads **API Contracts** with the
subtitle *"Register SAP OData APIs as MCP tools from OpenAPI 3.0 JSON specs"*. A **Refresh**
button top-right reloads the registered list.

![Contracts page: the Upload Contract card and the list of registered contracts](../images/config-contracts.png)

## 2. Upload and preview a spec

In the **Upload Contract** card, click **Choose JSON file…** and pick the OpenAPI `.json` file
for your service. The card explains: *"Upload an OpenAPI 3.0 JSON file. The spec is parsed to
extract entity sets, operations, and fields. YAML files must be converted to JSON first."*

The file is parsed immediately in the browser:

| Result | What happens |
|---|---|
| Parsed successfully | A preview panel opens showing the spec's **title**, the number of **entity sets**, and the filename. A toast confirms *"Parsed `<title>` — N entity set(s)"*. |
| Not valid JSON | A toast — *"Only JSON files are supported. Convert YAML to JSON first."* — and nothing is registered. |
| No entity sets found | A toast — *"No entity sets could be extracted from this OpenAPI spec."* |

The preview lists each entity set in a table with three columns — **Entity Set**,
**Operations**, and **Description**. The operation badges reflect the HTTP methods the spec
declares: **LIST** and **GET** (read), **POST** (create), **PATCH** (update), **DEL**
(delete). If a contract with the same name is already registered, a **Will replace existing**
badge appears in the preview header.

> **Tip — the preview is your check.** Confirm the entity sets and operations match what you
> expect before registering. What you see in this table is exactly what becomes available to
> the agent as tools.

## 3. Register the contract

Click **Register Contract** to save it. A toast — *"`<title>` registered"* — confirms, and the
contract appears in the list below. Click **Cancel** to discard the preview without
registering.

## 4. Review registered contracts

The **Registered Contracts (N)** card lists everything currently registered. Each row shows:

| Element | Meaning |
|---|---|
| **Title + tag** | The contract name, tagged **built-in** or **custom**. |
| Path + filename | The service path prefix and the source filename. |
| Entity set count | How many entity sets the contract exposes. |
| Expand chevron | Opens the same entity-set table shown in the preview. |
| Delete (trash) | Removes a **custom** contract after a confirmation prompt. |

The built-in **`salesorder`** contract carries the **built-in** tag and has **no delete
button** — it is part of the platform and stays registered. Removing a custom contract asks
you to confirm — *"Remove contract `<name>`?"* — first.

> **Warning — registering replaces by name.** Uploading a spec whose name matches an existing
> contract **replaces** it (the preview flags this with **Will replace existing**). To keep
> both, ensure their OpenAPI **titles** differ before converting to JSON.

---

## What's next

→ **[MCP Server](06-mcp-server.md)** — confirm the MCP endpoint that serves these contracts is
reachable.
→ Once contracts are registered, the agent can invoke them as SAP actions from chat.
