from fastapi import APIRouter, Depends
from model.crawlModel import CrawlRequest, RetryRequest, RetrySelectedRequest
from service.crawlSvc import runCrawlBatch, getErrorLogC, retryErrorUrls, getCrawlSummary, retrySelectedUrls
from encryption.encAuth import verifyApiKey

router = APIRouter(prefix="/crawl", tags=["crawl"])

@router.post("/run")
def run(req: CrawlRequest, api_key=Depends(verifyApiKey)):
    """
    배치 크롤링 실행
    - 인증 필요 이유: 서버 리소스 소모 작업
    """
    return runCrawlBatch(urls=req.urls, lang=req.lang, batch_id=req.batch_id)

@router.get("/summary")
def summary(api_key=Depends(verifyApiKey)):
    """
    크롤링 현황 집계
    - 인증 필요 이유: 내부 운영 현황 데이터 보호
    """
    return getCrawlSummary()

@router.get("/errors/{batch_id}")
def errors(batch_id: str, api_key=Depends(verifyApiKey)):
    """
    실패 URL 조회
    - 인증 필요 이유: 내부 크롤링 오류 데이터 보호
    """
    error_urls = getErrorLogC(batch_id)
    return {"batch_id": batch_id, "error_urls": error_urls, "total": len(error_urls)}

@router.post("/retry")
def retry(req: RetryRequest, api_key=Depends(verifyApiKey)):
    """
    전체 실패 URL 재크롤링
    - 인증 필요 이유: 서버 리소스 소모 작업
    """
    return retryErrorUrls(batch_id=req.batch_id, lang=req.lang)

@router.post("/retry/selected")
def retrySelected(req: RetrySelectedRequest, api_key=Depends(verifyApiKey)):
    """
    선택적 재크롤링
    - 인증 필요 이유: 서버 리소스 소모 작업
    """
    return retrySelectedUrls(
        urls=req.urls, batch_id=req.batch_id, lang=req.lang
    )