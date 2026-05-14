from pydantic import BaseModel
from typing import Optional, Dict, Any


class LogSearchRequest(BaseModel):
    """ 로그 조회 요청
    - 모든 필드 Optional → 조건 없으면 전체 조회
    - start_time, end_time : ISO 8601 형식 ("2024-01-01T00:00:00")
    - size : 최대 조회 건수 (기본 100)
    """
    level: Optional[str] = None
    subject: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    keyword: Optional[str] = None
    size: Optional[int] = 100

class LogWriteRequest(BaseModel):
    """ 로그 기록 요청
    - subject : 로그 주제 --> logs_{subject} 인덱스에 저장
    - level   : 로그 레벨
    - message : 로그 메시지
    - extra   : 자유 필드 --> 단계별로 다른 데이터 저장 가능
                예) crawl: {"batch_id": "...", "crawl_cnt": 500}
                    ml:    {"doc_id": "...", "tend_score": 0.95}
    """
    subject: str
    level: str
    message: str
    extra: Optional[Dict[str, Any]] = {}  # default= empty DICT