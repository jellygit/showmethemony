
import backtest_engine
import json
from datetime import datetime

params = {
    "strategy": "top10_turtle",
    "start_date": "2023-01-01",
    "end_date": "2024-05-01",
    "db_path": "stock_price.db",
    "capital": 100000000,
    "stocks": [],
    "no_rebalance": False,
    "no_drip": False,
    "interval": "1D",  # 터틀은 매일 체크
    "periodic_investment": 0,
    "rolling_window": None,
    "market": "KRX",
    "top_n": 10,
    "turtle_params": {
        "entry_days": 20,
        "exit_days": 10,
        "risk_factor": 0.01  # 계좌의 1% 리스크
    }
}

print("백테스트 시작: top10_turtle (KRX)")
try:
    results = backtest_engine.run_backtest(params)
    
    print("\n--- 백테스트 결과 요약 ---")
    print(f"최종 포트폴리오 가치: {results['summary']['final_portfolio_value']:,.0f}원")
    print(f"수익률: {results['summary']['final_roi']*100:.2f}%")
    
    mdd_data = results['summary']['mdd']
    if mdd_data:
        print(f"MDD: {mdd_data['percentage']*100:.2f}% (기간: {mdd_data['peak_date']} ~ {mdd_data['trough_date']})")
    
    print("\n--- 주요 거래 로그 (종목 교체 확인) ---")
    # 종목 교체나 손절 등의 주요 로그만 필터링하여 출력
    important_logs = [log for log in results['logs'] if log.get('action') in ['SELL_ALL', 'INITIAL_BUY', 'BUY', 'SELL_ADJUST']]
    
    for log in important_logs:
        action = log['action']
        ticker = log.get('ticker', '')
        date = log['date']
        shares = log.get('shares', 0)
        price = log.get('price', 0)
        
        if action == 'SELL_ALL':
            print(f"[{date}] [종목교체/전량매도] {ticker}: {shares}주 @ {price:,.0f}원")
        elif action in ['INITIAL_BUY', 'BUY']:
            print(f"[{date}] [매수] {ticker}: {shares}주 @ {price:,.0f}원")

    # 상위 10위권 이탈로 인한 매도가 있었는지 별도 확인
    sell_all_logs = [log for log in results['logs'] if log.get('action') == 'SELL_ALL']
    if sell_all_logs:
        print(f"\n상위권 이탈로 인한 전량 매도 발생 횟수: {len(sell_all_logs)}회")
        print("최근 매도 예시:", sell_all_logs[-1])
    else:
        print("\n백테스트 기간 동안 상위권 이탈로 인한 전량 매도가 발생하지 않았거나 조건이 충족되지 않았습니다.")

except Exception as e:
    print(f"오류 발생: {e}")
    import traceback
    traceback.print_exc()
