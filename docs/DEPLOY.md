# Deploying hwval

Four ways to run this, from "already have Docker" to "click a button on
Streamlit Cloud." All four use the same `src/hwval` package — nothing is
deployment-specific except configuration.

---

## a) Local docker-compose

Requires Docker + Docker Compose v2 (`docker compose version`).

```bash
git clone <this-repo> && cd nxp-hw-validation-agent
cp .env.example .env          # edit if you want a real LLM key; optional
docker compose up --build -d
```

This starts two services (see `docker-compose.yml`):

- `db` — `postgres:16-alpine`, with a healthcheck gating `app`'s startup and
  data persisted in the named volume `hwval-pgdata`.
- `app` — the Streamlit UI (`Dockerfile`), reachable at
  <http://localhost:8501>, `DATABASE_URL` pre-wired to `db`.

Seed and train from inside the running container (no local Python needed):

```bash
docker compose exec app python -m hwval.cli init
docker compose exec app python -m hwval.cli seed --duts 60
docker compose exec app python -m hwval.cli train
```

or just click **Seed database** / **Train models** in the app's sidebar — both
run against the same `db` container.

The optional MCP server (streamable HTTP, for a client outside this compose
project) is behind a profile so it isn't started by default:

```bash
docker compose --profile mcp up -d mcp   # serves on http://localhost:8765/mcp
```

Tear down:

```bash
docker compose down            # keep the postgres volume
docker compose down -v         # also delete it (full reset)
```

---

## b) Streamlit Community Cloud + Neon (free tier)

This is the zero-cost, zero-local-infra path: a managed Postgres and a
managed Streamlit host, both free tier.

### 1. Create the Neon project and database

1. Sign up at <https://neon.tech>, create a project (any region).
2. In the Neon console, note the connection string it gives you — it looks
   like:

   ```text
   postgresql://neondb_owner:AbCdEf123456@ep-example-12345.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
3. Create the `hwval` database (Neon's default DB is `neondb`; either rename
   the connection string's path to a database you create, or just reuse
   `neondb` — either works, hwval doesn't assume a database name).
4. Bootstrap the schema, either from your machine:

   ```bash
   psql "postgresql://neondb_owner:AbCdEf123456@ep-example-12345.us-east-2.aws.neon.tech/neondb?sslmode=require" \
     -f scripts/init_neon.sql
   ```

   or from Neon's web SQL editor — paste the contents of
   `scripts/init_neon.sql` and run it. Either way this only creates empty
   tables; seed data comes from the app itself (step 4 below).

### 2. Build the SQLAlchemy URL

`hwval.config.Settings.database_url` expects the `psycopg2` driver in the
scheme and **`sslmode=require`** (Neon rejects plaintext connections):

```text
postgresql+psycopg2://neondb_owner:AbCdEf123456@ep-example-12345.us-east-2.aws.neon.tech/neondb?sslmode=require
```

(Neon's own connection string uses `postgresql://` — just add `+psycopg2`
after `postgresql`.)

### 3. Push this repo to GitHub, then deploy on Streamlit Cloud

1. <https://share.streamlit.io> → **New app** → pick this repo/branch.
2. **Main file path:** `app/streamlit_app.py`.
3. Streamlit Cloud installs `requirements.txt` automatically — nothing else
   to configure there. **This is why `requirements.txt` deliberately excludes
   TensorFlow**: the free tier's build has limited time/disk, and the CPU
   wheel is large enough to risk both. `hwval.ml.train_tf` / `predict.py`
   detect the missing import and fall back to a PCA-based reconstruction
   autoencoder automatically — same interface, same downstream scoring code,
   just a classical model instead of an LSTM. The "Model performance" tab
   will show `autoencoder_backend: pca_fallback` in that case, which is
   expected, not an error.
4. **Secrets**: in the app's **Settings → Secrets**, add (TOML syntax):

   ```toml
   DATABASE_URL = "postgresql+psycopg2://neondb_owner:AbCdEf123456@ep-example-12345.us-east-2.aws.neon.tech/neondb?sslmode=require"

   # Optional -- omit entirely to run on the offline deterministic planner
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```

   Streamlit injects `st.secrets` entries as environment variables at
   startup, which is exactly what `hwval.config.Settings` (a
   `pydantic-settings` `BaseSettings`) reads from.
5. Deploy. First boot has an empty schema (tables only, no rows) — open the
   app and click **Seed database** in the sidebar, then **Train models**.
   From then on the app is stateful across restarts because the data lives
   in Neon, not in the container.

### Notes specific to this path

- Neon's free tier auto-suspends an idle branch; the first query after a
  cold start takes a few extra seconds while it wakes up. `SQLAlchemy`'s
  `pool_pre_ping=True` (already set in `hwval.db.engine` for non-SQLite URLs)
  means a stale pooled connection is detected and replaced rather than
  surfacing as an error.
