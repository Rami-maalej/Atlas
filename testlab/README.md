# TestLab

A lightweight test-case management web application. Create test cases, track their
status (draft / pass / fail / blocked), filter and search them, and see summary
statistics like pass rate — all from a clean single-page UI.

Built with **zero external dependencies**: it uses only the Node.js standard
library on the backend and vanilla HTML/CSS/JS on the frontend. There is nothing
to install — just run it.

## Features

- Full CRUD for test cases: title, description, steps, priority, status
- Quick status switching (Pass / Fail / Blocked / Draft) with one click
- Search by title or description, filter by status
- Summary stats: totals per status and overall pass rate
- Input validation with clear error messages (client + server)
- Data persisted to `data/testcases.json` with atomic writes
- Path-traversal protection and request body size limits
- Responsive UI, works on mobile widths

### Stretch goals (not implemented)

- Test suites / tags / grouping
- Import/export of the JSON dataset
- Run history and audit log per test case
- Dark mode

## Tech Stack

| Layer     | Choice                                              |
|-----------|-----------------------------------------------------|
| Runtime   | Node.js >= 18.17 (no frameworks, stdlib `http`)      |
| Storage   | JSON file with atomic write (temp file + rename)     |
| Frontend  | Vanilla HTML/CSS/JavaScript single page app          |
| Testing   | `node:test` built-in test runner                     |
| Linting   | `node --check` based syntax lint (`scripts/lint.js`) |

## Project Structure

```
testlab/
├── server.js          # HTTP server: API routes + static file serving
├── lib/
│   ├── store.js       # Persistence layer (JSON file, CRUD, stats)
│   └── validate.js    # Input validation
├── public/
│   ├── index.html     # UI markup
│   ├── styles.css     # Styling
│   └── app.js         # Frontend logic
├── test/
│   ├── store.test.js  # Unit tests for the store
│   └── api.test.js    # Integration tests for the HTTP API
├── scripts/lint.js    # Syntax lint over all .js files
└── data/              # Created at runtime (gitignored)
```

## Installation

Nothing to install. You only need Node.js 18.17+ (no `npm install` required —
there are zero dependencies).

## Run

```bash
npm start
```

Then open **http://localhost:3000**.

Useful variations:

```bash
PORT=8080 npm start        # custom port
npm run dev                # auto-restart on file changes (node --watch)
npm test                   # run the test suite (20 tests)
npm run lint               # syntax-check all source files
TESTLAB_DATA=./my.json npm start   # custom data file location
```

## API

| Method         | Endpoint            | Description                                  |
|----------------|---------------------|----------------------------------------------|
| GET            | `/api/health`       | Health check → `{ "status": "ok" }`          |
| GET            | `/api/tests`        | List test cases. Query: `?status=`, `?q=`    |
| POST           | `/api/tests`        | Create test case (`title` required)          |
| GET            | `/api/tests/:id`    | Get one test case                            |
| PUT / PATCH    | `/api/tests/:id`    | Partially update a test case                 |
| DELETE         | `/api/tests/:id`    | Delete a test case                           |
| GET            | `/api/stats`        | Counts per status + pass rate                |

Example:

```bash
curl -X POST http://localhost:3000/api/tests \
  -H 'Content-Type: application/json' \
  -d '{"title": "Login with valid credentials", "priority": "high"}'
```

A test case looks like:

```json
{
  "id": "2c8752ed-d6e1-47ef-a130-0188055bff79",
  "title": "Login with valid credentials",
  "description": "",
  "steps": "",
  "status": "draft",
  "priority": "high",
  "createdAt": "2026-11-14T12:14:42.144Z",
  "updatedAt": "2026-11-14T12:14:42.144Z"
}
```

Statuses: `draft`, `pass`, `fail`, `blocked`. Priorities: `low`, `medium`, `high`.
