import json
import requests
from typing import List
from fastapi import HTTPException, status
from pydantic import BaseModel

import pymysql
from fastapi import APIRouter, Request, Response, Depends
from model.authModel import AdminLoginRequest, AdminLoginResponse
from service.adminSvc import adminLogin, adminLogout
from encryption.encAuth import  verify_admin
from dataStorage.mariaDb.db import getConn
from logs.logger import getLogger

router = APIRouter(prefix="/admin", tags=["admin"])
logger = getLogger("system")
LOG_SERVER_URL='http://100.88.143.23:9200'

@router.post("/login", response_model=AdminLoginResponse)
def login(req: AdminLoginRequest, response: Response):
    """
    관리자 로그인 API
    - logViewer 로그인 화면 처리
    - 성공 시 쿠키에 세션 토큰 저장

    [Set-Cookie 설정]
    - httponly  : JS에서 쿠키 접근 불가 → XSS 공격 방어
    - samesite  : CSRF 공격 방어
    - max_age   : 쿠키 유효 시간 (초) → 8시간

    요청:
        POST /admin/login
        {"email": "admin@finance.com", "password": "Admin1234!"}

    응답:
        {"message": "로그인 성공", "email": "admin@finance.com"}
        Set-Cookie: admin_session=abc123...; HttpOnly; SameSite=lax
    """
    result = adminLogin(email=req.email, password=req.password)

    # 쿠키에 세션 토큰 저장
    response.set_cookie(
        key      = "admin_session",
        value    = result["token"],
        httponly = True,        # JS 접근 차단 (XSS 방어)
        samesite = "lax",       # CSRF 방어
        max_age  = 60 * 60 * 8  # 8시간
    )

    return {"message": "로그인 성공", "email": result["email"]}


@router.post("/logout")
def logout(request: Request, response: Response):
    """
    관리자 로그아웃 API
    - logViewer 로그아웃 버튼 처리
    - 세션 삭제 + 쿠키 삭제
    """
    token = request.cookies.get("admin_session")
    if token:
        adminLogout(token)

    # 쿠키 삭제
    response.delete_cookie("admin_session", path="/", samesite="lax")
    return {"message": "로그아웃 완료"}


@router.get("/me")
def me(admin=Depends(verify_admin)):
    """
    현재 로그인한 관리자 정보 조회
    - logViewer 상단 로그인 상태 확인
    - 세션 또는 API Key 인증 모두 허용
    """
    return {"email": admin}


class RetryRegisterRequest(BaseModel):
    """프론트엔드 HTML 대시보드 스펙과 일치하는 요청 포맷"""
    log_ids: List[str]

class RetryRegisterResponse(BaseModel):
    """대시보드가 수신할 최종 결과 피드백 데이터 규격"""
    success: bool
    saved_cnt: int
    deleted_log_cnt: int


