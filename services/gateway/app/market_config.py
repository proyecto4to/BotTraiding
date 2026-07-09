"""Fase 4 market configuration API.

Markets and symbols live in DB (ARCHITECTURE.md principle 7: dynamic
configuration, never recompiling). Admins toggle markets/symbols globally;
any authenticated user can additionally opt out of a market for themselves
via /config/me/markets. Reads require authentication (any role); writes
require the `admin` role from the JWT claims.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_token_payload, require_admin
from app.models import Market, Symbol, UserMarketSetting
from app.schemas import (
    MarketOut,
    MarketUpdate,
    SymbolCreate,
    SymbolOut,
    SymbolUpdate,
    UserMarketOut,
    UserMarketSettingIn,
)
from trading_contracts.auth import TokenPayload

router = APIRouter(prefix="/config", tags=["config"])


def _get_market_or_404(db: Session, market_id: str) -> Market:
    market = db.get(Market, market_id)
    if market is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Market not found")
    return market


# -- markets (global, admin-managed) ------------------------------------------


@router.get("/markets", response_model=list[MarketOut])
def list_markets(
    db: Session = Depends(get_db),
    _payload: TokenPayload = Depends(get_token_payload),
) -> list[Market]:
    return list(db.scalars(select(Market).order_by(Market.name)))


@router.patch("/markets/{market_id}", response_model=MarketOut)
def update_market(
    market_id: str,
    body: MarketUpdate,
    db: Session = Depends(get_db),
    _admin: TokenPayload = Depends(require_admin),
) -> Market:
    market = _get_market_or_404(db, market_id)
    if body.enabled is not None:
        market.enabled = body.enabled
    if body.trading_hours is not None:
        market.trading_hours = body.trading_hours
    db.commit()
    db.refresh(market)
    return market


@router.get("/markets/{market_id}/symbols", response_model=list[SymbolOut])
def list_market_symbols(
    market_id: str,
    db: Session = Depends(get_db),
    _payload: TokenPayload = Depends(get_token_payload),
) -> list[Symbol]:
    _get_market_or_404(db, market_id)
    return list(
        db.scalars(
            select(Symbol).where(Symbol.market_id == market_id).order_by(Symbol.ticker)
        )
    )


# -- symbols -------------------------------------------------------------------


@router.get("/symbols", response_model=list[SymbolOut])
def list_symbols(
    market_id: str | None = None,
    db: Session = Depends(get_db),
    _payload: TokenPayload = Depends(get_token_payload),
) -> list[Symbol]:
    query = select(Symbol).order_by(Symbol.ticker)
    if market_id is not None:
        query = query.where(Symbol.market_id == market_id)
    return list(db.scalars(query))


@router.post("/symbols", response_model=SymbolOut, status_code=status.HTTP_201_CREATED)
def create_symbol(
    body: SymbolCreate,
    db: Session = Depends(get_db),
    _admin: TokenPayload = Depends(require_admin),
) -> Symbol:
    _get_market_or_404(db, body.market_id)
    duplicate = db.scalar(
        select(Symbol).where(
            Symbol.market_id == body.market_id, Symbol.ticker == body.ticker
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ticker '{body.ticker}' already exists in this market",
        )
    symbol = Symbol(market_id=body.market_id, ticker=body.ticker, name=body.name)
    db.add(symbol)
    db.commit()
    db.refresh(symbol)
    return symbol


@router.patch("/symbols/{symbol_id}", response_model=SymbolOut)
def update_symbol(
    symbol_id: str,
    body: SymbolUpdate,
    db: Session = Depends(get_db),
    _admin: TokenPayload = Depends(require_admin),
) -> Symbol:
    symbol = db.get(Symbol, symbol_id)
    if symbol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")
    if body.name is not None:
        symbol.name = body.name
    if body.is_active is not None:
        symbol.is_active = body.is_active
    db.commit()
    db.refresh(symbol)
    return symbol


# -- per-user market activation -------------------------------------------------


def _user_market_view(db: Session, user_id: str) -> list[UserMarketOut]:
    markets = list(db.scalars(select(Market).order_by(Market.name)))
    settings = {
        s.market_id: s
        for s in db.scalars(
            select(UserMarketSetting).where(UserMarketSetting.user_id == user_id)
        )
    }
    out: list[UserMarketOut] = []
    for market in markets:
        setting = settings.get(market.id)
        user_enabled = setting.enabled if setting is not None else True
        out.append(
            UserMarketOut(
                market_id=market.id,
                name=market.name,
                code=market.code,
                asset_class=market.asset_class,
                market_enabled=market.enabled,
                user_enabled=user_enabled,
                effective_enabled=market.enabled and user_enabled,
            )
        )
    return out


@router.get("/me/markets", response_model=list[UserMarketOut])
def get_my_markets(
    db: Session = Depends(get_db),
    payload: TokenPayload = Depends(get_token_payload),
) -> list[UserMarketOut]:
    return _user_market_view(db, payload.sub)


@router.put("/me/markets", response_model=list[UserMarketOut])
def put_my_markets(
    body: list[UserMarketSettingIn],
    db: Session = Depends(get_db),
    payload: TokenPayload = Depends(get_token_payload),
) -> list[UserMarketOut]:
    for item in body:
        _get_market_or_404(db, item.market_id)
        setting = db.get(UserMarketSetting, (payload.sub, item.market_id))
        if setting is None:
            db.add(
                UserMarketSetting(
                    user_id=payload.sub, market_id=item.market_id, enabled=item.enabled
                )
            )
        else:
            setting.enabled = item.enabled
    db.commit()
    return _user_market_view(db, payload.sub)
