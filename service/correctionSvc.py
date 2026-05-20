import json
from elasticsearch.helpers import scan
from dataStorage.elasticSearch.es import getEs, ANALYZE_DATA_IDX
from logs.logger import getLogger


logger = getLogger("ml")

def detectIrregular() -> dict:
    """
    비정형 감지 - tend_score 95 이상 또는 5 이하 기사 탐지
    → dataCon UI 검토 필요 목록 처리
    """
    logger.info("비정형 감지 시작", extra={"action": "detectIrregular"})

    es = getEs()
    result = es.search(
        index=ANALYZE_DATA_IDX,
        body={
            "query": {"bool": {"should": [
                {"range": {"tend_score": {"gte": 95}}},
                {"range": {"tend_score": {"lte":  5}}}
            ]}},
            "_source": ["doc_id", "title", "url", "tend_score", "tendency"],
            "size": 1000
        }
    )
    docs = []
    for hit in result["hits"]["hits"]:
        source = hit["_source"]
        doc_id = source.get("doc_id") or hit["_id"]

        # news_ko → news_en 순으로 url 조회
        url = None
        for index in ["news_ko", "news_en"]:
            try:
                news_res = es.get(index=index, id=doc_id, _source=["url"])
                url = news_res["_source"].get("url")
                if url:
                    break
            except:
                continue

        source["url"] = url
        docs.append(source)

    es.close()

    logger.info(f"비정형 감지 완료 ({len(docs)})", extra={"action": "detectIrregular"})
    return {"total": len(docs), "docs": docs}


def applyCorrection(doc_id: str, tendency: str, tend_score: float) -> dict:
    """
    관리자 보정 확정
    1. analyze 인덱스 업데이트
    2. search  인덱스 업데이트
    3. 보정 로그 자동 기록 (logger → ESHandler → logs_ml)
    """
    logger.info("보정 확정 시작", extra={
        "action": "applyCorrection", "doc_id": doc_id, "tendency": tendency, "tend_score": tend_score})

    es = getEs()
    update_body = {"doc": {"tendency": tendency, "tend_score": tend_score}}

    es.update(index=ANALYZE_DATA_IDX, id=doc_id, body=update_body)
    # es.update(index=SEARCH_INDEX,  id=doc_id, body=update_body)
    es.close()

    logger.info("보정 확정 완료", extra={
        "action": "applyCorrection", "doc_id": doc_id, "tendency": tendency, "tend_score": tend_score})
    return {"doc_id": doc_id, "tendency": tendency, "tend_score": tend_score, "status": "보정 완료"}


def deleteArticle(doc_id: str) -> dict:
    """
    기사 삭제 - dataCon UI '삭제' 버튼 처리
    - analyze + search 인덱스에서 동시 삭제
    """
    logger.warning("기사 삭제 시작", extra={"doc_id": doc_id})

    es = getEs()
    es.delete(index=ANALYZE_DATA_IDX, id=doc_id)
    # es.delete(index=SEARCH_INDEX,  id=doc_id)
    es.close()

    logger.warning("기사 삭제 완료", extra={"action": "deleteArticle", "doc_id": doc_id})
    return {"doc_id": doc_id, "status": "삭제 완료"}


def exportCorrections(start_time: str, end_time: str) -> list:
    """
    보정 완료된 학습 데이터 JSONL 형식으로 내보내기
    - logs_ml 에서 "보정 확정" 로그 조회
    - ML 모델 재학습 데이터로 활용
    """
    logger.info("학습 데이터 내보내기 시작", extra={
        "action": "exportCorrections", "start_time": start_time, "end_time": end_time})

    es = getEs()
    docs = scan(
        es, index="logs_ml",
        query={
            "query": {"bool": {"must": [
                {"match": {"message": "보정 확정"}},
                {"range": {"timestamp": {"gte": start_time, "lte": end_time}}}
            ]}}
        },
        size=10000
    )
    jsonl = [json.dumps(doc["_source"]["extra"], ensure_ascii=False) for doc in docs]
    es.close()

    logger.info("학습 데이터 내보내기 완료", extra={"action": "exportCorrections", "export_cnt": len(jsonl)})
    return jsonl