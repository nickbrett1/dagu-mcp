"""Dagu Scheduler MCP — agent interface for the NAS dagu scheduler.

Serves tools to list, inspect, create/update/delete, enable/disable, run, and
read logs of dagu jobs. Design per memos/dagu-scheduler-mcp.

Strategy:
  * Edits  -> direct filesystem reads/writes of YAML in the dags dir (dagu
              hot-reloads *.yaml; edits land as git-able files).
  * Run/status/history/logs -> dagu CLI inside the dagu container via
              `docker exec dagu dagu ...` (avoids the dagu v2.15.1 REST
              ExecuteDAG nil-pointer bug and the API-key auth quirk).

Run: python3 server.py   (transport=http, port $DAGU_MCP_PORT or 3007)
"""

from __future__ import annotations

import os
import subprocess
import pathlib
import shutil
import yaml

from fastmcp import FastMCP

DAGS = pathlib.Path(os.environ.get("DAGU_DAGS_DIR", "/dags"))
LOGS = pathlib.Path(os.environ.get("DAGU_LOGS_DIR", "/logs"))
DAGU_CONTAINER = os.environ.get("DAGU_CONTAINER", "dagu")

mcp = FastMCP(
    "dagu-scheduler",
    instructions=(
        "NAS dagu job scheduler. Jobs are YAML files in the dags directory that "
        "dagu hot-reloads. Tools: list_jobs, get_job, create_job, update_job, "
        "delete_job, enable_job, disable_job, run_job, job_logs, search_jobs. "
        "Job YAML must be a mapping with a `schedule` (cron) and `steps` (graph "
        "type) or `tasks` (chain type). After any edit, dagu auto-reloads and "
        "the dags git repo auto-commits+pushes. Use run_job to trigger now."
    ),
)


def _dag_paths() -> list[pathlib.Path]:
    return sorted(DAGS.glob("*.yaml"))


def _job_name(f: pathlib.Path) -> str:
    return f.stem


def _load(name: str) -> dict:
    f = DAGS / f"{name}.yaml"
    if not f.exists():
        raise ValueError(f"job '{name}' not found (expected {f.name})")
    try:
        return yaml.safe_load(f.read_text()) or {}
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"job '{name}' YAML invalid: {e}") from e


def _validate(name: str, text: str) -> dict:
    try:
        data = yaml.safe_load(text)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("job YAML must be a mapping (top-level dict)")
    has_steps = isinstance(data.get("steps"), list) and data["steps"]
    has_tasks = isinstance(data.get("tasks"), list) and data["tasks"]
    if not (has_steps or has_tasks):
        raise ValueError("job YAML must define a non-empty `steps` or `tasks` list")
    if "schedule" not in data:
        # scheduled jobs need a schedule; allow manual-only but warn via description
        pass
    return data


