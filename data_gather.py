#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
주식 종목, 시세, 배당 데이터 초기화 스크립트 (tqdm 진행률 표시 복원)
"""

import argparse
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import FinanceDataReader as fdr
import pandas as pd
import yfinance as yf

# [추가] tqdm 라이브러리 임포트
from tqdm import tqdm

DB_PATH = "./stock_price.db"
MAX_WORKERS = 10


def init_db(db_path):
    """데이터베이스와 테이블 스키마를 생성합니다."""
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        # [Step 1] SQLite 성능 최적화 설정
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock_prices (
                Symbol TEXT, Date TEXT, Open REAL, High REAL, Low REAL, Close REAL,
                Volume INTEGER, Change REAL, PRIMARY KEY (Symbol, Date)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock_dividends (
                Symbol TEXT, Date TEXT, Dividend REAL, PRIMARY KEY (Symbol, Date)
            )
        """)
        # 시가총액 테이블 생성 (시장별)
        markets = ["KRX", "NASDAQ", "NYSE", "AMEX"]
        for market in markets:
            table_name = f"{market.lower()}_market_cap"
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    Date TEXT,
                    Symbol TEXT,
                    Name TEXT,
                    MarketCap INTEGER,
                    Stocks INTEGER,
                    PRIMARY KEY (Date, Symbol)
                )
            """)
        con.commit()


def sanitize_table_name(name):
    """테이블 이름에 사용할 수 없는 문자를 '_'로 변경합니다."""
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def update_symbols(market, db_path):
    """지정된 거래소의 종목 목록을 받아와 덮어씁니다."""
    print(f"[{market}] 전체 종목 목록을 업데이트합니다...")
    try:
        df = fdr.StockListing(market)
        if "Code" in df.columns and "Symbol" not in df.columns:
            df.rename(columns={"Code": "Symbol"}, inplace=True)
        if "Market" not in df.columns:
            df["Market"] = market

        table_name = sanitize_table_name(market)
        with sqlite3.connect(db_path) as con:
            df[["Symbol", "Name", "Market"]].to_sql(
                table_name, con, if_exists="replace", index=False
            )
            print(
                f"[{market}] 종목 목록을 '{table_name}' 테이블에 덮어쓰기 완료 ({len(df):,}개 종목)."
            )
    except Exception as e:
        print(f"[{market}] 종목 목록 업데이트 중 오류 발생: {e}", file=sys.stderr)


def fetch_price_data(symbol_info, start_date):
    """단일 종목의 시세 데이터를 가져옵니다."""
    original_symbol = symbol_info["Symbol"]
    query_symbol = original_symbol.replace(".", "-")
    try:
        price_df = fdr.DataReader(query_symbol, start_date)
        if not price_df.empty:
            price_df["Symbol"] = original_symbol
            return price_df
    except Exception:
        pass
    return None


def update_prices(market, db_path, start_year, delay=0):
    """멀티스레딩으로 종목별 시세 데이터를 업데이트합니다."""
    print(f"[{market}] 시세 데이터 업데이트 시작 (시작 연도: {start_year})...")
    table_name = sanitize_table_name(market)
    try:
        with sqlite3.connect(db_path) as con:
            symbols = pd.read_sql_query(
                f'SELECT Symbol, Name FROM "{table_name}"', con
            ).to_dict("records")
    except Exception as e:
        print(
            f"[{market}] '{table_name}' 테이블에서 종목 목록을 불러오는 중 오류: {e}",
            file=sys.stderr,
        )
        return

    start_date = f"{start_year}-01-01"
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for s in symbols:
            futures[executor.submit(fetch_price_data, s, start_date)] = s
            if delay > 0:
                time.sleep(delay)

        # [수정] tqdm을 사용하여 진행률 표시
        for future in tqdm(
            as_completed(futures), total=len(symbols), desc=f"시세 수집 ({market})"
        ):
            price_df = future.result()
            if price_df is not None:
                try:
                    with sqlite3.connect(DB_PATH) as conn_thread:
                        price_df.reset_index(inplace=True)
                        if (
                            "Date" not in price_df.columns
                            and "index" in price_df.columns
                        ):
                            price_df.rename(columns={"index": "Date"}, inplace=True)
                        if "Change" not in price_df.columns:
                            price_df["Change"] = (
                                price_df["Close"].pct_change().fillna(0)
                            )

                        required_cols = [
                            "Symbol",
                            "Date",
                            "Open",
                            "High",
                            "Low",
                            "Close",
                            "Volume",
                            "Change",
                        ]
                        for col in required_cols:
                            if col not in price_df.columns:
                                price_df[col] = 0

                        price_df = price_df[required_cols].copy()
                        price_df["Date"] = price_df["Date"].dt.strftime("%Y-%m-%d")

                        # 중복 방지를 위해 INSERT OR IGNORE 처리 (IntegrityError 대신 명시적 처리)
                        for _, row in price_df.iterrows():
                            try:
                                conn_thread.execute(
                                    "INSERT OR IGNORE INTO stock_prices (Symbol, Date, Open, High, Low, Close, Volume, Change) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                    (
                                        row["Symbol"],
                                        row["Date"],
                                        row["Open"],
                                        row["High"],
                                        row["Low"],
                                        row["Close"],
                                        row["Volume"],
                                        row["Change"],
                                    ),
                                )
                            except Exception:
                                pass
                except sqlite3.IntegrityError:
                    continue
                except Exception as e:
                    symbol_info = futures[future]
                    tqdm.write(
                        f"\n- {symbol_info['Name']}({symbol_info['Symbol']}) DB 저장 실패: {e}",
                        file=sys.stderr,
                    )
    print(f"[{market}] 시세 데이터 업데이트 완료.")


def fetch_dividend_data(symbol_info):
    """단일 종목의 배당 데이터를 yfinance로 가져옵니다."""
    original_symbol = symbol_info["Symbol"]
    
    # 한국 종목(6자리 숫자)인 경우 .KS 접미사 추가
    if original_symbol.isdigit() and len(original_symbol) == 6:
        query_symbol = f"{original_symbol}.KS"
    else:
        query_symbol = original_symbol.replace(".", "-")

    try:
        ticker = yf.Ticker(query_symbol)
        dividends = ticker.dividends
        if not dividends.empty:
            df = dividends.reset_index()
            df.columns = ["Date", "Dividend"]
            df["Symbol"] = original_symbol
            return df
    except Exception:
        pass
    return None


def update_dividends(market, db_path, delay=0):
    """멀티스레딩으로 종목별 배당 데이터를 업데이트합니다."""
    print(f"[{market}] 배당 데이터 업데이트 시작...")
    table_name = sanitize_table_name(market)
    try:
        with sqlite3.connect(db_path) as con:
            symbols = pd.read_sql_query(
                f'SELECT Symbol, Name FROM "{table_name}"', con
            ).to_dict("records")
    except Exception as e:
        print(
            f"[{market}] '{table_name}' 테이블에서 종목 목록을 불러오는 중 오류: {e}",
            file=sys.stderr,
        )
        return

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for s in symbols:
            futures[executor.submit(fetch_dividend_data, s)] = s
            if delay > 0:
                time.sleep(delay)

        # [수정] tqdm을 사용하여 진행률 표시
        for future in tqdm(
            as_completed(futures), total=len(symbols), desc=f"배당 수집 ({market})"
        ):
            dividend_df = future.result()
            if dividend_df is not None:
                try:
                    with sqlite3.connect(DB_PATH) as conn_thread:
                        dividend_df["Date"] = dividend_df["Date"].dt.strftime(
                            "%Y-%m-%d"
                        )
                        cur = conn_thread.cursor()
                        for _, row in dividend_df.iterrows():
                            cur.execute(
                                "INSERT OR IGNORE INTO stock_dividends (Symbol, Date, Dividend) VALUES (?, ?, ?)",
                                (row["Symbol"], row["Date"], row["Dividend"]),
                            )
                        conn_thread.commit()
                except sqlite3.IntegrityError:
                    continue
                except Exception as e:
                    symbol_info = futures[future]
                    tqdm.write(
                        f"\n- {symbol_info['Name']}({symbol_info['Symbol']}) 배당 DB 저장 실패: {e}",
                        file=sys.stderr,
                    )
    print(f"[{market}] 배당 데이터 업데이트 완료.")


def fetch_us_marcap_single(symbol_info):
    """미국 종목의 현재 시가총액과 주식 수를 yfinance로 가져옵니다."""
    symbol = symbol_info["Symbol"]
    name = symbol_info["Name"]
    query_symbol = symbol.replace(".", "-")
    try:
        ticker = yf.Ticker(query_symbol)
        info = ticker.info
        marcap = info.get("marketCap")
        stocks = info.get("sharesOutstanding")
        if marcap and stocks:
            return {
                "Symbol": symbol,
                "Name": name,
                "MarketCap": marcap,
                "Stocks": stocks,
            }
    except Exception:
        pass
    return None


def update_market_caps(market, db_path, start_date_str, end_date_str=None, delay=0):
    """지정된 날짜 범위의 시가총액 데이터를 업데이트합니다."""
    print(
        f"[{market}] 시가총액 데이터 업데이트 시작 ({start_date_str} ~ {end_date_str if end_date_str else start_date_str})..."
    )
    table_name = f"{market.lower()}_market_cap"

    try:
        start_date = pd.to_datetime(start_date_str)
        if end_date_str:
            end_date = pd.to_datetime(end_date_str)
        else:
            end_date = start_date

        date_range = pd.date_range(start_date, end_date, freq="B")  # 영업일 기준

        if market == "KRX":
            for current_date in tqdm(date_range, desc=f"시가총액 수집 ({market})"):
                date_query = current_date.strftime("%Y%m%d")
                date_db = current_date.strftime("%Y-%m-%d")

                try:
                    df = fdr.StockListing("KRX", start=date_query, end=date_query)
                    if df is None or df.empty:
                        continue

                    col_map = {
                        "Code": "Symbol",
                        "Symbol": "Symbol",
                        "Name": "Name",
                        "Marcap": "MarketCap",
                        "MarketCap": "MarketCap",
                        "Stocks": "Stocks",
                    }
                    available_cols = {
                        old: new for old, new in col_map.items() if old in df.columns
                    }
                    df_to_save = df[list(available_cols.keys())].copy()
                    df_to_save.rename(columns=available_cols, inplace=True)
                    df_to_save["Date"] = date_db

                    with sqlite3.connect(db_path) as conn:
                        data_list = df_to_save[
                            ["Date", "Symbol", "Name", "MarketCap", "Stocks"]
                        ].values.tolist()
                        conn.executemany(
                            f"INSERT OR REPLACE INTO {table_name} (Date, Symbol, Name, MarketCap, Stocks) VALUES (?, ?, ?, ?, ?)",
                            data_list,
                        )
                        conn.commit()
                    time.sleep(delay if delay > 0 else 0.5)
                except Exception as e:
                    tqdm.write(f"[{date_db}] 수집 중 오류 발생: {e}")
        else:
            # 미국 시장 (NASDAQ, NYSE, AMEX)
            # 1. 종목 리스트 가져오기
            sym_table = sanitize_table_name(market)
            try:
                with sqlite3.connect(db_path) as con:
                    symbols = pd.read_sql_query(
                        f'SELECT Symbol, Name FROM "{sym_table}"', con
                    ).to_dict("records")
            except Exception:
                # 테이블이 없으면 fdr에서 직접 가져오기
                df_sym = fdr.StockListing(market)
                if "Code" in df_sym.columns:
                    df_sym.rename(columns={"Code": "Symbol"}, inplace=True)
                symbols = df_sym[["Symbol", "Name"]].to_dict("records")

            # 2. 현재 시가총액 및 주식 수 수집 (멀티스레딩)
            print(f"[{market}] 현재 시가총액 정보 수집 중...")
            marcap_map = {}
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(fetch_us_marcap_single, s): s for s in symbols
                }
                for future in tqdm(
                    as_completed(futures),
                    total=len(symbols),
                    desc=f"Marcap 정보 ({market})",
                ):
                    res = future.result()
                    if res:
                        marcap_map[res["Symbol"]] = res
                    if delay > 0:
                        time.sleep(delay)

            # 3. 날짜별 데이터 저장
            # 미국 시장은 과거 시가총액을 한 번에 가져오기 어렵기 때문에, 
            # DB에 저장된 과거 주가(Close)와 현재 주식 수(Stocks)를 곱하여 추정합니다.
            with sqlite3.connect(db_path) as conn:
                for current_date in tqdm(date_range, desc=f"DB 저장 ({market})"):
                    date_db = current_date.strftime("%Y-%m-%d")
                    
                    # 해당 날짜의 주가 정보를 DB에서 가져옴
                    try:
                        price_df = pd.read_sql_query(
                            f"SELECT Symbol, Close FROM stock_prices WHERE Date = '{date_db}'", conn
                        )
                        price_map = dict(zip(price_df['Symbol'], price_df['Close']))
                    except Exception:
                        price_map = {}

                    data_to_insert = []
                    for sym, info in marcap_map.items():
                        # DB에 주가가 있으면 계산, 없으면 현재 수집된 시가총액 사용
                        price = price_map.get(sym)
                        if price and price > 0:
                            # 주가 * 주식수로 시가총액 추정
                            calculated_marcap = int(price * info["Stocks"])
                        else:
                            calculated_marcap = info["MarketCap"]

                        data_to_insert.append(
                            (
                                date_db,
                                sym,
                                info["Name"],
                                calculated_marcap,
                                info["Stocks"],
                            )
                        )

                    if data_to_insert:
                        conn.executemany(
                            f"INSERT OR REPLACE INTO {table_name} (Date, Symbol, Name, MarketCap, Stocks) VALUES (?, ?, ?, ?, ?)",
                            data_to_insert,
                        )
                conn.commit()

    except Exception as e:
        print(f"[{market}] 시가총액 업데이트 중 오류 발생: {e}", file=sys.stderr)


def main():
    """메인 실행 함수"""
    parser = argparse.ArgumentParser(
        description="주식 종목, 시세, 배당 데이터를 업데이트합니다."
    )
    parser.add_argument(
        "markets", nargs="*", help="처리할 거래소 목록 (예: KRX NASDAQ)"
    )
    parser.add_argument(
        "--update-symbols", action="store_true", help="종목 목록을 덮어씁니다."
    )
    parser.add_argument(
        "--update-prices", action="store_true", help="시세 데이터를 추가합니다."
    )
    parser.add_argument(
        "--update-dividends", action="store_true", help="배당 데이터를 추가합니다."
    )
    parser.add_argument(
        "--update-marcap",
        action="store_true",
        help="시가총액 데이터를 업데이트합니다.",
    )
    parser.add_argument(
        "--start-year", type=int, default=2000, help="시세 데이터를 받아올 시작 연도"
    )
    parser.add_argument(
        "--marcap-date",
        type=str,
        help="시가총액 수집 날짜 (YYYY-MM-DD 또는 YYYY-MM-DD:YYYY-MM-DD)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="요청 간 지연 시간 (초, 예: 0.1은 약 10it/s)",
    )
    args = parser.parse_args()

    if not any(
        [
            args.update_symbols,
            args.update_prices,
            args.update_dividends,
            args.update_marcap,
        ]
    ):
        parser.print_help()
        sys.exit(
            "\n오류: --update-symbols, --update-prices, --update-dividends, --update-marcap 중 하나 이상의 작업을 선택해야 합니다."
        )

    init_db(DB_PATH)
    start_time = time.time()
    try:
        # 시장 목록이 비어있으면 기본값 설정
        target_markets = args.markets if args.markets else ["KRX"]

        # 시가총액 업데이트
        if args.update_marcap:
            if not args.marcap_date:
                args.marcap_date = datetime.now().strftime("%Y-%m-%d")

            s_date = args.marcap_date
            e_date = None
            if ":" in args.marcap_date:
                s_date, e_date = args.marcap_date.split(":")

            for market in target_markets:
                update_market_caps(market, DB_PATH, s_date, e_date, args.delay)

        # 일반 거래소 작업 (symbols, prices, dividends)
        for market in target_markets:
            if any([args.update_symbols, args.update_prices, args.update_dividends]):
                print(f"\n===== '{market}' 거래소 작업 시작 =====")
                if args.update_symbols:
                    update_symbols(market, DB_PATH)
                if args.update_prices:
                    update_prices(market, DB_PATH, args.start_year, args.delay)
                if args.update_dividends:
                    update_dividends(market, DB_PATH, args.delay)
                print(f"===== '{market}' 거래소 작업 완료 =====\n")

        end_time = time.time()
        print(f"총 소요 시간: {end_time - start_time:.2f}초")
    except KeyboardInterrupt:
        print("\n\n사용자 요청으로 프로그램을 중단합니다.")
        sys.exit(0)


if __name__ == "__main__":
    main()
