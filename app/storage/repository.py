from __future__ import annotations

from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.events import (
    DevTransfer,
    HolderSnapshot,
    LiquidityChange,
    MarketEvent,
    PriceTick,
    SocialActivity,
    Swap,
    TokenSecurityUpdate,
    WalletBuy,
    WalletSell,
)
from app.storage.models import MarketEventRow, create_engine_for_url

EVENT_TYPES = {
    cls.__name__: cls
    for cls in (
        PriceTick,
        Swap,
        LiquidityChange,
        HolderSnapshot,
        WalletBuy,
        WalletSell,
        DevTransfer,
        TokenSecurityUpdate,
        SocialActivity,
    )
}


class EventRepository:
    def __init__(self, database_url: str = "sqlite:///meme_agent.sqlite3") -> None:
        self.engine = create_engine_for_url(database_url)

    def save_event(self, event: MarketEvent) -> None:
        payload = event.model_dump(mode="json")
        row = MarketEventRow(
            chain=event.chain,
            token=event.token,
            event_type=event.__class__.__name__,
            timestamp=event.timestamp.astimezone(UTC),
            source=event.source,
            payload=payload,
        )
        with Session(self.engine) as session:
            session.add(row)
            session.commit()

    def list_events(self, chain: str, token: str, limit: int) -> list[MarketEvent]:
        if limit < 1:
            return []
        statement = (
            select(MarketEventRow)
            .where(MarketEventRow.chain == chain, MarketEventRow.token == token)
            .order_by(MarketEventRow.timestamp.desc())
            .limit(limit)
        )
        with Session(self.engine) as session:
            rows = session.scalars(statement).all()
        return [self._deserialize(row) for row in rows]

    @staticmethod
    def _deserialize(row: MarketEventRow) -> MarketEvent:
        event_class = EVENT_TYPES.get(row.event_type, MarketEvent)
        payload = dict(row.payload)
        if row.timestamp.tzinfo is None:
            payload["timestamp"] = row.timestamp.replace(tzinfo=UTC)
        return event_class.model_validate(payload)
