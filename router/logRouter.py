from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, StreamingResponse
from logs.logModel import LogSearchRequest
from manager.logArchiveModel import ArchiveRequest
from service.logSvc import search_log, export_log_csv, get_log_summary
from service.logArchiveSvc import stream_logs, archive_logs
from encryption.encAuth import verify_api_key

router = APIRouter(prefix="/logs", tags=["logs"])

@router.post("/search")
def search(req: LogSearchRequest, api_key=Depends(verify_api_key)):
    """로그 조회 - logViewer 로그 목록 처리"""
    return search_log(req)

@router.post("/export")
def export(req: LogSearchRequest, api_key=Depends(verify_api_key)):
    """CSV 내보내기 - logViewer CSV 내보내기 버튼 처리"""
    csv_data = export_log_csv(req)
    return PlainTextResponse(csv_data, media_type="text/csv; charset=utf-8")

@router.get("/summary")
def summary(subject: str = None, api_key=Depends(verify_api_key)):
    """로그 집계 - logViewer 상단 집계 카드 처리"""
    return get_log_summary(subject=subject)

@router.get("/stream")
async def stream(subject: str = None, api_key=Depends(verify_api_key)):
    """실시간 로그 스트리밍 (SSE)"""
    return StreamingResponse(
        stream_logs(subject=subject),
        media_type="text/event-stream"
    )

@router.post("/archive")
def archive(req: ArchiveRequest, api_key=Depends(verify_api_key)):
    """로그 아카이빙 - before_date 이전 로그 파일 저장 후 ES 삭제"""
    return archive_logs(index=req.index, before_date=req.before_date)