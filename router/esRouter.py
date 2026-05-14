from fastapi import APIRouter, Depends
from model.esModel import IntegrityCheckRequest, CompareUrlRequest
from service.esSvc import getMissingUrl, recollectMissing, getIndexStatus # , runIntegrityCheck
from encryption.encAuth import verifyApiKey

router = APIRouter(prefix="/es", tags=["es"])

@router.get("/status")
def status(api_key=Depends(verifyApiKey)):
    """
    전체 인덱스 현황
    - 인증 필요 이유: ES 내부 데이터 구조 보호
    """
    return getIndexStatus()

# @router.post("/integrity")
# def integrity(req: IntegrityCheckRequest, api_key=Depends(verifyApiKey)):
#     """
#     정합성 검사
#     - 인증 필요 이유: 내부 데이터 정합성 정보 보호
#     """
#     return runIntegrityCheck(batch_id=req.batch_id, lang=req.lang)

@router.post("/compare")
def compare(req: CompareUrlRequest, api_key=Depends(verifyApiKey)):
    """
    누락 URL 목록 조회
    - esCon 누락 URL 목록 테이블 처리
    """
    return getMissingUrl(batch_id=req.batch_id, lang=req.lang)

@router.post("/recollect")
def recollect(req: CompareUrlRequest, api_key=Depends(verifyApiKey)):
    """
    누락 URL 재수집
    - 인증 필요 이유: 서버 리소스 소모 작업
    """
    return recollectMissing(batch_id=req.batch_id, lang=req.lang)