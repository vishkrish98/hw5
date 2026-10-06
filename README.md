# Campus Customs — Multi-Agent Operations

A simulated campus shop run by a five-agent team (Boss, Inventory, Accounting, Facilities,
Customer Service) built with PydanticAI, exposed to the agents through a FastMCP server, wired
to a FastAPI backend, and watched live from a React dashboard. Every agent runs on `gpt-6-luna`
through a Portkey gateway — no other model or API is used anywhere in this project.

See [`output/harness.md`](output/harness.md) for the full technical write-up (database schema,
every MCP tool and who can call it, the five agents, the API routes, and the safety rules), and
[`output/design.md`](output/design.md) for the dashboard's look-and-feel rationale.

## Prerequisites

- Python 3.11+
- Node.js 18+
- A [Portkey](https://portkey.ai) API key with access to `gpt-6-luna`

## Setup

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```bash
cd frontend
npm install
cd ..
```

Copy the example env file and fill in your real key — `.env` is gitignored and never committed:

```bash
cp .env.example .env
# then edit .env and set PORTKEY_API_KEY=<your real key>
```

## Running a clean copy of the database

`data/campus_customs.db` is the original, untouched reference copy. `data/campus_customs_new.db`
is the working copy every tool in `mcp_server/server.py` actually reads and writes. Both are
included in this repo so you can run the app immediately, but whenever you want to start from a
known-clean state (a fresh three-ticket run, or just to undo whatever a prior session left
behind), restore the working copy from the original first:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

The backend also exposes this as a live route — `POST http://localhost:8000/reset` (or the
"Reset database" button in the dashboard's top bar) does exactly this copy, so you don't need to
touch the file by hand once the backend is running. **Reset the database before a full
three-ticket run** (101 → 102 → 103) if you want cash and inventory numbers that start from the
same baseline `output/desk_tickets.html` and `output/resolved_tickets.json` describe.

## Starting the MCP server

You generally don't need to start this as its own long-running process: `backend/agents.py`
spawns a fresh instance of `mcp_server/server.py` over stdio automatically, once per agent, every
time a ticket is run — that's handled for you the moment the FastAPI backend is up.

To start it directly instead — to test a tool by hand, or to connect it to a chat-based MCP client
such as Claude Code — run it from the repo root:

```bash
.venv/bin/python mcp_server/server.py
```

This project's own `.mcp.json` already registers it as `campus-customs` for any MCP client that
reads that file from the repo root (reconnect your client's MCP session to pick it up). See
[`mcp_server/README.md`](mcp_server/README.md) for the full tool list.

## Starting the FastAPI backend

With the virtualenv active:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

The backend must run on port 8000 — the frontend is hard-coded to call
`http://localhost:8000`, and CORS is locked to the frontend's own origin
(`http://localhost:5173` / `127.0.0.1:5173`).

## Starting the React dashboard

In a separate terminal:

```bash
cd frontend
npm run dev
```

Open the URL Vite prints (`http://localhost:5173`). Pick a ticket, click "Run agent team," and
watch the five agent nameplates and the ledger-book feed update live as the run progresses.
Payments only ever move after you click Approve on the card in the right-hand column — no agent
can execute one on its own.

## Repo layout

```
AI_prompts.md        — log of every prompt used to build this, one section per problem
requirements.txt     — backend + MCP server Python dependencies
.env.example          — required environment variable names (no real values)
.mcp.json             — registers the MCP server for MCP-aware clients
data/                 — campus_customs.db (original) and campus_customs_new.db (working copy)
mcp_server/           — the FastMCP server and its own README
backend/              — FastAPI app, the five PydanticAI agents, and their prompts
frontend/             — the React + Vite + TypeScript dashboard
output/               — harness.md, design.md, the three-ticket planning/reflection page,
                        the resolved-run artifacts, and the full append-only audit trail
```
