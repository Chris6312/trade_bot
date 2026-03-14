# PROJECT STATE

Current Phase:
Phase 1 - Project Bootstrap

Completed Phases:
None

In Progress:
Phase 1 user-side apply and local runtime validation

Pending:
Phase 2 - Database and Core Settings
Phase 3 - Broker and Market Data Adapters
Phase 4 - Single Candle Worker
Phase 5 - Universe Engine
Phase 6 - Feature Engine
Phase 7 - Regime Engine
Phase 8 - Strategy Engine
Phase 9 - Risk and Sizing Engine

Known Issues:
- Frontend runtime and Docker Compose startup were not executed in this container because Docker is unavailable and npm dependency installation was not run here.
- Phase 1 should be considered ready for local validation after you extract the zip and run the project in your environment.

---

# HANDOFF SUMMARY

Phase Goal:
Create the initial full-stack skeleton and local development environment.

Phase Status:
In Progress

Summary:
Phase 1 scaffold files are prepared. The package includes a FastAPI backend, React frontend, Docker Compose stack, PostgreSQL container definition, root environment files, PowerShell startup helpers, and backend health tests. Backend tests passed in-container, and static validation passed for the compose file and frontend package metadata. Final Phase 1 closure depends on user-side startup and runtime verification.

---

# WHAT WAS COMPLETED

1. Created the backend FastAPI scaffold with environment-driven settings, CORS configuration, root endpoint, and health endpoints at `/health` and `/api/v1/health`.
2. Created the frontend React + Vite scaffold with a status dashboard that calls the backend health endpoint.
3. Added root `.env`, `.env.example`, Docker Compose, backend/frontend Dockerfiles, PowerShell startup scripts, and backend pytest coverage for the health endpoints.

---

# WHAT IS STILL IN PROGRESS

1. Apply the zip into the project root.
2. Start the stack in the local environment and verify backend, frontend, and PostgreSQL come up on the configured ports.
3. Confirm `.env` loading and Phase 1 exit criteria in the local workspace before moving into Phase 2.

> Leave this section in place only if the phase is not fully complete.
> If phase is complete, write: None.

---

# WHAT WE CHANGED

List every meaningful code, config, schema, logic, UI, worker, strategy, scheduler, or infrastructure change made in this phase.

1. File:
   .env
   .env.example
   Change:
   Added shared development environment configuration for backend, frontend, PostgreSQL, CORS, and API base URL.
   Reason:
   Phase 1 requires environment loading and non-blocked ports.
   Risk/Impact:
   Low. These are bootstrap defaults and will likely be edited later for real credentials and deployment settings.

2. File:
   docker-compose.yml
   backend/Dockerfile
   frontend/Dockerfile
   scripts/start-dev.ps1
   scripts/stop-dev.ps1
   scripts/wait-for-health.ps1
   Change:
   Added the local development stack, container definitions, and PowerShell helper scripts.
   Reason:
   Phase 1 requires Docker Compose, PostgreSQL, and a local start/stop flow.
   Risk/Impact:
   Low to medium. Runtime behavior depends on local Docker availability and future env changes.

3. File:
   backend/app/main.py
   backend/app/core/config.py
   backend/app/api/routes/health.py
   backend/tests/test_health.py
   backend/requirements.txt
   backend/pytest.ini
   backend/__init__.py
   backend/app/__init__.py
   backend/app/api/__init__.py
   backend/app/api/routes/__init__.py
   backend/app/core/__init__.py
   Change:
   Added the FastAPI app, settings loader, health endpoints, package structure, and backend tests.
   Reason:
   Phase 1 requires a base backend app and health endpoints with env-backed configuration.
   Risk/Impact:
   Low. This is intentionally narrow scaffolding and should be a safe base for Phase 2.

4. File:
   frontend/package.json
   frontend/index.html
   frontend/vite.config.js
   frontend/src/main.jsx
   frontend/src/App.jsx
   frontend/src/styles.css
   Change:
   Added a minimal React + Vite UI that reports backend health.
   Reason:
   Phase 1 requires a base frontend app and a visible sanity check path.
   Risk/Impact:
   Low. This is a placeholder shell meant to be extended later.

> Important:
> If anything was changed that may need to be re-applied later, include it here explicitly.
>
> Re-apply later if needed:
> - Keep host ports aligned to the project rules: backend 8101, frontend 4174, postgres 55432.
> - Preserve PowerShell-first helper scripts and avoid switching instructions to bash/curl for user-facing steps.

---

# AI PROMPT FOR NEXT CHAT 

Use this prompt for the next implementation pass:

You are continuing an existing Python trading bot project using 2026 coding standards. Maintain architecture consistency and avoid code drift.

Rules:
1. Read and follow README.md and PHASE_CHECKLIST.md before making any changes.
2. Treat the provided project files as the source of truth.
3. Do not refactor unrelated code.
4. Do not break existing working logic, API routes, workers, schedulers, tests, or frontend behavior.
5. Preserve backward compatibility unless the handoff explicitly says otherwise.
6. Use minimal, targeted edits.
7. Reuse existing patterns, naming, services, config style, and folder structure.
8. Keep stock, crypto, common, backend, and frontend boundaries clean.
9. Avoid placeholder code, dead code, duplicate helpers, and speculative rewrites.
10. If a fix is needed, implement the narrowest safe fix first.
11. If schema or config changes are required, update all dependent code paths.
12. Keep logging, error handling, and type safety production-ready.
13. Ensure changes follow 2026 standards for maintainability, readability, testability, and operational safety.
14. Do not silently change strategy thresholds, risk controls, scheduling behavior, or broker behavior unless explicitly requested.
15. After editing, run or prepare the appropriate tests for the changed area.
16. Perform backup of project using:
    root\scripts\backup_project.ps1
17. Output summary to:
    root\GPT-mini_Changes

Notes:
Validate and close out Phase 1 in the user's local environment first. After Phase 1 startup is verified, begin Phase 2 by adding Alembic, persistent settings tables, workflow tracking tables, account snapshot storage, and system event storage using minimal targeted edits.

---

# DATABASE / MIGRATION NOTES

Required:
No

Commands:
```powershell
# No Alembic migration is required for Phase 1.
# Phase 2 is expected to introduce Alembic.
```

---

# TESTING

Completed in this environment:
```powershell
cd backend
pytest -q
```

Result:
- 3 passed, 1 warning

Additional validation completed:
- Static validation of `docker-compose.yml`
- Static validation of `frontend/package.json`
- Presence checks for key Phase 1 files

Remaining user-side validation:
- Start Docker services locally
- Verify backend health at `http://localhost:8101/health`
- Verify frontend loads at `http://localhost:4174`
- Verify PostgreSQL binds on host port `55432`

---

# GIT / VERSION CONTROL

Status:
Not committed from this environment.

Recommended next commands after local validation:
```powershell
git add .
git commit -m "Phase 1 bootstrap scaffold"
git push
```

---

# NEXT CHAT CHECKLIST

1. Provide the updated full project zip as the new source of truth.
2. Confirm whether Phase 1 local startup succeeded or note any runtime errors.
3. If Phase 1 passes locally, proceed into Phase 2 database and core settings work.
