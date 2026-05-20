# login, signup, findId, findPw, changePw 등
import traceback
from fastapi import APIRouter, HTTPException, Request, status, Response

from router.commonFunc import ok
from dataStorage.mariaDb.db import getConn
from encryption.argonPepper import hashPassword, comparePassword
from logs.logger import getLogger
from encryption.reMail import findPassword
from model.memberModel import *
    # SignupRequest, LoginRequest, FindIdRequest, FindPwRequest
    # , ChangePwRequest, VerifyPwRequest, UpdateInfoRequest
    # , DeleteUserRequest, CheckEmailRequest

logger = getLogger("user")

# 일반 사용자용 라우터 — API Key 인증 없음
# API Key는 관리자 라우터(/admin/...)에서만 사용
router = APIRouter(prefix="/membership", tags=["membership"])


# ================================================================
# 상수
MAX_FAIL  = 5   # 최대 로그인 실패 횟수
LOCK_HOUR = 24  # 잠금 해제까지 걸리는 시간 (시간 단위)

# ================================================================
# [1] 로그인
# ================================================================
@router.post("/login")
def logIn(req: LoginRequest, request: Request, response: Response):
    """
    성공 →  { success: True,  message: "로그인 성공",   data: { u_id } }
    실패 →  { success: False, message: "<사유>",        data: null }

    로그인인데 어떻게 세션이 존재하는가 --> 로그에 찍을 세션이 존재하지 않은데.
    logger.warning("로그인 실패 - 존재하지 않는 이메일", extra={"action": "logIn", "u_id": req.u_id})
    """
    from encryption.encBase import ADMIN_EMAIL
    from service.adminSvc import adminLogin

    # if req.email == ADMIN_EMAIL:
    #     # 관리자 이메일이면 adminSvc로 위임
    #     result = adminLogin(email=req.email, password=req.password)
    #
    #     # 세션 쿠키 저장 - X 예정
    #     response.set_cookie(
    #         key="admin_session",
    #         value=result["token"],
    #         httponly=True,
    #         samesite="lax",
    #         max_age=60 * 60 * 8
    #     )
    #     return ok("관리자 로그인 성공", {"role": "admin", "email": result["email"]})

    conn = getConn()
    try:
        with conn.cursor() as cursor:

            # 1. 사용자 조회 (이메일 존재 여부 노출 방지 — 동일 메시지)
            cursor.execute(
                "SELECT u_id, encry_pw FROM user WHERE email = %s", (req.email,)
            )
            user = cursor.fetchone()
            if not user:
                logger.warning("로그인 실패 - 존재하지 않는 이메일", extra={"action": "logIn"})
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
                    logger.info("로그인 잠금 해제 - 24시간 경과", extra={"action": "logIn", "u_id": u_id})
                else:
                    remaining_hour = LOCK_HOUR - elapsed
                    logger.warning("로그인 잠금 중", extra={"action": "logIn", "u_id": u_id})
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
                logger.warning("로그인 실패 - 비밀번호 불일치", extra={"action": "logIn", "u_id": u_id})

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
            request.session["u_id"]= u_id

        logger.info("로그인 성공", extra={"action": "logIn", "u_id": u_id})
        return ok("로그인 성공", {"u_id": u_id})

    except HTTPException:
        raise
    except Exception as e:
        logger.error("로그인 중 오류", extra={"action": "logIn", "err_msg": str(e)})
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
        logger.warning("로그아웃 실패", extra={"action": "logOut", "err_msg": "Be not logged in"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인 상태가 아닙니다."
        )

    request.session.clear()

    logger.info("로그아웃 완료", extra={"action": "logOut", "u_id": u_id})
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
                logger.warning("회원가입 실패 - 이메일 중복", extra={"action": "signUp", "err_msg": "Used e-mail address"})
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
            new_id= cursor.lastrowid # auto-increment 가져오기

        logger.info("회원가입 성공", extra={"action": "signUp", "u_id": new_id})
        return ok("회원가입이 완료되었습니다.", {"u_id": new_id})

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("회원가입 중 오류", extra={"action": "signUp", "err_msg": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()


# ================================================================
# [3-1] 이메일 중복 확인
# ================================================================

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
        logger.error("이메일 중복 확인 오류", extra={"action": "checkEmail", "err_msg": str(e)})
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
                "SELECT u_id, email FROM user WHERE name = %s AND phone_num = %s",
                (req.name, cleaned_phone)
            )
            user = cursor.fetchone()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="일치하는 사용자 정보가 없습니다."
                )

        logger.info("아이디 찾기 성공", extra={"action": "findId", "u_id": user["u_id"]})
        return ok("아이디 찾기 성공", {"email": user["email"]})

    except HTTPException:
        raise
    except Exception as e:
        logger.error("아이디 찾기 중 오류", extra={"action": "findId", "err_msg": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()


# ================================================================
# [5-1] 비밀번호 찾기 — 임시 비밀번호 발급
# ================================================================
@router.post("/find-pw")
def findPw(req: FindPwRequest):
    conn = getConn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT u_id
                FROM user
                WHERE email     = %s
                  AND name      = %s
                  AND phone_num = %s
                """,
                (req.email, req.name, req.phone_num)
            )
            user = cursor.fetchone()

        if user:
            result = findPassword(user["u_id"], req.email, conn)
            if not result["success"]:
                raise HTTPException(status_code=500, detail="처리 중 오류 발생")
            conn.commit()

        # 이메일 존재 여부 노출 방지
        return ok("가입한 이메일을 확인해 주세요. (임시 비밀번호가 발송되었습니다)")

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        logger.error("비밀번호 찾기 중 오류", extra={"action": "findPw", "err_msg": str(e)})
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
    # 1. 세션에서 u_id를 가져옴 (email은 필요 없음)
    u_id = request.session.get("u_id")
    if not u_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    logger.info("비밀번호 변경 시작", extra={"action": "changePw", "u_id": u_id})
    conn = getConn()
    try:
        with conn.cursor() as cursor:
            # 2. u_id로 사용자 조회
            cursor.execute(
                "SELECT u_id, encry_pw FROM user WHERE u_id = %s", (u_id,)
            )
            user = cursor.fetchone()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="사용자를 찾을 수 없습니다."
                )

            # 3. 현재 비밀번호 확인
            if not comparePassword(user["encry_pw"], req.current_pw):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="현재 비밀번호와 일치하지 않습니다."
                )

            # 4. 새 비밀번호와 확인 일치 여부
            if req.new_pw != req.new_pw_check:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="새 비밀번호와 확인용 비밀번호가 일치하지 않습니다."
                )

            # 5. 현재 비밀번호와 동일한지 확인
            if comparePassword(user["encry_pw"], req.new_pw):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="현재 비밀번호와 동일한 비밀번호로 변경할 수 없습니다."
                )

            # 6. 비밀번호 업데이트
            cursor.execute(
                "UPDATE user SET encry_pw = %s WHERE u_id = %s",
                (hashPassword(req.new_pw), u_id)
            )
            conn.commit()

        logger.info("비밀번호 변경 성공", extra={"action": "changePw", "u_id": u_id})
        return ok("비밀번호가 변경되었습니다.")

    except HTTPException:
        logger.warning("비밀번호 변경 실패", extra={"u_id": u_id, "action": "changePw", "err_msg": "cause input value"})
        raise
    except Exception as e:
        conn.rollback()
        logger.error("비밀번호 변경 중 오류", extra={"action": "changePw", "u_id": u_id, "err_msg": str(e)})
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
    u_id = request.session.get("u_id")
    if not u_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    logger.info("본인 확인 시작", extra={"action": "verifyPw", "u_id": u_id})
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

        logger.info("본인 확인 성공", extra={"action": "changePw", "u_id": u_id})
        return ok("본인 확인이 완료되었습니다.")

    except HTTPException:
        logger.warning("본인 확인 실패", extra={"action": "changePw", "u_id": u_id, "err_msg": "cause input value"})
        raise
    except Exception as e:
        logger.error("본인 확인 중 오류", extra={"action": "changePw", "err_msg": str(e)})
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

    logger.info("회원정보 변경 시작", extra={"action": "updateInfo", "u_id": u_id})
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

        logger.info("회원정보 변경 성공", extra={"action": "updateInfo", "u_id": u_id})
        return ok("회원정보가 변경되었습니다.", {
            "u_id"     : u_id,
            "name"     : new_name,
            "phone_num": new_phone
        })

    except HTTPException:
        logger.info("회원정보 변경 실패", extra={"action": "updateInfo", "u_id": u_id, "err_msg": "cause input value"})
        raise
    except Exception as e:
        conn.rollback()
        logger.error("회원정보 변경 중 오류", extra={"action": "updateInfo", "err_msg": str(e)})
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

    if not req.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="탈퇴 확인이 필요합니다."
        )

    logger.info("회원 탈퇴 시작", extra={"action": "withDraw", "u_id": u_id})
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

        logger.info("회원 탈퇴 완료", extra={"action": "withDraw", "u_id": u_id})
        return ok("회원 탈퇴가 완료되었습니다.")

    except HTTPException:
        logger.warning("회원 탈퇴 실패", extra={"action": "withDraw", "u_id": u_id, "err_msg": "cause input value"})
        raise
    except Exception as e:
        conn.rollback()
        logger.error("회원 탈퇴 중 오류", extra={"action": "withDraw", "err_msg": str(e)})
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    finally:
        conn.close()