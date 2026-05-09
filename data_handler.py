# data_handler.py

import sqlite3
import sys
from datetime import datetime

import pandas as pd
from dateutil.relativedelta import relativedelta


def load_data(db_path, tickers, start_date_str, history_months=13):
    """DB에서 데이터를 로드하고, 지표 계산을 위해 충분한 과거 데이터를 포함합니다."""
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        load_start_date = start_date - relativedelta(months=history_months)

        with sqlite3.connect(db_path) as con:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            placeholders = ", ".join("?" for _ in tickers)
            query = f"SELECT Date, Symbol, High, Low, Close FROM stock_prices WHERE Symbol IN ({placeholders}) AND Date >= ? ORDER BY Date"
            df = pd.read_sql_query(
                query,
                con,
                params=list(tickers) + [load_start_date.strftime("%Y-%m-%d")],
            )
            df.rename(
                columns={
                    "Date": "date",
                    "Symbol": "ticker",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                },
                inplace=True,
            )
            df["date"] = pd.to_datetime(df["date"])

            # 각 지표별로 피벗팅
            high_df = df.pivot(index="date", columns="ticker", values="high").ffill()
            low_df = df.pivot(index="date", columns="ticker", values="low").ffill()
            close_df = df.pivot(index="date", columns="ticker", values="close").ffill()

            return {"high": high_df, "low": low_df, "close": close_df}
    except Exception as e:
        raise ValueError(f"데이터 로딩 중 오류 발생: {e}")


def prepare_strategy_data(stock_data):
    """전략에 필요한 모든 지표(모멘텀, 이동평균선, ATR, 돈치안 채널 등)를 미리 계산합니다."""
    print("전략 데이터 사전 계산 중 (모멘텀, ATR, 돈치안 채널 등)...")

    close_df = stock_data["close"]
    high_df = stock_data["high"]
    low_df = stock_data["low"]

    # 기존 모멘텀 데이터 계산 (HAA, DAA용)
    monthly_prices = close_df.resample("ME").last()
    momentum_data = {}
    for period in [1, 3, 6, 12]:
        momentum_data[f"roc_{period}"] = (
            monthly_prices / monthly_prices.shift(period) - 1
        )
    momentum_data["daa_momentum"] = (
        12 * momentum_data["roc_1"]
        + 4 * momentum_data["roc_3"]
        + 2 * momentum_data["roc_6"]
        + 1 * momentum_data["roc_12"]
    )
    momentum_data["sma_12_month"] = monthly_prices.rolling(window=12).mean()

    # 터틀 전략용 데이터 계산
    turtle_data = {}

    # ATR (N) 계산: 20일 기준
    tr1 = high_df - low_df
    tr2 = (high_df - close_df.shift(1)).abs()
    tr3 = (low_df - close_df.shift(1)).abs()
    tr = pd.DataFrame(index=close_df.index, columns=close_df.columns)
    for ticker in close_df.columns:
        tr[ticker] = pd.concat([tr1[ticker], tr2[ticker], tr3[ticker]], axis=1).max(
            axis=1
        )

    turtle_data["atr_20"] = tr.rolling(window=20).mean()

    # [수정] 다양한 윈도우에 대해 돈치안 채널 계산
    windows = [80, 55, 40, 25, 20, 10]
    for w in windows:
        turtle_data[f"high_{w}"] = high_df.shift(1).rolling(window=w).max()
        turtle_data[f"low_{w}"] = low_df.shift(1).rolling(window=w).min()

    daily_data = {}
    if "SPY" in close_df.columns:
        daily_data["sma_200_day"] = close_df["SPY"].rolling(window=200).mean()

    return monthly_prices, momentum_data, daily_data, turtle_data


