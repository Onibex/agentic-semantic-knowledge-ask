# Connect SAP AI Core

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Connect SAP AI Core**

> **How to.** Use the models of SAP's generative AI hub, through SAP AI Core, for the agent's answers
> and for its embeddings. One part happens in the SAP BTP cockpit and in SAP AI Launchpad, the other
> in ASK Setup. It works on any cloud the platform runs on: ASK reaches SAP AI Core over HTTPS, so the
> instance does not have to live next to the cluster.

| | |
|---|---|
| **Who** | A global account administrator of SAP BTP, together with an administrator of ASK Setup |
| **Time** | About 30 minutes, most of it in the SAP BTP cockpit |
| **You'll end with** | An SAP AI Core instance on the extended plan with its orchestration deployment running, and ASK Setup using it for the active model and for the embedder |

---

## Before you start

Have these three at hand.

1. **A platform that works**, with ASK Setup open as an administrator. Installing one is covered by
   [Deploy on Kubernetes with Helm](kubernetes-deploy.md). This page adds a provider; it does not
   install anything in the cluster.
2. **An SAP BTP global account whose contract includes SAP AI Core on the extended plan.** The
   generative AI hub comes only with the extended plan; the standard plan does not include it. With a
   consumption-based contract every eligible service is available. With a subscription-based one, only
   what was bought.
3. **A region that offers SAP AI Core and SAP AI Launchpad.** Not every region does: US West
   (Oregon), for one, offers neither. This page was followed in **US East (VA)** on Amazon Web
   Services. The SAP Discovery Center lists the regions of each service.

---

## Step 1. Create the subaccount

1. In the SAP BTP cockpit, open the global account, then **Account Explorer → Create → Subaccount**.
2. Name `onibex_aicore`. Region **US East (VA)** on Amazon Web Services, or another one from Before you
   start, point 3.
3. Keep the subdomain it proposes, leave **Used for production** unchecked, and press **Create**.

---

## Step 2. Assign the two services

The **Entitlements** tab of the subaccount's Overview only shows the assignments. They are changed on
the **Entitlements** page of the left-hand menu, which is folded by default.

1. Inside the subaccount, open **Entitlements** in the left-hand menu and press **Edit**. No **Edit**
   means you are not a global account administrator.
2. **Add Service Plans**: **SAP AI Core**, plan **extended**. If it asks for an amount, `1`.
3. **SAP AI Launchpad**, plan **free**. If free is not offered, **standard**.
4. Confirm with **Add Service Plans** in the dialog, then press **Save**.

If SAP AI Core is not in the dialog, the contract or the region does not offer it: Before you start,
points 2 and 3.

---

## Step 3. Enable Cloud Foundry and create a space

1. On the subaccount's **Overview**, **Enable Cloud Foundry**: plan **standard**, the names it proposes,
   **Create**. The standard plan charges for the memory of applications deployed on it, and this page
   deploys none.
2. **Create Space**, named `aicore`.

---

## Step 4. Create the instance and its service key

1. **Service Marketplace → SAP AI Core → Create**. Plan **extended**, Instance Name `ask-aicore`, the
   space `aicore`. **Next**, **Next** again without uploading any JSON, then **Create**.
2. Wait until **Instances and Subscriptions** shows the instance as **Created**.
3. On the instance, **Create Service Key**. Name it `onibex-ask` and press **Create**, again without
   uploading any JSON.

The key lets anyone use the instance at its cost. Keep it out of chats and tickets: Step 6 reads it
straight from the cockpit.

---

## Step 5. Check the orchestration deployment

ASK sends every request to the instance's orchestration deployment. SAP creates it with the instance,
in the resource group `default`, and this step confirms that it is there.

1. **Instances and Subscriptions → Create**: a subscription to **SAP AI Launchpad**, with the plan
   from Step 2. **Create**.
2. **Security → Users**, your user: assign the role collections whose names start with `ailaunchpad_`.
3. On the subscription's row, **Go to Application**. If it says you lack permission, sign out of the
   cockpit, sign in again, and repeat.
4. Add a connection named `ask-aicore` with the key from Step 4: **Download** it from the key, upload
   the file, and delete the file afterwards.
