from pydantic import BaseModel
from typing import Literal

class CorrectionRequest(BaseModel):
    """
    보정 확정 요청 모델
    - doc_id     : 보정할 기사 고유 ID
    - tendency   : 관리자가 확정한 성향
    - tend_score : 관리자가 확정한 성향 점수
    → analyze 인덱스 + search 인덱스 동시 업데이트
    → 로그 기록
    """
    doc_id:     str
    tendency:   Literal["긍정", "부정", "중립"]
    tend_score: float

class ExportRequest(BaseModel):
    """
    학습 데이터 내보내기 요청 모델
    - start_time : 내보낼 기간 시작
    - end_time   : 내보낼 기간 종료
    → logs_ml 에서 보정 완료 로그를 조회하여 JSONL 형식으로 반환
    """
    start_time: str
    end_time:   str

class DeleteRequest(BaseModel):
    doc_id: str