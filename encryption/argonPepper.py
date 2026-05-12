# 비밀번호 단방향 암호화 Argon2 , Pepper
import os, hmac, hashlib
from encryption.encBase import pepper
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
# 상대 경로 지정
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.normpath(os.path.join(current_dir, "..", "sub.env"))

# 로그 설정
# admin_logger= getLogger("USER")

# 아르곤 설정 (조정 순위 : time_cost -> paralleism -> memory_cost)
argon_pw= PasswordHasher(
    time_cost= 2        # 시간 비용 : 해시 반복 횟수
    , memory_cost= 65536# 메모리 비용 : 해싱에 사용할 RAM (64mb 표준)
    , parallelism= 4 )  # 병렬성   : 사용할 CPU 코어 (병렬 처리 스레드 수, 서버의 코어수와 맞출 것)


def getPepperedPassword(password):
    """ pepper + hmac (페퍼 가공 -> 적절한 고정 길이의 문자열) """
    h_pepper= hmac.new( key= pepper.encode("utf-8"), msg= password.encode("utf-8"), digestmod= hashlib.sha256 )
    return h_pepper.hexdigest()

#=================================================================
# 실사용 - 사용자의 pw 암호화
def hashPassword(password):
    """ final= Argon2 + PEPPER + HMAC (DB에 저장될 암호화된 PW) """
    pw_pepper = getPepperedPassword(password)
    return argon_pw.hash(pw_pepper)

# 실사용 - 사용자의 입력과 db에 저장된 pw 비교
# Params: (db 저장 값(암호화 된것) , 입력 값(날 것))
def comparePassword(encrypted_pw, input_pw):
    """ DB : input (두 값이 같은지 비교) """
    ip_pepper = getPepperedPassword(input_pw)
    try:
        argon_pw.verify(encrypted_pw, ip_pepper)
        # admin_logger.info(f"{input_pw} 성공적")
        return True
    except VerifyMismatchError:
        # admin_logger.error(f"입력 불일치")
        return False
    except Exception as e:
        # admin_logger.error(f"검증 중 오류 발생: {e}")
        return False
