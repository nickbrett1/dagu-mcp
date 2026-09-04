# dagu-mcp

MCP server for the NAS **dagu** job scheduler — an agent interface to list,
inspect, create/update/delete, enable/disable, run, and read logs of dagu jobs.

Design:
- **Edits** → direct filesystem reads/writes of YAML in the dags dir (dagu
  hot-reloads `*.yaml`).
- **Run/status/history/logs** → the dagu CLI inside the `dagu` container via
  `docker exec dagu dagu ...` (avoids a dagu v2.15.1 REST bug + the API-key
  auth quirk).

## Deploy (NAS)

Import `docker-compose.yml` as a Container Manager "Project". The service mounts
the dagu data dirs plus the host docker socket/CLI (so it can exec into dagu),
and runs the published image `ghcr.io/nickbrett1/dagu-mcp:latest`.

On push to `main`, CircleCI publishes `ghcr.io/nickbrett1/dagu-mcp:latest`;
Watchtower picks it up automatically.

## Develop

This repo includes a **Python devcontainer** (`.devcontainer/`) so you can open
it in VS Code/Cursor (or an iPad/phone via a remote devcontainer client) and
work on `server.py` in a consistent environment.

## Files

- `server.py` — the FastMCP server (tools for dagu jobs).
- `Dockerfile` — slim python image running `server.py`.
- `docker-compose.yml` — NAS deployment.
- `.circleci/config.yml` — CI: `build` (ruff + pytest) → `docker-publish` on `main`
  (uses the `common` context for `GHCR_USERNAME` / `GHCR_TOKEN`).