@router.post("/retry/register", response_model=RetryRegisterResponse, status_code=status.HTTP_200_OK)
def register_retry_crawl(payload: RetryRegisterRequest, admin=Depends(verify_admin)):
    """
    대시보드에서 선택한 log_ids를 받아 DB 대기열에 넣고 기존 로그를 지우는 올인원 API
    - 🔒 보안 보완: admin=Depends(verify_admin)를 주입하여 로그인한 관리자만 조작 가능하도록 방어
    """
    log_ids = payload.log_ids
    if not log_ids:
        raise HTTPException(status_code=400, detail="선택된 로그 ID가 없습니다.")

    logger.info(f"🔄 관리자[{admin}] 크롤링 재시도 일괄 등록 시작 (요청: {len(log_ids)}건)")

    # -----------------------------------------------------------------
    # [1단계] 로그 서버(ES)에서 log_ids 쿼리로 원본 URL들 한 방에 가져오기
    # -----------------------------------------------------------------
    target_urls = []
    try:
        es_query = {
            "query": {"ids": {"values": log_ids}},
            "size": len(log_ids)
        }
        response = requests.post(f"{LOG_SERVER_URL}/_search", json=es_query, timeout=5)

        if response.status_code != 200:
            raise Exception(f"로그 서버 에러 응답: {response.text}")

        hits = response.json().get("hits", {}).get("hits", [])

        for hit in hits:
            source = hit.get("_source", {})
            extra = source.get("extra", {})

            # extra 필드가 문자열 형태일 경우를 대비한 파싱 안전장치
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except:
                    extra = {}

            actual_url = source.get("url") or extra.get("url")

            if actual_url and actual_url.strip():
                # 파라미터(?), 해시(#) 제거하여 URL 정형화
                pure_url = actual_url.split('?')[0].split('#')[0].strip()
                target_urls.append((pure_url,))  # executemany용 튜플 포맷

    except Exception as e:
        logger.error(f"❌ [재시도 실패] 로그 서버에서 URL 추적 중 실패: {e}")
        raise HTTPException(status_code=500, detail=f"로그 서버 통신 에러: {str(e)}")

    if not target_urls:
        raise HTTPException(status_code=404, detail="선택한 로그에서 유효한 기사 URL을 찾지 못했습니다.")

    # -----------------------------------------------------------------
    # [2단계] 추출한 URL 리스트를 MariaDB retryQueue에 벌크(Bulk) 적재
    # -----------------------------------------------------------------
    conn = getConn()
    saved_cnt = 0
    try:
        # 💡 DictCursor 환경 탈피: 일반 튜플 커서를 강제로 지정하여 실행합니다.
        with conn.cursor(pymysql.cursors.Cursor) as cursor:
            # 유니크 제약조건 충돌 시 에러 없이 통과하는 IGNORE 쿼리 활용
            sql = "INSERT IGNORE INTO retryQueue (url) VALUES (%s)"

            # 일반 커서 상태이므로 튜플 묶음 데이터([('url1',), ('url2',)])가 완벽하게 바인딩됩니다.
            cursor.executemany(sql, target_urls)
            conn.commit()
            saved_cnt = cursor.rowcount  # 실제 새로 삽입된 행의 개수
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"❌ [재시도 실패] MariaDB 대기열 적재 중 실패: {e}")
        raise HTTPException(status_code=500, detail=f"데이터베이스 저장 에러: {str(e)}")
    finally:
        if conn: conn.close()

    # -----------------------------------------------------------------
    # [3단계] DB 적재가 무사히 끝났다면, 사용 완료된 에러 로그들 ES에서 일괄 영구 청소
    # -----------------------------------------------------------------
    deleted_log_cnt = 0
    try:
        from router.logRouter import deleteLog
        for log_id in log_ids:
            deleted_log_cnt += 1
            deleteLog(log_id)
        # # 💡 [변경] 메타데이터 ids 대신 문서 내부의 'log_id' 필드를 terms로 직접 타격
        # delete_query = {
        #     "query": {
        #         "terms": {
        #             "log_id.keyword": log_ids  # 만약 log_id 필드가 text 타입이면 .keyword를 붙이고, keyword 타입이면 .keyword를 떼어주세요.
        #         }
        #     }
        # }
        #
        # # 💡 URL 뒤에 대상 인덱스명(예: log_crawl)을 명시해 주는 것이 안전합니다.
        # del_response = requests.post(
        #     f"{LOG_SERVER_URL}/log_crawl/_delete_by_query?refresh=true",
        #     json=delete_query,
        #     timeout=5
        # )
        #
        # if del_response.status_code == 200:
        #     deleted_log_cnt = del_response.json().get("deleted", 0)
        logger.info(f"✅ [재시도 완료] DB 적재 성공 및 에러 로그 {deleted_log_cnt}건 삭제 완료.")

    except Exception as e:
        logger.warning(f"🔺 대기열 적재는 성공했으나 처리 완료된 로그 삭제 중 예외 발생 (무시 가능): {e}")

    # -----------------------------------------------------------------
    # [4단계] 프론트엔드 HTML 스크립트 규격에 딱 맞춘 최종 결과 반환
    # -----------------------------------------------------------------
    return RetryRegisterResponse(
        success=True,
        saved_cnt=saved_cnt,
        deleted_log_cnt=deleted_log_cnt if deleted_log_cnt else len(log_ids)
    )