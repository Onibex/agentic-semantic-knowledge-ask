# Sign in with SAP Cloud Identity Services

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Sign in with SAP Cloud Identity Services**

> **How to.** Replace the Keycloak the chart deploys with the customer's own SAP identity: SAP Cloud
> Identity Services, also called IAS. The platform keeps running and keeps its data; only who signs
> people in changes. It works on any cloud the chart runs on, because the apps talk to the tenant
> directly. **Shell:** bash. On Windows use Git Bash.

| | |
|---|---|
| **Who** | Whoever administers the customer's IAS tenant, together with whoever holds the cluster |
| **Time** | About 30 minutes, most of it in the IAS administration console |
| **You'll end with** | People signing in to all three apps with their company account, their roles coming from two IAS groups, and Keycloak still installed and idle, one flag away |

---

## Before you start

**The platform has to be installed and working first**, signing in with Keycloak, by the runbook for
its cloud: [Deploy on Kubernetes with Helm](kubernetes-deploy.md). This page switches an install that
works; it does not install one.

**You need an IAS tenant, and an administrator of it.** To see which tenants the SAP BTP global
account has, open the subaccount in the BTP cockpit, then **Security → Trust Configuration →
Establish Trust**, and read the list on the first screen. Then **cancel**: nothing on this page needs
the trust to be established, because the apps talk OIDC to the tenant directly rather than through
BTP. The tenant's console is at `https://<tenant>.accounts.ondemand.com/admin`.

> **Not the tenant you use to sign in to the cluster.** `kyma.accounts.ondemand.com` belongs to SAP
> and serves cluster access. Applications cannot be created there.

### Why IAS and not XSUAA

Both come with SAP BTP, and they are not interchangeable. The apps sign in as **public clients**, with
no secret, because a browser can never keep one. The same request was sent to both, a token exchange
with no secret and a fake code:

| | Answer | What it refuses |
|---|---|---|
| **XSUAA** | `401 invalid_client` | the client, before looking at the code |
| **IAS** | `400 invalid_grant` | only the fake code |

XSUAA cannot sign the apps in on its own, and the chart refuses `auth.mode: xsuaa` for that reason.

---

## Step 1. Create the application in the IAS console

Work top to bottom. The table at the end of this step is the checklist: every setting in one row,
with what goes wrong if it is missed. **Most of these fail without saying so**, which is why the
table exists.

1. **Applications & Resources → Applications → Create.** Display name `Onibex ASK Platform`, type
   `Unknown`, organization ID `global`, protocol **OpenID Connect**, and **Parent application: None**.
   An application with a parent inherits settings it cannot change.
2. **Trust → OpenID Connect Configuration → Configure.** Give the configuration a name without
   spaces, for example `onibex-ask-platform`. On its **URIs** tab, add six **Redirect** URIs and leave
   *Front-Channel Logout* and *Back-Channel Logout* empty:
   ```
   https://ask-studio.<cluster domain>/login/callback
   https://ask-chat.<cluster domain>/login/callback
   https://ask-setup.<cluster domain>/login/callback
   https://ask-studio.<cluster domain>/login
   https://ask-chat.<cluster domain>/login
   https://ask-setup.<cluster domain>/login
   ```
3. On its **Authentication** tab, **Grant Types → Edit**, and set them as the table says.
4. On the same tab, **Authentication Policy → Edit**, and raise **Maximum Sessions per User** to `10`.
5. Back on the application, **Application APIs → Client Authentication**. Turn **Enable Public Client
   Flows** on, and copy the **Client ID** shown there.
6. **Trust → Attributes**, and add two rows with **Add**, next to the ones already there.
7. **Users & Authorizations → Groups → Create**, twice: `ask-admin` and `ask-user`.

