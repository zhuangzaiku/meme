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

## Safe operation

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m app.main --mode paper --check-connectors
.venv/bin/python scripts/run_paper_validation.py --chains bnb,robinhood --trades 100
```

The validation smoke report is synthetic until both authoritative chain data
sources are configured and verified. It must report `approved_for_live: false`
in that state. The application does not load private keys in paper mode.
