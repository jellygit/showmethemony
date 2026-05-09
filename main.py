# main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import sqlite3
import backtest_engine
import asyncio
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager

# --- [Step 2] 비동기 프로세스 풀 설정 ---
# 32코어 장비임을 고려하여, 메모리 집약적인 백테스트 특성에 따라 8개 프로세스 할당
executor = ProcessPoolExecutor(max_workers=8)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시 실행
    yield
    # 서버 종료 시 프로세스 풀 안전하게 정리
    executor.shutdown()

async def run_backtest_async(params_dict):
    """CPU 집약적인 백테스트 연산을 프로세스 풀에서 실행"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, backtest_engine.run_backtest, params_dict)

# --- API 요청 파라미터를 위한 Pydantic 모델 정의 ---
class BacktestParams(BaseModel):
    capital: float = Field(..., example=10000, description="초기 투자금")
    start_date: str = Field(..., example="2020-01-01", description="시뮬레이션 시작일 (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, example="2023-12-31", description="시뮬레이션 종료일")
    db_path: str = Field("stock_price.db", description="DB 파일 경로")
    strategy: str = Field("default", example="laa", description="투자 전략 (default, haa, daa, laa)")
    interval: str = Field("1M", example="3M", description="리밸런싱 주기")
    periodic_investment: float = Field(0.0, example=1000, description="주기별 추가 투자금")
    no_rebalance: bool = Field(False, description="[기본 전략용] 리밸런싱 없이 추가 매수만 진행")
    no_drip: bool = Field(False, description="배당금 재투자 하지 않음, 출금하여 사용했다고 가정")
    stocks: Optional[List[str]] = Field(None, example=["SPY", "0.6", "AGG", "0.4"], description="[기본 전략용] 티커와 비중 목록")
    rolling_window: Optional[int] = Field(None, example=3, description="롤링 리턴 기간 (단위: 연)")
    rolling_step: str = Field("1Y", example="1Q", description="롤링 리턴 계산 빈도")

app = FastAPI(lifespan=lifespan)

# --- CORS 설정 ---
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Portfolio Backtest API"}

@app.post("/backtest")
async def run_backtest_endpoint(params: BacktestParams):
    """
    [Step 2] 백테스트 시뮬레이션을 비동기 프로세스 풀에서 실행합니다.
    """
    try:
        params_dict = params.dict()
        # 프로세스 풀에서 연산 수행 (API 서버는 차단되지 않음)
        results = await run_backtest_async(params_dict)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search-symbols")
def search_symbols(
    db_path: str = "stock_price.db", 
    q: str = Query(..., min_length=1, description="검색할 종목명 또는 심볼 (부분 일치)")
):
    """
    지정된 DB의 여러 테이블에서 종목명(Name)과 심볼(Symbol)을 검색하여 반환합니다.
    """
    tables_to_search = ['KRX', 'NYSE', 'NASDAQ', 'ETF_US', 'ETF_KR'] 
    all_results = []
    
    try:
        with sqlite3.connect(db_path) as con:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            cursor = con.cursor()
            for table in tables_to_search:
                try:
                    query_sql = f'SELECT Symbol, Name FROM "{table}" WHERE LOWER(Name) LIKE ? OR LOWER(Symbol) LIKE ?'
                    search_term = f"%{q.lower()}%"
                    cursor.execute(query_sql, (search_term, search_term))
                    results = cursor.fetchall()
                    for row in results:
                        all_results.append({"Symbol": row[0], "Name": row[1]})
                except sqlite3.OperationalError:
                    continue
                    
        unique_results = [dict(t) for t in {tuple(d.items()) for d in all_results}]
        return sorted(unique_results, key=lambda x: x['Name'])

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 검색 중 오류 발생: {str(e)}")