| # | Where | Set it to | If it is missed |
|---|---|---|---|
| 1 | Create application | Parent application **None** | The application inherits configuration it cannot change |
| 2 | OpenID Connect Configuration → URIs | The **three `/login/callback`** addresses | IAS shows its own error page the moment the app sends you to sign in, before asking for anything |
| 2 | OpenID Connect Configuration → URIs | The **three `/login`** addresses | Signing out does not come back to the app |
| 3 | Grant Types | **Authorization Code** on, and **Enforce PKCE (S256)** on | The apps always send PKCE, so this is not about them: it refuses a sign-in that somebody starts **without** PKCE using the public client id. On a client with no secret, a code from such a flow could be exchanged by whoever intercepted it |
| 3 | Grant Types | **Refresh** on | People are sent back to sign in every hour |
| 3 | Grant Types | **Password**, **Client Credentials** and **JWT Bearer** **off**. They come on by default | *Password* exchanges a user name and password for a token directly, **skipping the sign-in page and multi-factor authentication**, and on a public client anyone who reads the client id can try it |
| 4 | Authentication Policy | **Maximum Sessions per User: 10**. The default is 1 | It counts refresh tokens per user **for this application**, and the three apps share it. Each browser tab signs in on its own, so with 1, signing in to Chat cancels Studio's renewal, and Studio signs the person out an hour later for no visible reason |
| 5 | Client Authentication | **Enable Public Client Flows: on** | **No sign-in can ever complete.** This is the one XSUAA cannot do |
| 5 | Client Authentication | Copy the **Client ID** from here | The **Application ID** at the top of the application looks similar and is a different value |
| 5 | Client Authentication | **Client ID Lock: off** is recommended | It locks the client after five failed attempts with a secret. This client has no secret, and its id is public, served to every browser, so anyone could lock everyone out with five requests |
| 6 | Attributes | `email`: Source **Identity Directory**, Value **Email** | The apps read `email`. The existing `mail` row is a different name, so the apps would show the user's IAS identifier, `P000123`, instead of their address |
| 6 | Attributes | `groups`: Source **Identity Directory**, Value **All Groups** | **The roles never arrive.** The person signs in and can do nothing, with the right group assigned. There is no plain *Groups* value: *All Groups* is the one that carries ordinary user groups |
| 7 | Groups | `ask-admin` and `ask-user`, with **Name and Display Name identical** | The apps compare the exact string. Identical values mean whichever field IAS sends, it matches |
| 7 | Groups | Whoever authors and configures the platform in `ask-admin` | ASK Studio and ASK Setup refuse them |

> **The application comes out as "Charged", not "Bundled".** An application bundled with an SAP
> product comes with its license; one of your own counts against the IAS license. Whether that costs
> money depends on the contract, and only whoever holds the account can see it.

> **"All Groups" sends every group the person is in**, not only the two ASK ones. ASK reads only
> `ask-admin` and `ask-user` and ignores the rest, but the names of the others travel in the token.

---

## Step 2. Check it from outside, before anyone signs in

```bash
python scripts/check_ias.py \
  --tenant https://<tenant>.accounts.ondemand.com \
  --client-id <the client id from Client Authentication> \
  --domain <cluster domain>
```

It must end with `All checks passed.` It needs no credential and changes nothing. What it proves:

- The tenant answers, with the endpoints and PKCE support the apps are built for.
- **The three sign-in addresses are accepted, and an invented one is refused.** The refusal is what
  makes the acceptances mean something.
- **The application is a public client.** A secretless exchange is refused for the code, not the
  client. Run it once before step 1.5 and once after, and you will see the answer change.

If every address fails and it also reports `invalid_client`, it prints **READ THIS FIRST**: the client
id itself is wrong, and the other hints do not apply until it is right.

**What no check from outside can see**, and where to look instead: the two attributes and the group
memberships show on ASK Setup's **Identity Provider** page after a sign-in, in Step 5. The grant types
and the session limit have to be read in the console. And the `/login` addresses show when somebody
signs out: IAS answers a logout for a registered address and an invented one identically.

---

## Step 3. Point the platform at it

`values-ias-dev.yaml` holds the three values that switch the platform, for the Onibex development
tenant. For any other tenant, copy it and replace the `url` and the `clientId`. They are not
secrets: the client id is a public client's, and every browser reads it from the app anyway.

It is an **overlay**. It goes **after** the cloud profile, because Helm applies values files left to
right and the last one wins:

```bash
helm upgrade ask deploy/helm/onibex-ask -n onibex-ask \
  -f deploy/helm/onibex-ask/values-kyma-dev.yaml \
  -f deploy/helm/onibex-ask/values-ias-dev.yaml
```

Use your own cloud's profile in place of `values-kyma-dev.yaml`. **Render it first**, the same
command with `template` in place of `upgrade`: an empty `url` or `clientId` stops the render and names
the value, rather than producing pods that start and cannot sign anyone in.

---

## Step 4. Confirm the platform switched, before involving a person

Each app serves its configuration at `/config.js`. All three must name IAS, your tenant and your
client id:

