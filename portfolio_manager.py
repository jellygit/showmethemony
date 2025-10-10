# portfolio_manager.py
import pandas as pd
from config import BUY_COMMISSION_RATE, SELL_TAX_RATE

def _normalize_weights(weights):
    """주어진 가중치 딕셔너리의 합이 1이 되도록 정규화합니다."""
    if not weights:
        return {}
    total_weight = sum(weights.values())
    if total_weight == 0:
        return {ticker: 1.0 / len(weights) for ticker in weights}
    return {ticker: w / total_weight for ticker, w in weights.items()}

def get_active_target_weights(original_target_weights, prices):
    """현재 거래 가능한 종목만으로 목표 비중을 동적으로 재계산합니다."""
    available_tickers = [ticker for ticker in original_target_weights if pd.notna(prices.get(ticker)) and prices.get(ticker) > 0]
    active_weights = {ticker: original_target_weights[ticker] for ticker in available_tickers}
    return _normalize_weights(active_weights)

def _sweep_cash(holdings, cash, target_portfolio, prices, logs):
    """[내부 함수] 잔여 현금을 목표 비중에 맞춰 추가 매수하고 로그를 기록합니다."""
    target_prices = {t: prices.get(t) for t in target_portfolio if pd.notna(prices.get(t)) and prices.get(t) > 0}
    if not target_prices or cash <= min(target_prices.values()):
        return holdings, cash

    logs.append({"type": "INFO", "message": f"잔여 현금({cash:,.2f}) 추가 매수 실행"})
    cash_to_reinvest = cash - 1.0  # 거래 오류 방지용 버퍼
    
    for ticker, weight in target_portfolio.items():
        price = target_prices.get(ticker)
        if price is None: continue
        
        allocation = cash_to_reinvest * weight
        shares = int(allocation / (price * (1 + BUY_COMMISSION_RATE)))
        
        if shares > 0:
            base_cost, commission = shares * price, (shares * price) * BUY_COMMISSION_RATE
            total_cost = base_cost + commission
            if cash >= total_cost:
                holdings[ticker] = holdings.get(ticker, 0) + shares
                cash -= total_cost
                logs.append({"type": "TRANSACTION", "action": "SWEEP_BUY", "ticker": ticker, "shares": shares, "price": price, "amount": base_cost, "fee": commission})
    return holdings, cash

def execute_rebalancing(holdings, cash, target_portfolio, prices, logs):
    """[동적 전략용] 거래 비용 및 현금 최소화 로직을 포함하여 리밸런싱을 실행하고 로그를 기록합니다."""
    current_portfolio_value = cash + sum(holdings.get(t, 0) * prices.get(t, 0) for t in holdings if pd.notna(prices.get(t)))
    
    # 매도
    tickers_to_sell = [t for t in holdings if holdings[t] > 0 and t not in target_portfolio]
    for ticker in tickers_to_sell:
        shares, price = holdings[ticker], prices.get(ticker)
        if shares > 0 and pd.notna(price):
            holdings[ticker], base_proceeds = 0, shares * price
            tax = base_proceeds * SELL_TAX_RATE
            cash += base_proceeds - tax
            logs.append({"type": "TRANSACTION", "action": "SELL_ALL", "ticker": ticker, "shares": shares, "price": price, "amount": base_proceeds, "fee": tax})
            
    # 매수/비중조절
    for ticker, target_weight in target_portfolio.items():
        price = prices.get(ticker)
        if pd.isna(price) or price <= 0: continue
        delta_value = (current_portfolio_value * target_weight) - (holdings.get(ticker, 0) * price)
        if delta_value > 0:
            shares = int(delta_value / (price * (1 + BUY_COMMISSION_RATE)))
            if shares > 0:
                base_cost, commission = shares * price, (shares * price) * BUY_COMMISSION_RATE
                if cash >= base_cost + commission:
                    holdings[ticker] = holdings.get(ticker, 0) + shares
                    cash -= base_cost + commission
                    logs.append({"type": "TRANSACTION", "action": "BUY", "ticker": ticker, "shares": shares, "price": price, "amount": base_cost, "fee": commission})
        elif delta_value < 0:
            shares = int(-delta_value / price)
            if shares > 0 and holdings.get(ticker, 0) >= shares:
                holdings[ticker] -= shares
                base_proceeds = shares * price
                tax = base_proceeds * SELL_TAX_RATE
                cash += base_proceeds - tax
                logs.append({"type": "TRANSACTION", "action": "SELL_ADJUST", "ticker": ticker, "shares": shares, "price": price, "amount": base_proceeds, "fee": tax})
    
    return _sweep_cash(holdings, cash, target_portfolio, prices, logs)

def execute_periodic_buy(holdings, cash, initial_target_weights, prices, logs):
    """[Default-no-rebalance 용] 매도 없이, 현금을 동적 목표비중에 따라 추가 매수하고 로그를 기록합니다."""
    logs.append({"type": "INFO", "message": "주기적 추가 매수 실행 (리밸런싱 없음)"})
    active_target_weights = get_active_target_weights(initial_target_weights, prices)
    cash_to_invest = cash
    for ticker, weight in active_target_weights.items():
        price = prices.get(ticker)
        if pd.isna(price) or price <= 0: continue
        allocation = cash_to_invest * weight
        shares = int(allocation / (price * (1 + BUY_COMMISSION_RATE)))
        if shares > 0:
            base_cost, commission = shares * price, (shares * price) * BUY_COMMISSION_RATE
            if cash >= base_cost + commission:
                holdings[ticker] = holdings.get(ticker, 0) + shares
                cash -= base_cost + commission
                logs.append({"type": "TRANSACTION", "action": "PERIODIC_BUY", "ticker": ticker, "shares": shares, "price": price, "amount": base_cost, "fee": commission})
    return _sweep_cash(holdings, cash, active_target_weights, prices, logs)

def execute_default_rebalancing(holdings, cash, target_weights, prices, logs):
    """[Default-rebalance 용] 동적 목표 비중에 맞춰 리밸런싱하고 로그를 기록합니다."""
    logs.append({"type": "INFO", "message": "정적 비중 리밸런싱 실행"})
    active_target_weights = get_active_target_weights(target_weights, prices)
    return execute_rebalancing(holdings, cash, active_target_weights, prices, logs)
    
def evaluate_portfolio_state(date, holdings, cash, prices, all_tickers):
    """특정 시점의 포트폴리오 상태를 평가하여 딕셔너리로 반환합니다."""
    eval_result = {"Date": date.strftime("%Y-%m-%d"), "Cash": cash}
    valid_asset_value = 0
    for ticker in all_tickers:
        price = prices.get(ticker, 0.0)
        num_shares = holdings.get(ticker, 0)
        stock_value = num_shares * price
        eval_result.update({f"{ticker} Holdings": num_shares, f"{ticker} Price": price, f"{ticker} Value": stock_value})
        if num_shares > 0 and price > 0:
            valid_asset_value += stock_value
    if valid_asset_value > 0:
        for ticker in all_tickers:
            eval_result[f"{ticker} Weight"] = eval_result[f"{ticker} Value"] / valid_asset_value
    else:
        for ticker in all_tickers:
            eval_result[f"{ticker} Weight"] = 0
    return eval_result
