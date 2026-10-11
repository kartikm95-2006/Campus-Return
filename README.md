# Campus Return

Campus Return is a campus lost-and-found web app built with Flask and SQLite. Students can publish lost or found reports, browse and filter the board, see rule-based match suggestions, submit private ownership claims, and track their activity. Admins review claims, manage report statuses, and see simple campus analytics.

## Run locally

Requirements: Python 3.12+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open http://localhost:5000. The demo admin is `admin@campus.edu` with password `CampusAdmin123!`. Student accounts can be registered in the app.

## Run with Docker

Requirements: Docker Desktop with Compose.

```powershell
docker compose up --build
```

Open http://localhost:5001. SQLite data and uploaded photos persist in a named Docker volume. Set `HOST_PORT` if port 5001 is already occupied. To use non-demo credentials, set `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `SECRET_KEY` in your environment before starting Compose. Change the demo admin password and secret key before deploying anywhere beyond a local demonstration.

## Tests

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
```

Tests cover registration and password validation, search filters, lost-to-found suggestions, private verification details, duplicate claims, admin authorization, claim decisions, status updates, and notifications.

## GitHub Actions

The workflow at `.github/workflows/ci.yml` runs on pushes to `main`/`master` and on pull requests. It installs Python dependencies, runs the test suite, then builds a Docker image. Add a branch protection rule requiring the workflow to pass before merging. The workflow builds but does not publish the image to a registry.

## Suggested team split

- App flows and templates
- Database, matching, and claims
- Testing and QA
- Docker and GitHub Actions
- UI polish, documentation, and demo coordination

Use feature branches and pull requests so the CI workflow runs before changes are merged.
