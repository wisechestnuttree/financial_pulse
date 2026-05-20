from elasticsearch.helpers import scan
from dataStorage.elasticSearch.es import getEs, NEWS_KO_IDX, NEWS_EN_IDX, ANALYZE_DATA_IDX
from logs.logger import getLogger

logger = getLogger("system")



# def runIntegrityCheck(batch_id: str, lang: str = "ko") -> dict:
#     """
#     정합성 검사 - crawl_cnt vs save_cnt 비교
#     - diff = 0  : 정상
#     - diff > 0  : 누락 발생
#     """
#     logger.info("정합성 검사 시작", extra={"batch_id": batch_id, "lang": lang})
#
#     es           = getEs()
#     target_index = NEWS_KO_IDX if lang == "ko" else NEWS_EN_IDX
#
#     # 크롤링 종료 로그에서 crawl_cnt 조회
#     log_result = es.search(
#         index="logs_crawl",
#         body={
#             "query": {"bool": {"must": [
#                 {"term":  {"extra.batch_id": batch_id}},
#                 {"match": {"message": "크롤링 배치 종료"}}
#             ]}},
#             "size": 1
#         }
#     )
#
#     crawl_cnt = 0
#     if log_result["hits"]["hits"]:
#         crawl_cnt = log_result["hits"]["hits"][0]["_source"]["extra"].get("crawl_cnt", 0)
#
#     save_result = es.count(
#         index=target_index,
#         body={"query": {"term": {"extra.batch_id": batch_id}}}
#     )
#     save_cnt = save_result["count"]
#     diff     = crawl_cnt - save_cnt
#     status   = "정상" if diff == 0 else "불일치"
#
#     if diff == 0:
#         logger.info(f"정합성 검사 결과: {status}", extra={
#             "batch_id": batch_id, "crawl_cnt": crawl_cnt,
#             "save_cnt": save_cnt, "diff": diff
#         })
#     else:
#         logger.warning(f"정합성 검사 결과: {status}", extra={
#             "batch_id": batch_id, "crawl_cnt": crawl_cnt,
#             "save_cnt": save_cnt, "diff": diff
#         })
#
#     es.close()
#     return {
#         "batch_id":  batch_id,
#         "crawl_cnt": crawl_cnt,
#         "save_cnt":  save_cnt,
#         "diff":      diff,
#         "status":    status
#     }


def getMissingUrl(lang: str = "ko") -> dict:
    """
    URL 집합 비교로 누락 URL 특정
    - 크롤링 시도한 URL 집합 (로그에서 추출)
    - 실제 저장된 URL 집합 (뉴스 인덱스에서 추출)
    - 차집합 = 누락 URL
    """
    logger.info("URL 비교 시작", extra={"action":"getMissingUrl", "lang": lang})

    es = getEs()
    target_index = NEWS_KO_IDX if lang == "ko" else NEWS_EN_IDX

    log_docs = scan(
        es, index="logs_crawl",
        query={"query": {"match_all": {}}},
        size=10000
    )
    crawled_urls = {
        doc["_source"]["extra"]["url"]
        for doc in log_docs
        if "url" in doc["_source"].get("extra", {})
    }

    saved_docs = scan(
        es, index=target_index,
        query={"query": {"match_all": {}}},
        size=10000
    )
    saved_urls   = {doc["_source"]["url"] for doc in saved_docs}
    missing_urls = list(crawled_urls - saved_urls)

    logger.info(f"URL 비교 완료 ({len(missing_urls)} 차이)"
                , extra={"action":"getMissingUrl", "lang": lang})

    es.close()
    return {
        "lang": lang,
        "missing_cnt": len(missing_urls),
        "missing_urls": missing_urls
    }


def recollectMissing(lang: str = "ko") -> dict:
    """누락 URL 재수집"""
    from service.crawlSvc import runCrawlBatch

    result = getMissingUrl(lang=lang)
    missing_urls = result["missing_urls"]

    if not missing_urls:
        logger.info("누락 URL 없음"
                    , extra={"action":"recollectMissing", "lang": lang})
        return {"message": "누락 URL 없음"}

    logger.info("누락 URL 재수집 시작"
                , extra={"action":"recollectMissing", "lang": lang})
    return runCrawlBatch(urls=missing_urls, lang=lang)


def getIndexStatus() -> dict:
    """
    전체 인덱스 현황 조회
    - esCon UI 인덱스 현황 테이블 처리
    - 인덱스별 건수 / crawl_cnt / save_cnt / missing_cnt 반환
    """
    logger.info("인덱스 현황 조회 시작", extra={"action":"getIndexStatus"})

    es = getEs()
    indices = [
        {"name": "news_ko", "index": NEWS_KO_IDX},
        {"name": "news_en", "index": NEWS_EN_IDX},
        {"name": "analyze", "index": ANALYZE_DATA_IDX},
        {"name": "logs_crawl", "index": "logs_crawl"},
        {"name": "logs_ml", "index": "logs_ml"},
    ]

    result = []
    for target in indices:
        # 전체 건수
        count_result = es.count(index=target["index"])
        total = count_result["count"]

        # crawl_cnt (크롤링 로그에서 최신 배치 기준)
        crawl_cnt = None
        save_cnt = None
        missing_cnt = 0

        if target["index"] in [NEWS_KO_IDX, NEWS_EN_IDX]:
            log_result = es.search(
                index="logs_crawl",
                body={
                    "query": {"match": {"message": "크롤링 배치 종료"}},
                    "sort": [{"timestamp": {"order": "desc"}}],
                    "size": 1
                }
            )
            if log_result["hits"]["hits"]:
                extra     = log_result["hits"]["hits"][0]["_source"]["extra"]
                crawl_cnt = extra.get("crawl_cnt", 0)
                save_cnt  = total
                missing_cnt = max(0, crawl_cnt - save_cnt)

        status = "누락감지" if missing_cnt > 0 else "정상"

        result.append({
            "index":       target["name"],
            "total":       total,
            "crawl_cnt":   crawl_cnt,
            "save_cnt":    save_cnt,
            "missing_cnt": missing_cnt,
            "status":      status
        })

    es.close()
    logger.info("인덱스 현황 조회 완료", extra={"action": "getIndexStatus"})
    return {"indices": result}