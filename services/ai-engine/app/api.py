"""REST endpoints for the AI engine (Fase 11).

The AI engine detects regimes, ranks strategies, flags anomalies and
recommends disabling underperformers. It NEVER emits trade signals and
NEVER enables/disables anything itself - outputs are advisory data and
events that authorized consumers act on (docs/ARCHITECTURE.md: la IA no
sustituye las reglas de trading).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from . import events
from .anomaly import detect_anomalies
from .db import get_db
from .models import RecommendationRecord
from .providers import get_bar_provider, refresh_symbols
from .regime import RegimeState, default_detector
from .schemas import (
    AnomalyRequest,
    AnomalyResponse,
    RecommendationOut,
    RegimeRefreshRequest,
    RegimeRefreshResponse,
    RegimeRefreshResult,
    RegimeRequest,
    SelectRequest,
    SelectResponse,
    UnderperformanceRequest,
    UnderperformanceResponse,
)
from .selector import rank_strategies, registry_strategies
from .underperformance import Recommendation, RuleConfig, evaluate_strategy

logger = logging.getLogger("ai-engine.api")

router = APIRouter(prefix="/ai", tags=["ai"])


async def _publish(subject: str, payload: dict) -> None:
    try:
        await events.get_publisher().publish(subject, payload)
    except Exception:  # noqa: BLE001 - publishing must never break the API
        logger.exception("failed to publish %s", subject)


@router.post("/regime", response_model=RegimeState)
async def classify_regime(body: RegimeRequest) -> RegimeState:
    """Classify the market regime of a Bar series (oldest first)."""
    try:
        regime = default_detector.detect(body.bars)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await _publish(
        events.REGIME_UPDATED_SUBJECT,
        {
            "symbol": body.bars[-1].symbol,
            "timeframe": body.bars[-1].timeframe,
            "regime": regime.model_dump(),
        },
    )
    return regime


@router.post("/regime/refresh", response_model=RegimeRefreshResponse)
async def refresh_regimes(body: RegimeRefreshRequest) -> RegimeRefreshResponse:
    """Recompute regimes for the configured symbols (scheduler-triggered).

    Bars come from the injectable BarProvider seam; without one the call
    degrades gracefully so the scheduler job never hard-fails.
    """
    provider = get_bar_provider()
    if provider is None:
        return RegimeRefreshResponse(
            refreshed=[], detail="no bar provider configured; nothing refreshed"
        )
    symbols = body.symbols if body.symbols is not None else refresh_symbols()
    if not symbols:
        return RegimeRefreshResponse(
            refreshed=[], detail="no symbols configured (AI_REGIME_SYMBOLS)"
        )
    results: list[RegimeRefreshResult] = []
    for symbol in symbols:
        try:
            bars = await provider.get_bars(symbol, body.timeframe, body.limit)
            regime = default_detector.detect(bars)
        except Exception as exc:  # noqa: BLE001 - isolate per-symbol failures
            results.append(RegimeRefreshResult(symbol=symbol, error=str(exc)))
            continue
        results.append(RegimeRefreshResult(symbol=symbol, regime=regime))
        await _publish(
            events.REGIME_UPDATED_SUBJECT,
            {
                "symbol": symbol,
                "timeframe": body.timeframe,
                "regime": regime.model_dump(),
            },
        )
    return RegimeRefreshResponse(refreshed=results, detail="ok")


@router.post("/select", response_model=SelectResponse)
def select_strategies(body: SelectRequest) -> SelectResponse:
    """Rank strategies for a regime; weights sum to 1 (advisory only)."""
    strategies = (
        body.strategies
        if body.strategies is not None
        else registry_strategies(market=body.market, timeframe=body.timeframe)
    )
    if not strategies:
        raise HTTPException(status_code=422, detail="no candidate strategies")
    ranked = rank_strategies(body.regime, strategies, body.performance, body.top_n)
    return SelectResponse(regime=body.regime, ranked=ranked)


@router.post("/anomalies", response_model=AnomalyResponse)
def find_anomalies(body: AnomalyRequest) -> AnomalyResponse:
    """Scan performance/market series for anomalies (advisory flags)."""
    flags = []
    for series in body.series:
        try:
            flags.extend(
                detect_anomalies(
                    series,
                    zscore_window=body.zscore_window,
                    zscore_threshold=body.zscore_threshold,
                    dd_window=body.drawdown_window,
                    dd_threshold=body.drawdown_threshold,
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"series '{series.strategy_key}': {exc}"
            )
    return AnomalyResponse(flags=flags)


@router.post("/underperformance", response_model=UnderperformanceResponse)
async def evaluate_underperformance(
    body: UnderperformanceRequest, db: Session = Depends(get_db)
) -> UnderperformanceResponse:
    """Apply the disable-recommendation rules to recent trade returns.

    Recommendations are persisted and published; NOTHING is disabled here
    - consumers act on the event/API.
    """
    cfg = RuleConfig.from_env()
    recommendations: list[Recommendation] = []
    for record in body.records:
        recommendations.extend(
            evaluate_strategy(record.strategy_key, record.trade_returns, cfg)
        )
    if body.persist and recommendations:
        for rec in recommendations:
            db.add(
                RecommendationRecord(
                    strategy_key=rec.strategy_key,
                    action=rec.action,
                    rule=rec.rule,
                    reason=rec.reason,
                    severity=rec.severity,
                    metrics=rec.metrics,
                )
            )
        db.commit()
        for rec in recommendations:
            await _publish(events.RECOMMENDATION_CREATED_SUBJECT, rec.model_dump())
    return UnderperformanceResponse(recommendations=recommendations)


@router.get("/recommendations", response_model=list[RecommendationOut])
def list_recommendations(
    strategy_key: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[RecommendationOut]:
    """Recent persisted recommendations, newest first."""
    query = db.query(RecommendationRecord)
    if strategy_key:
        query = query.filter(RecommendationRecord.strategy_key == strategy_key)
    rows = (
        query.order_by(RecommendationRecord.created_at.desc(), RecommendationRecord.id)
        .limit(limit)
        .all()
    )
    return [
        RecommendationOut(
            id=row.id,
            strategy_key=row.strategy_key,
            action=row.action,
            rule=row.rule,
            reason=row.reason,
            severity=row.severity,
            metrics=row.metrics,
            created_at=row.created_at,
        )
        for row in rows
    ]
