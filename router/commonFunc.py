# ok 함수 여기에 정의
from fastapi.responses import JSONResponse
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