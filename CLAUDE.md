# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A FastAPI service that provisions and tears down a Minecraft server on AWS on demand. The HTTP endpoints drive Pulumi's Automation API in-process — there is no `pulumi` CLI invocation at runtime. `POST /tetracubed/start` runs the equivalent of `pulumi up`, `POST /tetracubed/stop` runs `pulumi destroy`.

## Commands

Uses `uv` for Python deps (Python 3.13+).

```bash
uv sync                                   # install deps
uv run uvicorn main:app --reload          # run the API locally
PULUMI_STACK_NAME=dev uv run uvicorn main:app   # override stack (defaults to "dev")
```

There are no tests, no linter config, and no build step.

Pulumi state and secrets are sourced from **Pulumi ESC** — the stack adds the `tetracubed-api/dev` environment at runtime, and `/tetracubed/start` will fail fast if no ESC environment is configured. You must be logged into Pulumi (`pulumi login`) and AWS (creds available to boto3) before hitting the endpoints.

## Architecture

### Two layers, one process

1. **FastAPI layer** (`main.py`) — auth (`/token`, JWT via `pwdlib` + `pyjwt`), and three operational endpoints that all wrap the same `create_pulumi_program()` function via `pulumi.automation.create_or_select_stack(...).up()` / `.destroy()` / `.outputs()`.
2. **Pulumi program** (`create_pulumi_program` in `main.py`, components under `infrastructure/`) — defined as a Python function rather than a separate `__main__.py`, so the FastAPI process *is* the Pulumi program. The `work_dir` passed to the Automation API is the repo root so `Pulumi.yaml` / `Pulumi.dev.yaml` are picked up.

### Orchestrated lifecycle via dynamic providers

The hard part of this codebase is that **start** isn't just "create infra" and **stop** isn't just "destroy infra" — world data has to be moved and DNS has to be updated at very specific points. This is done with three Pulumi **dynamic providers** (`infrastructure/*/[*_provider.py]`) that do real boto3/HTTP work inside their `create`/`delete` hooks:

| Resource | `create` (during `up`) | `delete` (during `destroy`) |
|---|---|---|
| `DataSyncExecution("s3-to-efs-auto", run_on_create=True, run_on_delete=False)` | Runs S3 → EFS DataSync, waits for SUCCESS | no-op |
| `EcsServiceManager` | `update_service desiredCount=1`, waits for stable, returns task's public IP | `update_service desiredCount=0`, waits for tasks to drain |
| `DynamicDnsUpdate` | POSTs to No-IP `dynupdate` with public IP | **no-op** (DNS record intentionally left in place) |
| `DataSyncExecution("efs-to-s3-auto", run_on_create=False, run_on_delete=True)` | no-op | Runs EFS → S3 DataSync to save world data |

Pulumi destroys in reverse-creation order, so the `up` chain (`s3-to-efs → ecs service start → ddns`) becomes a `destroy` chain of (`ddns no-op → ecs service stop → efs-to-s3 save → tear down EFS/ECS/VPC`). The `depends_on` wiring in `create_pulumi_program` is what makes this ordering correct — don't reorder those without thinking through both directions.

Two consequences worth knowing:
- The `aws.ecs.Service` is declared with `desired_count=0`. `EcsServiceManager` is what actually scales it up/down. Setting `desired_count` on the `Service` resource itself would fight the dynamic provider.
- The task definition uses `replace_on_changes=["containerDefinitions"]` so edits to env vars / image / ops list force a new task definition revision rather than an in-place mutation that ECS would silently ignore.

### Infrastructure components

`infrastructure/` is laid out by AWS concern (`networking/`, `storage/`, `ecs/`, `data/`, `dns/`). Each is a `pulumi.ComponentResource` that takes the upstream components as constructor args — wiring happens in `create_pulumi_program`, not via globals.

### Config

`config/config.py` exposes a single `config` singleton built from `pulumi.Config()`. Notable: `ops_list` is a JSON-encoded secret string (`config.require_secret("ops_list").apply(json.loads)`), not a plain list — keep `.apply(...)` semantics in mind when consuming it (see `ecs.py` which uses `pulumi.Output.all(...).apply(...)` to splice it into the container definition).

The `OPS_LIST` env var override in `main.py` is also stored as a *secret* config value; other env-var overrides are non-secret.

### Stale top-level scripts

`datasync.py`, `ecs_service.py`, `update_hostname_ip.py` at the repo root are earlier procedural versions of what the dynamic providers under `infrastructure/` now do. They're not imported anywhere in the live code path — prefer editing the providers, and treat the top-level scripts as either dead code or reference material.

## Auth model

Users come from a `USERS_DB` env var containing a JSON object of `{username: {hashed_password, ...}}`. `JWT_SECRET_KEY` signs tokens (HS256, 30-minute expiry). There is no user store, no registration endpoint, no refresh — adding one means changing the source of `USERS_DB`, not adding a database.
