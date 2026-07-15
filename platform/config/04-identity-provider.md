# ASK Setup · Identity Provider

> **Configuration flow.** See who signs in to the platform, and how. This page is **read-only by
> design**: the identity provider is chosen at deploy time and baked into the build — the page
> exists to show you the active configuration and your own session, not to edit them.

| | |
|---|---|
| **Who** | Administrator |
| **Time** | ~1 minute (review only) |
| **Prerequisites** | You can sign in to **ASK Setup** (see [Installation](../01-installation.md)). |
| **You'll end with** | A clear view of the active identity provider, its OIDC configuration, and the roles carried in your token. |

**Where this fits:** **Configure — Identity Provider (you are here)** → Author → Publish → Ask

> The screenshots below show illustrative issuer and client values. Substitute your own — none of it
> is editable here, so there is nothing secret to type in.

---

## Concepts (30-second version)

- Authentication is configured **at deploy time**, not in the UI. Everything on this page is
  **read-only** — there are no editable fields by design.
- The platform supports three modes:
  - **Keycloak** — a self-hosted OIDC realm; the default for local and on-prem deployments.
  - **SAP BTP — Cloud Identity (IAS / XSUAA)** — managed identity for SAP BTP deployments.
  - **Dev bypass (no authentication)** — local development only; requests are **not** authenticated.
    Never use it in production.
- Sign-in uses **OIDC with PKCE**. The SPA reads its provider from a build-time variable and the
  backend validates tokens with matching environment variables.
- Your token carries **roles**. The two roles that mean something to the product are **`ask-admin`**
  and **`ask-user`**; other roles are identity-provider plumbing.
- **To switch providers you change environment variables and rebuild the SPA** (then restart the
  backend). There is no in-app switch.

---

## 1. Open the Identity Provider page

In the ASK Setup sidebar, open **Identity Provider**. The header reads *"Who signs in, and how. The
provider is chosen at deploy time; this page shows the active configuration and your current
session, read-only."* A **Refresh** button reloads the page.

![ASK Setup Identity Provider page: the Active provider card, the read-only OIDC configuration, the "Your session" panel, and the Supported providers list](../images/config-identity.png)

## 2. Read the active provider

The **Active provider** card names the identity provider that *authenticates every sign-in*. A pill
on the right shows **OIDC · PKCE** when a real provider is bound (or **disabled** for dev bypass),
and a small **mode:** chip shows the raw mode value (`keycloak`, `xsuaa` or `none`).

| Mode | Card shows |
|---|---|
| **Keycloak** | The **realm** and **client** id decoded from the issuer. |
| **SAP BTP — Cloud Identity (IAS / XSUAA)** | The bound **client** id. |
| **Dev bypass (no authentication)** | *"no identity provider bound"* — authentication is off. |

## 3. Review the OIDC configuration (read-only)

When a real provider is active, the **OIDC configuration** card lists the connection details, marked
**Baked at build time** (a lock icon):

| Field | Meaning |
|---|---|
| **Issuer** | The OIDC issuer URL. |
| **Client ID** | The public client the SPA authenticates as. |
| **Scopes** | The scopes requested at sign-in. |
| **Authorization endpoint** | Where the browser is sent to sign in. |
| **Token endpoint** | Where the authorization code is exchanged for tokens. |
| **End-session endpoint** | Where sign-out (RP-initiated logout) is sent. |

An information note under the table explains the wiring: the SPA reads the provider from
**`VITE_AUTH_MODE`** (compiled into the bundle at build), and the backend validates tokens using
**`AUTH_MODE`** plus **`KEYCLOAK_JWKS_URL`** / **`XSUAA_*`**. *"To switch providers, change the env
vars and rebuild — there is nothing to edit here by design."*

> **Note — dev bypass looks different.** When the platform runs with authentication bypassed
> (`VITE_AUTH_MODE` unset), this card is replaced by an amber notice telling you to set the mode to
> `keycloak` or `xsuaa` and rebuild to enable a real identity provider. There is no session panel in
> that mode.

## 4. Check your session and roles

The **Your session** panel (*"decoded from your token"*) shows the identity you signed in with: your
**email**, your **sub** (subject) id, a **signed in** badge, and your **Roles**. The product roles
**`ask-admin`** and **`ask-user`** are highlighted; any other roles appear muted. If your token
carries no roles, the panel says *"no roles in token."*

> **Tip — roles gate what you can do.** `ask-admin` and `ask-user` are the RBAC roles the platform
> recognises (see [Concepts](../02-concepts.md)). If an action returns a permission error, confirm
> the expected role appears here — your identity provider assigns it, not this page.

## 5. Understand the supported providers

The **Supported providers** list shows the two production identity providers — **Keycloak** and
**SAP BTP — Cloud Identity (IAS / XSUAA)** — each with its mode id, a short description, and an
**Active** or **Available** badge. Because switching is a deploy-time change, this list is
informational: it tells you what the platform can be built against, not a menu you select from.

> **Warning — switching providers is an operations task.** Changing the identity provider means
> updating the build-time and backend environment variables (`VITE_AUTH_MODE` / `AUTH_MODE` and the
> matching `KEYCLOAK_*` or `XSUAA_*` values), **rebuilding the SPA**, and restarting the backend. It
> cannot be done from this page.

---

## What's next

→ **[ASK Setup · SAP Connection](05-sap-connection.md)** — S/4HANA OData credentials.
→ **[ASK Setup · LLM Providers](03-llm-providers.md)** — the model registry and shared embedder.
→ **[Concepts](../02-concepts.md)** — how the `ask-admin` / `ask-user` roles map to what each person
can do.
