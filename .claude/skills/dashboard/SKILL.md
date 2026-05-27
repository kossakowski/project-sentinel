---
name: dashboard
description: >-
  Start the Sentinel Article Dashboard locally — syncs the production database,
  launches the Flask backend and Vite dev server, and opens Chrome to the dashboard.
  Only invoke when the user explicitly calls /dashboard. Do NOT auto-trigger.
---

# /dashboard — Start Article Dashboard

Launch the local dashboard with a single command. No arguments needed.

## Steps

Execute all steps automatically. No user confirmation needed between steps.

### 1. Sync production database

```bash
cd /home/kossa/code/project-sentinel && ./dashboard/run-dashboard.sh --sync --port 5001 &
```

This starts the Flask backend on port 5001. The `--sync` flag pulls a fresh copy of the production SQLite database before starting. Wait for the line containing `Running on` in the output before proceeding.

If the sync or backend fails to start within 30 seconds → **STOP** and report the error.

### 2. Start Vite dev server

```bash
cd /home/kossa/code/project-sentinel/dashboard/frontend && npm run dev &
```

Wait for the line containing `Local:` or `localhost:5173` in the output before proceeding.

If it fails to start within 30 seconds → **STOP** and report the error.

### 3. Open Chrome

```bash
google-chrome http://localhost:5173 2>/dev/null &
```

### 4. Report

Tell the user:
- Dashboard is running at **http://localhost:5173**
- Flask backend at **http://localhost:5001**
- To stop: kill both background processes (Ctrl+C in each terminal, or run `pkill -f "run-dashboard"` and `pkill -f "vite"`)
