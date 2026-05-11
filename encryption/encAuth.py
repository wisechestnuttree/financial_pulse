from fastapi import Header, HTTPException, status
from encBase import ADMIN_API_KEY
from logs.logger import get_logger

logger = get_logger("user")

def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """
    API Key 검증 의존성 함수
    - 요청 헤더의 X-API-Key 값 검증
    - 일치하면 통과
    - 불일치하면 403 반환

    사용법:
        @router.get("/admin/only")
        def admin_only(api_key=Depends(verify_api_key)):
            ...

    요청 헤더:
        X-API-Key: fp-admin-secret-key-2000
    """
    if x_api_key != ADMIN_API_KEY:
        logger.warning("API Key 인증 실패")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="유효하지 않은 API Key입니다."
        )
    logger.info("API Key 인증 성공")