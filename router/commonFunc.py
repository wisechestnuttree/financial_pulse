# ok 함수 여기에 정의
from fastapi.responses import JSONResponse
# ================================================================
# 공통 성공 응답
def ok(message: str, data: dict | None = None):
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": message,
            "data"   : data
        }
    )