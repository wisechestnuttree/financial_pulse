import csv, io

from dataStorage.elasticSearch.es import getEs, ALL_LOG_IDX
from model.logModel import LogSearchRequest
from logs.logger import getLogger

logger = getLogger("system")

def buildQuery(req: LogSearchRequest) -> dict:
    """
    로그 검색 쿼리 생성 공통 함수

    - subject → term 쿼리 (정확히 일치)
    - level   → term 쿼리 (정확히 일치)
    - 시간범위 → range 쿼리
    - keyword → match 쿼리 (형태소 분석 후 검색)
    """
    must = []

    if req.subject:
        must.append({"term": {"subject": req.subject}})

    if req.level:
        must.append({"term": {"level": req.level}})

    if req.start_time or req.end_time:
        time_range = {}
        if req.start_time: time_range["gte"] = req.start_time
        if req.end_time:   time_range["lte"] = req.end_time
        must.append({"range": {"timestamp": time_range}})

    if req.keyword:
        # match: 형태소 분석 후 검색 (부분 일치 가능)
        must.append({"match": {"message": req.keyword}})

    return {"bool": {"must": must}} if must else {"match_all": {}}

def searchLog(req: LogSearchRequest) -> dict:
    """
    필터 조건으로 fp-logs-all 에서 로그 조회
    - level, subject, 시간 범위 필터
    - 최신순 정렬
    """
    # subject에 따라 조회할 인덱스 결정
    index = f"logs_{req.subject}" if req.subject else ALL_LOG_IDX

    logger.info("로그 조회 시작", extra={"action": "searchLog", "index": index, "keyword": req.keyword})

    es   = getEs()
    query= buildQuery(req)

    result = es.search(
        index=index,
        body={
            "query": query,
            "sort":  [{"timestamp": {"order": "desc"}}],
            "size":  req.size
        }
    )

    logs = [hit["_source"] for hit in result["hits"]["hits"]]
    es.close()

    logger.info(f"로그 조회 완료 / cnt: {len(logs)}", extra={"action": "searchLog", "index": index})
    return {"total": len(logs), "logs": logs}


def getLogSummary(subject: str = None) -> dict:
    """
    로그 집계 조회
    - logViewer 상단 집계 카드 (총로그/ERROR/WARN/SUCCESS) 처리
    - crawCon 상단 집계 카드 처리
    """
    es   = getEs()
    index = f"logs_{subject}" if subject else ALL_LOG_IDX

    result = es.search(
        index=index,
        body={
            "query": {"match_all": {}},
            "aggs": {
                # 레벨별 집계
                "by_level": {
                    "terms": {"field": "level", "size": 10}
                },
                # 가장 최근 로그 시각
                "latest": {
                    "max": {"field": "timestamp"}
                }
            },
            "size": 0  # 집계만 필요하므로 도큐먼트는 가져오지 않음
        }
    )

    # 레벨별 집계 결과 파싱
    buckets   = result["aggregations"]["by_level"]["buckets"]
    level_map = {b["key"]: b["doc_count"] for b in buckets}
    latest    = result["aggregations"]["latest"]

    summary = {
        "total":   result["hits"]["total"]["value"],
        "error":   level_map.get("ERROR",   0),
        "warning": level_map.get("WARNING", 0),
        "info":    level_map.get("INFO",    0),
        "latest":  latest.get("value_as_string") if latest.get("value") else None
    }

    es.close()
    return summary


def exportLogCsv(req: LogSearchRequest) -> str:
    """
    로그 조회 결과를 CSV 형식으로 변환
    - logViewer의 CSV 내보내기 버튼 처리
    - BOM(utf-8-sig) 추가로 한글 깨짐 방지
    """
    import csv
    import io

    logger.info("CSV 내보내기 시작", extra={"action": "exportLogCsv"})

    result = searchLog(req)
    logs   = result["logs"]

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["timestamp", "subject", "level", "message", "extra"]
    )
    writer.writeheader()

    for log in logs:
        writer.writerow({
            "log_id":    log.get("log_id", ""),
            "timestamp": log.get("timestamp", ""),
            "subject":   log.get("subject", ""),
            "level":     log.get("level", ""),
            "message":   log.get("message", ""),
            "extra":     str(log.get("extra", {}))
        })

    logger.info(f"CSV 내보내기 완료 /export_cnt: {len(logs)}", extra={"action": "exportLogCsv"})

    # BOM 추가 (한글 깨짐 방지)
    return "\ufeff" + output.getvalue()


