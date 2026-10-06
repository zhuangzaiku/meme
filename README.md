# Meme Agent

Paper-first realtime Meme strategy agent for BNB Smart Chain and Robinhood Chain.

The default mode is `paper`. Live signing is disabled until the virtual
validation gate and approval-mode checks pass. Network endpoints are supplied
through environment variables and verified before use.

## Local setup

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

Use `BNB_RPC_URL` and `ROBINHOOD_RPC_URL` for read-only connector endpoints.
Do not place private keys in this repository.
