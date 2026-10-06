from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, TypeVar
from uuid import uuid4

from app.chains.base import Quote
from app.data.collectors import Collector
from app.data.connector_health import ConnectorHealth
from app.data.events import (
    ExternalSignal,
    HolderSnapshot,
    LiquidityChange,
    MarketEvent,
    PriceTick,
    SocialActivity,
    Swap,
    TokenSecurityUpdate,
)
from app.data.freshness import FreshnessPolicy
from app.execution.orders import Order
from app.execution.paper_broker import OrderResult, PaperBroker
from app.intelligence.scoring import CandidateSnapshot, score_candidate
from app.intelligence.token_risk import RiskDecision as TokenRiskDecision
from app.risk.limits import AccountSnapshot, MarketSnapshot, RiskEngine
from app.storage.repository import EventRepository
from app.strategy.signals import Decision, StrategySnapshot, StrategyState
from app.strategy.state_machine import StrategyEngine

if TYPE_CHECKING:
    from app.config import RiskSettings

EventType = TypeVar("EventType", bound=MarketEvent)


@dataclass(frozen=True)
class RuntimeReport:
    started_at: datetime
    finished_at: datetime
    events_seen: int
    decisions: list[Decision] = field(default_factory=list)
    order_results: list[OrderResult] = field(default_factory=list)
    health: dict[str, ConnectorHealth] = field(default_factory=dict)

    @property
    def orders_submitted(self) -> int:
        return len(self.order_results)

    @property
    def filled_orders(self) -> int:
        return sum(result.status == "filled" for result in self.order_results)


