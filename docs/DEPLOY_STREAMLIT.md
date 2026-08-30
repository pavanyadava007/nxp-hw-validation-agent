# Deploying the demo to Streamlit Community Cloud (free)

This gives you a public URL for the live app — good for interviews and your
résumé. No API key and no database server required: the app runs on SQLite and
the offline rule-based agent by default.

## What makes the free deploy work

Streamlit Community Cloud installs `requirements.txt` on a fresh container and
runs `app/streamlit_app.py` from the repo root. Two things are handled in the
app entrypoint so no extra infra is needed (see the "deploy shim" and
`_bootstrap_demo_data` in `app/streamlit_app.py`):

1. **Import path** — `src/` is added to `sys.path` so `import hwval` resolves
   even though the package is not `pip install -e .`'d.
2. **Zero-infra database** — when the host sets no `DATABASE_URL`, the app
   defaults to `sqlite:///artifacts/hwval.db`.
3. **First-run data** — on a fresh database the app seeds a 60-DUT campaign,
   trains the scikit-learn models, and scores runs once (~30 s, shown with a
   spinner). Redeploys with an existing DB skip this.

TensorFlow is intentionally **not** a deploy dependency (its CPU wheel blows
past the free-tier build budget); the LSTM autoencoder degrades to a PCA
fallback, which is announced in the UI.

## Steps

1. Push this repo to GitHub (public):

   ```bash
   gh auth login                      # or set up an SSH/HTTPS remote manually
   gh repo create nxp-hw-validation-agent --public --source=. --remote=origin --push
   # (or) git remote add origin https://github.com/<you>/nxp-hw-validation-agent.git
   #      git push -u origin main
   ```

2. Go to <https://share.streamlit.io> → **Create app** → **Deploy a public app
   from GitHub**.

3. Fill in:
   - **Repository:** `<you>/nxp-hw-validation-agent`
   - **Branch:** `main`
   - **Main file path:** `app/streamlit_app.py`
   - **Advanced settings → Python version:** `3.11`

4. Click **Deploy**. First boot installs deps (~2–3 min) then runs the one-time
   seed/train (~30 s). After that the six tabs (Overview, Ask the agent,
   Anomalies, Model performance, Maintenance, Reports) are live.

## Optional: enable a real LLM

The agent works fully offline. To have it reason with a real model instead,
add a key under **App → Settings → Secrets** and set the provider, e.g.:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
LLM_PROVIDER = "anthropic"
```

Note: real-LLM mode depends on the `.env`/secrets values reaching the process
environment; verify the agent's reported `provider` in the "Ask the agent" tab
after setting secrets.
