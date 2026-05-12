from pydantic import BaseModel, EmailStr, field_validator
import re


# ================================================================
# 요청 스키마
# ================================================================

class SignupRequest(BaseModel):
    email    : EmailStr
    password : str
    name     : str
    phone_num: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("비밀번호는 8자 이상이어야 합니다.")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("비밀번호에 영문자가 포함되어야 합니다.")
        if not re.search(r"\d", v):
            raise ValueError("비밀번호에 숫자가 포함되어야 합니다.")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("비밀번호에 특수문자가 포함되어야 합니다.")
        return v

    @field_validator("phone_num")
    @classmethod
    def validate_phone(cls, v):
        cleaned = re.sub(r"[-\s]", "", v)
        if not re.fullmatch(r"010[0-9]{8}", cleaned):
            raise ValueError("올바른 전화번호 형식이 아닙니다.")
        return cleaned


class LoginRequest(BaseModel):
    email   : EmailStr
    password: str


class FindIdRequest(BaseModel):
    name     : str
    phone_num: str


class FindPwRequest(BaseModel):
    email: EmailStr


class ChangePwRequest(BaseModel):
    current_pw  : str
    new_pw      : str
    new_pw_check: str

    @field_validator("new_pw")
    @classmethod
    def validate_new_password(cls, v):
        if len(v) < 8:
            raise ValueError("비밀번호는 8자 이상이어야 합니다.")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("비밀번호에 영문자가 포함되어야 합니다.")
        if not re.search(r"\d", v):
            raise ValueError("비밀번호에 숫자가 포함되어야 합니다.")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("비밀번호에 특수문자가 포함되어야 합니다.")
        return v


class VerifyPwRequest(BaseModel):
    password: str


class UpdateInfoRequest(BaseModel):
    name     : str | None = None
    phone_num: str | None = None

    @field_validator("phone_num")
    @classmethod
    def validate_phone(cls, v):
        if v is None:
            return v
        cleaned = re.sub(r"[-\s]", "", v)
        if not re.fullmatch(r"010[0-9]{8}", cleaned):
            raise ValueError("올바른 전화번호 형식이 아닙니다.")
        return cleaned


class DeleteUserRequest(BaseModel):
    confirmed: bool     # 프론트 최종 확인 팝업에서 "예" 선택 시 True 전달
