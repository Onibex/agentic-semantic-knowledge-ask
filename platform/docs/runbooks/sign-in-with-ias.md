# Sign in with SAP Cloud Identity Services

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Sign in with SAP Cloud Identity Services**

> **How to.** Replace the Keycloak the chart deploys with the customer's own SAP identity: SAP Cloud
> Identity Services, also called IAS. The platform keeps running and keeps its data; only who signs
> people in changes. It works on any cloud the chart runs on. **Shell:** bash, from `platform/`. On
> Windows use Git Bash.

| | |
|---|---|
| **Who** | Whoever administers the customer's IAS tenant, together with whoever holds the cluster |
| **Time** | About 30 minutes, most of it in the IAS administration console |
| **You'll end with** | People signing in to all three apps with their company account, their roles coming from two IAS groups, and Keycloak still installed and idle, one flag away |

---

## Before you start

Have these three at hand.

1. **A platform that works with Keycloak**, installed by the runbook for its cloud:
   [Deploy on Kubernetes with Helm](kubernetes-deploy.md). This page switches an install; it does not
   install one.
2. **Your three app hosts**, the names in the addresses people open. They are the `publicUrls` of the
   values file you installed with. Use your own cloud's profile in place of `values-kyma-dev.yaml`:
   ```bash
   grep -A3 '^publicUrls:' deploy/helm/onibex-ask/values-kyma-dev.yaml
   ```
   Below they appear as `<studio host>`, `<chat host>` and `<setup host>`, without `https://`.
3. **Your IAS tenant**, and someone who administers it. Its console is at
   `https://<tenant>.accounts.ondemand.com/admin`. To see which tenants the SAP BTP global account
   has, open the subaccount in the BTP cockpit, then **Security → Trust Configuration → Establish
   Trust**, read the list, and **cancel**. Not `kyma.accounts.ondemand.com`: that one is SAP's, for
   signing in to the cluster, and applications cannot be created there.

---

## Step 1. Create the application in the IAS console

1. **Applications & Resources → Applications → Create**, with:
   - Display name `Onibex ASK Platform`
   - Type `Unknown`
   - Organization ID `global`
   - Protocol **OpenID Connect**
   - Parent application **None**
2. **Trust → OpenID Connect Configuration → Configure.** Name it `onibex-ask-platform`. On its
   **URIs** tab:
   - **Redirect → Add**, three times:
     ```
     https://<studio host>/login/callback
     https://<chat host>/login/callback
     https://<setup host>/login/callback
     ```
   - **Post Logout Redirect → Add**, three times. It is further down the same tab, below
     *Back-Channel Logout*:
     ```
     https://<studio host>/login
     https://<chat host>/login
     https://<setup host>/login
     ```
   - Leave *Front-Channel Logout* and *Back-Channel Logout* empty.
3. On the **Authentication** tab, **Grant Types → Edit**:
   - On: **Authorization Code**, **Enforce PKCE (S256)** and **Refresh**
   - Off: **Password**, **Client Credentials** and **JWT Bearer**. They come on by default.
4. On the same tab, **Authentication Policy → Edit**, and set **Maximum Sessions per User** to `10`.
5. Back on the application, **Application APIs → Client Authentication**:
   - **Enable Public Client Flows** on
   - **Client ID Lock** off
   - Copy the **Client ID** shown there. Not the *Application ID* at the top of the application,
     which looks similar and is a different value.
6. **Trust → Attributes → Add**, twice, next to the rows already there:
   - `email`, Source **Identity Directory**, Value **Email**
   - `groups`, Source **Identity Directory**, Value **All Groups**
7. **Users & Authorizations → Groups**: `ask-admin` and `ask-user`, each with **Name and Display Name
   identical**. If they already exist, keep them. Put whoever authors and configures the platform in
   `ask-admin`.

---

## Step 2. Check it from outside

```bash
python scripts/check_ias.py \
  --tenant https://<tenant>.accounts.ondemand.com \
  --client-id <the Client ID from step 1.5> \
  --studio <studio host> --chat <chat host> --setup <setup host>
```

It must end with `All checks passed.` Each failure says what to change. If you saved something in
the console a moment ago, run it again before believing a failure: IAS takes a moment to apply a
change everywhere.

---

## Step 3. Point the platform at it

1. In `deploy/helm/onibex-ask/values-ias-dev.yaml`, set `auth.ias.url` to
   `https://<tenant>.accounts.ondemand.com` and `auth.ias.clientId` to the Client ID from step 1.5.
2. Render it. Silence means it rendered; an empty value stops it and names it:
   ```bash
   helm template ask deploy/helm/onibex-ask -n onibex-ask \
     -f deploy/helm/onibex-ask/values-kyma-dev.yaml \
     -f deploy/helm/onibex-ask/values-ias-dev.yaml > /dev/null
   ```
3. Apply it. The IAS file goes **second**, because the last file wins:
   ```bash
   helm upgrade ask deploy/helm/onibex-ask -n onibex-ask \
     -f deploy/helm/onibex-ask/values-kyma-dev.yaml \
     -f deploy/helm/onibex-ask/values-ias-dev.yaml
   ```
4. Wait for the five services that restart:
   ```bash
   for d in studio chat setup admin-api orchestrator; do
     kubectl -n onibex-ask rollout status deployment ask-onibex-ask-$d
   done
   ```

In steps 2 and 3, use your own cloud's profile in place of `values-kyma-dev.yaml`.

---

