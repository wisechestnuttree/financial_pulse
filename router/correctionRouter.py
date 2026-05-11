from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from manager.correctionModel import CorrectionRequest, ExportRequest
from service.correctionSvc import detect_irregular, apply_correction, delete_article, export_corrections
from encryption.encAuth import verify_api_key

router = APIRouter(prefix="/correction", tags=["correction"])

@router.get("/detect")
def detect(api_key=Depends(verify_api_key)):
    """
    비정형 감지
    - 인증 필요 이유: 내부 ML 분석 데이터 보호
    """
    return detect_irregular()

@router.post("/apply")
def apply(req: CorrectionRequest, api_key=Depends(verify_api_key)):
    """
    보정 확정
    - 인증 필요 이유: 데이터 직접 수정 작업
    """
    return apply_correction(
        doc_id=req.doc_id,
        tendency=req.tendency,
        tend_score=req.tend_score
    )

@router.delete("/article/{doc_id}")
def delete(doc_id: str, api_key=Depends(verify_api_key)):
    """
    기사 삭제
    - 인증 필요 이유: 데이터 영구 삭제 작업
                      가장 민감한 작업이므로 반드시 인증 필요
    """
    return delete_article(doc_id=doc_id)

@router.post("/export")
def export(req: ExportRequest, api_key=Depends(verify_api_key)):
    """
    학습 데이터 내보내기
    - 인증 필요 이유: ML 학습 데이터 외부 유출 방지
    """
    jsonl = export_corrections(
        start_time=req.start_time,
        end_time=req.end_time
    )
    return PlainTextResponse("\n".join(jsonl), media_type="application/x-ndjson")