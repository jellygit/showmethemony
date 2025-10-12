# main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import sqlite3
import backtest_engine

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

app = FastAPI()

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
def run_backtest_endpoint(params: BacktestParams):
    """
    백테스트 시뮬레이션을 실행하고 결과를 JSON으로 반환합니다.
    """
    try:
        params_dict = params.dict()
        results = backtest_engine.run_backtest(params_dict)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search-symbols")
def search_symbols(
    db_path: str = "stock_price.db", 
    q: str = Query(..., min_length=1, description="검색할 종목명 또는 심볼 (부분 일치)")
):
    """
    [수정] 지정된 DB의 여러 테이블에서 종목명(Name)과 심볼(Symbol)을 검색하여 반환합니다.
    """
    tables_to_search = ['KRX', 'NYSE', 'NASDAQ', 'ETF_US', 'ETF_KR'] 
    all_results = []
    
    try:
        with sqlite3.connect(db_path) as con:
            cursor = con.cursor()
            for table in tables_to_search:
                try:
                    # [수정] WHERE 절에 'LOWER(Symbol) LIKE ?' 조건을 OR로 추가
                    query_sql = f'SELECT Symbol, Name FROM "{table}" WHERE LOWER(Name) LIKE ? OR LOWER(Symbol) LIKE ?'
                    
                    search_term = f"%{q.lower()}%"
                    
                    # [수정] 파라미터를 2개 전달
                    cursor.execute(query_sql, (search_term, search_term))
                    results = cursor.fetchall()
                    
                    for row in results:
                        all_results.append({"Symbol": row[0], "Name": row[1]})
                
                except sqlite3.OperationalError:
                    continue
                    
        unique_results = [dict(t) for t in {tuple(d.items()) for d in all_results}]
        
        # 이름순으로 정렬하여 반환
        return sorted(unique_results, key=lambda x: x['Name'])

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 검색 중 오류 발생: {str(e)}")