class PaperRuntime:
    """Event-driven paper runner; it never loads a signer or broadcasts a tx."""

    def __init__(
        self,
        collectors: dict[str, Collector],
        broker: PaperBroker,
        *,
        repository: EventRepository,
        initial_cash: float,
        risk_engine: RiskEngine | None = None,
        strategy: StrategyEngine | None = None,
        freshness: FreshnessPolicy | None = None,
    ) -> None:
        self.collectors = collectors
        self.broker = broker
        self.repository = repository
        self.initial_cash = initial_cash
        self.risk_engine = risk_engine or RiskEngine()
        self.strategy = strategy or StrategyEngine()
        self.freshness = freshness or FreshnessPolicy()
        self.events: dict[tuple[str, str], list[MarketEvent]] = {}
        self.states: dict[tuple[str, str], StrategyState] = {}
        self._latest_prices: dict[tuple[str, str], float] = {}
        self._consecutive_losses = 0
        self.broker.quote_provider = self._quote_for_order

    @classmethod
    def from_risk_settings(
        cls,
        collectors: dict[str, Collector],
        broker: PaperBroker,
        *,
        repository: EventRepository,
        initial_cash: float,
        risk: RiskSettings,
    ) -> PaperRuntime:
        return cls(
            collectors,
            broker,
            repository=repository,
            initial_cash=initial_cash,
            risk_engine=RiskEngine(
                risk_per_trade=risk.risk_per_trade,
                max_position_percent=risk.max_position_percent,
                max_concurrent_positions=risk.max_concurrent_positions,
                max_narrative_exposure=risk.max_narrative_exposure,
                max_slippage_percent=risk.max_slippage_percent,
                daily_loss_limit=risk.daily_loss_limit,
                max_consecutive_losses=risk.max_consecutive_losses,
                reserve_balance_percent=risk.reserve_balance_percent,
            ),
        )

    async def run_once(
        self,
        collection_timeout_seconds: float | None = None,
        *,
        collector_names: Iterable[str] | None = None,
        collection_timeouts: Mapping[str, float] | None = None,
    ) -> RuntimeReport:
        if collection_timeout_seconds is not None and collection_timeout_seconds <= 0:
            raise ValueError("collection timeout must be positive")
        selected_names = list(collector_names or self.collectors)
        unknown_names = set(selected_names) - self.collectors.keys()
        if unknown_names:
            raise ValueError(f"unknown collectors: {sorted(unknown_names)}")
        selected_collectors = {name: self.collectors[name] for name in selected_names}
        started_at = datetime.now(UTC)
        collected: list[MarketEvent] = []
        collection_results = await asyncio.gather(
            *(
                self._collect_from_collector(
                    name,
                    collector,
                    self._timeout_for(
                        name,
                        collection_timeout_seconds,
                        collection_timeouts,
                    ),
                )
                for name, collector in selected_collectors.items()
            )
        )
        for events in collection_results:
            collected.extend(events)
        self._record_events(collected)
        return self._make_report(started_at, len(collected))

    def _timeout_for(
        self,
        name: str,
        fallback: float | None,
        overrides: Mapping[str, float] | None,
    ) -> float | None:
        timeout = overrides.get(name) if overrides is not None and name in overrides else fallback
        if timeout is not None and timeout <= 0:
            raise ValueError("collection timeout must be positive")
        return timeout

    async def _collect_from_collector(
        self,
        name: str,
        collector: Collector,
        timeout_seconds: float | None,
    ) -> list[MarketEvent]:
        try:
            if timeout_seconds is None:
                return await collector.run_once()
            return await asyncio.wait_for(collector.run_once(), timeout=timeout_seconds)
        except TimeoutError:
            collector.health = ConnectorHealth(
                name,
                "degraded",
                error=f"collection timed out after {timeout_seconds:.2f}s",
            )
            return []

    async def run_forever(
        self,
        *,
        interval_seconds: float = 5.0,
        collection_timeout_seconds: float | None = None,
        poll_intervals: Mapping[str, float] | None = None,
        collection_timeouts: Mapping[str, float] | None = None,
        stop_event: asyncio.Event | None = None,
        on_report: Callable[[RuntimeReport], Awaitable[None] | None] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        names = list(self.collectors)
        intervals = {
            name: poll_intervals.get(name, interval_seconds)
            if poll_intervals is not None
            else interval_seconds
            for name in names
        }
        for name, interval in intervals.items():
            if interval <= 0:
                raise ValueError(f"poll interval for {name} must be positive")
        loop = asyncio.get_running_loop()
        next_due = {name: loop.time() for name in names}
        next_report_at = loop.time()
        tasks: dict[asyncio.Task[list[MarketEvent]], str] = {}
        try:
            while stop_event is None or not stop_event.is_set():
                now = loop.time()
                for name, collector in self.collectors.items():
                    if now >= next_due[name] and name not in tasks.values():
                        timeout = self._timeout_for(
                            name,
                            collection_timeout_seconds,
                            collection_timeouts,
                        )
                        task = asyncio.create_task(
                            self._collect_from_collector(name, collector, timeout)
                        )
                        tasks[task] = name
                        next_due[name] = now + intervals[name]

                next_wake = min(next_due.values(), default=next_report_at)
                next_wake = min(next_wake, next_report_at)
                delay = max(0.0, next_wake - loop.time())
                if tasks:
                    done, _ = await asyncio.wait(
                        tasks,
                        timeout=delay,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                else:
                    await asyncio.sleep(delay)
                    done = set()

                events_seen = 0
                for task in done:
                    name = tasks.pop(task)
                    events = task.result()
                    events_seen += len(events)
                    self._record_events(events)
                    next_due[name] = loop.time() + intervals[name]

                now = loop.time()
                if now >= next_report_at:
                    report = self._make_report(datetime.now(UTC), events_seen)
                    if on_report is not None:
                        callback_result = on_report(report)
                        if callback_result is not None:
                            await callback_result
                    while next_report_at <= now:
                        next_report_at += interval_seconds
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    def _record_events(self, events: Iterable[MarketEvent]) -> None:
        for event in events:
            key = (event.chain, event.token)
            self.events.setdefault(key, []).append(event)
            if isinstance(event, PriceTick):
                self._latest_prices[key] = event.price

    def _make_report(self, started_at: datetime, events_seen: int) -> RuntimeReport:
        decisions: list[Decision] = []
        results: list[OrderResult] = []
        for key in sorted(self.events):
            snapshot = self._build_snapshot(key)
            if snapshot is None:
                continue
            decision = self.strategy.evaluate(snapshot)
            decisions.append(decision)
            result = self._execute_decision(key, snapshot, decision)
            if result is not None:
                results.append(result)
        return RuntimeReport(
            started_at=started_at,
            finished_at=datetime.now(UTC),
            events_seen=events_seen,
            decisions=decisions,
            order_results=results,
            health={name: collector.health for name, collector in self.collectors.items()},
        )

    def _build_snapshot(self, key: tuple[str, str]) -> StrategySnapshot | None:
        events = self.events[key]
        prices = [event for event in events if isinstance(event, PriceTick)]
        if not prices:
            return None
        now = datetime.now(UTC)
        latest_security = self._latest(events, TokenSecurityUpdate)
        latest_liquidity = self._latest(events, LiquidityChange)
        latest_external = self._latest(events, ExternalSignal)
        latest_quote = prices[-1]
        swaps = [event for event in events if isinstance(event, Swap)]
        buy_swaps = [event for event in swaps if event.side.lower() == "buy"]
        sell_swaps = [event for event in swaps if event.side.lower() == "sell"]
        buy_value = sum(event.amount * (event.price or latest_quote.price) for event in buy_swaps)
        sell_value = sum(event.amount * (event.price or latest_quote.price) for event in sell_swaps)
        independent_wallets = len({event.wallet.lower() for event in buy_swaps})
        social_present = any(isinstance(event, SocialActivity) for event in events)
        holder_growth = any(
            isinstance(event, HolderSnapshot) and event.holder_count > 0 for event in events
        )
        security_fresh = latest_security is not None and self.freshness.is_fresh(
            "security", latest_security.timestamp, now
        )
        quote_fresh = self.freshness.is_fresh("quote", latest_quote.timestamp, now)
        security_ok = latest_security is not None and latest_security.passed
        liquidity_ok = latest_liquidity is not None and latest_liquidity.liquidity > 0
        external_fresh = latest_external is not None and self.freshness.is_fresh(
            "social", latest_external.timestamp, now
        )
        external = latest_external if external_fresh else None
        if latest_security is None:
            risk_decision = TokenRiskDecision.block("missing security data")
        elif not latest_security.passed:
            risk_decision = TokenRiskDecision(
                "BLOCK", latest_security.indicators or ["security check failed"]
            )
        elif not liquidity_ok:
            risk_decision = TokenRiskDecision.block("missing liquidity data")
        else:
            risk_decision = TokenRiskDecision.allow()

        flow_ratio = buy_value / max(sell_value, 1e-12)
        external_wallets = external.unique_callout_wallets if external is not None else 0
        independent_wallets = max(independent_wallets, external_wallets)
        candidate = CandidateSnapshot(
            wallet_quality=max(
                min(25.0, independent_wallets * 25.0 / 3.0),
                external.smart_money_score * 0.25 if external is not None else 0.0,
            ),
            contract_distribution=min(30.0, independent_wallets * 10.0),
            capital_flow=max(
                25.0 if buy_value > sell_value and buy_value > 0 else 0.0,
                external.smart_money_score * 0.25 if external is not None else 0.0,
            ),
            narrative_social=max(
                10.0 if social_present else 0.0,
                (
                    external.narrative_score * 0.06 + external.social_score * 0.04
                    if external is not None
                    else 0.0
                ),
            ),
            market_position=10.0 if len(prices) >= 2 else 0.0,
            independent_wallets=independent_wallets,
            confirmation_signals=sum(
                (
                    independent_wallets >= 3,
                    security_ok,
                    liquidity_ok,
                    social_present,
                    external is not None and external.smart_money_score >= 50,
                )
            ),
            risk_decision=risk_decision,
            trade_shape="early_convergence" if independent_wallets >= 3 else None,
            external_smart_money=external.smart_money_score if external is not None else 0.0,
            external_narrative=external.narrative_score if external is not None else 0.0,
            external_social=external.social_score if external is not None else 0.0,
        )
        score_result = score_candidate(candidate)
        return StrategySnapshot(
            score_result=score_result,
            candidate=candidate,
            trade_shape=candidate.trade_shape,
            quote_fresh=quote_fresh,
            security_fresh=security_fresh,
            structure_valid=security_ok and liquidity_ok,
            capital_flow_positive=flow_ratio > 1.0,
            holder_growth=holder_growth or independent_wallets >= 3,
            smart_money_distributing=sell_value > buy_value,
            now=now,
            current_state=self.states.get(key, "WATCH"),
        )

    def _execute_decision(
        self,
        key: tuple[str, str],
        snapshot: StrategySnapshot,
        decision: Decision,
    ) -> OrderResult | None:
        self.states[key] = decision.state
        chain, token = key
        price = self._latest_prices[key]
        if decision.action not in {"BUY_PROBE", "EXIT"}:
            return None
        if decision.action == "BUY_PROBE":
            amount = self.initial_cash * 0.01 / price
            side: Literal["buy", "sell"] = "buy"
        else:
            positions = [
                position
                for position in self.broker.positions()
                if (position.chain, position.token) == key
            ]
            if not positions:
                return None
            amount = positions[0].amount
            side = "sell"
        order = Order(
            order_id=str(uuid4()),
            chain=chain,
            token=token,
            side=side,
            amount=amount,
            max_slippage_percent=self.risk_engine.max_slippage_percent,
            strategy_state=decision.state,
        )
        account = AccountSnapshot(
            equity=self.broker.equity(),
            cash=self.broker.cash,
            daily_pnl=self.broker.equity() - self.initial_cash,
            consecutive_losses=self._consecutive_losses,
            open_positions=len(self.broker.positions()),
            narrative_exposure=(self.initial_cash - self.broker.cash)
            / max(self.broker.equity(), 1e-12),
        )
        risk = self.risk_engine.check(
            order,
            account,
            MarketSnapshot(price=price, quote_fresh=True, slippage_percent=0.5),
        )
        if not risk.allowed:
            return OrderResult(order.order_id, "rejected", reason=risk.code)
        return self.broker.submit(order)

    def _quote_for_order(self, order: Order) -> Quote:
        price = self._latest_prices.get((order.chain, order.token))
        if price is None:
            raise ValueError(f"no current price for {order.chain}/{order.token}")
        multiplier = 1.005 if order.side == "buy" else 0.995
        return Quote(
            token=order.token,
            side=order.side,
            amount=max(1, int(order.amount)),
            mid_price=price,
            executable_price=price * multiplier,
            timestamp=datetime.now(UTC),
        )

    @staticmethod
    def _latest(
        events: list[MarketEvent], event_type: type[EventType]
    ) -> EventType | None:
        matches = [event for event in events if isinstance(event, event_type)]
        return matches[-1] if matches else None
