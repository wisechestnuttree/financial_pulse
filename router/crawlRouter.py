from fastapi import APIRouter, Depends
from crawling.crawlModel import CrawlRequest, RetryRequest, RetrySelectedRequest
from service.crawlSvc import run_crawl_batch, extract_error_urls, retry_error_urls, get_crawl_summary, retry_selected_urls
from encryption.encAuth import verify_api_key

router = APIRouter(prefix="/crawl", tags=["crawl"])

@router.post("/run")
def run(req: CrawlRequest, api_key=Depends(verify_api_key)):
    """
    배치 크롤링 실행
    - 인증 필요 이유: 서버 리소스 소모 작업
    """
    return run_crawl_batch(urls=req.urls, lang=req.lang, batch_id=req.batch_id)

@router.get("/summary")
def summary(api_key=Depends(verify_api_key)):
    """
    크롤링 현황 집계
    - 인증 필요 이유: 내부 운영 현황 데이터 보호
    """
    return get_crawl_summary()

@router.get("/errors/{batch_id}")
def errors(batch_id: str, api_key=Depends(verify_api_key)):
    """
    실패 URL 조회
    - 인증 필요 이유: 내부 크롤링 오류 데이터 보호
    """
    error_urls = extract_error_urls(batch_id)
    return {"batch_id": batch_id, "error_urls": error_urls, "total": len(error_urls)}

@router.post("/retry")
def retry(req: RetryRequest, api_key=Depends(verify_api_key)):
    """
    전체 실패 URL 재크롤링
    - 인증 필요 이유: 서버 리소스 소모 작업
    """
    return retry_error_urls(batch_id=req.batch_id, lang=req.lang)

@router.post("/retry/selected")
def retry_selected(req: RetrySelectedRequest, api_key=Depends(verify_api_key)):
    """
    선택적 재크롤링
    - 인증 필요 이유: 서버 리소스 소모 작업
    """
    return retry_selected_urls(
        urls=req.urls, batch_id=req.batch_id, lang=req.lang
    )