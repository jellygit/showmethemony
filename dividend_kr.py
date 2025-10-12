#!/usr/bin/env python
import sqlite3
import pandas as pd
from typing import List, Tuple
# tqdm 라이브러리 추가
from tqdm import tqdm

# --- 설정 (Configuration) ---
ODS_FILE_PATH: str = "주식 배당.ods"
DB_FILE_PATH: str = "stock_price.db"
TABLE_NAME: str = "stock_dividends"


def create_dividends_table(db_path: str) -> None:
    """
    stock_dividends 테이블을 생성합니다. (테이블이 없는 경우에만)

    Args:
        db_path: SQLite 데이터베이스 파일 경로.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            Symbol TEXT,
            Date TEXT,
            Dividend REAL,
            PRIMARY KEY (Symbol, Date)
        );
        """
        cursor.execute(create_table_query)
        print(f"'{TABLE_NAME}' 테이블이 준비되었습니다.")


def load_and_clean_dividend_data(ods_path: str) -> pd.DataFrame:
    """
    ODS 파일에서 배당금 데이터를 불러오고 정제합니다.

    YYYYMMDD 형식의 날짜를 정확히 파싱하고, 배당금이 0인 데이터는 제외합니다.

    Args:
        ods_path: ODS 스프레드시트 파일 경로.

    Returns:
        정제된 배당금 데이터가 담긴 pandas DataFrame.
    """
    try:
        # PEP 8: 변수명 snake_case, 타입 힌트 사용
        df: pd.DataFrame = pd.read_excel(ods_path, engine="odf")
    except FileNotFoundError:
        print(f"오류: ODS 파일 '{ods_path}'을(를) 찾을 수 없습니다.")
        return pd.DataFrame()
    except Exception as e:
        print(f"오류: ODS 파일을 읽는 중 문제가 발생했습니다: {e}")
        return pd.DataFrame()

    column_mapping = {
        "배정기준일": "Date",
        "종목코드": "Symbol",
        "주당배당금": "Dividend",
    }
    required_cols = list(column_mapping.keys())
    if not all(col in df.columns for col in required_cols):
        print(f"오류: ODS 파일에 필요한 컬럼({required_cols})이 없습니다.")
        return pd.DataFrame()

    df = df[required_cols].rename(columns=column_mapping)
    df.dropna(subset=["Date", "Symbol", "Dividend"], inplace=True)
    df = df[df["Dividend"] != "-"]

    # 날짜 형식 변환 및 표준화: YYYYMMDD -> YYYY-M-D
    df["Date"] = pd.to_datetime(
        df["Date"], format="%Y%m%d", errors="coerce"
    ).dt.strftime("%Y-%-m-%-d")

    # 종목 코드 6자리 zero-padding 처리
    df["Symbol"] = df["Symbol"].astype(str).str.zfill(6)
    # 숫자형 변환 (오류 발생 시 NaN)
    df["Dividend"] = pd.to_numeric(df["Dividend"], errors="coerce")
    
    # Dividend 값이 0이 아닌 행만 선택하여 필터링합니다. (명시적 필터링)
    df = df[df["Dividend"] != 0]

    df.dropna(inplace=True)

    return df


def insert_dividends_into_db(db_path: str, dividend_df: pd.DataFrame) -> None:
    """
    정제된 배당금 데이터를 SQLite 데이터베이스에 삽입합니다.
    데이터 준비 과정에 tqdm을 적용하여 진행률을 표시합니다.

    Args:
        db_path: SQLite 데이터베이스 파일 경로.
        dividend_df: 삽입할 배당금 데이터가 담긴 DataFrame.
    """
    # PEP 20: 명시적으로 어떤 작업을 하는지 tqdm 설명을 추가
    print("데이터베이스 삽입을 위한 데이터 준비 중...")
    
    # 데이터프레임을 순회하며 SQLite 삽입용 튜플 리스트를 생성합니다.
    # tqdm으로 iterrows()를 감싸 진행률을 표시합니다.
    insert_data: List[Tuple[str, str, float]] = [
        (row["Symbol"], row["Date"], row["Dividend"])
        for _, row in tqdm(
            dividend_df.iterrows(), 
            total=len(dividend_df), 
            desc="데이터 준비", 
            unit="건"
        )
    ]

    if not insert_data:
        print("입력할 유효한 배당금 데이터가 없습니다.")
        return

    # executemany를 사용한 벌크 삽입으로 I/O 오버헤드를 최소화합니다. (성능 최적화)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        insert_query = (
            f"INSERT OR IGNORE INTO {TABLE_NAME} (Symbol, Date, Dividend) "
            f"VALUES (?, ?, ?)"
        )
        # INSERT OR IGNORE 전략을 사용하여 PRIMARY KEY 중복 문제를 방지합니다.
        cursor.executemany(insert_query, insert_data)
        conn.commit()
        
        # 실제 반영된 rowcount를 확인 (SQLite는 total_changes 사용 가능)
        changes = (
            conn.total_changes if hasattr(conn, "total_changes") else cursor.rowcount
        )
        print(
            f"\n총 {len(insert_data)} 건의 데이터를 처리하여 {changes} 건의 신규 배당금 정보를 입력했습니다."
        )


def main() -> None:
    """
    메인 실행 함수: 테이블 생성, 데이터 로딩, DB 입력을 순차적으로 수행합니다.
    """
    # PEP 484: 반환 값에 대한 타입 힌트 명시
    create_dividends_table(DB_FILE_PATH)
    print(f"'{ODS_FILE_PATH}' 파일에서 배당금 데이터를 불러옵니다...")
    clean_data: pd.DataFrame = load_and_clean_dividend_data(ODS_FILE_PATH)

    if not clean_data.empty:
        print(f"정제된 배당금 데이터 {len(clean_data)}건을 확인했습니다.")
        print(f"'{DB_FILE_PATH}' 데이터베이스에 데이터 입력을 시작합니다...")
        insert_dividends_into_db(DB_FILE_PATH, clean_data)
    else:
        print("처리할 유효한 데이터를 찾지 못했습니다.")

    print("--- 배당금 데이터 입력 작업이 완료되었습니다. ---")


if __name__ == "__main__":
    main()

