# Security Documentation

Last verified: 2026-10-03 (deployed commit 6429124)

Guides for hardening the VPS before deploying Project Sentinel. Do the hardening before you deploy the application.

The repeatable procedure is the script `deploy/01-harden-server.sh` with the files in `deploy/configs/`. Production was hardened with it on 2026-03-23. The guide below is its manual equivalent and also records where production differs today.

## Documents

| Document | Purpose |
|----------|---------|
| [VPS Hardening Guide](vps-hardening.md) | Step-by-step server security setup (Step 0 + Steps 1–12), which steps the script performs, production state, service sandbox |

## Quick Order of Operations

1. Create the VPS on Hetzner and set up the Hetzner Cloud Firewall (guide Step 0).
2. Harden the server: run `deploy/01-harden-server.sh` as root, or follow the [VPS Hardening Guide](vps-hardening.md) Steps 1–11 by hand.
3. Reboot and run the post-hardening checklist.
4. As `deploy`, run `deploy/02-deploy-app.sh`, then `deploy/03-setup-services.sh`. Later updates go through `/deploy`; see the [Server Runbook](../server-runbook.md) for ongoing operations. Warning: these scripts do not yet produce a working service. Script 02 creates and uses `venv/`, while the unit installed by script 03 runs `.venv/bin/python`, and script 02 installs `config/config.example.yaml` instead of the repo's `config/config.yaml`. A rebuild also needs `/etc/sentinel/openai.env` and the `20-openai.conf` drop-in, which no script creates (see [Server Runbook, Secrets](../server-runbook.md#secrets)). Both gaps are tracked in TODO.md §6.1.