```bash
for app in ask-studio ask-chat ask-setup; do
  curl -s "https://$app.<cluster domain>/config.js" | grep -E "AUTH_MODE|IAS_URL|IAS_CLIENT_ID"
done
```

And the browser has to be allowed to talk to the tenant, which the apps' security policy decides:

```bash
curl -sI "https://ask-setup.<cluster domain>/" | grep -io "connect-src[^;]*"
```

The tenant must appear there. Without it the browser blocks the token exchange, and the sign-in fails
after the password with nothing in the tenant's logs.

---

## Step 5. Sign in, first without the administrator role

**Use a private window, and this is not optional.** If the browser holds any IAS session for that
tenant, for example an administrator signed in to the console, IAS signs the app in as **that**
person without asking, and every result below belongs to someone else.

1. **Put the person testing in `ask-user` only**, not in `ask-admin`.
2. **Open ASK Studio** and sign in. It sends you to the tenant's sign-in page, not to Keycloak.
   Expected: **Access restricted**, naming `ask-admin` as required and listing the roles you have.
   The list proves the groups arrived.
3. **Check that the server refuses too**, not only the page. Studio stopped before calling anything,
   so this is the only way to see the backend's answer. With that Studio tab open, press F12, open
   the **Console**, and type:
   ```js
   fetch('/api/yamls', {headers: {Authorization: 'Bearer ' + sessionStorage.getItem('auth_access_token')}}).then(r => console.log(r.status))
   ```
   Expected: **403**. The token never leaves the browser. A `200` here means administrators are not
   being told apart from everyone else, and nothing else on this page matters until it is fixed.
4. **Open ASK Chat** in the same window. Expected: it signs you in without asking again, and a
   question gets an answer.
5. **Add the person to `ask-admin`, close every private window, and open a new one.** A token keeps
   the groups it was issued with, so a fresh one is needed.
6. **Open ASK Studio and ASK Setup.** Both open. In ASK Setup, the **Identity Provider** page must
   show **SAP Cloud Identity Services (IAS)** as the active provider, with your tenant, your client id
   and your roles: `ask-admin`, `ask-user`, and any other group the person is in.

---

## When something is wrong

From the first install against a real tenant, on 2026-09-23. Some of these were seen happen; the
others follow from how that tenant was measured to behave.

| What you see | Why | What to do |
|---|---|---|
| IAS shows *"OpenID provider cannot process the request because the configuration is incorrect"* as soon as you press Sign in | A `/login/callback` address is missing, or the client id is wrong | Step 1.2, then `check_ias.py` |
| *Authentication error* on returning to the app, or `invalid_client` | Public client flows are off | Step 1.5 |
| **Access restricted** for someone who is in `ask-admin` | The `groups` attribute is missing or not *All Groups*, or the token predates the change | Step 1.6, then a new private window |
| An identifier like `P000123` where the email should be | The `email` attribute is missing | Step 1.6 |
| The session belongs to someone else | A normal window, with another IAS session open | A private window |
| Studio signs out about an hour after signing in to Chat | Maximum Sessions per User is 1 | Step 1.4 |
| Every check fails and it says **READ THIS FIRST** | The client id is wrong, often the Application ID copied instead | Copy it from Client Authentication |

---

## Going back to Keycloak

The same `helm upgrade` **without** the second `-f`. Keycloak ran the whole time with its realm, so
people sign in with their Keycloak accounts again at once, and the IAS application stays configured
for the next switch.

---

## Before a customer depends on this

This is a first delivery, and three things are decisions rather than steps:

- **Anyone in the tenant can use ASK Chat.** ASK Chat requires a signed-in user and no role, so with
  IAS every person in the customer's directory can sign in to it and ask questions of their data,
  whether or not they are in `ask-user`. With Keycloak that was harmless, because the realm held
  only the accounts created for it. Either the IAS application is restricted to the right people, or
  ASK Chat is made to require `ask-user`. This is read from the code and not yet measured with a
  person in neither group.
- **Keycloak keeps running, published, and unused.** It is what makes going back one flag. A customer
  on IAS for good should turn it off, and that is a separate change.
- **"All Groups" carries every group.** Applications can have groups of their own, which would limit
  the token to the ASK ones; that route has not been verified.

---

[← Back to the manual](../README.md) · [Deploy on Kubernetes with Helm](kubernetes-deploy.md) · [Kubernetes reference](kubernetes-reference.md)
