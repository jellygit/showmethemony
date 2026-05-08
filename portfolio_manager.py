# portfolio_manager.py
import pandas as pd
from config import BUY_COMMISSION_RATE, SELL_TAX_RATE

def _normalize_weights(weights):
    if not weights: return {}
    total_weight = sum(weights.values())
    if total_weight == 0: return {t: 1.0 / len(weights) for t in weights}
    return {t: w / total_weight for t, w in weights.items()}

def get_active_target_weights(original_target_weights, prices):
    available = [t for t in original_target_weights if pd.notna(prices.get(t)) and prices.get(t) > 0]
    active_weights = {t: original_target_weights[t] for t in available}
    return _normalize_weights(active_weights)

def _sweep_cash(holdings, cash, target_portfolio, prices, logs, date):
    target_prices = {t: prices.get(t) for t in target_portfolio if pd.notna(prices.get(t)) and prices.get(t) > 0}
    if not target_prices or cash <= min(target_prices.values()):
        return holdings, cash
    
    logs.append({"date": date, "type": "INFO", "message": f"잔여 현금({cash:,.2f}) 추가 매수 실행"})
    cash_to_reinvest = cash - 1.0
    
    for ticker, weight in target_portfolio.items():
        price = target_prices.get(ticker)
        if price is None: continue
        shares = int((cash_to_reinvest * weight) / (price * (1 + BUY_COMMISSION_RATE)))
        if shares > 0:
            base_cost, commission = shares * price, (shares * price) * BUY_COMMISSION_RATE
            if cash >= base_cost + commission:
                holdings[ticker] = holdings.get(ticker, 0) + shares
                cash -= base_cost + commission
                logs.append({"date": date, "type": "TRANSACTION", "action": "SWEEP_BUY", "ticker": ticker, "shares": shares, "price": price, "amount": base_cost, "fee": commission})
    return holdings, cash

def execute_rebalancing(holdings, cash, target_portfolio, prices, logs, date):
    current_portfolio_value = cash + sum(holdings.get(t, 0) * prices.get(t, 0) for t in holdings if pd.notna(prices.get(t)))
    
    for t in [t for t in holdings if holdings[t] > 0 and t not in target_portfolio]:
        shares, price = holdings[t], prices.get(t)
        if shares > 0 and pd.notna(price):
            holdings[t], base_proceeds = 0, shares * price
            cash += base_proceeds * (1 - SELL_TAX_RATE)
            logs.append({"date": date, "type": "TRANSACTION", "action": "SELL_ALL", "ticker": t, "shares": shares, "price": price, "amount": base_proceeds, "fee": base_proceeds * SELL_TAX_RATE})
            
    for ticker, weight in target_portfolio.items():
        price = prices.get(ticker)
        if pd.isna(price) or price <= 0: continue
        delta = (current_portfolio_value * weight) - (holdings.get(ticker, 0) * price)
        if delta > 0:
            shares = int(delta / (price * (1 + BUY_COMMISSION_RATE)))
            if shares > 0:
                base_cost, commission = shares * price, (shares * price) * BUY_COMMISSION_RATE
                if cash >= base_cost + commission:
                    holdings[ticker] = holdings.get(ticker, 0) + shares
                    cash -= base_cost + commission
                    logs.append({"date": date, "type": "TRANSACTION", "action": "BUY", "ticker": ticker, "shares": shares, "price": price, "amount": base_cost, "fee": commission})
        elif delta < 0:
            shares = int(-delta / price)
            if shares > 0 and holdings.get(ticker, 0) >= shares:
                holdings[ticker] -= shares
                base_proceeds = shares * price
                cash += base_proceeds * (1 - SELL_TAX_RATE)
                logs.append({"date": date, "type": "TRANSACTION", "action": "SELL_ADJUST", "ticker": ticker, "shares": shares, "price": price, "amount": base_proceeds, "fee": base_proceeds * SELL_TAX_RATE})
    
    return _sweep_cash(holdings, cash, target_portfolio, prices, logs, date)

def execute_periodic_buy(holdings, cash, initial_target_weights, prices, logs, date):
    logs.append({"date": date, "type": "INFO", "message": "주기적 추가 매수 실행 (리밸런싱 없음)"})
    active_target_weights = get_active_target_weights(initial_target_weights, prices)
    for ticker, weight in active_target_weights.items():
        price = prices.get(ticker)
        if pd.isna(price) or price <= 0: continue
        shares = int((cash * weight) / (price * (1 + BUY_COMMISSION_RATE)))
        if shares > 0:
            base_cost, commission = shares * price, (shares * price) * BUY_COMMISSION_RATE
            if cash >= base_cost + commission:
                holdings[ticker] = holdings.get(ticker, 0) + shares
                cash -= base_cost + commission
                logs.append({"date": date, "type": "TRANSACTION", "action": "PERIODIC_BUY", "ticker": ticker, "shares": shares, "price": price, "amount": base_cost, "fee": commission})
    return _sweep_cash(holdings, cash, active_target_weights, prices, logs, date)

def execute_default_rebalancing(holdings, cash, target_weights, prices, logs, date):
    logs.append({"date": date, "type": "INFO", "message": "정적 비중 리밸런싱 실행"})
    active_target_weights = get_active_target_weights(target_weights, prices)
    return execute_rebalancing(holdings, cash, active_target_weights, prices, logs, date)
    
def evaluate_portfolio_state(date, holdings, cash, prices, all_tickers):
    eval_result = {"Date": date.strftime("%Y-%m-%d"), "Cash": cash}
    valid_asset_value = 0
    for t in all_tickers:
        price, num_shares = prices.get(t, 0.0), holdings.get(t, 0)
        stock_value = num_shares * price
        eval_result.update({f"{t} Holdings": num_shares, f"{t} Price": price, f"{t} Value": stock_value})
        if num_shares > 0 and price > 0:
            valid_asset_value += stock_value
    for t in all_tickers:
        eval_result[f"{t} Weight"] = eval_result[f"{t} Value"] / valid_asset_value if valid_asset_value > 0 else 0
    return eval_result
