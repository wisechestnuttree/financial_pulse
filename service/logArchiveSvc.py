import asyncio
import json
import csv
import io
from datetime import datetime, timezone
from elasticsearch.helpers import scan
from dataStorage.elasticSearch.es import getEs
from model.logModel import LogSearchRequest
from service.logSvc import searchLog
from logs.logger import getLogger

logger = getLogger("system")

async def streamLogs(subject: str = None):
    """
    SSE - 실시간 로그 스트리밍
    - 2초마다 새 로그 조회하여 클라이언트에 전송
    - subject 필터로 특정 주제 로그만 스트리밍 가능
    """
    logger.info("실시간 로그 스트리밍 시작", extra={"subject": subject})
    last_timestamp = datetime.now(timezone.utc).isoformat()

    while True:
        req    = LogSearchRequest(subject=subject, start_time=last_timestamp, size=100)
        result = searchLog(req)

        for log in result["logs"]:
            last_timestamp = log["timestamp"]
            yield f"data: {json.dumps(log, ensure_ascii=False)}\n\n"

        await asyncio.sleep(2)


def archiveLogs(index: str, before_date: str) -> dict:
    """
    오래된 로그 아카이빙
    1. before_date 이전 로그 전체 추출
    2. JSONL 파일로 저장
    3. ES 인덱스에서 삭제
    """
    logger.info("로그 아카이빙 시작", extra={
        "index": index, "before_date": before_date
    })

    es   = getEs()
    docs = list(scan(
        es, index=index,
        query={"query": {"range": {"timestamp": {"lte": before_date}}}},
        size=10000
    ))
    archive = [doc["_source"] for doc in docs]
    output = io.StringIO()
    if archive:
        writer = csv.DictWriter(output, fieldnames=archive[0].keys())
        writer.writeheader()
        writer.writerows(archive)
    csv_bytes = ('\ufeff' + output.getvalue()).encode('utf-8')

    # ES에서 삭제
    es.delete_by_query(
        index=index,
        body={"query": {"range": {"timestamp": {"lte": before_date}}}}
    )
    es.close()

    logger.info("로그 아카이빙 완료", extra={
        "index": index, "archived_cnt": len(archive)
    })

    return csv_bytes, len(archive)