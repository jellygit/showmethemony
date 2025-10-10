# backtest_engine.py
import sys
import pandas as pd
from config import STRATEGY_ASSETS, BUY_COMMISSION_RATE
from data_handler import load_data, prepare_strategy_data
from strategies import decide_haa_portfolio, decide_daa_portfolio, decide_laa_portfolio
from portfolio_manager import execute_rebalancing, evaluate_portfolio_state, execute_periodic_buy, get_active_target_weights
from reporting import calculate_mdd, calculate_rolling_returns

def run_backtest(params: dict):
    """파라미터를 받아 백테스트를 실행하고 모든 결과를 딕셔너리로 반환합니다."""
    
    # --- 1. 파라미터 추출 및 설정 ---
    strategy = params['strategy']
    start_date = params['start_date']
    end_date = params['end_date']
    db_path = params['db_path']
    capital = params['capital']
    stocks = params['stocks']
    no_rebalance = params['no_rebalance']
    
    if strategy == 'default':
        if not stocks or len(stocks) < 2 or len(stocks) % 2 != 0:
            raise ValueError("기본(default) 전략을 사용하려면 stocks에 티커와 비중을 쌍으로 입력해야 합니다.")
        all_tickers = set(stocks[::2])
        original_target_weights = {t: float(w) for t, w in zip(stocks[::2], stocks[1::2])}
    else:
        assets = STRATEGY_ASSETS[strategy]
        all_tickers = set.union(*[set(v) for v in assets.values()])
        original_target_weights = {}

    # --- 2. 데이터 준비 ---
    stock_data = load_data(db_path, all_tickers, start_date)
    monthly_prices, momentum_data, daily_data = prepare_strategy_data(stock_data)

    # --- 3. 시뮬레이션 기간 설정 ---
    sim_start_date = pd.to_datetime(start_date)
    sim_end_date = pd.to_datetime(end_date) if end_date else monthly_prices.index[-1]
    
    theoretical_dates = pd.date_range(start=sim_start_date, end=sim_end_date, freq=params['interval'])
    date_indices = monthly_prices.index.searchsorted(theoretical_dates, side='left')
    evaluation_dates = monthly_prices.index[sorted(list(set(date_indices)))]
    evaluation_dates = evaluation_dates[(evaluation_dates >= sim_start_date) & (evaluation_dates <= sim_end_date)]

    # --- 4. 시뮬레이션 실행 ---
    cash = capital
    holdings = {ticker: 0 for ticker in all_tickers}
    total_investment = capital
    results = []
    logs = []

    for i, date in enumerate(evaluation_dates):
        logs.append({"date": date.strftime('%Y-%m-%d'), "type": "EVALUATION_START"})
        
        if i > 0 and params['periodic_investment'] > 0:
            cash += params['periodic_investment']
            total_investment += params['periodic_investment']
            logs.append({"date": date.strftime('%Y-%m-%d'), "type": "DEPOSIT", "amount": params['periodic_investment']})
            
        current_prices = stock_data.loc[stock_data.index.asof(date)]
        
        target_portfolio = {}
        if strategy == 'default': target_portfolio = get_active_target_weights(original_target_weights, current_prices)
        elif strategy == 'haa': target_portfolio = decide_haa_portfolio(date, monthly_prices, momentum_data)
        elif strategy == 'daa': target_portfolio = decide_daa_portfolio(date, momentum_data)
        elif strategy == 'laa': target_portfolio = decide_laa_portfolio(date, current_prices, daily_data)
        
        if not target_portfolio:
            logs.append({"date": date.strftime('%Y-%m-%d'), "type": "INFO", "message": "목표 포트폴리오를 결정할 수 없어 현재 상태 유지"})
        else:
            if i == 0:
                initial_portfolio_value = cash
                for ticker, weight in target_portfolio.items():
                    price = current_prices.get(ticker)
                    if price is not None and price > 0:
                        allocation = initial_portfolio_value * weight
                        shares = int(allocation / (price * (1 + BUY_COMMISSION_RATE)))
                        if shares > 0:
                            base_cost, commission = shares * price, (shares * price) * BUY_COMMISSION_RATE
                            total_cost = base_cost + commission
                            if cash >= total_cost:
                                holdings[ticker], cash = shares, cash - total_cost
                                logs.append({"date": date.strftime('%Y-%m-%d'), "type": "TRANSACTION", "action": "BUY", "ticker": ticker, "shares": shares, "price": price, "amount": base_cost, "fee": commission})
            else:
                if strategy == 'default' and no_rebalance:
                    holdings, cash = execute_periodic_buy(holdings.copy(), cash, original_target_weights, current_prices, logs)
                else:
                    holdings, cash = execute_rebalancing(holdings.copy(), cash, target_portfolio, current_prices, logs)
        
        eval_result = evaluate_portfolio_state(date, holdings, cash, current_prices, all_tickers)
        eval_result['Total Investment'] = total_investment
        results.append(eval_result)
        
    # --- 5. 최종 결과 집계 ---
    if not results:
        return {"error": "시뮬레이션 결과가 없습니다."}

    numeric_df = pd.DataFrame(results).fillna(0)
    numeric_df['Date'] = pd.to_datetime(numeric_df['Date'])
    numeric_df.set_index('Date', inplace=True)
    
    value_columns = [f"{t} Value" for t in all_tickers if f"{t} Value" in numeric_df.columns]
    numeric_df["Portfolio Value"] = numeric_df[value_columns].sum(axis=1) + numeric_df["Cash"]
    numeric_df['ROI'] = (numeric_df['Portfolio Value'] - numeric_df['Total Investment']) / numeric_df['Total Investment']
    
    # 요약 지표 계산
    summary_mdd = calculate_mdd(numeric_df)
    summary_rolling = calculate_rolling_returns(numeric_df, params['rolling_window'], params['rolling_step']) if params['rolling_window'] else None

    # 최종 JSON 구조화
    final_results = []
    for date, row in numeric_df.iterrows():
        assets_data = {t: {"holdings": row[f"{t} Holdings"], "price": row[f"{t} Price"], "value": row[f"{t} Value"], "weight": row[f"{t} Weight"]} for t in all_tickers}
        final_results.append({
            "date": date.strftime('%Y-%m-%d'),
            "portfolio_value": row["Portfolio Value"],
            "total_investment": row["Total Investment"],
            "roi": row["ROI"],
            "cash": row["Cash"],
            "assets": assets_data
        })
    
    chart_data = {
        "labels": numeric_df.index.strftime('%Y-%m-%d').tolist(),
        "datasets": {
            "portfolio_value": numeric_df["Portfolio Value"].tolist(),
            "total_investment": numeric_df["Total Investment"].tolist(),
            "roi": numeric_df["ROI"].tolist()
        }
    }

    final_json = {
        "summary": {
            "final_portfolio_value": numeric_df["Portfolio Value"].iloc[-1],
            "total_investment": numeric_df["Total Investment"].iloc[-1],
            "final_roi": numeric_df["ROI"].iloc[-1],
            "mdd": summary_mdd,
            "rolling_returns": summary_rolling
        },
        "logs": logs,
        "results": final_results,
        "chart_data": chart_data
    }
    
    return final_json
