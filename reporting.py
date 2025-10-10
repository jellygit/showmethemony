# reporting.py
import pandas as pd
import numpy as np

def calculate_mdd(numeric_df):
    """포트폴리오의 최대 낙폭(MDD)을 계산하여 딕셔셔리로 반환합니다."""
    portfolio_values = numeric_df['Portfolio Value']
    running_peak = portfolio_values.cummax()
    drawdown = (portfolio_values - running_peak) / running_peak
    mdd = drawdown.min()
    trough_date = drawdown.idxmin()
    peak_date = running_peak.loc[:trough_date][running_peak.loc[:trough_date] == running_peak.loc[trough_date]].index[0]
    
    return {
        "percentage": mdd,
        "peak_date": peak_date.strftime('%Y-%m-%d'),
        "trough_date": trough_date.strftime('%Y-%m-%d'),
        "peak_value": portfolio_values.loc[peak_date],
        "trough_value": portfolio_values.loc[trough_date]
    }

def calculate_rolling_returns(numeric_df, window_years, step_freq):
    """롤링 리턴을 계산하여 딕셔너리로 반환합니다."""
    portfolio_values = numeric_df['Portfolio Value']
    freq_map = {'Y': 'YE', 'A': 'YE', 'Q': 'QE', 'M': 'ME'}
    base_freq = ''.join(filter(str.isalpha, step_freq))
    if base_freq in freq_map:
        step_freq = step_freq.replace(base_freq, freq_map[base_freq])

    start_dates = portfolio_values.resample(step_freq).first().index
    
    periods = []
    cagrs = []
    for start_date in start_dates:
        end_date = start_date + pd.DateOffset(years=window_years)
        try:
            actual_start_date = portfolio_values.index[portfolio_values.index.searchsorted(start_date, side='left')]
            if end_date > portfolio_values.index[-1]: continue
            actual_end_date = portfolio_values.index[portfolio_values.index.searchsorted(end_date, side='left')]
            start_value, end_value = portfolio_values.loc[actual_start_date], portfolio_values.loc[actual_end_date]
            years = (actual_end_date - actual_start_date).days / 365.25
            if start_value > 0 and years > 0:
                cagr = (end_value / start_value) ** (1 / years) - 1
                cagrs.append(cagr)
                periods.append({
                    "start": actual_start_date.strftime('%Y-%m-%d'),
                    "end": actual_end_date.strftime('%Y-%m-%d'),
                    "cagr": cagr
                })
        except IndexError:
            continue

    if not cagrs:
        return None

    return {
        "average_cagr": np.mean(cagrs),
        "min_cagr": np.min(cagrs),
        "max_cagr": np.max(cagrs),
        "stdev_cagr": np.std(cagrs),
        "periods": periods
    }
