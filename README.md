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
Market discovery uses the local proxy `MARKET_PROXY_URL` and defaults to
`http://127.0.0.1:7890`. Do not place private keys in this repository.

Run a bounded, read-only market-source smoke check before starting paper mode:

```bash
MARKET_PROXY_URL=http://127.0.0.1:7890 \
.venv/bin/python -m app.data.sources.smoke \
  --chains bnb,robinhood --max-pools 1 --max-log-span 25
```

The smoke check validates configured chain IDs, discovers pools, checks pool
contracts, and reads a bounded log window. `observation_only` is expected when
the source is reachable but no verified event was found in that window; it is
not a permission to trade.

Start the paper runtime with no signer loaded:

```bash
.venv/bin/python -m app.main --mode paper
```

The paper runtime checks the market sources every 5 seconds by default and
reports status with the same cadence. For a bounded run, use `--once` or
`--duration 60`. It only creates paper orders after authoritative normalized
events and the existing security/risk gates are available. A source that is
reachable but has no verified event remains `observation_only` and submits no
entry order.

## Safe operation

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m app.main --mode paper --check-connectors
.venv/bin/python scripts/run_paper_validation.py --chains bnb,robinhood --trades 100
```

The validation smoke report is synthetic until both authoritative chain data
sources are configured and verified. It must report `approved_for_live: false`
in that state. The application does not load private keys in paper mode.
