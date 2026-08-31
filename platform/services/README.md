<!--
SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
Copyright (c) 2026 Onibex, LLC. All rights reserved.
-->

# Services

Runtime services that are not Python packages.

- **[`ask-mcp-server`](ask-mcp-server/README.md).** A Model Context Protocol server exposing SAP write operations as
  tools the agent can call. It is what turns *"create a purchase requisition"* from a
  description into an action.

Configure it from ASK Setup: [Enable the MCP server](../docs/ask-setup/06-mcp-server.md), and
[Register an OpenAPI contract](../docs/ask-setup/07-contracts.md) to turn an OData spec into
tools.

---

[← Back to the platform](../README.md)