## Step 4. Confirm the platform switched

```bash
for h in <studio host> <chat host> <setup host>; do
  curl -s "https://$h/config.js" | grep -E "AUTH_MODE|IAS_URL|IAS_CLIENT_ID"
done
curl -sI "https://<setup host>/" | grep -io "connect-src[^;]*"
```

Each app must print `AUTH_MODE: 'ias'`, your tenant and your Client ID, and the last line must name
your tenant.

---

## Step 5. Sign in, first without the administrator role

Use a **new private window** each time this step says so. A normal window can hold another IAS
session, the console's for example, and IAS would sign the app in as that person without asking.

1. In IAS, put yourself in **`ask-user` only**, not in `ask-admin`.
2. In a new private window, open ASK Studio and sign in. Expected: **Access restricted**, naming
   `ask-admin` as required and listing your roles.
3. In that tab, press F12, open **Console** and run this. If the browser refuses to paste, type
   `allow pasting` first and press Enter.
   ```js
   fetch('/api/yamls', {headers: {Authorization: 'Bearer ' + sessionStorage.getItem('auth_access_token')}}).then(r => console.log(r.status))
   ```
   Expected: **403**. A `404` is a typo in the address. A `200` means administrators are not being
   told apart from everyone else, and nothing else on this page matters until it is fixed.
4. In the same window, open ASK Chat. Expected: it signs you in without asking again.
5. In IAS, add yourself to **`ask-admin`**. Close every private window.
6. In a new private window, open ASK Studio and ASK Setup. Expected: both open, and ASK Setup's
   **Identity Provider** page shows **SAP Cloud Identity Services (IAS)** with your tenant, your
   Client ID and your roles.
7. In a new private window, open only ASK Chat and sign in. Press **Sign out**, the button next to
   your email at the bottom of the sidebar, then **Sign in** again. Expected: Chat's sign-in screen,
   and then IAS asking for your credentials again.

---

## When something is wrong

| What you see | Why | What to do |
|---|---|---|
| IAS shows *"OpenID provider cannot process the request because the configuration is incorrect"* as soon as you press Sign in | A `/login/callback` address is missing, or the client id is wrong | Step 1.2, then Step 2 |
| IAS shows *"OpenID provider cannot process the logout request because the post_logout_redirect_uri is unknown"* when you sign out | The `/login` addresses are not under **Post Logout Redirect**, often because they went under Redirect | Step 1.2, then Step 2 |
| *Authentication error* on returning to the app, or `invalid_client` | Public client flows are off | Step 1.5 |
| The sign-in fails after the password, with nothing in the tenant's logs | The browser was not allowed to reach the tenant: the last line of Step 4 does not name it | Step 3 again |
| **Access restricted** for someone who is in `ask-admin` | The `groups` attribute is missing or not *All Groups*, or the token predates the change | Step 1.6, then a new private window |
| An identifier like `P000123` where the email should be | The `email` attribute is missing | Step 1.6 |
| The session belongs to someone else | A normal window, with another IAS session open | A new private window |
| Studio signs out about an hour after signing in to Chat | Maximum Sessions per User is 1 | Step 1.4 |
| Step 2 prints **READ THIS FIRST** | The client id is wrong, often the Application ID copied instead | Copy it from Client Authentication |

---

## Going back to Keycloak

The same `helm upgrade` **without** the second `-f`. Keycloak ran the whole time with its realm, so
people sign in with their Keycloak accounts again at once, and the IAS application stays configured
for the next switch.

---

## Before a customer depends on this

These are decisions rather than steps:

- **Anyone in the tenant can use ASK Chat.** ASK Chat requires a signed-in user and no role, so with
  IAS every person in the customer's directory can sign in to it and ask questions of their data,
  whether or not they are in `ask-user`. Either the IAS application is restricted to the right
  people, or ASK Chat is made to require `ask-user`. This is read from the code and not yet measured
  with a person in neither group.
- **Keycloak keeps running, published, and unused.** It is what makes going back one flag. A customer
  on IAS for good should turn it off, and that is a separate change.
- **"All Groups" carries every group** the person is in, not only the two ASK ones. ASK ignores the
  rest, but their names travel in the token.
- **The application comes out as "Charged", not "Bundled".** It counts against the IAS license, and
  whether that costs money depends on the contract.

---

## Why it is set up this way

- **IAS and not XSUAA.** The apps sign in as public clients, with no secret, because a browser can
  never keep one. Sent the same secretless token exchange, XSUAA refuses the client
  (`401 invalid_client`) and IAS refuses only the fake code (`400 invalid_grant`). The chart refuses
  `auth.mode: xsuaa` for that reason.
- **Password, Client Credentials and JWT Bearer off.** *Password* exchanges a user name and password
  for a token directly, skipping the sign-in page and multi-factor authentication, and anyone who
  reads the public client id can try it.
- **Enforce PKCE on.** The apps always send it. It refuses a sign-in that someone starts without it
  using the public client id, whose code anyone who intercepted it could exchange.
- **Maximum Sessions per User 10.** It counts refresh tokens per person for this application, and the
  three apps share it. With 1, signing in to Chat cancels Studio's renewal.
- **Client ID Lock off.** It locks the client after five failed attempts with a secret. This client
  has no secret and its id is public, so anyone could lock everyone out with five requests.

---

[← Back to the manual](../README.md) · [Deploy on Kubernetes with Helm](kubernetes-deploy.md) · [Kubernetes reference](kubernetes-reference.md)
