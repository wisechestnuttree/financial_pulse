from fastapi import APIRouter, Request, Response, Depends
from model.authModel import AdminLoginRequest, AdminLoginResponse
from service.adminSvc import adminLogin, adminLogout
from encryption.encAuth import  verify_admin

router = APIRouter(prefix="/admin", tags=["admin"])

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