- Streamlit Cloud's filesystem is ephemeral — `artifacts/models`,
  `artifacts/figures` and `artifacts/reports` do **not** survive an app
  restart/redeploy. That's fine for a demo (re-run **Train models** after a
  restart); it is not a place to keep anything you need long-term. The
  database rows in Neon are the durable state.

---

## c) Hugging Face Spaces (Docker alternative)

If you'd rather run the same Docker image Spaces-side instead of Streamlit
Cloud's native runtime:

1. Create a new Space at <https://huggingface.co/new-space>, **Space SDK:
   Docker**, template "Blank".
2. Push this repo's contents to the Space's git remote (Spaces are git repos):

   ```bash
   git remote add space https://huggingface.co/spaces/<you>/hwval
   git push space main
   ```

   Spaces builds whatever `Dockerfile` it finds at the repo root — the one in
   this repo already does the right thing (`EXPOSE 8501`, healthcheck,
   `streamlit run ... --server.port=8501`). Spaces expects the container to
   listen on port `7860` by default, so either:
   - add `app_port: 8501` to the Space's `README.md` YAML front-matter, e.g.:

     ```yaml
     ---
     title: hwval
     sdk: docker
     app_port: 8501
     ---
     ```
   - or override the Dockerfile's port at build time to `7860` (edit
     `EXPOSE`/`--server.port` to `7860`) if you'd rather not touch the Space
     config.
3. In the Space's **Settings → Repository secrets**, add `DATABASE_URL` (a
   Neon URL as in section b, or point at any Postgres reachable from the
   internet) and, optionally, an LLM key. Spaces injects repository secrets
   as environment variables into the container, same contract as Docker's
   `-e`.
4. Rebuild triggers automatically on push. Unlike Streamlit Cloud, this path
   **can** include TensorFlow if you want the real LSTM autoencoder — Spaces'
   free CPU tier has more headroom than Streamlit Cloud's build step; add
   `tensorflow-cpu` to a Spaces-specific requirements file or build the image
   with `pip install .[tf]` instead of `-r requirements.txt` in the
   Dockerfile if you go this route.

---

## d) MCP server → Claude Desktop

The MCP server (`src/hwval/mcp_server/server.py`) exposes the same audited
tool set as the LangChain agent — schema introspection, SQL, anomaly
detection, plotting, reports, test plans, DB maintenance — to any MCP client,
Claude Desktop included.

### stdio (simplest — Claude Desktop launches the process itself)

1. Find your Python environment's absolute path (the one with `hwval`
   installed, e.g. from `make install`):

   ```bash
   which python3   # e.g. /Users/you/nxp-hw-validation-agent/.venv/bin/python3
   ```
2. Edit Claude Desktop's config file:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`
3. Add an `hwval` entry under `mcpServers`:

   ```json
   {
     "mcpServers": {
       "hwval": {
         "command": "/absolute/path/to/nxp-hw-validation-agent/.venv/bin/python3",
         "args": ["-m", "hwval.mcp_server.server"],
         "env": {
           "PYTHONPATH": "/absolute/path/to/nxp-hw-validation-agent/src",
           "DATABASE_URL": "sqlite:////absolute/path/to/nxp-hw-validation-agent/artifacts/hwval.db"
         }
       }
     }
   }
   ```

   Use a real Postgres `DATABASE_URL` here instead if you want Claude Desktop
   talking to the same database as your docker-compose/Neon deployment.
4. Restart Claude Desktop. The tool icon (🔨) in the composer should list
   `describe_schema`, `run_sql_query`, `detect_anomalies`, `build_report`,
   `run_db_maintenance`, etc. Try the bundled prompt template: type `/hwval`
   or ask "triage test run 42" — that maps to the server's `triage_run`
   MCP prompt.

### streamable HTTP (server runs elsewhere, e.g. the docker-compose `mcp`
service or a HF Space)

```bash
python -m hwval.mcp_server.server --http 8765
# or: docker compose --profile mcp up -d mcp
```

Claude Desktop's config for a remote/HTTP MCP server:

```json
{
  "mcpServers": {
    "hwval": {
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

(If your Claude Desktop version only supports stdio servers, use
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote) as a local stdio ↔
HTTP bridge instead of the `url` form above.)

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `psycopg2.OperationalError: SSL connection required` | Neon URL missing `sslmode=require` | Append `?sslmode=require` (or `&sslmode=require` if there's already a `?`) |
| Streamlit Cloud build fails/times out | Something is trying to pull TensorFlow | Confirm you didn't add `tensorflow`/`tensorflow-cpu` to `requirements.txt` — it belongs only in `requirements-dev.txt` / the `tf` extra |
| "Offline deterministic planner" badge won't go away after setting a key | Key set in `.env` but not exported / not in Streamlit secrets | `.env` is only read by processes started from the repo root with `python-dotenv` loaded (the CLI, `make` targets); Streamlit Cloud needs the key in **Secrets**, Docker needs it in `docker-compose.yml`'s `environment:` or the shell environment |
| `hwval evaluate`/`score` return everything as `LOW`/NaN | No trained model yet | `make train` (or the sidebar's **Train models** button) before scoring |
