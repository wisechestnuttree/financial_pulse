'''
[ 코딩 규칙 ]
1. 매개변수 작성할 때 , 뒤에는 공백 필수
    ex) def example(num1, num2)

2. 필드, 코드 지역에 선언되는 변수는 SNAKE 기법을 사용.
    ex) df_list = ...
        csv_to_df = ...

3. 함수명, 클래스명은 CAMEL 기법을 사용.
    ex) def getNewsCrawler()
        def setInfo()
        class MLBERTopic

4. 들여쓰기는 공백 4칸으로 통일.

5. 변수명, 함수명, 클래스명을 만들 때 - 어떤 기능, 행동을 하는지 의미를 포함해 만들어야 한다.
    ex) 데이터 프레임을 리스트화 한 것 : df_list = ...
        회원정보 테이블 조회 기능 : def getUserInfo()
        토픽 모델링에 관한 코드가 있는 클래스 : class NewsTopicModeling

    줄여쓰기는 가능하다, BUT 가급적 풀어서 쓰는 것을 권장

6. 각 폴더의 txt 파일에 날짜와 수정 사항을 기록한다.

7. 주석은 간단 명료하게 작성한다.
   행동 과정까지 작성할 필요는 없다.
   해당 코드를 통해 어떤 결과를 얻으려 하는지, 어떤 기능인지 작성

8. 로그 형식
    [시간] [level] [trace_id] [주체] [message]
    * trace_id= 로그의 고유 식별자 느낌으로 검색에 용이
        : 기능_날짜_시간 형식으로 작성
            추후 _ split을 통해 구분.

* 추후 개발
기사 요약 -by 서율
'''

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
import os
from dotenv import load_dotenv
from router.dashboardRouter import router as dashboardRouter
from router.keywordRouter import router as keywordRouter
from router.spikeRouter import router as spikeRouter
from router.searchRouter import router as searchRouter
from router.adminRouter import router as adminRouter
from router.logRouter import router as logRouter
from router.crawlRouter import router as crawlRouter
from router.esRouter import router as esRouter
from router.correctionRouter import router as correctionRouter
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

app = FastAPI()

# ── HTML 라우트 (마운트보다 먼저 등록) ──
@app.get("/")
def root():
    return FileResponse("view/index.html")

@app.get("/{filename}.html")
def serve_html(filename: str):
    import os
    path = f"view/{filename}.html"
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"success": False, "message": "페이지를 찾을 수 없습니다.", "data": None})
    return FileResponse(path)

# ================================================================
# 세션 미들웨어 등록
# secret_key : 세션 쿠키 서명에 사용 — 반드시 .env에서 관리
# max_age    : 세션 유지 시간 (초 단위, 3600 = 1시간)
# https_only : 운영 환경에서는 반드시 True (HTTPS 전용)
# ================================================================
app.add_middleware(
    SessionMiddleware,
    secret_key = os.getenv("SESSION_SECRET_KEY"),
    max_age    = 3600,
    https_only = False,     # TODO: 운영 배포 시 True 로 변경
)


# ================================================================
# 공통 에러 핸들러
# ================================================================
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "data"   : None
        }
    )


# ================================================================
# 라우터 등록
# ================================================================
from router.memberRouter import router as memberRouter

app.include_router(memberRouter)
app.include_router(dashboardRouter)
app.include_router(keywordRouter)
app.include_router(spikeRouter)
app.include_router(searchRouter)
app.include_router(adminRouter)
app.include_router(logRouter)
app.include_router(crawlRouter)
app.include_router(esRouter)
app.include_router(correctionRouter)

app.mount("/", StaticFiles(directory="view"), name="static")