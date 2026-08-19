---
name: deploy-ec2
description: >-
  Package and deploy the Onibex ASK Platform stack to a single EC2 dev box (HTTP,
  no TLS). Use when the user says "empaqueta/empaquetado para EC2", "deploy to EC2",
  "sube el stack a EC2", "redeploy on EC2", or asks to build the deploy tarball.
  Wraps scripts/package-ec2.sh (build the secret-free tarball) + redeploy.sh (on-box
  rebuild) and points at the authoritative runbook. EC2 and local run the SAME
  docker-compose.yml — the only difference is .env.
---

# Deploy the ASK stack to an EC2 dev box

All platform paths live under `platform/` in this monorepo; run the tools from
there. **Authority:** the internal runbook (untracked, team-local) at
`platform/_internal/docs/runbooks/ec2-dev-deploy.md` — Security Group, Keycloak
redirect URIs, the plain-HTTP Chrome flag, troubleshooting. Read it before doing
anything non-obvious. This skill is the short operational path.

## Key facts (do not violate)
- **There is NO EC2 compose overlay.** EC2 runs the same `docker-compose.yml` as
  local; only `.env` differs. One var, `EXTERNAL_HOST`, repoints Keycloak's issuer
  and all three SPAs' baked `VITE_KEYCLOAK_URL` to the public host.
- **The tarball must never carry secrets.** `scripts/package-ec2.sh` excludes the
  local `.env` and `config/aicore_config.json` (and heavy build artifacts). Never
  hand-tar without those excludes — you would leak `ONIBEX_ENCRYPTION_KEY` / SAP
  creds and clobber the box's own `.env`. The templates `.env.ec2.example` /
  `.env.example` DO ship.
- **SPAs are baked at BUILD time.** `VITE_*` (incl. `EXTERNAL_HOST`) are compiled
  into the bundles, so the three SPAs MUST be rebuilt whenever `EXTERNAL_HOST`
  changes. `redeploy.sh` rebuilds everything.
- **`ONIBEX_ENCRYPTION_KEY` must stay stable** across redeploys — it decrypts the
  provider/DB secrets stored in OpenSearch. Changing it makes them undecryptable.
- **`ENVIRONMENT` accepts only `local` / `production`** (never `dev`), and
  `DEV_BYPASS_AUTH` is honored only when `ENVIRONMENT=local`.
- **OpenSearch :9200 is host-published with no auth** — never open it in the
  Security Group.
- A bare `docker compose up -d` (and `redeploy.sh`) starts all 9 containers;
  `teams-bot` + `mcp-server` idle until given creds. To skip them, target the 7
  core services explicitly.

## The tools
- `platform/scripts/package-ec2.sh` — runs on the DEV machine (Git Bash / WSL /
  macOS / Linux). Resolves its root as the parent of `scripts/`, so it packages
  `platform/` and builds `platform-deploy.tar.gz` one level up; `--upload --host
  user@ip --key k.pem` also scp's it. Self-asserts that `.env` never entered the
  archive.
- `platform/redeploy.sh` — runs ON THE BOX. Rebuilds images from the working
  tree + recreates containers (`ONLY=<svc>` for one service, `NO_CACHE=1` for a
  clean build). Keeps volumes.
- `platform/.env.ec2.example` — the EC2 `.env` template (copy to `.env` on the box).
- **On the box, keep extracting into the SAME directory as previous deploys**
  (historically `~/onibex-ask`) — its configured `.env` lives there and must
  survive; the tarball never carries one.

## Procedure

### A. First-time deploy
1. **Package** (dev machine, from `platform/`):
   `./scripts/package-ec2.sh --upload --host ec2-user@<IP> --key <key.pem>`
   (or run without `--upload`, then scp `platform-deploy.tar.gz` yourself).
2. **Extract** (box): `mkdir -p ~/onibex-ask && tar -xzf ~/platform-deploy.tar.gz -C ~/onibex-ask/`
3. **Configure `.env`** (box): `cd ~/onibex-ask && cp .env.ec2.example .env`, then
   fill in `EXTERNAL_HOST`, generate `ONIBEX_ENCRYPTION_KEY`
   (`python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`),
   set `SEMANTIC_LAYER_HOST_PATH` (must be a real git repo — `git init` it first),
   change `KC_ADMIN_PASSWORD` / `ASK_INGEST_API_KEY`. See runbook §3.
4. **Build + start**: `./redeploy.sh` (first SPA build ~15-20 min). Or bring up in
   layers per runbook §4.
5. **Keycloak init** (only on a fresh `keycloak-data` volume): `sslRequired=NONE`
   on `master`, register the EC2 redirect URIs for `ask-studio-spa` / `ask-setup-spa`.
   See runbook §5.
6. **Security Group + access**: open only 5173/5174/5175/8180 (+ 8091/8085/4004 for
   M2M) to the team's IPs; never 9200. Apply the Chrome insecure-origin flag for the
   admin/setup SPAs. Runbook §6-§7.
7. **Verify**: `docker compose ps`; curl `http://<EXTERNAL_HOST>:<ORCH_HOST_PORT>/v1/health`.

### B. Re-deploy (reusing the same `.env`)
1. **Repackage + upload** (dev, from `platform/`):
   `./scripts/package-ec2.sh --upload --host … --key …`
2. **Swap + rebuild** (box):
   `cd ~/onibex-ask && docker compose down && tar -xzf ~/platform-deploy.tar.gz -C ~/onibex-ask/ && ./redeploy.sh`
   The tarball has no `.env`, so the box's configured `.env` survives the extract.

## When code touched deploy config
If `docker-compose.yml`, the service memory limits, ports, `.env.ec2.example`,
`redeploy.sh`, or `package-ec2.sh` changed, **update the internal runbook
(`platform/_internal/docs/runbooks/ec2-dev-deploy.md`) to match** — its §0 tables
(ports, container names, mem limits), §3 `.env` table, and §5 Keycloak claims are
the parts that drift. Verify each against the actual source files (compose,
`keycloak-realm-config.json`, the env template) before reporting done.

## Verify before reporting
- Run `platform/scripts/package-ec2.sh` and confirm the archive listing has NO `./.env` and
  NO `aicore_config.json`, but DOES have `.env.ec2.example` + `docker-compose.yml`.
- Any runbook edit's facts (ports, mem, container names, secrets, redirect URIs)
  trace to a real line in compose / `keycloak-realm-config.json` / `.env.ec2.example`.
