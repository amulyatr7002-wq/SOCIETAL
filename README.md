# CIVIC CONNECT
### Hyperlocal Civic Issue and Relief Dispatch Platform

Civic Connect is a Flask + SQLite demonstration application for reporting neighbourhood issues, coordinating response teams, and tracking progress. The frontend is plain HTML, CSS, and JavaScript. Leaflet uses OpenStreetMap tiles and Chart.js powers the administrator analytics. No map or chart API key is required.

## What works

- Citizen registration and login with Werkzeug password hashing and role-based access.
- Civic issue reports with a unique reference, validated details, map-picked coordinates, severity, and optional validated photo.
- Citizen-only complaint tracking, status timelines, and status notifications.
- Administrator report review, status updates, priority overrides, response-team assignment, interactive report map, and analytics.
- Response-team queue, progress updates, resolution-photo uploads, and completion.
- Explainable 0–100 priority calculation: severity contributes up to 50 points, similar reports within 1 km contribute up to 30 points, and elapsed time (up to 7 days) contributes up to 20 points. Labels: Critical (80+), High (60–79), Medium (35–59), Low (0–34). Administrators can override the label; the original score and factor breakdown remain visible.
- Demo data in Bengaluru, including reports at different workflow stages.http://127.0.0.1:5000

## Requirements

- Python 3.10 or later (tested with Python 3.12).
- Internet access in the browser for Google Fonts, Leaflet/OpenStreetMap map tiles, and Chart.js CDN. The application does not need an API key.

## Run in VS Code

1. Open the `scoietal` project folder in VS Code.
2. Open **Terminal → New Terminal** and create a virtual environment:

   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, use `.venv\Scripts\python.exe` instead of activating the environment.

3. Install the dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Initialize the SQLite database and demonstration accounts/data:

   ```powershell
   python -m flask --app app init-db
   ```

   The database file (`civic_connect.db`) is created in the project directory. The application also initializes it at startup, so the CLI step is safe to repeat.

5. Start the server:

   ```powershell
   python app.py
   ```

6. Open [http://127.0.0.1:5000](http://127.0.0.1:5000).

## Demonstration accounts

| Role | Email | Password |
|---|---|---|
| Administrator | `admin@civicconnect.local` | `CivicAdmin24!` |
| Citizen | `maya@civicconnect.local` | `Citizen24!` |
| Citizen | `kabir@civicconnect.local` | `Citizen24!` |
| Roads response team | `team@civicconnect.local` | `TeamLead24!` |
| Water response team | `water@civicconnect.local` | `TeamLead24!` |

These are local demonstration credentials only. Do not expose them or the development server publicly.

## Suggested project evaluation walkthrough

1. Sign in as `maya@civicconnect.local`, open **My reports**, and inspect the seeded reports and their status timelines.
2. Submit a new issue: select a category, enter a title and description, click the map to pin a location, optionally upload a JPEG/PNG/WebP photo, then submit. Note the generated `CC-...` reference.
3. Sign out, then sign in as the administrator. Open **All reports**, assign the new report to a team, adjust its status or priority, and inspect **Analytics** and **Neighbourhood map**.
4. Sign out and sign in as the response-team account assigned to the report. Open **Assigned reports**, set the report to **In Progress**, upload a resolution photo, then mark it **Resolved**.
5. Sign back in as the citizen and open the report to see the status history and uploaded photos. Use **Track a complaint** with the reference to look up the report.

## Project layout

```text
.
├── app.py                 # Flask routes, validation, authorization, scoring
├── database.py            # SQLite schema and demonstration seed data
├── requirements.txt
├── civic_connect.db       # Created on first run; ignored by Git
├── uploads/               # Validated issue and resolution images
└── static/
    ├── index.html
    ├── styles.css
    └── app.js
```

## Configuration and security notes

- Set `CIVIC_SECRET_KEY` to a long, random value before deploying beyond a local demo.
- Set `CIVIC_HTTPS=true` when serving behind HTTPS so session cookies are marked secure.
- Uploaded images are limited to 6 MB, decoded and validated as JPEG, PNG, or WebP, resized, and stored under generated filenames.
- The server enforces role permissions and validates report fields, locations, status values, assignments, and upload types. Session-changing requests use a session-bound CSRF token.
- This is a college-project demonstration, not a production deployment template. A public deployment should add operational controls such as HTTPS termination, rate limiting, backups, audit/retention policy, and a production-grade secret-management strategy.