def _dagu_cli(args: list[str], timeout: int = 180) -> tuple[str, str, int]:
    """Run a dagu CLI command inside the dagu container."""
    try:
        p = subprocess.run(
            ["docker", "exec", DAGU_CONTAINER, "dagu", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return p.stdout, p.stderr, p.returncode
    except Exception as e:  # noqa: BLE001
        return "", f"docker exec failed: {e}", 1


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@mcp.tool
def list_jobs() -> list[dict]:
    """List all dagu jobs: name, file, schedule, description, disabled."""
    out = []
    for f in _dag_paths():
        try:
            d = yaml.safe_load(f.read_text()) or {}
            out.append({
                "name": d.get("name") or f.stem,
                "file": f.name,
                "schedule": str(d.get("schedule", "") or ""),
                "description": d.get("description", "") or "",
                "disabled": False,
            })
        except Exception as e:  # noqa: BLE001
            out.append({"name": f.stem, "file": f.name, "error": str(e)})
    # include disabled (renamed) jobs
    for f in sorted(DAGS.glob("*.yaml.disabled")):
        out.append({"name": f.stem, "file": f.name, "schedule": "", "description": "(disabled)", "disabled": True})
    return out


@mcp.tool
def get_job(name: str) -> dict:
    """Return a job's full YAML plus recent run history."""
    _load(name)  # raises if missing / invalid
    hist, herr, rc = _dagu_cli(["history", name])
    history = (hist or herr or "")[-4000:]
    return {"name": name, "yaml": (DAGS / f"{name}.yaml").read_text(), "history": history}


@mcp.tool
def search_jobs(query: str) -> list[dict]:
    """Search jobs by name/schedule/description substring (case-insensitive)."""
    q = query.lower()
    return [j for j in list_jobs() if q in (j.get("name") or "").lower() or q in (j.get("schedule") or "").lower() or q in (j.get("description") or "").lower()]


@mcp.tool
def job_logs(name: str, limit: int = 60) -> str:
    """Return the tail of the most recent run's log for a job."""
    d = LOGS / name
    if not d.is_dir():
        return f"no log directory for '{name}'"
    runs = sorted([p for p in d.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    if not runs:
        return f"no runs recorded for '{name}'"
    latest = runs[0]
    # prefer merged/step .log, else *.out
    logs = sorted(latest.glob("*.log")) + sorted(latest.glob("*/*.log"))
    if logs:
        txt = logs[0].read_text(errors="replace")
    else:
        outs = sorted(latest.rglob("*.out")) + sorted(latest.rglob("*.err"))
        txt = "\n".join(p.read_text(errors="replace") for p in outs[-2:])
    lines = txt.splitlines()
    return "\n".join(lines[-limit:])


# --------------------------------------------------------------------------- #
# Writes (filesystem)
# --------------------------------------------------------------------------- #
@mcp.tool
def create_job(name: str, yaml_text: str) -> dict:
    """Create a new dagu job from YAML text. Name must match the file."""
    _validate(name, yaml_text)
    f = DAGS / f"{name}.yaml"
    if f.exists():
        raise ValueError(f"job '{name}' already exists — use update_job")
    f.write_text(yaml_text)
    return {"ok": True, "file": f.name}


@mcp.tool
def update_job(name: str, yaml_text: str) -> dict:
    """Replace an existing job's YAML (validated). dagu hot-reloads it."""
    _validate(name, yaml_text)
    f = DAGS / f"{name}.yaml"
    if not f.exists():
        raise ValueError(f"job '{name}' not found — use create_job")
    f.write_text(yaml_text)
    return {"ok": True, "file": f.name}


@mcp.tool
def delete_job(name: str) -> dict:
    """Delete a dagu job (removes its YAML file)."""
    f = DAGS / f"{name}.yaml"
    if not f.exists():
        raise ValueError(f"job '{name}' not found")
    f.unlink()
    return {"ok": True, "deleted": name}


@mcp.tool
def disable_job(name: str) -> dict:
    """Disable a job (rename to *.yaml.disabled so dagu stops loading it)."""
    f = DAGS / f"{name}.yaml"
    if not f.exists():
        raise ValueError(f"job '{name}' not found (or already disabled)")
    f.rename(DAGS / f"{name}.yaml.disabled")
    return {"ok": True, "disabled": name}


@mcp.tool
def enable_job(name: str) -> dict:
    """Re-enable a disabled job (rename back to *.yaml)."""
    d = DAGS / f"{name}.yaml.disabled"
    if not d.exists():
        raise ValueError(f"job '{name}' not disabled (or not found)")
    d.rename(DAGS / f"{name}.yaml")
    return {"ok": True, "enabled": name}


# --------------------------------------------------------------------------- #
# Run (via dagu CLI inside the container — avoids REST API bug)
# --------------------------------------------------------------------------- #
@mcp.tool
def run_job(name: str) -> dict:
    """Trigger a job run now (async). Returns the dagu CLI output."""
    _load(name)
    out, err, rc = _dagu_cli(["start", f"/var/lib/dagu/dags/{name}.yaml"])
    return {"ok": rc == 0, "rc": rc, "output": (out or err or "")[-3000:]}


@mcp.tool
def stop_job(name: str) -> dict:
    """Stop active runs of a job."""
    out, err, rc = _dagu_cli(["stop", name])
    return {"ok": rc == 0, "output": (out or err or "")[-1500:]}


if __name__ == "__main__":
    port = int(os.environ.get("DAGU_MCP_PORT", "3007"))
    mcp.run(transport="http", host="0.0.0.0", port=port)
