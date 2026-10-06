from __future__ import annotations

import argparse
import json

from app.replay.fixtures import synthetic_fills
from app.replay.runner import ReplayRunner, ValidationGate


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a paper validation smoke report")
    parser.add_argument("--chains", default="bnb,robinhood")
    parser.add_argument("--trades", type=int, default=100)
    args = parser.parse_args()

    chains = [chain.strip() for chain in args.chains.split(",") if chain.strip()]
    result = ReplayRunner().run(synthetic_fills(args.trades, chains))
    gate = ValidationGate().evaluate(result.metrics)
    report = {
        "synthetic": True,
        "trade_count": result.metrics.trade_count,
        "net_pnl": result.metrics.net_pnl,
        "expectancy": result.metrics.expectancy,
        "max_drawdown": result.metrics.max_drawdown,
        "approved_for_live": gate.approved_for_live,
        "reasons": gate.reasons,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
