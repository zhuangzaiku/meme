from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.chains.base import Quote
from app.data.events import PriceTick
from app.execution.orders import Order
from app.execution.paper_broker import PaperBroker
from app.intelligence.scoring import CandidateSnapshot, ScoreResult
from app.intelligence.token_risk import RiskDecision
from app.main import create_app
from app.storage.repository import EventRepository
from app.strategy.signals import StrategySnapshot
from app.strategy.state_machine import StrategyEngine


def make_snapshot(chain: str, *, quote_fresh: bool = True) -> StrategySnapshot:
    candidate = CandidateSnapshot(
        wallet_quality=25,
        contract_distribution=30,
        capital_flow=25,
        narrative_social=10,
        market_position=10,
        independent_wallets=3,
        confirmation_signals=2,
        risk_decision=RiskDecision.allow(),
    )
    return StrategySnapshot(
        score_result=ScoreResult("ARMED", 100, [chain], []),
        candidate=candidate,
        trade_shape="early_convergence",
        quote_fresh=quote_fresh,
        security_fresh=True,
        structure_valid=True,
        capital_flow_positive=True,
        holder_growth=True,
        smart_money_distributing=False,
        now=datetime.now(UTC),
    )


def test_two_chain_paper_pipeline_isolated_and_persisted(tmp_path) -> None:
    repository = EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}")
    strategy = StrategyEngine()
    for chain in ("bnb", "robinhood"):
        repository.save_event(
            PriceTick(
                chain=chain,
                token="0x1",
                price=1.0,
                timestamp=datetime.now(UTC),
            )
        )
        decision = strategy.evaluate(make_snapshot(chain))
        assert decision.action == "BUY_PROBE"
        broker = PaperBroker(
            lambda _: Quote("0x1", "buy", 100, 1.0, 1.01),
            initial_cash=1_000,
            fee_rate=0.01,
            gas_fee=1,
        )
        result = broker.submit(Order(f"{chain}-1", chain, "0x1", "buy", 100, 1.5))
        assert result.status == "filled"
        assert repository.list_events(chain, "0x1", 1)[0].chain == chain


def test_stale_event_and_hard_veto_block_entry() -> None:
    stale = StrategyEngine().evaluate(make_snapshot("bnb", quote_fresh=False))
    assert stale.action == "BLOCK"

    vetoed = make_snapshot("bnb")
    vetoed.candidate = CandidateSnapshot(
        wallet_quality=25,
        contract_distribution=30,
        capital_flow=25,
        narrative_social=10,
        market_position=10,
        independent_wallets=3,
        confirmation_signals=2,
        risk_decision=RiskDecision.block("honeypot"),
    )
    assert StrategyEngine().evaluate(vetoed).action == "BLOCK"


def test_pause_blocks_orders_but_allows_exit() -> None:
    with TestClient(create_app()) as client:
        assert client.post("/pause").status_code == 200
        assert client.post("/orders", json={"token": "0x1", "side": "buy"}).status_code == 423
        assert client.post("/positions/p1/exit").status_code == 200
