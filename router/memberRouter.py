# login, signup, findId, findPw, changePw 등
import re
import secrets
import string
from fastapi import APIRouter, HTTPException, Request, status

from router.commonFunc import ok
from dataStorage.mariaDb.db import getConn
from encryption.argonPepper import hashPassword, comparePassword
from logs.logger import getLogger
from model.memberModel import (
    SignupRequest, LoginRequest, FindIdRequest, FindPwRequest,
    ChangePwRequest, VerifyPwRequest, UpdateInfoRequest, DeleteUserRequest
)
import traceback

logger = getLogger("user")

# 일반 사용자용 라우터 — API Key 인증 없음
# API Key는 관리자 라우터(/admin/...)에서만 사용
router = APIRouter(prefix="/member", tags=["member"])


# ================================================================
# 상수
MAX_FAIL  = 5   # 최대 로그인 실패 횟수
LOCK_HOUR = 24  # 잠금 해제까지 걸리는 시간 (시간 단위)

# ================================================================
# [1] 로그인
# ================================================================
@router.post("/login")
def logIn(req: LoginRequest, request: Request):
    """
    성공 →  { success: True,  message: "로그인 성공",   data: { u_id } }
    실패 →  { success: False, message: "<사유>",        data: null }
    """
    conn = getConn()
    try:
        with conn.cursor() as cursor:

            # 1. 사용자 조회 (이메일 존재 여부 노출 방지 — 동일 메시지)
            cursor.execute(
                "SELECT u_id, encry_pw FROM user WHERE email = %s", (req.email,)
            )
            user = cursor.fetchone()
            if not user:
                logger.warning("로그인 실패 - 존재하지 않는 이메일", extra={"action": "managedDriver", "u_id": req.u_id})
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="이메일 또는 비밀번호가 올바르지 않습니다."
                )

            u_id = user["u_id"]

            # 2. 실패 횟수 조회 (DB row count 방식)
            cursor.execute(
                "SELECT COUNT(*) AS fail_count FROM loginFail WHERE u_id = %s", (u_id,)
            )
            fail_count = cursor.fetchone()["fail_count"]

            if fail_count >= MAX_FAIL:
                # 가장 오래된 실패 시각 기준 24시간 경과 확인
                cursor.execute(
                    "SELECT MIN(dateFail) AS oldest FROM loginFail WHERE u_id = %s", (u_id,)
                )
                oldest = cursor.fetchone()["oldest"]
                cursor.execute(
                    "SELECT TIMESTAMPDIFF(HOUR, %s, NOW()) AS elapsed", (oldest,)
                )
                elapsed = cursor.fetchone()["elapsed"]

                if elapsed >= LOCK_HOUR:
                    # 24시간 경과 → 실패 기록 삭제 후 재시도 허용
                    cursor.execute("DELETE FROM loginFail WHERE u_id = %s", (u_id,))
                    conn.commit()
                    fail_count = 0
                    logger.info("로그인 잠금 해제 - 24시간 경과", extra={"u_id": u_id})
                else:
                    remaining_hour = LOCK_HOUR - elapsed
                    logger.warning("로그인 잠금 중", extra={"u_id": u_id})
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"로그인이 잠겼습니다. {remaining_hour}시간 후 다시 시도해주세요."
                    )

            # 3. 비밀번호 비교
            if not comparePassword(user["encry_pw"], req.password):
                cursor.execute(
                    "INSERT INTO loginFail (u_id, dateFail) VALUES (%s, NOW())", (u_id,)
                )
                conn.commit()
                remaining_try = MAX_FAIL - (fail_count + 1)
                logger.warning("로그인 실패 - 비밀번호 불일치", extra={"u_id": u_id})

                if remaining_try <= 0:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=f"로그인이 잠겼습니다. {LOCK_HOUR}시간 후 다시 시도해주세요."
                    )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"이메일 또는 비밀번호가 올바르지 않습니다. (남은 시도: {remaining_try}회)"
                )

            # 4. 성공 — 실패 기록 초기화 + 세션 저장
            cursor.execute("DELETE FROM loginFail WHERE u_id = %s", (u_id,))
            conn.commit()
            request.session["u_id"]  = u_id
            request.session["email"] = req.email

        logger.info("로그인 성공", extra={"u_id": u_id})
        return ok("로그인 성공", {"u_id": u_id})

    except HTTPException:
        raise
    except Exception as e:
        logger.error("로그인 중 오류", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()


# ================================================================
# [2] 로그아웃
# ================================================================
@router.post("/logout")
def logOut(request: Request):
    """
    성공 →  { success: True,  message: "로그아웃 되었습니다.", data: null }
    실패 →  { success: False, message: "<사유>",              data: null }
    """
    u_id = request.session.get("u_id")
    if not u_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인 상태가 아닙니다."
        )

    request.session.clear()

    logger.info("로그아웃 완료", extra={"u_id": u_id})
    return ok("로그아웃 되었습니다.")


