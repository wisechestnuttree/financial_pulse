# ok 함수 여기에 정의
from fastapi.responses import JSONResponse
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
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

SECTOR_KO = {
    "Tech"             : "IT/기술",
    "Finance"          : "금융",
    "Industry"         : "중공업/인프라",
    "Consumer"         : "소비재/서비스",
    "Healthcare"       : "바이오/헬스",
    "Mobility"         : "모빌리티",
    "Macro & Policy"   : "매크로/정책",
}

SECTOR_EN = {v: k for k, v in SECTOR_KO.items()}
# 결과: { "IT/기술": "Tech", "금융": "Finance", ... }

def translateSectorToEn(name: str) -> str:
    return SECTOR_EN.get(name, name)

def translateSector(name: str) -> str:
    return SECTOR_KO.get(name, name)

def getDocIds(es, index: str, date_from: str, date_to: str, size: int = 10000) -> list:
    res = es.search(
        index = index,
        body  = {
            "query"  : {"range": {"published_at": {"gte": date_from, "lte": date_to}}},
            "_source": ["doc_id"],
            "size"   : size
        }
    )
    return [hit["_source"]["doc_id"] for hit in res["hits"]["hits"]]

KST = ZoneInfo("Asia/Seoul")

KO_SCHEDULES = ["07:30", "11:30", "18:30", "23:59"]
EN_SCHEDULES = ["06:10", "21:00"]

def getTodayRange(lang: str) -> tuple[str, str]:
    now = datetime.now(KST)
    today = now.date()
    current_time = now.strftime("%H:%M")

    schedules = KO_SCHEDULES if lang == "ko" else EN_SCHEDULES

    # 현재 시간 기준 가장 최근 크롤링 시간 찾기
    last_crawl = None
    for sched in schedules:
        if current_time >= sched:
            last_crawl = sched
        else:
            break

    if last_crawl is None:
        # 오늘 첫 크롤링 이전 → 전날 마지막 크롤링
        last_crawl = schedules[-1]
        end_dt = datetime.strptime(f"{today - timedelta(days=1)} {last_crawl}", "%Y-%m-%d %H:%M")
    else:
        end_dt = datetime.strptime(f"{today} {last_crawl}", "%Y-%m-%d %H:%M")

    start_dt = end_dt - timedelta(hours=24)
    real_dt= now

    return start_dt.strftime("%Y-%m-%d %H:%M:%S"), real_dt.strftime("%Y-%m-%d %H:%M:%S")