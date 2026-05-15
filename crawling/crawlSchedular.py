"""
crawlSchedular.py
통합 크롤링 스케줄러

[ 스케줄 ]
한국어 뉴스 : 07:30 / 11:30 / 18:30 / 23:59
영문 뉴스   : 07:30 / 21:00
경제지표    : 23:30 (1회)

[ 저장 대상 ]
한국어 : ES news_ko 인덱스
영문   : ES news_en 인덱스
경제지표: DB economicIndicator 테이블
"""

import json
import time
import uuid
from datetime import datetime

import requests
import schedule

import collectKoNews
import collectEnNews
from crawling.collectEconomic import dailyJob as runEconomicCrawl


# ================================================================
# 설정
# ================================================================
ES_HOST  = "http://100.88.143.23:9200"
KO_INDEX = "news_ko"
EN_INDEX = "news_en"

KO_SCHEDULES = [
    ("07:30", "새벽 마감"),
    ("11:30", "오전 흐름"),
    ("18:30", "초판"),
    ("23:59", "하루 마감"),
    ("09:40", "ko_test")
]

EN_SCHEDULES = [
    ("06:10", "미국 장 마감·한국 장 개장 직전"),
    ("21:00", "미국 장 개장 직전"),
    ("10:30","en_test")
]

ECONOMIC_SCHEDULE = "23:30"


# ================================================================
# ES 유틸
# ================================================================
def _ensure_index(index_name, use_nori=True):
    """
    인덱스 없으면 생성

    index_name : ES 인덱스명
    use_nori   : True → korean_analyzer, False → standard
    """
    url = f"{ES_HOST}/{index_name}"
    if requests.head(url).status_code == 200:
        print(f"[ES] '{index_name}' 인덱스 이미 존재")
        return

    analyzer = "korean" if use_nori else "standard"
    settings = {"number_of_shards": 1, "number_of_replicas": 0}

    if use_nori:
        settings["analysis"] = {
            "analyzer": {
                "korean": {
                    "type"     : "custom",
                    "tokenizer": "nori_tokenizer",
                    "filter"   : ["lowercase"],
                }
            }
        }

    mapping = {
        "settings": settings,
        "mappings": {
            "properties": {
                "doc_id"      : {"type": "keyword"},
                "lang"        : {"type": "keyword"},
                "url"         : {"type": "keyword"},
                "title"       : {"type": "text", "analyzer": analyzer},
                "content"     : {"type": "text", "analyzer": analyzer},
                "published_at": {
                    "type"  : "date",
                    "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time||epoch_millis"
                },
                "collected_at": {
                    "type"  : "date",
                    "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time||epoch_millis"
                },
            }
        },
    }

    res = requests.put(url, json=mapping)
    if res.status_code in (200, 201):
        print(f"[ES] '{index_name}' 인덱스 생성 완료")
    else:
        print(f"[ES] '{index_name}' 인덱스 생성 실패: {res.status_code} {res.text[:200]}")


def _bulk_index(index_name, rows):
    """
    Bulk API 일괄 색인

    index_name : ES 인덱스명
    rows       : [ { doc_id, lang, url, title, content, published_at, collected_at }, ... ]
    """
    if not rows:
        print(f"[ES] '{index_name}' 색인할 신규 데이터 없음")
        return

    lines = []
    for row in rows:
        doc_id = row.get("doc_id") or str(uuid.uuid4())
        lines.append({"index": {"_index": index_name, "_id": doc_id}})
        lines.append({
            "doc_id"      : doc_id,
            "lang"        : row.get("lang",         ""),
            "url"         : row.get("url",          ""),
            "title"       : row.get("title",        ""),
            "content"     : row.get("content",      ""),
            "published_at": row.get("published_at", ""),
            "collected_at": row.get("collected_at", ""),
        })

    ndjson = "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n"
    res    = requests.post(
        f"{ES_HOST}/_bulk",
        data    = ndjson.encode("utf-8"),
        headers = {"Content-Type": "application/x-ndjson"},
    )

    if res.status_code == 200:
        items    = res.json().get("items", [])
        ok_cnt   = sum(1 for i in items if i.get("index", {}).get("result") in ("created", "updated"))
        fail_cnt = len(items) - ok_cnt
        print(f"[ES] '{index_name}' 색인 완료: 성공 {ok_cnt}건 / 실패 {fail_cnt}건")
    else:
        print(f"[ES] Bulk 실패: {res.status_code} {res.text[:300]}")


# ================================================================
# 한국어 뉴스 수집 잡
# ================================================================
def run_ko_crawl(label):
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start = time.time()
    # 수정 제안
    line = '=' * 55
    print(f"\n{line}\n[KO 스케줄] {label} 수집 시작 ({now})\n{line}")

    rows     = collectKoNews.runStandaloneKo()
    seen     = set()
    new_rows = []
    for row in (rows or []):
        url = row.get("url", "")
        if url and url not in seen:
            seen.add(url)
            new_rows.append(row)

    print(f"[KO] 신규: {len(new_rows)}건")

    _ensure_index(KO_INDEX, use_nori=True)
    _bulk_index(KO_INDEX, new_rows)

    print(f"[KO 스케줄] {label} 종료 (소요: {time.time()-start:.1f}초)\n")


# ================================================================
# 영문 뉴스 수집 잡
# ================================================================
def run_en_crawl(label):
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start = time.time()
    # 수정 제안
    line = '=' * 55
    print(f"\n{line}\n[KO 스케줄] {label} 수집 시작 ({now})\n{line}")

    rows     = collectEnNews.runCollector()
    seen     = set()
    new_rows = []
    for row in (rows or []):
        url = row.get("url", "")
        if url and url not in seen:
            seen.add(url)
            new_rows.append(row)

    print(f"[EN] 신규: {len(new_rows)}건")

    _ensure_index(EN_INDEX, use_nori=False)
    _bulk_index(EN_INDEX, new_rows)

    print(f"[EN 스케줄] {label} 종료 (소요: {time.time()-start:.1f}초)\n")


# ================================================================
# 경제지표 수집 잡
# ================================================================
def run_economic_crawl():
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start = time.time()
    # 수정 제안
    line = '=' * 55
    print(f"\n{line}\n[KO 스케줄] 수집 시작 ({now})\n{line}")

    runEconomicCrawl()

    print(f"[ECO 스케줄] 종료 (소요: {time.time()-start:.1f}초)\n")


# ================================================================
# 스케줄 등록 및 실행
# ================================================================
def main():
    print("=" * 55)
    print("  통합 크롤링 스케줄러 시작")
    print("=" * 55)

    for run_time, label in KO_SCHEDULES:
        schedule.every().day.at(run_time).do(run_ko_crawl, label=label)
        print(f"  [KO]  {run_time} - {label}")

    for run_time, label in EN_SCHEDULES:
        schedule.every().day.at(run_time).do(run_en_crawl, label=label)
        print(f"  [EN]  {run_time} - {label}")

    schedule.every().day.at(ECONOMIC_SCHEDULE).do(run_economic_crawl)
    print(f"  [ECO] {ECONOMIC_SCHEDULE} - 경제지표 일일 수집")

    print("\n[스케줄러] 대기 중... (종료: Ctrl+C)\n")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
