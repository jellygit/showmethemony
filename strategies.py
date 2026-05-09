# strategies.py

import pandas as pd

from config import STRATEGY_ASSETS


def decide_haa_portfolio(date, monthly_prices, momentum_data):
    """HAA 전략에 따라 목표 포트폴리오를 결정합니다."""
    assets = STRATEGY_ASSETS["haa"]
    roc_6 = momentum_data["roc_6"].loc[date]
    sma_12 = momentum_data["sma_12_month"].loc[date]

    offensive_pick = roc_6[assets["offensive"]].idxmax()
    defensive_pick = roc_6[assets["defensive"]].idxmax()

    canary_price = monthly_prices.loc[date, assets["canary"][0]]
    canary_sma = sma_12[assets["canary"][0]]

    if pd.isna(canary_price) or pd.isna(canary_sma):
        return {}

    if canary_price > canary_sma:
        return {offensive_pick: 1.0}
    else:
        return {defensive_pick: 1.0}


def decide_daa_portfolio(date, momentum_data):
    """DAA 전략에 따라 목표 포트폴리오를 결정합니다."""
    assets = STRATEGY_ASSETS["daa"]
    daa_momentum = momentum_data["daa_momentum"].loc[date]

    canary_scores = daa_momentum[assets["canary"]]
    if canary_scores.isnull().all() or canary_scores.mean() < 0:
        defensive_pick = daa_momentum[assets["defensive"]].idxmax()
        return {defensive_pick: 1.0}
    else:
        offensive_picks = daa_momentum[assets["offensive"]].nlargest(3).index
        return {ticker: 1.0 / len(offensive_picks) for ticker in offensive_picks}


def decide_laa_portfolio(date, current_prices, daily_data):
    """LAA (Lethargic Asset Allocation) 전략에 따라 목표 포트폴리오를 결정합니다."""
    assets = STRATEGY_ASSETS["laa"]
    target_portfolio = {ticker: 0.25 for ticker in assets["core"]}

    spy_price = current_prices.get("SPY")
    # daily_data["sma_200_day"]는 Series이므로 .get(date) 또는 .loc[date] 사용
    spy_sma = daily_data["sma_200_day"].get(date)

    if pd.isna(spy_price) or pd.isna(spy_sma):
        return {}

    if spy_price > spy_sma:
        target_portfolio[assets["offensive"][0]] = 0.25
    else:
        target_portfolio[assets["defensive"][0]] = 0.25

    return target_portfolio


def decide_turtle_portfolio(
    date,
    current_prices,
    state_tracker,
    portfolio_value,
    turtle_data,
    entry_days=20,
    exit_days=10,
    risk_factor=0.02,
):
    """
    터틀 매매 전략에 따라 목표 포트폴리오 비중을 결정합니다.
    """
    target_portfolio = {}
    max_units = 5

    for ticker in current_prices.index:
        price = current_prices.get(ticker)
        if pd.isna(price) or price <= 0:
            continue

        n = turtle_data["atr_20"].loc[date, ticker]
        high_val = turtle_data[f"high_{entry_days}"].loc[date, ticker]
        low_val = turtle_data[f"low_{exit_days}"].loc[date, ticker]

        if pd.isna(n) or pd.isna(high_val) or pd.isna(low_val) or n <= 0:
            continue

        state = state_tracker.get(
            ticker, {"units": 0, "entry_price": 0, "last_unit_price": 0}
        )
        units = state["units"]
        last_price = state["last_unit_price"]

        # 1. 포지션 보유 중인 경우 (청산/손절/피라미딩 체크)
        if units > 0:
            # 손절: 마지막 진입가 대비 2N 하락
            # 청산: 저점 이탈
            if price <= (last_price - 2 * n) or price < low_val:
                target_portfolio[ticker] = 0.0
                continue

            # 피라미딩: 0.5N 상승 시 추가 매수 (최대 5유닛)
            if units < max_units and price >= (last_price + 0.5 * n):
                new_units = units + 1
                unit_shares = (portfolio_value * risk_factor) / n
                target_weight = (new_units * unit_shares * price) / portfolio_value
                target_portfolio[ticker] = target_weight
            else:
                unit_shares = (portfolio_value * risk_factor) / n
                target_weight = (units * unit_shares * price) / portfolio_value
                target_portfolio[ticker] = target_weight

        # 2. 포지션 미보유 중인 경우 (진입 체크)
        else:
            if price > high_val:
                unit_shares = (portfolio_value * risk_factor) / n
                target_weight = (1 * unit_shares * price) / portfolio_value
                target_portfolio[ticker] = target_weight

    return target_portfolio
