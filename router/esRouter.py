from fastapi import APIRouter, Depends
from dataStorage.elasticSearch.esModel import IntegrityCheckRequest, CompareUrlRequest
from service.esSvc import run_integrity_check, compare_urls, recollect_missing, get_index_status
from encryption.encAuth import verify_api_key

router = APIRouter(prefix="/es", tags=["es"])

@router.get("/status")
def status(api_key=Depends(verify_api_key)):
    """
    전체 인덱스 현황
    - 인증 필요 이유: ES 내부 데이터 구조 보호
    """
    return get_index_status()

@router.post("/integrity")
def integrity(req: IntegrityCheckRequest, api_key=Depends(verify_api_key)):
    """
    정합성 검사
    - 인증 필요 이유: 내부 데이터 정합성 정보 보호
    """
    return run_integrity_check(batch_id=req.batch_id, lang=req.lang)

@router.post("/compare")
def compare(req: CompareUrlRequest, api_key=Depends(verify_api_key)):
    """
    URL 집합 비교
    - 인증 필요 이유: 내부 URL 목록 보호
    """
    return compare_urls(batch_id=req.batch_id, lang=req.lang)

@router.post("/recollect")
def recollect(req: CompareUrlRequest, api_key=Depends(verify_api_key)):
    """
    누락 URL 재수집
    - 인증 필요 이유: 서버 리소스 소모 작업
    """
    return recollect_missing(batch_id=req.batch_id, lang=req.lang)