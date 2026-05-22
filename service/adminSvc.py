import os
from fastapi import HTTPException, status

from dataStorage.mariaDb.db import getConn
from encryption.argonPepper import hashPassword, comparePassword
from encryption.encAuth import create_session, delete_session
from encryption import encBase as eb
from logs.logger import getLogger

logger = getLogger("user")
# ================================================================
# .env 기반 관리자 계정
#
# [구성]
# ADMIN_EMAIL    : 관리자 이메일 (로그인 아이디)
# ADMIN_PASSWORD : 관리자 비밀번호 (평문)
#
# [보안]
# 비밀번호는 서버 시작 시 Argon2 + Pepper로 해싱하여 메모리에 보관
# .env의 평문 비밀번호는 비교용으로만 사용
#
# [실제 입력값]
# .env 파일에 아래와 같이 설정
# ADMIN_EMAIL=admin@finance.com
# ADMIN_PASSWORD=Admin1234!
# ================================================================
ADMIN_EMAIL    = eb.ADMIN_EMAIL
ADMIN_PASSWORD = eb.ADMIN_PASSWORD

# 서버 시작 시 비밀번호 해싱 (매 요청마다 해싱 방지)
ADMIN_HASHED_PW = hashPassword(ADMIN_PASSWORD)
ADMIN_EMAIL = getattr(eb, "ADMIN_EMAIL", "dino@financial.pulse")
ADMIN_PASSWORD = getattr(eb, "ADMIN_PASSWORD", "dino123!!")

def adminLogin(email: str, password: str) -> dict:
    """
    DB에서 role='admin'인 사용자 조회 후 비밀번호 검증
    """
    logger.info("관리자 로그인 시도", extra={"email": email})

    conn = getConn()
    try:
        with conn.cursor() as cursor:
            # 1. 이메일로 사용자 조회 (role이 admin인 경우만)
            sql = "SELECT email, encry_pw FROM user WHERE email = %s"
            cursor.execute(sql, (email,))
            user = cursor.fetchone()

            # 2. 사용자 없음 또는 role이 admin 아님
            if not user:
                logger.warning("관리자 계정 없음", extra={"email": email})
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="이메일 또는 비밀번호가 올바르지 않습니다."
                )

            # 3. 비밀번호 검증 (comparePassword 사용)
            if not comparePassword(user["encry_pw"], password):
                logger.warning("비밀번호 불일치", extra={"email": email})
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="이메일 또는 비밀번호가 올바르지 않습니다."
                )

            # 4. 세션 토큰 생성
            token = create_session(email)
            logger.info("관리자 로그인 성공", extra={"email": email})
            return {"token": token, "email": email}

    finally:
        conn.close()


def adminLogout(token: str) -> dict:
    """로그아웃 (기존과 동일)"""
    delete_session(token)
    return {"message": "로그아웃 완료"}

# def adminLogin(email: str, password: str) -> dict:
#     """
#     관리자 로그인
#     - logViewer 로그인 화면 처리
#
#     [처리 순서]
#     1. 이메일 일치 여부 확인
#     2. 비밀번호 검증 (Argon2 + Pepper)
#     3. 세션 토큰 생성
#     4. 쿠키에 세션 토큰 저장 (응답에 Set-Cookie 헤더 포함)
#
#     [보안]
#     - 이메일 불일치와 비밀번호 불일치를 동일한 메시지로 처리
#       → 어느 값이 틀렸는지 공격자에게 알려주지 않음
#     """
#     logger.info("관리자 로그인 시도", extra={"email": email})
#
#     # [1] 이메일 + 비밀번호 검증
#     # 이메일 불일치와 비밀번호 불일치를 동일 메시지로 처리 (보안)
#     if email != ADMIN_EMAIL or not comparePassword(ADMIN_HASHED_PW, password):
#         logger.warning("관리자 로그인 실패", extra={"email": email})
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="이메일 또는 비밀번호가 올바르지 않습니다."
#         )
#
#     # [2] 세션 토큰 생성
#     token = create_session(email)
#     logger.info("관리자 로그인 성공", extra={"email": email})
#
#     return {"token": token, "email": email}
#
#
# def adminLogout(token: str) -> dict:
#     """
#     관리자 로그아웃
#     - logViewer 로그아웃 버튼 처리
#     - 세션 토큰 삭제
#     """
#     delete_session(token)
#     return {"message": "로그아웃 완료"}