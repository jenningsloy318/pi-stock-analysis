#!/usr/bin/env python3
"""7-layer signal aggregation engine — combines signals from technical, factor,
event-driven, institutional flow, options, alt data, and cross-asset layers
into a unified directional verdict with confluence detection.

Usage:
    compute_signal_aggregator.py TICKER [--output PATH] \
        [--trade-signals-json PATH] [--factors-json PATH] \
        [--sentiment-json PATH] [--earnings-edge-json PATH] \
        [--options-json PATH] [--alternatives-json PATH] \
        [--news-nlp-json PATH] [--breadth-json PATH] \
        [--credit-json PATH] [--short-interest-json PATH] \
        [--activist-json PATH] [--capital-structure-json PATH] \
        [--tech-json PATH] [--money-flow-json PATH] \
        [--scores-json PATH]

All input paths are optional. When missing, the corresponding layer is
skipped and its weight is redistributed proportionally to remaining layers.

Layers:
    L1 Technical        (from trade-signals-json)       weight=0.25
    L2 Factor           (from factors-json + scores-json + tech-json)  weight=0.15
    L3 Event-Driven     (from sentiment + earnings-edge + activist + capital-structure) weight=0.20
    L4 Institutional    (from short-interest + money-flow)  weight=0.15
    L5 Options-Derived  (from options-json)             weight=0.10
    L6 Alt Data         (from alternatives + news-nlp)  weight=0.05
    L7 Cross-Asset      (from breadth + credit)         weight=0.10

Output: JSON to stdout or --output file.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"

LAYER_WEIGHTS: dict[str, float] = {
    "L1_technical": 0.25,
    "L2_factor": 0.15,
    "L3_event": 0.20,
    "L4_institutional": 0.15,
    "L5_options": 0.10,
    "L6_alt_data": 0.05,
    "L7_cross_asset": 0.10,
}

# Direction encoding
DIR_BUY = +1
DIR_SELL = -1
DIR_NEUTRAL = 0


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _load_json(path: str | None) -> dict | None:
    """Safely load a JSON file. Returns None if path is None or file missing."""
    if not path:
        return None
    if not os.path.isfile(path):
        sys.stderr.write(f"[WARN] File not found: {path}\n")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        sys.stderr.write(f"[WARN] Failed to load {path}: {e}\n")
        return None


def _safe_get(data: dict | None, *keys, default=None):
    """Safely traverse nested dict keys."""
    if data is None:
        return default
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def _direction_label(d: int) -> str:
    """Convert numeric direction to label."""
    if d > 0:
        return "BUY"
    elif d < 0:
        return "SELL"
    return "NEUTRAL"


def _make_signal(
    signal_id: str,
    name_cn: str,
    direction: int,
    confidence: float,
    rationale: str,
    data_points: dict | None = None,
) -> dict:
    """Construct a standardized signal dict."""
    return {
        "signal_id": signal_id,
        "name_cn": name_cn,
        "direction": direction,
        "direction_label": _direction_label(direction),
        "confidence": round(min(max(confidence, 0.0), 1.0), 3),
        "rationale": rationale,
        "data_points": data_points or {},
    }


# ---------------------------------------------------------------------------
# L1: Technical Layer (技术面信号)
# ---------------------------------------------------------------------------


def compute_l1_technical(trade_signals_data: dict | None) -> dict:
    """Pass through B1-B6, S1-S6 signals from compute_trade_signals.py output.

    Signal IDs: B1-B6 (买入信号), S1-S6 (卖出信号)
    """
    layer_id = "L1_technical"
    layer_name = "技术面信号"
    signals: list[dict] = []

    if not trade_signals_data:
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": "无技术信号数据",
        }

    try:
        # Extract buy signals (B1-B6)
        buy_signals = trade_signals_data.get("buy_signals", [])
        for sig in buy_signals:
            sid = sig.get("signal_id", sig.get("id", "B?"))
            name = sig.get("name", sig.get("name_cn", f"买入信号{sid}"))
            conf = sig.get("confidence") or 0.7
            reason = sig.get("rationale", sig.get("description", ""))
            signals.append(_make_signal(sid, name, DIR_BUY, conf, reason))

        # Extract sell signals (S1-S6)
        sell_signals = trade_signals_data.get("sell_signals", [])
        for sig in sell_signals:
            sid = sig.get("signal_id", sig.get("id", "S?"))
            name = sig.get("name", sig.get("name_cn", f"卖出信号{sid}"))
            conf = sig.get("confidence") or 0.7
            reason = sig.get("rationale", sig.get("description", ""))
            signals.append(_make_signal(sid, name, DIR_SELL, conf, reason))

        # Compute net direction
        buy_weight = sum(s["confidence"] for s in signals if s["direction"] > 0)
        sell_weight = sum(s["confidence"] for s in signals if s["direction"] < 0)
        total_weight = buy_weight + sell_weight

        if total_weight == 0:
            net_dir = DIR_NEUTRAL
            layer_conf = 0.0
        else:
            net_score = (buy_weight - sell_weight) / total_weight
            net_dir = (
                DIR_BUY
                if net_score > 0.1
                else (DIR_SELL if net_score < -0.1 else DIR_NEUTRAL)
            )
            layer_conf = abs(net_score)

        # Also pick up overall verdict if available
        verdict = trade_signals_data.get("verdict", {})
        if verdict and isinstance(verdict, dict):
            v_dir = verdict.get("direction", "")
            if v_dir == "BUY" and net_dir == DIR_NEUTRAL:
                net_dir = DIR_BUY
                layer_conf = max(layer_conf, 0.4)
            elif v_dir == "SELL" and net_dir == DIR_NEUTRAL:
                net_dir = DIR_SELL
                layer_conf = max(layer_conf, 0.4)

        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": True,
            "signals": signals,
            "net_direction": net_dir,
            "layer_confidence": round(layer_conf, 3),
            "summary": f"买入信号{len(buy_signals)}个, 卖出信号{len(sell_signals)}个",
        }

    except Exception as e:
        sys.stderr.write(f"[ERROR] L1 Technical: {e}\n")
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": f"技术面信号处理异常: {e}",
        }


# ---------------------------------------------------------------------------
# L2: Factor Layer (因子信号)
# ---------------------------------------------------------------------------


def compute_l2_factor(
    factors_data: dict | None,
    scores_data: dict | None,
    tech_data: dict | None,
) -> dict:
    """Factor-based signals: momentum, value, quality, earnings revision, low-vol, size+momentum.

    Signal IDs: F1-F6
    """
    layer_id = "L2_factor"
    layer_name = "因子信号"
    signals: list[dict] = []

    if not factors_data and not scores_data and not tech_data:
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": "无因子数据",
        }

    try:
        # --- F1: Momentum (动量因子) ---
        # 12-1M return > +20% AND RSI < 75 → BUY
        mom_12m = _safe_get(factors_data, "factor_exposures", "momentum", default=None)
        if mom_12m is None:
            mom_12m = _safe_get(tech_data, "momentum", "return_12m", default=None)
        rsi = _safe_get(tech_data, "rsi", "rsi_14", default=None)
        if rsi is None:
            rsi = _safe_get(tech_data, "indicators", "rsi_14", default=None)

        if mom_12m is not None:
            rsi_ok = rsi is None or rsi < 75
            if mom_12m > 0.20 and rsi_ok:
                signals.append(
                    _make_signal(
                        "F1",
                        "动量因子",
                        DIR_BUY,
                        0.75,
                        f"12个月回报{mom_12m:.1%}, RSI={rsi or 'N/A'}, 动量强劲且未超买",
                        {"return_12m": mom_12m, "rsi_14": rsi},
                    )
                )
            elif mom_12m < -0.15:
                signals.append(
                    _make_signal(
                        "F1",
                        "动量因子",
                        DIR_SELL,
                        0.65,
                        f"12个月回报{mom_12m:.1%}, 动量显著为负",
                        {"return_12m": mom_12m, "rsi_14": rsi},
                    )
                )

        # --- F2: Value (价值因子) ---
        # valuation_attractiveness >= 7 → BUY, <= 3 → SELL
        val_score = _safe_get(
            scores_data, "components", "valuation_attractiveness", "score", default=None
        )
        if val_score is None:
            val_score = _safe_get(scores_data, "valuation_attractiveness", default=None)

        if val_score is not None:
            if val_score >= 7:
                signals.append(
                    _make_signal(
                        "F2",
                        "价值因子",
                        DIR_BUY,
                        0.70 + (val_score - 7) * 0.05,
                        f"估值吸引力评分{val_score:.1f}/10, 显著低估",
                        {"valuation_score": val_score},
                    )
                )
            elif val_score <= 3:
                signals.append(
                    _make_signal(
                        "F2",
                        "价值因子",
                        DIR_SELL,
                        0.65,
                        f"估值吸引力评分{val_score:.1f}/10, 显著高估",
                        {"valuation_score": val_score},
                    )
                )

        # --- F3: Quality (质量因子) ---
        # financial_health >= 8 → BUY, <= 3 → SELL
        fh_score = _safe_get(
            scores_data, "components", "financial_health", "score", default=None
        )
        if fh_score is None:
            fh_score = _safe_get(scores_data, "financial_health", default=None)

        if fh_score is not None:
            if fh_score >= 8:
                signals.append(
                    _make_signal(
                        "F3",
                        "质量因子",
                        DIR_BUY,
                        0.70,
                        f"财务健康评分{fh_score:.1f}/10, 基本面优秀",
                        {"financial_health": fh_score},
                    )
                )
            elif fh_score <= 3:
                signals.append(
                    _make_signal(
                        "F3",
                        "质量因子",
                        DIR_SELL,
                        0.60,
                        f"财务健康评分{fh_score:.1f}/10, 基本面堪忧",
                        {"financial_health": fh_score},
                    )
                )

        # --- F4: Earnings Revision (盈利修正因子) ---
        # strong_upgrade_trend + score >= 7 → BUY
        revision_trend = _safe_get(
            factors_data, "earnings_revision", "trend", default=None
        )
        revision_score = _safe_get(
            factors_data, "earnings_revision", "score", default=None
        )
        if revision_score is None:
            revision_score = _safe_get(
                scores_data, "components", "earnings_revision", "score", default=None
            )

        if revision_score is not None and revision_score >= 7:
            is_upgrade = revision_trend in ("strong_upgrade", "upgrade", "positive")
            if is_upgrade:
                signals.append(
                    _make_signal(
                        "F4",
                        "盈利修正因子",
                        DIR_BUY,
                        0.75,
                        f"盈利预期上调趋势, 修正评分{revision_score:.1f}",
                        {
                            "revision_trend": revision_trend,
                            "revision_score": revision_score,
                        },
                    )
                )
        elif revision_score is not None and revision_score <= 3:
            signals.append(
                _make_signal(
                    "F4",
                    "盈利修正因子",
                    DIR_SELL,
                    0.60,
                    f"盈利预期下调趋势, 修正评分{revision_score:.1f}",
                    {
                        "revision_trend": revision_trend,
                        "revision_score": revision_score,
                    },
                )
            )

        # --- F5: Low Volatility (低波动因子) ---
        # NOTE: F5 is BUY-only — creates structural bullish asymmetry
        # beta < 0.8 + financial_health >= 6 → BUY (defensive quality)
        beta = _safe_get(factors_data, "factor_exposures", "market", default=None)
        if beta is None:
            beta = _safe_get(tech_data, "beta", default=None)

        if beta is not None and beta < 0.8:
            fh_ok = fh_score is not None and fh_score >= 6
            if fh_ok:
                signals.append(
                    _make_signal(
                        "F5",
                        "低波动因子",
                        DIR_BUY,
                        0.55,
                        f"Beta={beta:.2f} < 0.8, 财务健康{fh_score:.1f}>=6, 防御性优质标的",
                        {"beta": beta, "financial_health": fh_score},
                    )
                )

        # --- F6: Size + Momentum Combo (小盘+动量组合) ---
        # NOTE: F6 is BUY-only — creates structural bullish asymmetry
        # market_cap < $10B + momentum positive → BUY
        mkt_cap = _safe_get(factors_data, "market_cap", default=None)
        if mkt_cap is None:
            mkt_cap = _safe_get(scores_data, "metadata", "market_cap", default=None)

        if mkt_cap is not None and mkt_cap < 10e9:
            mom_positive = mom_12m is not None and mom_12m > 0.05
            if mom_positive:
                signals.append(
                    _make_signal(
                        "F6",
                        "小盘动量组合",
                        DIR_BUY,
                        0.60,
                        f"市值${mkt_cap/1e9:.1f}B < $10B + 正动量{mom_12m:.1%}",
                        {"market_cap_b": mkt_cap / 1e9, "momentum": mom_12m},
                    )
                )

        # Net direction
        buy_conf = sum(s["confidence"] for s in signals if s["direction"] > 0)
        sell_conf = sum(s["confidence"] for s in signals if s["direction"] < 0)
        total = buy_conf + sell_conf
        if total == 0:
            net_dir = DIR_NEUTRAL
            layer_conf = 0.0
        else:
            net_score = (buy_conf - sell_conf) / total
            net_dir = (
                DIR_BUY
                if net_score > 0.15
                else (DIR_SELL if net_score < -0.15 else DIR_NEUTRAL)
            )
            layer_conf = abs(net_score)

        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": True,
            "signals": signals,
            "net_direction": net_dir,
            "layer_confidence": round(layer_conf, 3),
            "summary": f"因子信号{len(signals)}个 (买:{sum(1 for s in signals if s['direction']>0)}, 卖:{sum(1 for s in signals if s['direction']<0)})",
        }

    except Exception as e:
        sys.stderr.write(f"[ERROR] L2 Factor: {e}\n")
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": f"因子信号处理异常: {e}",
        }


# ---------------------------------------------------------------------------
# L3: Event-Driven Layer (事件驱动信号)
# ---------------------------------------------------------------------------


def compute_l3_event(
    sentiment_data: dict | None,
    earnings_edge_data: dict | None,
    activist_data: dict | None,
    capital_structure_data: dict | None,
) -> dict:
    """Event-driven signals: earnings surprise, insider buying, buyback, activist entry.

    Signal IDs: E1-E4
    """
    layer_id = "L3_event"
    layer_name = "事件驱动信号"
    signals: list[dict] = []

    if (
        not sentiment_data
        and not earnings_edge_data
        and not activist_data
        and not capital_structure_data
    ):
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": "无事件驱动数据",
        }

    try:
        # --- E1: Earnings Surprise (盈利惊喜) ---
        # beat > 10% + PEAD positive → BUY
        beat_pct = _safe_get(
            earnings_edge_data, "latest_surprise", "beat_pct", default=None
        )
        if beat_pct is None:
            beat_pct = _safe_get(
                sentiment_data, "earnings", "surprise_pct", default=None
            )
        pead = _safe_get(earnings_edge_data, "pead", "direction", default=None)
        pead_positive = pead in ("positive", "up", True)

        if beat_pct is not None:
            if beat_pct > 0.10 and pead_positive:
                signals.append(
                    _make_signal(
                        "E1",
                        "盈利惊喜",
                        DIR_BUY,
                        0.80,
                        f"盈利超预期{beat_pct:.1%} + PEAD正向漂移, 强买入信号",
                        {"beat_pct": beat_pct, "pead_direction": pead},
                    )
                )
            elif beat_pct > 0.10:
                signals.append(
                    _make_signal(
                        "E1",
                        "盈利惊喜",
                        DIR_BUY,
                        0.60,
                        f"盈利超预期{beat_pct:.1%}, 但PEAD未确认",
                        {"beat_pct": beat_pct, "pead_direction": pead},
                    )
                )
            elif beat_pct < -0.10:
                signals.append(
                    _make_signal(
                        "E1",
                        "盈利惊喜",
                        DIR_SELL,
                        0.70,
                        f"盈利不及预期{beat_pct:.1%}, 下行风险",
                        {"beat_pct": beat_pct, "pead_direction": pead},
                    )
                )

        # --- E2: Insider Buying (内部人买入) ---
        # net open-market buys > $500K in 90d → BUY
        insider_net = _safe_get(
            sentiment_data, "insider", "net_buy_value_90d", default=None
        )
        if insider_net is None:
            insider_net = _safe_get(
                sentiment_data, "insider_trading", "net_purchase_value", default=None
            )

        if insider_net is not None:
            if insider_net > 500_000:
                signals.append(
                    _make_signal(
                        "E2",
                        "内部人买入",
                        DIR_BUY,
                        0.75,
                        f"90天内部人净买入${insider_net/1e6:.2f}M > $500K, 管理层信心强",
                        {"net_insider_buy_90d": insider_net},
                    )
                )
            elif insider_net < -1_000_000:
                signals.append(
                    _make_signal(
                        "E2",
                        "内部人买入",
                        DIR_SELL,
                        0.55,
                        f"90天内部人净卖出${abs(insider_net)/1e6:.2f}M, 管理层减持",
                        {"net_insider_buy_90d": insider_net},
                    )
                )

        # --- E3: Buyback (回购信号) ---
        # NOTE: E3 is BUY-only — creates structural bullish asymmetry
        # active buyback > 5% float → BUY
        buyback_pct = _safe_get(
            capital_structure_data, "buyback", "pct_of_float", default=None
        )
        if buyback_pct is None:
            buyback_pct = _safe_get(
                capital_structure_data, "buyback_roi", "buyback_yield", default=None
            )
        buyback_active = _safe_get(
            capital_structure_data, "buyback", "active", default=False
        )

        if buyback_pct is not None and buyback_pct > 0.05:
            signals.append(
                _make_signal(
                    "E3",
                    "回购信号",
                    DIR_BUY,
                    0.65,
                    f"活跃回购占流通股{buyback_pct:.1%} > 5%, 股价下限支撑",
                    {
                        "buyback_pct_float": buyback_pct,
                        "buyback_active": buyback_active,
                    },
                )
            )
        elif buyback_pct is not None and buyback_pct > 0.03 and buyback_active:
            signals.append(
                _make_signal(
                    "E3",
                    "回购信号",
                    DIR_BUY,
                    0.45,
                    f"活跃回购占流通股{buyback_pct:.1%}, 温和支撑",
                    {
                        "buyback_pct_float": buyback_pct,
                        "buyback_active": buyback_active,
                    },
                )
            )

        # --- E4: Activist Entry (激进投资者进入) ---
        # NOTE: E4 is BUY-only — creates structural bullish asymmetry
        # 13D filing by known activist → BUY
        has_13d = _safe_get(activist_data, "has_recent_13d", default=False)
        activist_name = _safe_get(activist_data, "activist_name", default=None)
        activist_stake = _safe_get(activist_data, "stake_pct", default=None)

        if has_13d:
            # Safe numeric coercion — activist_stake may be string from JSON
            _stake_num = (
                float(activist_stake)
                if isinstance(activist_stake, (int, float, str))
                and str(activist_stake).replace(".", "", 1).isdigit()
                else 0
            )
            conf = 0.70 if _stake_num > 0.05 else 0.55
            try:
                stake_str = f"持股{float(activist_stake):.1%}"
            except (ValueError, TypeError):
                stake_str = f"持股{activist_stake}"
            signals.append(
                _make_signal(
                    "E4",
                    "激进投资者进入",
                    DIR_BUY,
                    conf,
                    f"13D备案: {activist_name or '未知'} {stake_str}"
                    if activist_stake
                    else f"13D备案: {activist_name or '未知激进投资者'}",
                    {
                        "has_13d": True,
                        "activist_name": activist_name,
                        "stake_pct": activist_stake,
                    },
                )
            )

        # Net direction
        buy_conf = sum(s["confidence"] for s in signals if s["direction"] > 0)
        sell_conf = sum(s["confidence"] for s in signals if s["direction"] < 0)
        total = buy_conf + sell_conf
        if total == 0:
            net_dir = DIR_NEUTRAL
            layer_conf = 0.0
        else:
            net_score = (buy_conf - sell_conf) / total
            net_dir = (
                DIR_BUY
                if net_score > 0.1
                else (DIR_SELL if net_score < -0.1 else DIR_NEUTRAL)
            )
            layer_conf = abs(net_score)

        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": True,
            "signals": signals,
            "net_direction": net_dir,
            "layer_confidence": round(layer_conf, 3),
            "summary": f"事件信号{len(signals)}个 (买:{sum(1 for s in signals if s['direction']>0)}, 卖:{sum(1 for s in signals if s['direction']<0)})",
        }

    except Exception as e:
        sys.stderr.write(f"[ERROR] L3 Event: {e}\n")
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": f"事件驱动信号处理异常: {e}",
        }


# ---------------------------------------------------------------------------
# L4: Institutional Flow Layer (机构资金流信号)
# ---------------------------------------------------------------------------


def compute_l4_institutional(
    short_interest_data: dict | None,
    money_flow_data: dict | None,
    tech_data: dict | None = None,
) -> dict:
    """Institutional flow signals: short squeeze, dark pool, accumulation, ETF flow.

    Signal IDs: M1-M4
    """
    layer_id = "L4_institutional"
    layer_name = "机构资金流信号"
    signals: list[dict] = []

    if not short_interest_data and not money_flow_data:
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": "无机构资金流数据",
        }

    try:
        # --- M1: Short Interest (做空挤压设置) ---
        # NOTE: M1 creates structural bullish asymmetry (BUY-only signal type).
        # Counterpart SELL added below when momentum is breaking down.
        # SI > 20% + DTC > 5 + CTB rising → BUY squeeze setup
        si_pct = _safe_get(short_interest_data, "short_interest_pct", default=None)
        if si_pct is None:
            si_pct = _safe_get(short_interest_data, "si_pct_float", default=None)
        dtc = _safe_get(short_interest_data, "days_to_cover", default=None)
        ctb_rising = _safe_get(short_interest_data, "ctb_trend", default=None) in (
            "rising",
            "up",
        )
        squeeze_score = _safe_get(short_interest_data, "squeeze_score", default=None)

        if si_pct is not None and si_pct > 0.20 and dtc is not None and dtc > 5:
            conf = 0.70 if ctb_rising else 0.55
            signals.append(
                _make_signal(
                    "M1",
                    "做空挤压设置",
                    DIR_BUY,
                    conf,
                    f"空头比例{si_pct:.1%} > 20%, 覆盖天数{dtc:.1f} > 5, CTB{'上升' if ctb_rising else '稳定'}, 逼空风险",
                    {"si_pct": si_pct, "days_to_cover": dtc, "ctb_rising": ctb_rising},
                )
            )
        elif (
            si_pct is not None
            and si_pct > 0.15
            and squeeze_score is not None
            and squeeze_score > 7
        ):
            signals.append(
                _make_signal(
                    "M1",
                    "做空挤压设置",
                    DIR_BUY,
                    0.55,
                    f"空头比例{si_pct:.1%}, 逼空评分{squeeze_score}/10",
                    {"si_pct": si_pct, "squeeze_score": squeeze_score},
                )
            )

        # M1 counterpart SELL: momentum breakdown (RSI < 30 from oversold collapse)
        m1_rsi = _safe_get(tech_data, "rsi", "rsi_14", default=None)
        if m1_rsi is None:
            m1_rsi = _safe_get(tech_data, "indicators", "rsi_14", default=None)
        if m1_rsi is not None and m1_rsi < 30:
            signals.append(
                _make_signal(
                    "M1",
                    "动量崩溃",
                    DIR_SELL,
                    0.60,
                    f"RSI={m1_rsi:.1f} < 30, 动量崩溃/持续下行",
                    {"rsi_14": m1_rsi},
                )
            )

        # --- M2: Dark Pool Proxy (隐性吸筹) ---
        # price flat + OBV rising → BUY stealth accumulation
        obv_trend = _safe_get(money_flow_data, "obv", "trend", default=None)
        price_trend = _safe_get(money_flow_data, "price_trend", default=None)
        obv_divergence = _safe_get(
            money_flow_data, "obv", "price_divergence", default=None
        )

        if obv_trend in ("rising", "up", "strongly_rising"):
            price_flat = price_trend in ("flat", "sideways", "consolidating", None)
            if price_flat or obv_divergence in ("positive", "bullish"):
                signals.append(
                    _make_signal(
                        "M2",
                        "隐性吸筹",
                        DIR_BUY,
                        0.65,
                        f"OBV趋势{obv_trend}, 价格{price_trend or '横盘'}, 隐性资金流入",
                        {
                            "obv_trend": obv_trend,
                            "price_trend": price_trend,
                            "divergence": obv_divergence,
                        },
                    )
                )
        elif obv_trend in ("falling", "down", "strongly_falling") and price_trend in (
            "rising",
            "up",
        ):
            signals.append(
                _make_signal(
                    "M2",
                    "隐性吸筹",
                    DIR_SELL,
                    0.60,
                    "OBV下降但价格上涨, 量价背离, 注意派发风险",
                    {"obv_trend": obv_trend, "price_trend": price_trend},
                )
            )

        # --- M3: Institutional Accumulation (机构持续流入) ---
        # inflow >= 5 days + vol-price symmetry → BUY
        inflow_days = _safe_get(
            money_flow_data, "consecutive_inflow_days", default=None
        )
        if inflow_days is None:
            inflow_days = _safe_get(
                money_flow_data, "net_flow", "consecutive_inflow", default=None
            )
        vol_price_sym = _safe_get(
            money_flow_data, "volume_price_symmetry", default=None
        )

        if inflow_days is not None and inflow_days >= 5:
            conf = (
                0.70
                if vol_price_sym in ("symmetric", "positive", "confirming")
                else 0.55
            )
            signals.append(
                _make_signal(
                    "M3",
                    "机构持续流入",
                    DIR_BUY,
                    conf,
                    f"连续{inflow_days}天净流入, 量价{'对称' if vol_price_sym in ('symmetric', 'positive', 'confirming') else '待确认'}",
                    {
                        "consecutive_inflow_days": inflow_days,
                        "vol_price_symmetry": vol_price_sym,
                    },
                )
            )
        elif inflow_days is not None and inflow_days <= -5:
            signals.append(
                _make_signal(
                    "M3",
                    "机构持续流入",
                    DIR_SELL,
                    0.60,
                    f"连续{abs(inflow_days)}天净流出, 资金撤离",
                    {"consecutive_outflow_days": abs(inflow_days)},
                )
            )

        # --- M4: ETF Flow Proxy (ETF资金流向) ---
        # sector strong_inflow → BUY tailwind
        sector_flow = _safe_get(
            money_flow_data, "sector_etf_flow", "trend", default=None
        )
        if sector_flow is None:
            sector_flow = _safe_get(money_flow_data, "etf_flow", default=None)

        if sector_flow in ("strong_inflow", "significant_inflow"):
            signals.append(
                _make_signal(
                    "M4",
                    "ETF资金流向",
                    DIR_BUY,
                    0.50,
                    f"行业ETF资金{sector_flow}, 板块顺风",
                    {"sector_etf_flow": sector_flow},
                )
            )
        elif sector_flow in ("strong_outflow", "significant_outflow"):
            signals.append(
                _make_signal(
                    "M4",
                    "ETF资金流向",
                    DIR_SELL,
                    0.50,
                    f"行业ETF资金{sector_flow}, 板块逆风",
                    {"sector_etf_flow": sector_flow},
                )
            )

        # Net direction
        buy_conf = sum(s["confidence"] for s in signals if s["direction"] > 0)
        sell_conf = sum(s["confidence"] for s in signals if s["direction"] < 0)
        total = buy_conf + sell_conf
        if total == 0:
            net_dir = DIR_NEUTRAL
            layer_conf = 0.0
        else:
            net_score = (buy_conf - sell_conf) / total
            net_dir = (
                DIR_BUY
                if net_score > 0.1
                else (DIR_SELL if net_score < -0.1 else DIR_NEUTRAL)
            )
            layer_conf = abs(net_score)

        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": True,
            "signals": signals,
            "net_direction": net_dir,
            "layer_confidence": round(layer_conf, 3),
            "summary": f"资金流信号{len(signals)}个 (买:{sum(1 for s in signals if s['direction']>0)}, 卖:{sum(1 for s in signals if s['direction']<0)})",
        }

    except Exception as e:
        sys.stderr.write(f"[ERROR] L4 Institutional: {e}\n")
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": f"机构资金流信号处理异常: {e}",
        }


# ---------------------------------------------------------------------------
# L5: Options-Derived Layer (期权衍生信号)
# ---------------------------------------------------------------------------


def compute_l5_options(options_data: dict | None) -> dict:
    """Options-derived signals: unusual activity, PCR extreme, IV signals, max pain.

    Signal IDs: O1-O4
    """
    layer_id = "L5_options"
    layer_name = "期权衍生信号"
    signals: list[dict] = []

    if not options_data:
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": "无期权数据",
        }

    try:
        # --- O1: Unusual Options Activity (异常期权活动) ---
        # call_vol > 3x avg → BUY
        call_vol_ratio = _safe_get(
            options_data, "unusual_activity", "call_volume_ratio", default=None
        )
        if call_vol_ratio is None:
            call_vol_ratio = _safe_get(options_data, "call_vol_vs_avg", default=None)
        put_vol_ratio = _safe_get(
            options_data, "unusual_activity", "put_volume_ratio", default=None
        )

        if call_vol_ratio is not None and call_vol_ratio > 3.0:
            signals.append(
                _make_signal(
                    "O1",
                    "异常期权活动",
                    DIR_BUY,
                    0.70,
                    f"看涨期权成交量为平均{call_vol_ratio:.1f}倍 > 3x, 聪明资金看多",
                    {"call_volume_ratio": call_vol_ratio},
                )
            )
        elif put_vol_ratio is not None and put_vol_ratio > 3.0:
            signals.append(
                _make_signal(
                    "O1",
                    "异常期权活动",
                    DIR_SELL,
                    0.65,
                    f"看跌期权成交量为平均{put_vol_ratio:.1f}倍 > 3x, 保护/看空",
                    {"put_volume_ratio": put_vol_ratio},
                )
            )

        # --- O2: Put/Call Ratio Extreme Contrarian (看跌看涨比极端) ---
        # PCR > 1.5 → contrarian BUY
        pcr = _safe_get(options_data, "put_call_ratio", default=None)
        if pcr is None:
            pcr = _safe_get(options_data, "pcr", "current", default=None)

        if pcr is not None:
            if pcr > 1.5:
                signals.append(
                    _make_signal(
                        "O2",
                        "看跌看涨比极端",
                        DIR_BUY,
                        0.60,
                        f"PCR={pcr:.2f} > 1.5, 极端恐慌, 反向指标看多",
                        {"put_call_ratio": pcr},
                    )
                )
            elif pcr < 0.5:
                signals.append(
                    _make_signal(
                        "O2",
                        "看跌看涨比极端",
                        DIR_SELL,
                        0.55,
                        f"PCR={pcr:.2f} < 0.5, 极端乐观, 反向指标看空",
                        {"put_call_ratio": pcr},
                    )
                )

        # --- O3: IV Signal (隐含波动率信号) ---
        # IV rank > 80th + no catalyst → neutral; IV crushed + price holds → BUY
        iv_rank = _safe_get(options_data, "iv_rank", default=None)
        if iv_rank is None:
            iv_rank = _safe_get(options_data, "iv_surface", "iv_rank", default=None)
        iv_crushed = _safe_get(options_data, "iv_crushed", default=False)
        price_holds = _safe_get(options_data, "price_holding", default=None)

        if iv_crushed and price_holds in (True, "yes", "holding"):
            signals.append(
                _make_signal(
                    "O3",
                    "隐含波动率信号",
                    DIR_BUY,
                    0.55,
                    "IV被压缩后价格坚挺, 波动率收缩后扩张前兆",
                    {"iv_rank": iv_rank, "iv_crushed": True, "price_holds": True},
                )
            )
        elif iv_rank is not None and iv_rank > 80:
            # High IV without catalyst — may indicate priced-in fear
            has_catalyst = _safe_get(options_data, "near_catalyst", default=False)
            if not has_catalyst:
                signals.append(
                    _make_signal(
                        "O3",
                        "隐含波动率信号",
                        DIR_NEUTRAL,
                        0.40,
                        f"IV Rank={iv_rank}% > 80, 无近期催化剂, 波动率偏高但方向中性",
                        {"iv_rank": iv_rank, "has_catalyst": False},
                    )
                )

        # --- O4: Max Pain Magnet (最大痛点磁性) ---
        # price < max_pain near expiry → short-term BUY pressure
        max_pain = _safe_get(options_data, "max_pain", "price", default=None)
        current_price = _safe_get(options_data, "current_price", default=None)
        days_to_expiry = _safe_get(
            options_data, "max_pain", "days_to_expiry", default=None
        )

        if max_pain is not None and current_price is not None:
            gap_pct = (
                (max_pain - current_price) / current_price if current_price > 0 else 0
            )
            near_expiry = days_to_expiry is not None and days_to_expiry <= 7

            if gap_pct > 0.03 and near_expiry:
                signals.append(
                    _make_signal(
                        "O4",
                        "最大痛点磁性",
                        DIR_BUY,
                        0.50,
                        f"当前价低于最大痛点{gap_pct:.1%}, 距到期{days_to_expiry}天, 短期上拉压力",
                        {
                            "max_pain": max_pain,
                            "current_price": current_price,
                            "gap_pct": gap_pct,
                            "dte": days_to_expiry,
                        },
                    )
                )
            elif gap_pct < -0.03 and near_expiry:
                signals.append(
                    _make_signal(
                        "O4",
                        "最大痛点磁性",
                        DIR_SELL,
                        0.45,
                        f"当前价高于最大痛点{abs(gap_pct):.1%}, 距到期{days_to_expiry}天, 短期下压",
                        {
                            "max_pain": max_pain,
                            "current_price": current_price,
                            "gap_pct": gap_pct,
                            "dte": days_to_expiry,
                        },
                    )
                )

        # Net direction
        buy_conf = sum(s["confidence"] for s in signals if s["direction"] > 0)
        sell_conf = sum(s["confidence"] for s in signals if s["direction"] < 0)
        total = buy_conf + sell_conf
        if total == 0:
            net_dir = DIR_NEUTRAL
            layer_conf = 0.0
        else:
            net_score = (buy_conf - sell_conf) / total
            net_dir = (
                DIR_BUY
                if net_score > 0.1
                else (DIR_SELL if net_score < -0.1 else DIR_NEUTRAL)
            )
            layer_conf = abs(net_score)

        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": True,
            "signals": signals,
            "net_direction": net_dir,
            "layer_confidence": round(layer_conf, 3),
            "summary": f"期权信号{len(signals)}个 (买:{sum(1 for s in signals if s['direction']>0)}, 卖:{sum(1 for s in signals if s['direction']<0)})",
        }

    except Exception as e:
        sys.stderr.write(f"[ERROR] L5 Options: {e}\n")
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": f"期权信号处理异常: {e}",
        }


# ---------------------------------------------------------------------------
# L6: Alt Data Layer (另类数据信号)
# ---------------------------------------------------------------------------


def compute_l6_alt_data(
    alternatives_data: dict | None,
    news_nlp_data: dict | None,
) -> dict:
    """Alternative data signals: app momentum, hiring, social sentiment, search trends.

    Signal IDs: A1-A4
    """
    layer_id = "L6_alt_data"
    layer_name = "另类数据信号"
    signals: list[dict] = []

    if not alternatives_data and not news_nlp_data:
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": "无另类数据",
        }

    try:
        # --- A1: App/Digital Momentum (应用/数字动量) ---
        # downloads up 20%+ MoM → BUY
        app_growth = _safe_get(
            alternatives_data, "app_store", "download_growth_mom", default=None
        )
        if app_growth is None:
            app_growth = _safe_get(
                alternatives_data, "digital_footprint", "app_growth", default=None
            )
        web_traffic_growth = _safe_get(
            alternatives_data, "web_traffic", "growth_mom", default=None
        )

        if app_growth is not None and app_growth > 0.20:
            signals.append(
                _make_signal(
                    "A1",
                    "应用数字动量",
                    DIR_BUY,
                    0.65,
                    f"App下载量月环比增长{app_growth:.1%} > 20%, 用户增长加速",
                    {"app_download_growth_mom": app_growth},
                )
            )
        elif web_traffic_growth is not None and web_traffic_growth > 0.25:
            signals.append(
                _make_signal(
                    "A1",
                    "应用数字动量",
                    DIR_BUY,
                    0.55,
                    f"网站流量月环比增长{web_traffic_growth:.1%} > 25%",
                    {"web_traffic_growth_mom": web_traffic_growth},
                )
            )
        elif app_growth is not None and app_growth < -0.20:
            signals.append(
                _make_signal(
                    "A1",
                    "应用数字动量",
                    DIR_SELL,
                    0.55,
                    f"App下载量月环比下降{app_growth:.1%}, 用户流失",
                    {"app_download_growth_mom": app_growth},
                )
            )

        # --- A2: Hiring Signal (招聘信号) ---
        # R&D jobs up 30%+ → BUY
        rd_hiring_growth = _safe_get(
            alternatives_data, "hiring", "rd_growth", default=None
        )
        if rd_hiring_growth is None:
            rd_hiring_growth = _safe_get(
                alternatives_data, "glassdoor", "rd_job_growth", default=None
            )
        total_hiring = _safe_get(
            alternatives_data, "hiring", "total_growth", default=None
        )

        if rd_hiring_growth is not None and rd_hiring_growth > 0.30:
            signals.append(
                _make_signal(
                    "A2",
                    "招聘信号",
                    DIR_BUY,
                    0.55,
                    f"研发岗位增长{rd_hiring_growth:.1%} > 30%, 管理层投资未来",
                    {"rd_hiring_growth": rd_hiring_growth},
                )
            )
        elif total_hiring is not None and total_hiring < -0.20:
            signals.append(
                _make_signal(
                    "A2",
                    "招聘信号",
                    DIR_SELL,
                    0.50,
                    f"总招聘下降{total_hiring:.1%}, 可能业务收缩信号",
                    {"total_hiring_growth": total_hiring},
                )
            )

        # --- A3: Social Sentiment Extreme (社交情绪极端) ---
        # extremely negative + at support → contrarian BUY
        social_sentiment = _safe_get(
            alternatives_data, "social", "sentiment_score", default=None
        )
        if social_sentiment is None:
            social_sentiment = _safe_get(
                news_nlp_data, "social_sentiment", "score", default=None
            )
        sentiment_extreme = _safe_get(news_nlp_data, "sentiment_extreme", default=None)

        if social_sentiment is not None:
            if social_sentiment < -0.7:
                signals.append(
                    _make_signal(
                        "A3",
                        "社交情绪极端",
                        DIR_BUY,
                        0.55,
                        f"社交情绪={social_sentiment:.2f}, 极端负面, 反向指标看多",
                        {"social_sentiment": social_sentiment},
                    )
                )
            elif social_sentiment > 0.8:
                signals.append(
                    _make_signal(
                        "A3",
                        "社交情绪极端",
                        DIR_SELL,
                        0.45,
                        f"社交情绪={social_sentiment:.2f}, 极端乐观, 反向指标谨慎",
                        {"social_sentiment": social_sentiment},
                    )
                )

        # --- A4: Search Trend (搜索趋势) ---
        # NOTE: A4 is BUY-only — creates structural bullish asymmetry
        # brand search spike > 2x → BUY for consumer
        search_spike = _safe_get(
            alternatives_data, "google_trends", "brand_spike_ratio", default=None
        )
        if search_spike is None:
            search_spike = _safe_get(
                alternatives_data, "search", "spike_ratio", default=None
            )

        if search_spike is not None and search_spike > 2.0:
            signals.append(
                _make_signal(
                    "A4",
                    "搜索趋势",
                    DIR_BUY,
                    0.50,
                    f"品牌搜索量突增{search_spike:.1f}x > 2x均值, 消费者关注度飙升",
                    {"search_spike_ratio": search_spike},
                )
            )

        # Net direction
        buy_conf = sum(s["confidence"] for s in signals if s["direction"] > 0)
        sell_conf = sum(s["confidence"] for s in signals if s["direction"] < 0)
        total = buy_conf + sell_conf
        if total == 0:
            net_dir = DIR_NEUTRAL
            layer_conf = 0.0
        else:
            net_score = (buy_conf - sell_conf) / total
            net_dir = (
                DIR_BUY
                if net_score > 0.1
                else (DIR_SELL if net_score < -0.1 else DIR_NEUTRAL)
            )
            layer_conf = abs(net_score)

        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": True,
            "signals": signals,
            "net_direction": net_dir,
            "layer_confidence": round(layer_conf, 3),
            "summary": f"另类数据信号{len(signals)}个 (买:{sum(1 for s in signals if s['direction']>0)}, 卖:{sum(1 for s in signals if s['direction']<0)})",
        }

    except Exception as e:
        sys.stderr.write(f"[ERROR] L6 Alt Data: {e}\n")
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": f"另类数据信号处理异常: {e}",
        }


# ---------------------------------------------------------------------------
# L7: Cross-Asset Layer (跨资产信号)
# ---------------------------------------------------------------------------


def compute_l7_cross_asset(
    breadth_data: dict | None,
    credit_data: dict | None,
) -> dict:
    """Cross-asset signals: credit spread, VIX, dollar, copper-gold, rate-equity divergence.

    Signal IDs: X1-X5
    """
    layer_id = "L7_cross_asset"
    layer_name = "跨资产信号"
    signals: list[dict] = []

    if not breadth_data and not credit_data:
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": "无跨资产数据",
        }

    try:
        # --- X1: Credit Spread (信用利差) ---
        # HY spread narrowing → BUY high-beta
        hy_trend = _safe_get(credit_data, "hy_spread", "trend", default=None)
        if hy_trend is None:
            hy_trend = _safe_get(credit_data, "spreads", "hy_oas_trend", default=None)
        hy_spread = _safe_get(credit_data, "hy_spread", "current", default=None)

        if hy_trend in ("narrowing", "tightening", "compressing"):
            signals.append(
                _make_signal(
                    "X1",
                    "信用利差",
                    DIR_BUY,
                    0.55,
                    f"高收益利差收窄趋势({hy_trend}), 信用环境改善, 利好高Beta",
                    {"hy_spread_trend": hy_trend, "hy_spread_current": hy_spread},
                )
            )
        elif hy_trend in ("widening", "blowing_out", "expanding"):
            signals.append(
                _make_signal(
                    "X1",
                    "信用利差",
                    DIR_SELL,
                    0.60,
                    f"高收益利差扩大({hy_trend}), 信用收缩, 风险偏好下降",
                    {"hy_spread_trend": hy_trend, "hy_spread_current": hy_spread},
                )
            )

        # --- X2: VIX Regime (VIX体制) ---
        # VIX > 35 + contango returning → contrarian BUY
        vix = _safe_get(breadth_data, "vix", "current", default=None)
        if vix is None:
            vix = _safe_get(breadth_data, "volatility", "vix", default=None)
        vix_term = _safe_get(breadth_data, "vix", "term_structure", default=None)
        if vix_term is None:
            vix_term = _safe_get(breadth_data, "vix_term_structure", default=None)

        if vix is not None:
            if vix > 35 and vix_term in (
                "contango",
                "returning_contango",
                "normalizing",
            ):
                signals.append(
                    _make_signal(
                        "X2",
                        "VIX体制",
                        DIR_BUY,
                        0.65,
                        f"VIX={vix:.1f} > 35 + 期限结构{'回归正态' if vix_term else '未知'}, 恐慌见顶, 反向看多",
                        {"vix": vix, "vix_term_structure": vix_term},
                    )
                )
            elif vix > 35 and vix_term in ("backwardation", "inverted"):
                signals.append(
                    _make_signal(
                        "X2",
                        "VIX体制",
                        DIR_NEUTRAL,
                        0.40,
                        f"VIX={vix:.1f} > 35 + 倒挂, 恐慌持续, 等待信号",
                        {"vix": vix, "vix_term_structure": vix_term},
                    )
                )
            elif vix < 12:
                signals.append(
                    _make_signal(
                        "X2",
                        "VIX体制",
                        DIR_SELL,
                        0.45,
                        f"VIX={vix:.1f} < 12, 极端自满, 潜在修正风险",
                        {"vix": vix, "vix_term_structure": vix_term},
                    )
                )

        # --- X3: Dollar Signal (美元信号) ---
        # DXY breaking down → BUY EM/commodity
        dxy_trend = _safe_get(breadth_data, "dxy", "trend", default=None)
        if dxy_trend is None:
            dxy_trend = _safe_get(breadth_data, "dollar", "trend", default=None)
        dxy_level = _safe_get(breadth_data, "dxy", "level", default=None)

        if dxy_trend in ("breaking_down", "declining", "weakening"):
            signals.append(
                _make_signal(
                    "X3",
                    "美元信号",
                    DIR_BUY,
                    0.50,
                    f"美元指数走弱({dxy_trend}), 利好新兴市场/大宗商品",
                    {"dxy_trend": dxy_trend, "dxy_level": dxy_level},
                )
            )
        elif dxy_trend in ("surging", "strengthening", "breaking_out"):
            signals.append(
                _make_signal(
                    "X3",
                    "美元信号",
                    DIR_SELL,
                    0.50,
                    f"美元指数走强({dxy_trend}), 利空EM/大宗/跨国企业",
                    {"dxy_trend": dxy_trend, "dxy_level": dxy_level},
                )
            )

        # --- X4: Copper-Gold Ratio (铜金比) ---
        # rising → BUY cyclicals
        cu_au_trend = _safe_get(breadth_data, "copper_gold", "trend", default=None)
        if cu_au_trend is None:
            cu_au_trend = _safe_get(
                breadth_data, "macro_signals", "copper_gold_ratio_trend", default=None
            )
        cu_au_ratio = _safe_get(breadth_data, "copper_gold", "ratio", default=None)

        if cu_au_trend in ("rising", "up", "improving"):
            signals.append(
                _make_signal(
                    "X4",
                    "铜金比",
                    DIR_BUY,
                    0.50,
                    f"铜金比上升({cu_au_trend}), 经济扩张预期, 利好周期股",
                    {
                        "copper_gold_trend": cu_au_trend,
                        "copper_gold_ratio": cu_au_ratio,
                    },
                )
            )
        elif cu_au_trend in ("falling", "down", "deteriorating"):
            signals.append(
                _make_signal(
                    "X4",
                    "铜金比",
                    DIR_SELL,
                    0.50,
                    f"铜金比下降({cu_au_trend}), 经济收缩预期, 避险情绪上升",
                    {
                        "copper_gold_trend": cu_au_trend,
                        "copper_gold_ratio": cu_au_ratio,
                    },
                )
            )

        # --- X5: Rate-Equity Divergence (利率-权益背离) ---
        # yields down + equities not up → SELL risk-off
        yield_trend = _safe_get(breadth_data, "rates", "10y_trend", default=None)
        if yield_trend is None:
            yield_trend = _safe_get(credit_data, "rates", "trend", default=None)
        equity_trend = _safe_get(breadth_data, "market", "sp500_trend", default=None)
        if equity_trend is None:
            equity_trend = _safe_get(
                breadth_data, "broad_market", "trend", default=None
            )

        if yield_trend in ("falling", "declining", "down"):
            if equity_trend in ("flat", "declining", "down", "falling"):
                signals.append(
                    _make_signal(
                        "X5",
                        "利率权益背离",
                        DIR_SELL,
                        0.60,
                        "国债收益率下降 + 权益未涨, risk-off模式, 避险为主",
                        {"yield_trend": yield_trend, "equity_trend": equity_trend},
                    )
                )
            elif equity_trend in ("rising", "up"):
                signals.append(
                    _make_signal(
                        "X5",
                        "利率权益背离",
                        DIR_BUY,
                        0.50,
                        "国债收益率下降 + 权益上涨, 流动性驱动牛市",
                        {"yield_trend": yield_trend, "equity_trend": equity_trend},
                    )
                )

        # Net direction
        buy_conf = sum(s["confidence"] for s in signals if s["direction"] > 0)
        sell_conf = sum(s["confidence"] for s in signals if s["direction"] < 0)
        total = buy_conf + sell_conf
        if total == 0:
            net_dir = DIR_NEUTRAL
            layer_conf = 0.0
        else:
            net_score = (buy_conf - sell_conf) / total
            net_dir = (
                DIR_BUY
                if net_score > 0.1
                else (DIR_SELL if net_score < -0.1 else DIR_NEUTRAL)
            )
            layer_conf = abs(net_score)

        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": True,
            "signals": signals,
            "net_direction": net_dir,
            "layer_confidence": round(layer_conf, 3),
            "summary": f"跨资产信号{len(signals)}个 (买:{sum(1 for s in signals if s['direction']>0)}, 卖:{sum(1 for s in signals if s['direction']<0)})",
        }

    except Exception as e:
        sys.stderr.write(f"[ERROR] L7 Cross-Asset: {e}\n")
        return {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "available": False,
            "signals": [],
            "net_direction": DIR_NEUTRAL,
            "layer_confidence": 0.0,
            "summary": f"跨资产信号处理异常: {e}",
        }


# ---------------------------------------------------------------------------
# Aggregation Engine (聚合引擎)
# ---------------------------------------------------------------------------


def _redistribute_weights(layers: list[dict]) -> dict[str, float]:
    """Redistribute layer weights proportionally when layers are missing.

    Returns a dict mapping layer_id → adjusted weight (sums to 1.0).
    """
    available_ids = [l["layer_id"] for l in layers if l.get("available")]
    if not available_ids:
        return {}

    available_raw = {lid: LAYER_WEIGHTS[lid] for lid in available_ids}
    total_raw = sum(available_raw.values())

    if total_raw == 0:
        # Uniform fallback
        w = 1.0 / len(available_ids)
        return {lid: w for lid in available_ids}

    return {lid: w / total_raw for lid, w in available_raw.items()}


def _compute_cross_layer_confirmation(layers: list[dict]) -> dict:
    """Count how many layers agree on each direction separately.

    Returns DIRECTIONAL confirmation scores so BUY verdicts use buy_confirmation
    and SELL verdicts use sell_confirmation (prevents cross-direction leakage).

    Score mapping per direction:
        5+ layers agree: score = 10
        4 layers agree:  score = 8
        3 layers agree:  score = 6
        2 layers agree:  score = 4
        0-1 layers:      score = 2
    """
    available = [l for l in layers if l.get("available")]
    buy_count = sum(1 for l in available if l["net_direction"] > 0)
    sell_count = sum(1 for l in available if l["net_direction"] < 0)
    neutral_count = sum(1 for l in available if l["net_direction"] == 0)

    dominant_direction = (
        DIR_BUY
        if buy_count > sell_count
        else (DIR_SELL if sell_count > buy_count else DIR_NEUTRAL)
    )

    def _count_to_score(count: int) -> int:
        if count >= 5:
            return 10
        elif count == 4:
            return 8
        elif count == 3:
            return 6
        elif count == 2:
            return 4
        else:
            return 2

    buy_confirmation = _count_to_score(buy_count)
    sell_confirmation = _count_to_score(sell_count)
    # Legacy field: max of both for backward compatibility in non-verdict contexts
    confirm_score = max(buy_confirmation, sell_confirmation)

    return {
        "confirmation_score": confirm_score,
        "buy_confirmation": buy_confirmation,
        "sell_confirmation": sell_confirmation,
        "buy_layers": buy_count,
        "sell_layers": sell_count,
        "neutral_layers": neutral_count,
        "dominant_direction": dominant_direction,
        "dominant_direction_label": _direction_label(dominant_direction),
        "total_available": len(available),
    }


def _compute_weighted_direction(layers: list[dict], weights: dict[str, float]) -> float:
    """Compute weighted direction score: sum(weight × direction_numeric).

    Returns a float in [-1, +1].
    """
    score = 0.0
    for layer in layers:
        lid = layer["layer_id"]
        if lid in weights and layer.get("available"):
            w = weights[lid]
            direction = layer["net_direction"]
            confidence = layer.get("layer_confidence", 0.5)
            # Weight by both assigned weight and layer's own confidence
            score += w * direction * confidence
    return score


def _determine_verdict(weighted_dir: float, confirm: dict) -> dict:
    """Determine final verdict based on weighted direction and DIRECTIONAL confirmation.

    Uses buy_confirmation for BUY verdicts and sell_confirmation for SELL verdicts
    to prevent cross-direction confirmation leakage.

    Verdict rules:
        STRONG_BUY:  weighted_dir > 0.5  AND buy_confirmation >= 6
        BUY:         weighted_dir > 0.3  AND buy_confirmation >= 4
        LEAN_BUY:    weighted_dir > 0.1  (no confirmation gate)
        NEUTRAL:     -0.1 <= weighted_dir <= 0.1
        LEAN_SELL:   weighted_dir < -0.1 (no confirmation gate)
        SELL:        weighted_dir < -0.3 AND sell_confirmation >= 4
        STRONG_SELL: weighted_dir < -0.5 AND sell_confirmation >= 6
    """
    buy_conf = confirm.get("buy_confirmation", confirm["confirmation_score"])
    sell_conf = confirm.get("sell_confirmation", confirm["confirmation_score"])

    if weighted_dir > 0.5 and buy_conf >= 6:
        verdict = "STRONG_BUY"
        verdict_cn = "强烈买入"
        action = "建仓/加仓"
    elif weighted_dir > 0.3 and buy_conf >= 4:
        verdict = "BUY"
        verdict_cn = "买入"
        action = "建仓"
    elif weighted_dir > 0.1:
        verdict = "LEAN_BUY"
        verdict_cn = "偏多"
        action = "观望/小仓位试探"
    elif weighted_dir >= -0.1:
        verdict = "NEUTRAL"
        verdict_cn = "中性"
        action = "持有/观望"
    elif weighted_dir > -0.3:
        verdict = "LEAN_SELL"
        verdict_cn = "偏空"
        action = "减仓/观望"
    elif weighted_dir < -0.5 and sell_conf >= 6:
        verdict = "STRONG_SELL"
        verdict_cn = "强烈卖出"
        action = "清仓"
    elif weighted_dir <= -0.3 and sell_conf >= 4:
        verdict = "SELL"
        verdict_cn = "卖出"
        action = "减仓/清仓"
    else:
        # weighted_dir between -0.3 and -0.1 but didn't match LEAN_SELL above,
        # or sell_confirmation too low for SELL/STRONG_SELL
        verdict = "LEAN_SELL"
        verdict_cn = "偏空"
        action = "减仓/观望"

    return {
        "verdict": verdict,
        "verdict_cn": verdict_cn,
        "recommended_action": action,
        "weighted_direction": round(weighted_dir, 4),
        "confirmation_score": confirm["confirmation_score"],
        "buy_confirmation": buy_conf,
        "sell_confirmation": sell_conf,
    }


def _detect_confluence(layers: list[dict]) -> list[dict]:
    """Identify multi-layer confluence patterns.

    Looks for known signal combinations that strengthen conviction.
    Only counts a layer as contributing in a direction if its net_direction agrees.
    """
    confluences: list[dict] = []

    # Build layer net direction map for directional gating
    layer_net_dir: dict[str, int] = {}
    for layer in layers:
        if layer.get("available"):
            layer_net_dir[layer["layer_id"]] = layer["net_direction"]

    # Collect all fired signal IDs
    all_signals: dict[str, dict] = {}
    for layer in layers:
        if not layer.get("available"):
            continue
        for sig in layer.get("signals", []):
            all_signals[sig["signal_id"]] = sig

    signal_ids = set(all_signals.keys())

    # Pattern 1: Technical + Flow + Options (三重确认)
    # Only count tech_buy if L1's net direction is positive
    tech_buy = (
        any(sid.startswith("B") for sid in signal_ids)
        and layer_net_dir.get("L1_technical", 0) > 0
    )
    flow_buy = (
        any(
            sid in ("M2", "M3") and all_signals[sid]["direction"] > 0
            for sid in signal_ids
            if sid in all_signals
        )
        and layer_net_dir.get("L4_institutional", 0) > 0
    )
    options_buy = (
        any(
            sid in ("O1", "O2") and all_signals[sid]["direction"] > 0
            for sid in signal_ids
            if sid in all_signals
        )
        and layer_net_dir.get("L5_options", 0) > 0
    )

    if tech_buy and flow_buy and options_buy:
        confluences.append(
            {
                "pattern": "三重确认 (技术+资金+期权)",
                "pattern_id": "CONF_001",
                "direction": "BUY",
                "description": "技术面买入信号 + 资金流入确认 + 期权市场看多, 高置信度",
                "strength": "HIGH",
            }
        )

    # Pattern 2: Earnings + Insider + Momentum (基本面驱动)
    has_e1_buy = "E1" in all_signals and all_signals["E1"]["direction"] > 0
    has_e2_buy = "E2" in all_signals and all_signals["E2"]["direction"] > 0
    has_f1_buy = "F1" in all_signals and all_signals["F1"]["direction"] > 0

    if has_e1_buy and has_e2_buy:
        confluences.append(
            {
                "pattern": "内外夹击 (盈利超预期+内部人买入)",
                "pattern_id": "CONF_002",
                "direction": "BUY",
                "description": "盈利超预期 + 内部人同步买入, 信息优势强烈",
                "strength": "HIGH",
            }
        )

    if has_e1_buy and has_f1_buy:
        confluences.append(
            {
                "pattern": "盈利动量 (超预期+价格动量)",
                "pattern_id": "CONF_003",
                "direction": "BUY",
                "description": "盈利超预期 + 强劲价格动量, PEAD效应验证",
                "strength": "MEDIUM",
            }
        )

    # Pattern 3: Short Squeeze + Call Volume (逼空叠加)
    has_m1 = "M1" in all_signals and all_signals["M1"]["direction"] > 0
    has_o1_buy = "O1" in all_signals and all_signals["O1"]["direction"] > 0

    if has_m1 and has_o1_buy:
        confluences.append(
            {
                "pattern": "逼空催化 (高空头+异常看涨期权)",
                "pattern_id": "CONF_004",
                "direction": "BUY",
                "description": "高空头比例 + 看涨期权异常放量, Gamma Squeeze潜力",
                "strength": "HIGH",
            }
        )

    # Pattern 4: Credit widening + VIX spike + selling (系统性风险)
    # Only fire if L7 cross-asset layer net direction is negative
    has_x1_sell = "X1" in all_signals and all_signals["X1"]["direction"] < 0
    has_x2_sell = "X2" in all_signals and all_signals["X2"]["direction"] < 0
    has_x5_sell = "X5" in all_signals and all_signals["X5"]["direction"] < 0

    if (
        has_x1_sell
        and (has_x2_sell or has_x5_sell)
        and layer_net_dir.get("L7_cross_asset", 0) < 0
    ):
        confluences.append(
            {
                "pattern": "系统性风险 (信用恶化+波动飙升/利率背离)",
                "pattern_id": "CONF_005",
                "direction": "SELL",
                "description": "信用利差扩大 + 波动率飙升或利率-权益背离, 宏观风险升级",
                "strength": "HIGH",
            }
        )

    # Pattern 5: Alt data + fundamentals divergence (先行信号)
    has_a1_buy = "A1" in all_signals and all_signals["A1"]["direction"] > 0
    has_a2_buy = "A2" in all_signals and all_signals["A2"]["direction"] > 0
    has_f3_buy = "F3" in all_signals and all_signals["F3"]["direction"] > 0

    if (has_a1_buy or has_a2_buy) and has_f3_buy:
        confluences.append(
            {
                "pattern": "先行确认 (另类数据+质量因子)",
                "pattern_id": "CONF_006",
                "direction": "BUY",
                "description": "另类数据领先指标 + 基本面质量确认, 潜在α来源",
                "strength": "MEDIUM",
            }
        )

    # Pattern 6: Value + Contrarian Sentiment (逆向价值)
    has_f2_buy = "F2" in all_signals and all_signals["F2"]["direction"] > 0
    has_a3_buy = "A3" in all_signals and all_signals["A3"]["direction"] > 0
    has_o2_buy = "O2" in all_signals and all_signals["O2"]["direction"] > 0

    if has_f2_buy and (has_a3_buy or has_o2_buy):
        confluences.append(
            {
                "pattern": "逆向价值 (低估+极端悲观情绪)",
                "pattern_id": "CONF_007",
                "direction": "BUY",
                "description": "估值显著低估 + 情绪极端恐慌, 经典逆向投资机会",
                "strength": "HIGH",
            }
        )

    return confluences


def _identify_risk_factors(layers: list[dict], verdict: dict) -> list[dict]:
    """Identify key risk factors that could invalidate the signal aggregate."""
    risks: list[dict] = []

    # Check for contradicting layers
    available = [l for l in layers if l.get("available")]
    buy_layers = [l for l in available if l["net_direction"] > 0]
    sell_layers = [l for l in available if l["net_direction"] < 0]

    # Risk: Strong disagreement
    if len(buy_layers) >= 2 and len(sell_layers) >= 2:
        risks.append(
            {
                "risk_id": "R1",
                "name_cn": "信号分歧",
                "severity": "MEDIUM",
                "description": f"买入层{len(buy_layers)}个 vs 卖出层{len(sell_layers)}个, 方向分歧显著, 降低置信度",
            }
        )

    # Risk: Low confidence across layers
    # Exclude layers with zero signals from average — they shouldn't pull down confidence
    layers_with_signals = [l for l in available if l.get("signals")]
    avg_conf = sum(l.get("layer_confidence", 0) for l in layers_with_signals) / max(
        len(layers_with_signals), 1
    )
    if avg_conf < 0.4:
        risks.append(
            {
                "risk_id": "R2",
                "name_cn": "低置信度",
                "severity": "MEDIUM",
                "description": f"各层平均置信度{avg_conf:.2f} < 0.4, 信号强度不足",
            }
        )

    # Risk: Missing critical layers
    missing = [
        lid
        for lid, w in LAYER_WEIGHTS.items()
        if w >= 0.15
        and not any(l["layer_id"] == lid and l.get("available") for l in layers)
    ]
    if missing:
        risks.append(
            {
                "risk_id": "R3",
                "name_cn": "关键数据缺失",
                "severity": "HIGH" if len(missing) >= 2 else "MEDIUM",
                "description": f"权重>=15%的层缺失: {', '.join(missing)}, 结论可能不完整",
            }
        )

    # Risk: Cross-asset warning when bullish
    if verdict["verdict"] in ("STRONG_BUY", "BUY"):
        cross_sell = any(
            l["layer_id"] == "L7_cross_asset" and l["net_direction"] < 0
            for l in available
        )
        if cross_sell:
            risks.append(
                {
                    "risk_id": "R4",
                    "name_cn": "宏观逆风",
                    "severity": "HIGH",
                    "description": "个股信号偏多但跨资产层偏空, 宏观环境可能压制上行空间",
                }
            )

    # Risk: Only alt data supporting (low conviction source)
    if verdict["verdict"] in ("LEAN_BUY", "BUY"):
        strong_buy_layers = [
            l for l in buy_layers if l["layer_id"] not in ("L6_alt_data",)
        ]
        if len(strong_buy_layers) <= 1:
            risks.append(
                {
                    "risk_id": "R5",
                    "name_cn": "信号来源单薄",
                    "severity": "MEDIUM",
                    "description": "买入信号主要来自低权重层(另类数据), 核心层支持不足",
                }
            )

    return risks


def aggregate_signals(
    ticker: str,
    layers: list[dict],
) -> dict:
    """Main aggregation: combine all layers into a unified verdict."""
    # Redistribute weights for available layers
    adj_weights = _redistribute_weights(layers)

    # Cross-layer confirmation
    confirmation = _compute_cross_layer_confirmation(layers)

    # Weighted direction
    weighted_dir = _compute_weighted_direction(layers, adj_weights)

    # Verdict
    verdict = _determine_verdict(weighted_dir, confirmation)

    # Confluence detection
    confluences = _detect_confluence(layers)

    # Risk factors
    risks = _identify_risk_factors(layers, verdict)

    # Summary statistics
    available_count = sum(1 for l in layers if l.get("available"))
    total_signals = sum(len(l.get("signals", [])) for l in layers if l.get("available"))
    buy_signals = sum(
        sum(1 for s in l.get("signals", []) if s["direction"] > 0)
        for l in layers
        if l.get("available")
    )
    sell_signals = sum(
        sum(1 for s in l.get("signals", []) if s["direction"] < 0)
        for l in layers
        if l.get("available")
    )

    return {
        "ticker": ticker,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
        "layers": layers,
        "aggregation": {
            "available_layers": available_count,
            "total_layers": len(LAYER_WEIGHTS),
            "adjusted_weights": {k: round(v, 4) for k, v in adj_weights.items()},
            "weighted_direction": round(weighted_dir, 4),
            "confirmation": confirmation,
            "total_signals_fired": total_signals,
            "buy_signals_count": buy_signals,
            "sell_signals_count": sell_signals,
            "neutral_signals_count": total_signals - buy_signals - sell_signals,
        },
        "verdict": verdict,
        "confluence_events": confluences,
        "risk_factors": risks,
        "metadata": {
            "methodology": (
                "7-layer signal aggregation with proportional weight redistribution. "
                "L1=0.25 技术, L2=0.15 因子, L3=0.20 事件, L4=0.15 资金流, "
                "L5=0.10 期权, L6=0.05 另类, L7=0.10 跨资产. "
                "Verdict = f(weighted_direction, cross_layer_confirmation). "
                "Confluence detection identifies multi-layer patterns."
            ),
            "layer_descriptions": {
                "L1_technical": "技术面信号 (B1-B6买入, S1-S6卖出)",
                "L2_factor": "因子信号 (F1动量, F2价值, F3质量, F4盈利修正, F5低波动, F6小盘动量)",
                "L3_event": "事件驱动信号 (E1盈利惊喜, E2内部人买入, E3回购, E4激进投资者)",
                "L4_institutional": "机构资金流 (M1逼空, M2隐性吸筹, M3持续流入, M4 ETF流向)",
                "L5_options": "期权衍生信号 (O1异常活动, O2 PCR极端, O3 IV信号, O4最大痛点)",
                "L6_alt_data": "另类数据 (A1应用动量, A2招聘, A3社交极端, A4搜索趋势)",
                "L7_cross_asset": "跨资产信号 (X1信用利差, X2 VIX, X3美元, X4铜金比, X5利率背离)",
            },
        },
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="7-layer signal aggregation engine — combines multi-source signals into unified verdict"
    )
    parser.add_argument("ticker", help="Stock ticker symbol (e.g., AAPL, NVDA)")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--trade-signals-json", help="Path to compute_trade_signals.py output JSON (L1)"
    )
    parser.add_argument(
        "--factors-json", help="Path to compute_factors.py output JSON (L2)"
    )
    parser.add_argument(
        "--sentiment-json", help="Path to fetch_sentiment.py output JSON (L3)"
    )
    parser.add_argument(
        "--earnings-edge-json", help="Path to compute_earnings_edge.py output JSON (L3)"
    )
    parser.add_argument(
        "--options-json", help="Path to calculate_options.py output JSON (L5)"
    )
    parser.add_argument(
        "--alternatives-json", help="Path to fetch_alternatives.py output JSON (L6)"
    )
    parser.add_argument(
        "--news-nlp-json", help="Path to fetch_news_nlp.py output JSON (L6)"
    )
    parser.add_argument(
        "--breadth-json", help="Path to fetch_market_breadth.py output JSON (L7)"
    )
    parser.add_argument(
        "--credit-json", help="Path to fetch_credit.py output JSON (L7)"
    )
    parser.add_argument(
        "--short-interest-json", help="Path to fetch_short_interest.py output JSON (L4)"
    )
    parser.add_argument(
        "--activist-json", help="Path to fetch_activist_exposure.py output JSON (L3)"
    )
    parser.add_argument(
        "--capital-structure-json",
        help="Path to fetch_capital_structure.py output JSON (L3)",
    )
    parser.add_argument(
        "--tech-json", help="Path to fetch_technicals.py output JSON (L2)"
    )
    parser.add_argument("--money-flow-json", help="Path to money flow data JSON (L4)")
    parser.add_argument(
        "--scores-json", help="Path to compute_scores.py output JSON (L2)"
    )

    args = parser.parse_args()
    ticker = args.ticker.upper()

    # Load all input data
    trade_signals_data = _load_json(args.trade_signals_json)
    factors_data = _load_json(args.factors_json)
    scores_data = _load_json(args.scores_json)
    tech_data = _load_json(args.tech_json)
    sentiment_data = _load_json(args.sentiment_json)
    earnings_edge_data = _load_json(args.earnings_edge_json)
    activist_data = _load_json(args.activist_json)
    capital_structure_data = _load_json(args.capital_structure_json)
    short_interest_data = _load_json(args.short_interest_json)
    money_flow_data = _load_json(args.money_flow_json)
    options_data = _load_json(args.options_json)
    alternatives_data = _load_json(args.alternatives_json)
    news_nlp_data = _load_json(args.news_nlp_json)
    breadth_data = _load_json(args.breadth_json)
    credit_data = _load_json(args.credit_json)

    # Compute each layer
    layers: list[dict] = []

    # L1: Technical
    layers.append(compute_l1_technical(trade_signals_data))

    # L2: Factor
    layers.append(compute_l2_factor(factors_data, scores_data, tech_data))

    # L3: Event-Driven
    layers.append(
        compute_l3_event(
            sentiment_data, earnings_edge_data, activist_data, capital_structure_data
        )
    )

    # L4: Institutional Flow
    layers.append(
        compute_l4_institutional(short_interest_data, money_flow_data, tech_data)
    )

    # L5: Options
    layers.append(compute_l5_options(options_data))

    # L6: Alt Data
    layers.append(compute_l6_alt_data(alternatives_data, news_nlp_data))

    # L7: Cross-Asset
    layers.append(compute_l7_cross_asset(breadth_data, credit_data))

    # Aggregate
    result = aggregate_signals(ticker, layers)

    # Output
    output_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        sys.stderr.write(f"[OK] Signal aggregation written to {args.output}\n")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