def load_dividends_data(db_path, tickers):
    """[신규] DB에서 지정된 티커들의 배당 정보를 불러옵니다."""
    print("배당 정보 로딩 중...")
    dividends_by_ticker = {}
    try:
        with sqlite3.connect(db_path) as con:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            placeholders = ", ".join("?" for _ in tickers)
            query = f"SELECT Symbol, Date, Dividend FROM stock_dividends WHERE Symbol IN ({placeholders}) ORDER BY Date"
            df = pd.read_sql_query(query, con, params=list(tickers))

            if df.empty:
                print("경고: DB에서 배당 정보를 찾을 수 없습니다.")
                return {}

            df["Date"] = pd.to_datetime(df["Date"])

            # 각 티커별로 데이터를 그룹화하여 딕셔너리에 저장
            for symbol, group in df.groupby("Symbol"):
                # 날짜를 인덱스로, 배당금을 값으로 하는 Series 생성
                dividends_by_ticker[symbol] = group.set_index("Date")["Dividend"]

            print("배당 정보 로딩 완료.")
            return dividends_by_ticker

    except Exception as e:
        print(f"배당 정보 로딩 중 오류 발생: {e}", file=sys.stderr)
        return {}


def get_top_n_tickers_in_period(
    db_path, start_date, end_date, market="KRX", n=10
):
    """지정된 기간 동안 한 번이라도 시가총액 상위 N위에 들었던 모든 티커의 집합을 반환합니다."""
    table_map = {
        "KRX": "krx_market_cap",
        "NASDAQ": "nasdaq_market_cap",
        "NYSE": "nyse_market_cap",
        "AMEX": "amex_market_cap",
    }
    table_name = table_map.get(market.upper(), "krx_market_cap")

    try:
        with sqlite3.connect(db_path) as con:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            query = f"""
                SELECT DISTINCT Symbol 
                FROM (
                    SELECT Symbol, RANK() OVER (PARTITION BY Date ORDER BY MarketCap DESC) as rank
                    FROM {table_name}
                    WHERE Date BETWEEN ? AND ?
                )
                WHERE rank <= ?
            """
            df = pd.read_sql_query(query, con, params=[start_date, end_date, n])
            return set(df["Symbol"].tolist())
    except Exception as e:
        print(f"기간 내 상위 종목 추출 중 오류 발생: {e}", file=sys.stderr)
        return set()


def get_top_n_tickers_at_date(db_path, date, market="KRX", n=10):
    """특정 날짜 기준 시가총액 상위 N개 종목의 티커 리스트를 반환합니다."""
    table_map = {
        "KRX": "krx_market_cap",
        "NASDAQ": "nasdaq_market_cap",
        "NYSE": "nyse_market_cap",
        "AMEX": "amex_market_cap",
    }
    table_name = table_map.get(market.upper(), "krx_market_cap")

    try:
        with sqlite3.connect(db_path) as con:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            # 지정된 날짜와 가장 가까운 이전 날짜를 찾음
            query = f"SELECT Date FROM {table_name} WHERE Date <= ? ORDER BY Date DESC LIMIT 1"
            df_date = pd.read_sql_query(query, con, params=[date])
            if df_date.empty:
                # 데이터가 없으면 가장 이른 날짜 사용
                query = f"SELECT Date FROM {table_name} ORDER BY Date ASC LIMIT 1"
                df_date = pd.read_sql_query(query, con)

            target_date = df_date.iloc[0]["Date"] if not df_date.empty else None

            if not target_date:
                return []

            query = f"SELECT Symbol FROM {table_name} WHERE Date = ? ORDER BY MarketCap DESC LIMIT ?"
            df = pd.read_sql_query(query, con, params=[target_date, n])
            return df["Symbol"].tolist()
    except Exception as e:
        print(f"특정 시점 상위 종목 조회 중 오류 발생: {e}", file=sys.stderr)
        return []


def get_ticker_names(db_path, tickers):
    """DB의 여러 테이블에서 티커 리스트에 해당하는 종목명을 조회하여 딕셔너리로 반환합니다."""
    ticker_name_map = {}
    if not tickers:
        return ticker_name_map

    tables = ["KRX", "NASDAQ", "NYSE", "ETF_KR", "ETF_US"]
    try:
        with sqlite3.connect(db_path) as con:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            placeholders = ", ".join("?" for _ in tickers)
            for table in tables:
                try:
                    query = f'SELECT Symbol, Name FROM "{table}" WHERE Symbol IN ({placeholders})'
                    df = pd.read_sql_query(query, con, params=list(tickers))
                    for _, row in df.iterrows():
                        ticker_name_map[row["Symbol"]] = row["Name"]
                except sqlite3.OperationalError:
                    continue
        return ticker_name_map
    except Exception as e:
        print(f"종목명 조회 중 오류 발생: {e}", file=sys.stderr)
        return ticker_name_map
