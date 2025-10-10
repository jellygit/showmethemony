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
    """LAA 규칙에 따라 목표 포트폴리오를 결정합니다."""
    assets = STRATEGY_ASSETS["laa"]
    spy_price = current_prices.get("SPY")
    spy_sma_200 = daily_data["sma_200_day"].asof(date)

    if pd.isna(spy_price) or pd.isna(spy_sma_200):
        return {}

    target_portfolio = {ticker: 0.25 for ticker in assets["core"]}

    if spy_price > spy_sma_200:
        target_portfolio[assets["offensive"][0]] = 0.25
    else:
        target_portfolio[assets["defensive"][0]] = 0.25

    return target_portfolio
