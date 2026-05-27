---
name: dashboard
description: >-
  Start or stop the Sentinel Article Dashboard locally. With no arguments (or /dashboard):
  syncs the production database, launches Flask backend + Vite dev server, opens Chrome.
  With --close or -c: kills all dashboard processes and closes the Chrome tab.
disable-model-invocation: true
---

# /dashboard — Article Dashboard

Check for arguments: if the user typed `/dashboard --close`, `/dashboard -c`, or `/dashboard close`, jump to **Close mode**. Otherwise run **Start mode**.

---

## Start mode (default, no arguments)

Execute all steps automatically. No user confirmation needed.

### 1. Check if already running

```bash
pgrep -f "run-dashboard" || pgrep -f "vite.*dashboard"
```

If either process is found → tell the user the dashboard is already running and offer to open Chrome to `http://localhost:5173`. Do not start duplicate processes.

### 2. Sync production database and start Flask backend

```bash
cd /home/kossa/code/project-sentinel && ./dashboard/run-dashboard.sh --sync --port 5001 &
```

This starts the Flask backend on port 5001. The `--sync` flag pulls a fresh copy of the production SQLite database before starting. Wait for the line containing `Running on` in the output before proceeding.

If the sync or backend fails to start within 30 seconds → **STOP** and report the error.

### 3. Start Vite dev server

```bash
cd /home/kossa/code/project-sentinel/dashboard/frontend && npm run dev &
```

Wait for the line containing `Local:` or `localhost:5173` in the output before proceeding.

If it fails to start within 30 seconds → **STOP** and report the error.

### 4. Open Chrome

```bash
google-chrome http://localhost:5173 2>/dev/null &
```

### 5. Report

Tell the user:
- Dashboard is running at **http://localhost:5173**
- Flask backend at **http://localhost:5001**
- To stop: `/dashboard --close`

---

## Close mode (`/dashboard --close` or `/dashboard -c`)

Kill all dashboard-related processes in one shot.

### 1. Kill processes

```bash
pkill -f "run-dashboard" 2>/dev/null; pkill -f "python -m dashboard" 2>/dev/null; pkill -f "vite.*dashboard" 2>/dev/null
```

### 2. Verify

```bash
pgrep -f "run-dashboard" || pgrep -f "vite.*dashboard" || echo "All dashboard processes stopped"
```

### 3. Report

Tell the user: Dashboard stopped.
