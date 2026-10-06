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

Start the paper runtime with no signer loaded:

```bash
.venv/bin/python -m app.main --mode paper
```

For a bounded smoke run, use `--once` or `--duration 60`. The runtime only
trades after authoritative normalized events are available. With no RPC/DEX
event source configured it remains `degraded` and submits no paper orders.

## Safe operation

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m app.main --mode paper --check-connectors
.venv/bin/python scripts/run_paper_validation.py --chains bnb,robinhood --trades 100
```

The validation smoke report is synthetic until both authoritative chain data
sources are configured and verified. It must report `approved_for_live: false`
in that state. The application does not load private keys in paper mode.