5. Choose the connection `ask-aicore` and the resource group `default`.
6. Open **ML Operations → Deployments**. Expected: one deployment with the configuration
   `defaultOrchestrationConfig`, status **Running**.

---

## Step 6. Connect it in ASK Setup

1. In ASK Setup, open **LLM Providers** and press **Add LLM**. Provider **SAP AI Core**.
2. Display name `SAP AI Core · gpt-4o`. Model `gpt-4o`. The model is chosen by its name in the
   generative AI hub, as SAP AI Launchpad lists it under **Generative AI Hub → Model Library**; there
   is no deployment ID to enter.
3. **Service key (JSON)**: in the cockpit, open the key from Step 4, press **Copy JSON**, and paste the
   whole key, from its first `{` to its last `}`.
4. **Resource group**: leave it blank. Blank means `default`.
5. Press **Save connection**. The first connection you add becomes the active model by itself.
6. Press **Test** on its card. Expected: *LLM responded*.

---

## Step 7. Use it for the embedder too

1. In the **Embedder** section, press **Edit**. Provider **SAP AI Core**, Model
   `text-embedding-3-large`, the same service key. Press **Save embedder**.
2. Press **Test** on the embedder's card. Expected: *Embedder returned a 1024-dimension vector, the
   size the index stores*. The number is the size of your search index, which the card also shows.

---

## Step 8. Confirm it from ASK Chat

Ask any question in ASK Chat and open the token breakdown under the answer. Every row of **Per-call
detail** shows `sap/gpt-4o` in the **Model** column. On a platform with no database yet, the answer
says so after a single call, and that call is enough to confirm the model.

---

## When something is wrong

| What you see | Why | What to do |
|---|---|---|
| Saving says *The SAP AI Core service key is not valid JSON* | Only part of the key was pasted, or text around it | Step 6.3, with **Copy JSON** |
| Saving says the key *is missing* one of its fields | A piece of the key, often the credentials without `serviceurls` | Step 6.3 |
| The embedder test says it *returned 3072-dimension vectors and the search index stores 1024* | The model cannot shorten its output to the index's size | `text-embedding-3-large` or `text-embedding-3-small`, which can |
| The connection test fails, and Step 5 shows no orchestration deployment | The resource group has none | Step 5, in the resource group of Step 6.4 |
| No **Edit** on Entitlements | The Overview's tab, or not a global account administrator | Step 2 |
| SAP AI Core is missing from **Add Service Plans** | The contract or the region | Before you start |

Keeping a model that cannot shorten its output means recreating the search index at that model's size:
set `OPENSEARCH_EMBEDDING_DIM` on both backends, drop the registry indices, and publish every Data
Product again. That empties search until the publish finishes, which is why the index keeps its size
and the embedder adapts to it.

---

## Before a customer depends on this

These are decisions rather than steps:

- **Every call is paid in tokens.** With foundation models there is no compute, storage or baseline
  charge. SAP converts the tokens into capacity units, at a rate that depends on the model.
- **The extended plan cannot go back to standard.**
- **The active model and the embedder share one service key** in each running service, because both
  read it from the same place. Use the same instance for both. This is read from the code, not
  measured with two keys.
- **Each call finds the orchestration deployment again**, two extra requests to SAP before the call
  itself. Measured: the embedder test took between 1.4 and 2 seconds.

---

## Why it is set up this way

- **The orchestration service, not one deployment per model.** One deployment serves every model the
  region offers, chosen by name in each request, and SAP creates it with the instance. There is no
  deployment ID to keep in step with ASK Setup.
- **The whole key, as SAP issues it.** It is read as it comes, the token and API addresses are derived
  from it, and keys issued with a secret or with a certificate both work. Nothing is transcribed by
  hand. It is checked when saved, and the error names what is missing without repeating the key.
- **The embedder asks SAP AI Core for the index's size inside its model parameters.** The standard
  size parameter does not reach SAP AI Core: measured, the model returned 3072 dimensions. Asked
  inside the model parameters, it returned 1024.

---

[← Back to the manual](../README.md) · [Connect an LLM provider](../ask-setup/03-llm-providers.md) · [Sign in with SAP Cloud Identity Services](sign-in-with-ias.md)
