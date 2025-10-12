# backtest_engine.py
import sys
import pandas as pd
from config import STRATEGY_ASSETS, BUY_COMMISSION_RATE
from data_handler import load_data, prepare_strategy_data, load_dividends_data
from strategies import decide_haa_portfolio, decide_daa_portfolio, decide_laa_portfolio
from portfolio_manager import (
    execute_rebalancing, 
    evaluate_portfolio_state, 
    execute_periodic_buy, 
    execute_default_rebalancing,
    get_active_target_weights
)
from reporting import calculate_mdd, calculate_rolling_returns

def run_backtest(params: dict):
    """파라미터를 받아 백테스트를 실행하고 모든 결과를 딕셔너리로 반환합니다."""
    
    strategy = params['strategy']
    start_date = params['start_date']
    end_date = params['end_date']
    db_path = params['db_path']
    capital = params['capital']
    stocks = params['stocks']
    no_rebalance = params['no_rebalance']
    no_drip = params['no_drip']
    interval = params['interval']
    
    if strategy == 'default':
        if not stocks or len(stocks) < 2 or len(stocks) % 2 != 0:
            raise ValueError("기본(default) 전략을 사용하려면 stocks에 티커와 비중을 쌍으로 입력해야 합니다.")
        all_tickers = set(stocks[::2])
        original_target_weights = {t: float(w) for t, w in zip(stocks[::2], stocks[1::2])}
    else:
        assets = STRATEGY_ASSETS[strategy]
        all_tickers = set.union(*[set(v) for v in assets.values()])
        original_target_weights = {}

    stock_data = load_data(db_path, all_tickers, start_date)
    # [추가] 배당 데이터 로딩
    dividends_data = load_dividends_data(db_path, all_tickers)

    if stock_data.empty:
        raise ValueError(f"DB에 요청하신 기간에 해당하는 데이터가 없습니다. Tickers: {list(all_tickers)}")

    monthly_prices, momentum_data, daily_data = prepare_strategy_data(stock_data)

    if stock_data.empty:
        raise ValueError(f"DB에 요청하신 기간에 해당하는 데이터가 없습니다. Tickers: {list(all_tickers)}")

    monthly_prices, momentum_data, daily_data = prepare_strategy_data(stock_data)

    sim_start_date = pd.to_datetime(start_date)
    sim_end_date = pd.to_datetime(end_date) if end_date else stock_data.index[-1]
    
    theoretical_dates = pd.date_range(start=sim_start_date, end=sim_end_date, freq=interval)
    
    actual_trading_dates = []
    for t_date in theoretical_dates:
        next_day_index = stock_data.index.searchsorted(t_date, side='left')
        if next_day_index < len(stock_data.index):
            actual_trading_dates.append(stock_data.index[next_day_index])

    evaluation_dates = sorted(list(set(actual_trading_dates)))
    evaluation_dates = [d for d in evaluation_dates if d >= sim_start_date and d <= sim_end_date]
    evaluation_dates = pd.DatetimeIndex(evaluation_dates)


    cash = capital
    holdings = {ticker: 0 for ticker in all_tickers}
    total_investment = capital
    results = []
    logs = []

    for i, date in enumerate(evaluation_dates):
        logs.append({"date": date.strftime('%Y-%m-%d'), "type": "EVALUATION_START", "message": f"평가일: {date.strftime('%Y-%m-%d')}"})
        
        last_eval_date = evaluation_dates[i-1] if i > 0 else pd.Timestamp(start_date)

        # [추가] 배당금 수령 로직
        if i > 0:
            for ticker, shares in holdings.items():
                if shares > 0 and ticker in dividends_data:
                    # 지난 평가일과 현재 평가일 사이의 배당 내역을 찾음
                    period_dividends = dividends_data[ticker][
                        (dividends_data[ticker].index > last_eval_date) & 
                        (dividends_data[ticker].index <= date)
                    ]
                    if not period_dividends.empty:
                        for div_date, div_per_share in period_dividends.items():
                            dividend_income = ( div_per_share * shares ) * 0.846
                            if no_drip:
                                cash += 0
                            else:
                                cash += dividend_income
                            logs.append({"date": div_date.strftime('%Y-%m-%d'), "type": "DIVIDEND", "ticker": ticker, "amount": dividend_income})

        if i > 0 and params['periodic_investment'] > 0:
            cash += params['periodic_investment']
            total_investment += params['periodic_investment']
            logs.append({"date": date.strftime('%Y-%m-%d'), "type": "DEPOSIT", "amount": params['periodic_investment']})
            
        if i > 0 and params['periodic_investment'] > 0:
            cash += params['periodic_investment']
            total_investment += params['periodic_investment']
            logs.append({"date": date.strftime('%Y-%m-%d'), "type": "DEPOSIT", "amount": params['periodic_investment']})
            
        current_prices = stock_data.loc[date]
        
        decision_date = monthly_prices.index.asof(date)
        if pd.isna(decision_date):
             logs.append({"date": date.strftime('%Y-%m-%d'), "type": "INFO", "message": "모멘텀 데이터를 찾을 수 없어 거래를 건너뜁니다."})
             eval_result = evaluate_portfolio_state(date, holdings, cash, current_prices, all_tickers)
             eval_result['Total Investment'] = total_investment
             results.append(eval_result)
             continue

        target_portfolio = {}
        if strategy == 'default': target_portfolio = get_active_target_weights(original_target_weights, current_prices)
        elif strategy == 'haa': target_portfolio = decide_haa_portfolio(decision_date, monthly_prices, momentum_data)
        elif strategy == 'daa': target_portfolio = decide_daa_portfolio(decision_date, momentum_data)
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
                                logs.append({"date": date.strftime('%Y-%m-%d'), "type": "TRANSACTION", "action": "INITIAL_BUY", "ticker": ticker, "shares": shares, "price": price, "amount": base_cost, "fee": commission})
            else:
                if strategy == 'default' and no_rebalance:
                    holdings, cash = execute_periodic_buy(holdings.copy(), cash, original_target_weights, current_prices, logs)
                else:
                    holdings, cash = execute_rebalancing(holdings.copy(), cash, target_portfolio, current_prices, logs)
        
        eval_result = evaluate_portfolio_state(date, holdings, cash, current_prices, all_tickers)
        eval_result['Total Investment'] = total_investment
        results.append(eval_result)
        
    # [신규] 최종 평가일(end-date)에 대한 평가 로직 추가
    if sim_end_date and not evaluation_dates.empty and evaluation_dates[-1] < sim_end_date:
        # end_date와 가장 가까운 '이전' 거래일을 찾음
        final_eval_date = stock_data.index.asof(sim_end_date)
        
        # 마지막 리밸런싱 날짜와 최종 평가일이 다른 경우에만 추가 평가 수행
        if final_eval_date and final_eval_date > evaluation_dates[-1]:
            logs.append({"date": final_eval_date.strftime('%Y-%m-%d'), "type": "EVALUATION_START", "message": f"최종 평가일: {final_eval_date.strftime('%Y-%m-%d')}"})
            
            # 마지막 리밸런싱 상태의 holdings와 cash를 그대로 사용 (거래 없음)
            final_prices = stock_data.loc[final_eval_date]
            
            # 최종 평가 수행
            final_eval_result = evaluate_portfolio_state(final_eval_date, holdings, cash, final_prices, all_tickers)
            final_eval_result['Total Investment'] = total_investment
            results.append(final_eval_result)

    if not results:
        raise ValueError("시뮬레이션 결과가 없습니다.")

    numeric_df = pd.DataFrame(results).fillna(0)
    numeric_df['Date'] = pd.to_datetime(numeric_df['Date'])
    numeric_df.set_index('Date', inplace=True)
    
    value_columns = [f"{t} Value" for t in all_tickers if f"{t} Value" in numeric_df.columns]
    numeric_df["Portfolio Value"] = numeric_df[value_columns].sum(axis=1) + numeric_df["Cash"]
    numeric_df['ROI'] = (numeric_df['Portfolio Value'] - numeric_df['Total Investment']) / numeric_df['Total Investment']
    
    summary_mdd = calculate_mdd(numeric_df)
    summary_rolling = calculate_rolling_returns(numeric_df, params['rolling_window'], params['rolling_step']) if params['rolling_window'] else None

    final_results = []
    for date, row in numeric_df.iterrows():
        assets_data = {t: {"holdings": row[f"{t} Holdings"], "price": row[f"{t} Price"], "value": row[f"{t} Value"], "weight": row[f"{t} Weight"]} for t in all_tickers}
        final_results.append({
            "date": date.strftime('%Y-%m-%d'), "portfolio_value": row["Portfolio Value"],
            "total_investment": row["Total Investment"], "roi": row["ROI"], "cash": row["Cash"],
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

    return {
        "summary": {
            "final_portfolio_value": numeric_df["Portfolio Value"].iloc[-1],
            "total_investment": numeric_df["Total Investment"].iloc[-1],
            "final_roi": numeric_df["ROI"].iloc[-1],
            "mdd": summary_mdd,
            "rolling_returns": summary_rolling
        },
        "logs": logs, "results": final_results, "chart_data": chart_data
    }

