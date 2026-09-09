# Secret scanning and credential rotation

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Secret scanning and credential rotation**

> **How to.** Keep credentials out of the repository, and know what to do the day one gets in
> anyway. For the people who own the repository settings and the credentials themselves.
> **Scope:** the `Secret scanning` CI job, GitHub's own push protection, and the rotation
> procedure.

| | |
|---|---|
| **Who** | Repository administrator, or whoever owns the credential that leaked |
| **Time** | ~15 minutes for the settings; rotation depends on the credential |
| **Prerequisites** | Admin rights on the GitHub repository. For rotation, access to the system the credential belongs to. |
| **You'll end with** | Two independent guards against a committed secret, and a written order of operations for when one fires. |

---

## The two guards, and why there are two

**In the repository:** the `Secret scanning` job in `.github/workflows/platform-ci.yml`. It runs
`gitleaks` pinned to an exact version, scans what a pull request adds, and scans the full
history on a push to `main`.

**In GitHub:** secret scanning with push protection, which rejects a push containing a
recognised credential before it lands.

Neither replaces the other. Push protection can be bypassed by the person pushing, does not
apply to forks the same way, and is a setting somebody can switch off in a menu. The CI job
lives in the repository and travels with every clone of it. Belt and braces is correct here.

### Turning on GitHub's half

In the repository, **Settings › Code security**, enable **Secret scanning** and then **Push
protection**. Both are per-repository switches. Nothing else is needed: it applies to future
pushes immediately and starts a background scan of the existing history, whose results appear
under **Security › Secret scanning alerts**.

### The CI half, and its state today

The job is deliberately **not** a required status check yet. A new check should report the
truth on its first runs rather than block the pull request that introduces it, which is how
`Package test suites` was added and then promoted. Promote it in the `protect-main` ruleset
once the history findings below are resolved.

`gitleaks` runs with `--redact`, so matched values never reach the CI log. The fingerprints it
prints are safe to copy.

---

## When the job fails

**Rotate first. Remove second. Never the other way round.**

A secret that has been pushed is compromised from that moment, whatever happens to the file
afterwards. Deleting the file first feels like progress and changes nothing about the exposure;
it only makes the credential harder to find while it is still live.

1. **Identify what leaked** from the finding: which credential, which system, who uses it.
2. **Rotate it in the system it belongs to.** New value, old value invalidated.
3. **Update wherever the platform reads it.** Most credentials live in the encrypted store and
   are re-entered through ASK Setup; the three in the table below come from the environment.
4. **Remove it from the working tree** so the next commit does not re-add it.
5. **Record the finding** in `.gitleaksignore`, one entry with its commit and the note that it
   was rotated, so the job goes green for a reason a reader can check.

### History is not rewritten

Not with `filter-repo`, not with `filter-branch`. A rewrite breaks every clone and every fork,
and once the values are dead it is theatre. The archived BTP material under
`platform/_internal/archive` was tracked before it was archived, so `kubeconfig.yaml`,
`xs-security.json` and a script with hardcoded SAP credentials are in history permanently.
Every credential they reference is considered compromised and needs rotation, which is the only
remediation that is real.

### What protects that archive now

It stays in the working tree, because it is the reference material for the Kyma work. What
keeps it out of a commit is `platform/.gitignore`, which ignores `_internal/` entirely. That is
verifiable rather than assumed:

```bash
git add -An platform/_internal/archive/kubeconfig.yaml
# The following paths are ignored by one of your .gitignore files
```

`git add -A` cannot stage it. A deliberate `git add -f` still can, and that is what the pull
request scan is for: the second guard catches what a deliberate override gets past the first.

---

## The three credentials that live in the environment

Everything else the platform holds is encrypted inside OpenSearch and entered through ASK
Setup. These three cannot be, because each one is needed before that store can be read.

| Credential | Where it lives | Rotating it |
|---|---|---|
| `ONIBEX_ENCRYPTION_KEY` | Kubernetes Secret, or `.env` locally | **See the warning below. This one is not an ordinary rotation.** |
| `OPENSEARCH_PASSWORD` (plus host) | Kubernetes Secret, or `.env` locally | Change it in OpenSearch, then in the Secret, then restart the backends. |
| `KC_ADMIN_PASSWORD` | Kubernetes Secret, or `.env` locally | Keycloak bootstrap only, and only while Keycloak is part of the deployment. |

### ⚠️ `ONIBEX_ENCRYPTION_KEY` must stay byte-identical

**This key is the one thing on this page you cannot rotate casually.** It is the Fernet key that
decrypts everything the platform stores in OpenSearch: the LLM provider credentials, the
embedder credentials, the database connections and, since 2026-09-09, the SAP password.

**Changing it is not a rotation, it is a data-loss event.** Every stored secret becomes
unreadable at once, and the only recovery is re-entering all of them by hand through ASK Setup.
It must be **byte-identical across every deployment and every upgrade** of the same
environment. Generate it once, keep it in a vault, and copy it forward.

If it genuinely has to change, `platform/scripts/rotate_master_key.py` exists for exactly that
and re-encrypts the stored values under the new key. Read it before running it, and take a
snapshot of the index first.

---

[← Back to operating the platform](README.md)
