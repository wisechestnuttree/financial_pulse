from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, StreamingResponse
from model.logModel import LogSearchRequest
from model.logArchiveModel import ArchiveRequest
from service.logSvc import searchLog, exportLogCsv, getLogSummary
from service.logArchiveSvc import streamLogs, archiveLogs
from encryption.encAuth import verify_admin
import io

router = APIRouter(prefix="/logs", tags=["logs"])

@router.post("/search")
def search(req: LogSearchRequest, api_key=Depends(verify_admin)):
    """로그 조회 - logViewer 로그 목록 처리"""
    return searchLog(req)

@router.post("/export")
def export(req: LogSearchRequest, api_key=Depends(verify_admin)):
    """CSV 내보내기 - logViewer CSV 내보내기 버튼 처리"""
    csv_data = exportLogCsv(req)
    return PlainTextResponse(
        csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=logs.csv"}
    )

@router.get("/summary")
def summary(subject: str = None, api_key=Depends(verify_admin)):
    """로그 집계 - logViewer 상단 집계 카드 처리"""
    return getLogSummary(subject=subject)

@router.get("/stream")
async def stream(subject: str = None, api_key=Depends(verify_admin)):
    """실시간 로그 스트리밍 (SSE)"""
    return StreamingResponse(
        streamLogs(subject=subject),
        media_type="text/event-stream"
    )

@router.post("/archive")
def archive(req: ArchiveRequest, api_key=Depends(verify_admin)):
    """로그 아카이빙 - before_date 이전 로그 파일 저장 후 ES 삭제"""
    csv_data, count = archiveLogs(index=req.index, before_date=req.before_date)
    if count == 0:
        return {"success": False, "message": "아카이빙할 데이터가 없습니다.", "archived": 0}
    file_name = f"archive_{req.index}_{req.before_date}.csv"
    return StreamingResponse(
        io.BytesIO(csv_data),
        media_type="text/csv; charset=utf-8-sig",
        headers={
            "Content-Disposition": f"attachment; filename={file_name}",
            "X-Archived-Count": str(count)
        }
    )