# ================================================================
# [3] 회원가입
# ================================================================
@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signUp(req: SignupRequest):
    """
    성공 →  { success: True,  message: "회원가입이 완료되었습니다.", data: { u_id } }
    실패 →  { success: False, message: "<사유>",                   data: null }
    """
    conn = getConn()
    try:
        with conn.cursor() as cursor:

            # 1. 이메일 중복 확인
            cursor.execute("SELECT u_id FROM user WHERE email = %s", (req.email,))
            if cursor.fetchone():
                logger.warning("회원가입 실패 - 이메일 중복", extra={"email": req.email})
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="이미 사용 중인 이메일입니다."
                )

            # 2. 비밀번호 암호화 후 저장
            cursor.execute(
                "INSERT INTO user (email, encry_pw, name, phone_num) VALUES (%s, %s, %s, %s)",
                (req.email, hashPassword(req.password), req.name, req.phone_num)
            )
            conn.commit()
            new_id = cursor.lastrowid

        logger.info("회원가입 성공", extra={"u_id": new_id})
        return ok("회원가입이 완료되었습니다.", {"u_id": new_id})

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("회원가입 중 오류", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()


# ================================================================
# [3-2] 이메일 중복 확인
# ================================================================
from pydantic import EmailStr as _EmailStr
from pydantic import BaseModel as _BaseModel

class CheckEmailRequest(_BaseModel):
    email: _EmailStr

@router.post("/check-email")
def checkEmail(req: CheckEmailRequest):
    """
    성공 →  { success: True,  message: "사용 가능한 이메일입니다.", data: null }
    실패 →  { success: False, message: "이미 사용 중인 이메일입니다.", data: null }
    """
    conn = getConn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT u_id FROM user WHERE email = %s", (req.email,))
            if cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="이미 사용 중인 이메일입니다."
                )
        return ok("사용 가능한 이메일입니다.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("이메일 중복 확인 오류", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()


# ================================================================
# [4] 아이디 찾기
# ================================================================
@router.post("/find-id")
def findId(req: FindIdRequest):
    """
    성공 →  { success: True,  message: "아이디 찾기 성공", data: { email } }
    실패 →  { success: False, message: "<사유>",           data: null }
    """
    conn = getConn()
    try:
        with conn.cursor() as cursor:
            cleaned_phone = re.sub(r"[-\s]", "", req.phone_num)
            cursor.execute(
                "SELECT email FROM user WHERE name = %s AND phone_num = %s",
                (req.name, cleaned_phone)
            )
            user = cursor.fetchone()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="일치하는 사용자 정보가 없습니다."
                )

        logger.info("아이디 찾기 성공")
        return ok("아이디 찾기 성공", {"email": user["email"]})

    except HTTPException:
        raise
    except Exception as e:
        logger.error("아이디 찾기 중 오류", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()


# ================================================================
# [5-1] 비밀번호 찾기 — 임시 비밀번호 발급
# ================================================================
@router.post("/find-pw")
def findPw(req: FindPwRequest):
    """
    성공 →  { success: True,  message: "임시 비밀번호가 발급되었습니다.", data: null }
    실패 →  { success: False, message: "<사유>",                        data: null }
    * 이메일 존재 여부 노출 방지 — 없는 이메일도 성공 응답 반환
    * TODO: 이메일 발송 구현 후 temp_password 제거
    """
    conn = getConn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT u_id FROM user WHERE email = %s", (req.email,))
            user = cursor.fetchone()

            if not user:
                return ok("임시 비밀번호가 발급되었습니다.")

            chars  = string.ascii_letters + string.digits + "!@#$%^&*"
            temp_pw = "".join(secrets.choice(chars) for _ in range(12))
            cursor.execute(
                "UPDATE user SET encry_pw = %s WHERE u_id = %s",
                (hashPassword(temp_pw), user["u_id"])
            )
            conn.commit()

        logger.info("임시 비밀번호 발급", extra={"u_id": user["u_id"]})
        # TODO: 이메일 발송 구현 후 data에서 temp_password 제거
        return ok("임시 비밀번호가 발급되었습니다.", {"temp_password": temp_pw})

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("비밀번호 찾기 중 오류", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()


# ================================================================
# [5-2] 비밀번호 변경
# ================================================================
@router.put("/change-pw")
def changePw(req: ChangePwRequest, request: Request):
    """
    성공 →  { success: True,  message: "비밀번호가 변경되었습니다.", data: null }
    실패 →  { success: False, message: "<사유>",                   data: null }
    """
    email = request.session.get("email")
    print(email)
    if not email:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    conn = getConn()
    try:
        with conn.cursor() as cursor:

            cursor.execute(
                "SELECT u_id, encry_pw FROM user WHERE email = %s", (req.email,)
            )
            user = cursor.fetchone()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="사용자를 찾을 수 없습니다."
                )

            if not comparePassword(user["encry_pw"], req.current_pw):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="현재 비밀번호와 일치하지 않습니다."
                )

            if req.new_pw != req.new_pw_check:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="새 비밀번호와 확인용 비밀번호가 일치하지 않습니다."
                )

            if comparePassword(user["encry_pw"], req.new_pw):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="현재 비밀번호와 동일한 비밀번호로 변경할 수 없습니다."
                )

            cursor.execute(
                "UPDATE user SET encry_pw = %s WHERE u_id = %s",
                (hashPassword(req.new_pw), user["u_id"])
            )
            conn.commit()

        logger.info("비밀번호 변경 성공", extra={"u_id": user["u_id"]})
        return ok("비밀번호가 변경되었습니다.")

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        traceback.print_exc() #??????????????????
        logger.error("비밀번호 변경 중 오류", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()


# ================================================================
# [6-1] 회원정보 변경 1단계 — 비밀번호 본인 확인
# ================================================================
@router.post("/verify-pw")
def verifyPw(req: VerifyPwRequest,request: Request):
    """
    성공 →  { success: True,  message: "본인 확인이 완료되었습니다.", data: null }
    실패 →  { success: False, message: "<사유>",                    data: null }
    """
    # verifyPw 함수 맨 위에 임시로 추가
    print("세션 내용:", dict(request.session))
    u_id = request.session.get("u_id")
    if not u_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    u_id = int(u_id)
    conn = getConn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT encry_pw FROM user WHERE u_id = %s", (u_id,)
            )
            user = cursor.fetchone()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="사용자를 찾을 수 없습니다."
                )

            if not comparePassword(user["encry_pw"], req.password):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="비밀번호가 일치하지 않습니다."
                )

        logger.info("본인 확인 성공", extra={"u_id": u_id})
        return ok("본인 확인이 완료되었습니다.")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("본인 확인 중 오류", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()


# ================================================================
# [6-2] 회원정보 변경 2단계 — 이름 / 전화번호 변경
# ================================================================
@router.put("/update-info")
def updateInfo(req: UpdateInfoRequest, request: Request):
    """
        성공 →  { success: True,  message: "회원정보가 변경되었습니다.", data: { u_id, name, phone_num } }
        실패 →  { success: False, message: "<사유>",                   data: null }
    """
    u_id = request.session.get("u_id")
    if not u_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    u_id = int(u_id)
    if req.name is None and req.phone_num is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="변경할 항목(이름 또는 전화번호)을 하나 이상 입력해 주세요."
        )

    conn = getConn()
    try:
        with conn.cursor() as cursor:

            cursor.execute(
                "SELECT u_id, name, phone_num FROM user WHERE u_id = %s", (u_id,)
            )
            user = cursor.fetchone()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="사용자를 찾을 수 없습니다."
                )

            # 전달된 값만 변경 — 미전달 항목은 기존 값 유지
            new_name  = req.name      if req.name      is not None else user["name"]
            new_phone = req.phone_num if req.phone_num is not None else user["phone_num"]

            cursor.execute(
                "UPDATE user SET name = %s, phone_num = %s WHERE u_id = %s",
                (new_name, new_phone, u_id)
            )
            conn.commit()

        logger.info("회원정보 변경 성공", extra={"u_id": u_id})
        return ok("회원정보가 변경되었습니다.", {
            "u_id"     : u_id,
            "name"     : new_name,
            "phone_num": new_phone
        })

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("회원정보 변경 중 오류", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()


# ================================================================
# [7] 회원 탈퇴
# ================================================================
@router.delete("/withdraw")
def withdraw(req: DeleteUserRequest,request: Request):
    """
    성공 →  { success: True,  message: "회원 탈퇴가 완료되었습니다.", data: null }
    실패 →  { success: False, message: "<사유>",                    data: null }
    """
    u_id = request.session.get("u_id")
    if not u_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    u_id = int(u_id)
    if not req.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="탈퇴 확인이 필요합니다."
        )

    conn = getConn()
    try:
        with conn.cursor() as cursor:

            cursor.execute(
                "SELECT u_id FROM user WHERE u_id = %s", (u_id,)
            )
            if not cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="사용자를 찾을 수 없습니다."
                )

            # CASCADE로 userInterests, loginFail 자동 삭제
            cursor.execute("DELETE FROM user WHERE u_id = %s", (u_id,))
            conn.commit()

        logger.info("회원 탈퇴 완료")
        return ok("회원 탈퇴가 완료되었습니다.")

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("회원 탈퇴 중 오류", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()
