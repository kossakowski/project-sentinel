---
name: dashboard
description: >-
  Start or stop the Sentinel Article Dashboard locally. With no arguments (or /dashboard):
  syncs the production database, launches Flask backend + Vite dev server and prints the URL.
  With --close or -c: kills all dashboard processes.
disable-model-invocation: true
---

# /dashboard — Article Dashboard

Check for arguments: if the user typed `/dashboard --close`, `/dashboard -c`, or `/dashboard close`, jump to **Close mode**. Otherwise run **Start mode**.

---

## Start mode (default, no arguments)

Execute all steps automatically. No user confirmation needed.

### 1. Check if already running

Detect the dashboard by its listening ports (5001 Flask, 5173 Vite), not by process name. A `pgrep -f` pattern also matches the Bash tool's own wrapper shell, which contains the pattern text, so it always reports a hit.

```bash
ss -ltn | grep -E ':(5001|5173) ' || echo "not running"
```

If either port is listening → tell the user the dashboard is already running at `http://localhost:5173`. Do not start duplicate processes.

### 2. Sync production database and start Flask backend

```bash
cd /home/kossa/code/project-sentinel && ./dashboard/run-dashboard.sh --sync --port 5001 &
```

This starts the Flask backend on port 5001. The `--sync` flag copies the production `sentinel.db` file before starting. It copies only the main file, not the WAL file, so the newest writes may be missing from the copy. Wait for the line containing `Running on` in the output before proceeding.

If the sync or backend fails to start within 30 seconds → **STOP** and report the error.

### 3. Start Vite dev server

If `dashboard/frontend/node_modules` does not exist, install the frontend dependencies first. Without them `npm run dev` fails with `vite: not found`.

```bash
cd /home/kossa/code/project-sentinel/dashboard/frontend && [ -d node_modules ] || npm install
```

Then start the server:

```bash
cd /home/kossa/code/project-sentinel/dashboard/frontend && npm run dev &
```

Wait for the line containing `Local:` or `localhost:5173` in the output before proceeding.

If it fails to start within 30 seconds → **STOP** and report the error.

### 4. Report

Tell the user:
- Dashboard is running — open **http://localhost:5173** in your browser
- Flask backend at **http://localhost:5001**
- To stop: `/dashboard --close`

---

## Close mode (`/dashboard --close` or `/dashboard -c`)

Kill all dashboard-related processes in one shot. Stop them by port. Name patterns are unreliable here: `run-dashboard.sh` replaces itself with `python -m dashboard` (`exec`), the Vite command line is `node …/dashboard/frontend/node_modules/.bin/vite`, and `pkill -f` can match and kill the Bash tool's own shell.

### 1. Kill processes

```bash
fuser -k 5001/tcp 5173/tcp 2>/dev/null; true
```

### 2. Verify

```bash
ss -ltn | grep -E ':(5001|5173) ' || echo "All dashboard processes stopped"
```

If a port is still listening, show the `ss -ltnp` line and stop that PID.

### 3. Report

Tell the user: Dashboard stopped.
