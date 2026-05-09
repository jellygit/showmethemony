# main.py
import asyncio
import hashlib
import json
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from typing import List, Optional

import backtest_engine
import redis
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# --- [Step 4] Redis 설정 ---
# Arch Linux에 설치된 기본 Redis 연결 (6379 포트)
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

def generate_cache_key(params: dict) -> str:
    """요청 파라미터를 기반으로 고유한 MD5 해시 키 생성"""
    # 딕셔너리를 정렬된 JSON 문자열로 변환하여 동일 파라미터 보장
    param_str = json.dumps(params, sort_keys=True)
    return f"backtest:{hashlib.md5(param_str.encode()).hexdigest()}"

# --- [Step 2] 비동기 프로세스 풀 설정 ---
executor = ProcessPoolExecutor(max_workers=8)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시 Redis 연결 테스트 (선택 사항)
    try:
        redis_client.ping()
        print("Redis 연결 성공")
    except Exception as e:
        print(f"Redis 연결 실패 (캐싱 비활성화): {e}")
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
    strategy: str = Field("default", example="laa", description="투자 전략 (default, haa, daa, laa, turtle, top10_turtle)")
    interval: str = Field("1M", example="3M", description="리밸런싱 주기")
    periodic_investment: float = Field(0.0, example=1000, description="주기별 추가 투자금")
    no_rebalance: bool = Field(False, description="[기본 전략용] 리밸런싱 없이 추가 매수만 진행")
    no_drip: bool = Field(False, description="배당금 재투자 하지 않음")
    stocks: Optional[List[str]] = Field(None, example=["SPY", "0.6", "AGG", "0.4"], description="티커와 비중 목록")
    rolling_window: Optional[int] = Field(None, example=3, description="롤링 리턴 기간")
    rolling_step: str = Field("1Y", example="1Q", description="롤링 리턴 주기")
    market: str = Field("KRX", description="[top10_turtle용] 대상 시장")
    top_n: int = Field(10, description="[top10_turtle용] 상위 순위")
    turtle_params: Optional[dict] = Field(None, description="터틀 전략 파라미터")

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
    [Step 4] Redis 캐싱이 적용된 백테스트 엔드포인트
    """
    params_dict = params.dict()
    cache_key = generate_cache_key(params_dict)

    # 1. 캐시 확인
    try:
        cached_result = redis_client.get(cache_key)
        if cached_result:
            print(f"Cache Hit: {cache_key}")
            return json.loads(cached_result)
    except Exception as e:
        print(f"Redis 조회 오류: {e}")

    # 2. 캐시 없으면 연산 실행 (Step 2 프로세스 풀 활용)
    try:
        results = await run_backtest_async(params_dict)
        
        # 3. 결과 캐싱 (24시간 동안 유지)
        try:
            # numpy/datetime 객체가 포함될 수 있으므로 JSON 변환 시 주의 (engine에서 이미 처리됨 가정)
            # results가 dict이므로 json.dumps 사용
            redis_client.setex(cache_key, 86400, json.dumps(results, default=str))
        except Exception as e:
            print(f"Redis 저장 오류: {e}")
            
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
