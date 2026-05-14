from pydantic import BaseModel
from typing import Optional, List

class CrawlRequest(BaseModel):
    """ 크롤링 시도
    - urls     : 크롤링할 URL 목록
    - lang     : 언어 → "ko" : news_ko 인덱스 / "en" : news_en 인덱스
    - batch_id : 배치 묶음 ID (없으면 자동 UUID 생성)
                 정합성 검사, 재크롤링 시 batch_id로 추적
    """
    urls:     List[str]
    lang:     str = "ko"
    batch_id: Optional[str] = None

class RetryRequest(BaseModel):
    """ 재크롤링
    - batch_id : 재시도할 원본 배치 ID
                 해당 batch_id의 ERROR 로그에서 실패 URL을 추출하여 재크롤링
    - lang     : 언어
    """
    batch_id: str
    lang:     str = "ko"

class RetrySelectedRequest(BaseModel):
    """
    선택적 재크롤링
    - crawCon UI 체크박스로 선택한 URL 목록
    - batch_id : 원본 배치 ID (추적용)
    """
    urls:     List[str]
    batch_id: str
    lang:     str = "ko"