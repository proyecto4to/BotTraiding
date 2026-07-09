"""REST endpoints for strategy management (Fase 5/6).

Canonical strategy id in this API is the code-registry key
(e.g. "sma_crossover"), stable across environments; DB UUIDs are exposed
as ``db_id`` for auditing only. AuthN/AuthZ live in the gateway; this
internal API receives the acting user's id explicitly.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trading_strategies import (
    ParameterValidationError,
    StrategyCategory,
    UnknownStrategyError,
)
from trading_strategies.plugin import StrategyPlugin

from . import events
from .db import get_db
from .models import StrategyConfigRecord, StrategyRecord
from .registry import registry
from .schemas import (
    ConfigPutRequest,
    ConfigResponse,
    EvaluateRequest,
    EvaluateResponse,
    StrategyDetail,
    StrategySummary,
    StrategyToggleRequest,
)
from .sync import ensure_strategy_rows

logger = logging.getLogger("strategy-engine.api")

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _get_class(strategy_key: str) -> type[StrategyPlugin]:
    try:
        return registry.get(strategy_key)
    except UnknownStrategyError:
        raise HTTPException(status_code=404, detail=f"unknown strategy '{strategy_key}'")


def _enabled_map(db: Session, keys: list[str]) -> dict[str, bool]:
    rows = (
        db.query(StrategyRecord)
        .filter(StrategyRecord.strategy_key.in_(keys))
        .all()
    )
    return {row.strategy_key: row.enabled for row in rows}


def _summary(cls: type[StrategyPlugin], enabled: bool) -> StrategySummary:
    info = cls.describe()
    return StrategySummary(
        key=info["id"],
        name=info["name"],
        version=info["version"],
        category=info["category"],
        markets=info["markets"],
        timeframes=info["timeframes"],
        enabled=enabled,
        description=info["description"],
    )


@router.get("", response_model=list[StrategySummary])
def list_strategies(
    category: Optional[StrategyCategory] = None,
    market: Optional[str] = None,
    timeframe: Optional[str] = None,
    enabled: Optional[bool] = None,
    db: Session = Depends(get_db),
) -> list[StrategySummary]:
    keys = registry.ids(
        category=category.value if category else None,
        market=market,
        timeframe=timeframe,
    )
    enabled_by_key = _enabled_map(db, keys)
    out = []
    for key in keys:
        is_enabled = enabled_by_key.get(key, True)
        if enabled is not None and is_enabled != enabled:
            continue
        out.append(_summary(registry.get(key), is_enabled))
    return out


@router.get("/{strategy_key}", response_model=StrategyDetail)
def get_strategy(strategy_key: str, db: Session = Depends(get_db)) -> StrategyDetail:
    cls = _get_class(strategy_key)
    info = cls.describe()
    row = db.query(StrategyRecord).filter_by(strategy_key=strategy_key).one_or_none()
    return StrategyDetail(
        key=info["id"],
        name=info["name"],
        version=info["version"],
        category=info["category"],
        markets=info["markets"],
        timeframes=info["timeframes"],
        enabled=row.enabled if row is not None else True,
        description=info["description"],
        parameters=info["parameters"],
        recommended_risk_per_trade=info["recommended_risk_per_trade"],
        historical_metrics=info["historical_metrics"],
        db_id=row.id if row is not None else None,
    )


@router.patch("/{strategy_key}", response_model=StrategySummary)
def toggle_strategy(
    strategy_key: str,
    body: StrategyToggleRequest,
    db: Session = Depends(get_db),
) -> StrategySummary:
    cls = _get_class(strategy_key)
    row, _ = ensure_strategy_rows(db, cls)
    row.enabled = body.enabled
    db.commit()
    return _summary(cls, row.enabled)


def _find_config(
    db: Session, version_id: str, user_id: str, account_id: Optional[str]
) -> Optional[StrategyConfigRecord]:
    return (
        db.query(StrategyConfigRecord)
        .filter_by(
            strategy_version_id=version_id,
            user_id=user_id,
            account_id=account_id,
        )
        .one_or_none()
    )


@router.get("/{strategy_key}/config", response_model=ConfigResponse)
def get_config(
    strategy_key: str,
    user_id: str = Query(min_length=1),
    account_id: Optional[str] = None,
    db: Session = Depends(get_db),
) -> ConfigResponse:
    cls = _get_class(strategy_key)
    _, version = ensure_strategy_rows(db, cls)
    config = _find_config(db, version.id, user_id, account_id)
    if config is None:
        raise HTTPException(
            status_code=404,
            detail=f"no config for user '{user_id}' on '{strategy_key}'",
        )
    return ConfigResponse(
        strategy_key=strategy_key,
        version=version.version,
        user_id=config.user_id,
        account_id=config.account_id,
        overrides=config.overrides,
        is_active=config.is_active,
        updated_at=config.updated_at,
    )


@router.put("/{strategy_key}/config", response_model=ConfigResponse)
def put_config(
    strategy_key: str,
    body: ConfigPutRequest,
    db: Session = Depends(get_db),
) -> ConfigResponse:
    cls = _get_class(strategy_key)
    try:  # validate overrides merged over defaults (types, bounds, cross-field)
        merged = cls.validate_params(body.overrides)
    except ParameterValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)
    validated_overrides = {k: merged[k] for k in body.overrides}

    _, version = ensure_strategy_rows(db, cls)
    config = _find_config(db, version.id, body.user_id, body.account_id)
    if config is None:
        config = StrategyConfigRecord(
            strategy_version_id=version.id,
            user_id=body.user_id,
            account_id=body.account_id,
        )
        db.add(config)
    config.overrides = validated_overrides
    config.is_active = body.is_active
    db.commit()
    return ConfigResponse(
        strategy_key=strategy_key,
        version=version.version,
        user_id=config.user_id,
        account_id=config.account_id,
        overrides=config.overrides,
        is_active=config.is_active,
        updated_at=config.updated_at,
    )


@router.post("/{strategy_key}/evaluate", response_model=EvaluateResponse)
async def evaluate_strategy(
    strategy_key: str,
    body: EvaluateRequest,
    force: bool = False,
    db: Session = Depends(get_db),
) -> EvaluateResponse:
    """Evaluate a Bar sequence and PROPOSE a TradeSignal (or null).

    This is the seam the trading-engine and the backtester (Fase 8) call.
    ``force=true`` bypasses the enabled check (backtesting disabled
    strategies). Effective params = defaults < stored user config < body.
    """
    cls = _get_class(strategy_key)
    row = db.query(StrategyRecord).filter_by(strategy_key=strategy_key).one_or_none()
    if row is not None and not row.enabled and not force:
        raise HTTPException(
            status_code=409,
            detail=f"strategy '{strategy_key}' is disabled (use force=true to override)",
        )

    effective: dict[str, Any] = {}
    if body.user_id:
        _, version = ensure_strategy_rows(db, cls)
        config = _find_config(db, version.id, body.user_id, body.account_id)
        if config is not None and config.is_active:
            effective.update(config.overrides)
    effective.update(body.params)

    try:
        plugin = cls(effective)
    except ParameterValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)

    signal = plugin.evaluate(body.bars, market=body.market)
    if signal is not None:
        try:
            await events.get_publisher().publish_signal(signal)
        except Exception:  # noqa: BLE001 - publishing must never break the seam
            logger.exception("failed to publish signal.created")
    return EvaluateResponse(
        strategy_key=strategy_key, signal=signal, params_used=plugin.params
    )
