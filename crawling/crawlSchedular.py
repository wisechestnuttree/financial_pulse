""" <<<참고용>>>
통합 크롤링 스케줄러
─────────────────────────────────────────
[한국어] 07:30 / 11:30 / 18:30 / 23:59
[영문]   07:30 (미국 장 마감·한국 장 개장 직전)
         21:00 (미국 장 개장 직전)
─────────────────────────────────────────
저장 대상
  - 한국어: CSV(ml_input_news.csv) + ES 인덱스 ko_test
  - 영문:   ES 인덱스 en_test  (CSV 저장 없음)
"""

import csv
import json
import os
import time
import uuid
from datetime import datetime

import requests
import schedule

import hankyungCrawl
import naverCrawl
import googleCrawl
import yahooCrawl

# ── 설정 ──────────────────────────────────────────
KO_CSV_FILE   = "ml_input_news.csv"
KO_FIELDNAMES = ["doc_id", "lang", "url", "title", "content", "published_at", "collected_at"]

ES_HOST   = "http://192.168.0.129:9200"
KO_INDEX  = "ko_test"
EN_INDEX  = "en_test"

KO_SCHEDULES = [
    ("07:30", "새벽 마감"),
    ("11:30", "오전 흐름"),
    ("18:30", "초판"),
    ("23:59", "하루 마감"),
]

EN_SCHEDULES = [
    ("07:30", "미국 장 마감·한국 장 개장 직전"),
    ("21:00", "미국 장 개장 직전"),
    ("11:45","test")
]


# ── CSV 유틸 (한국어 전용) ─────────────────────────

def _load_existing_urls():
    try:
        with open(KO_CSV_FILE, "r", encoding="utf-8-sig") as f:
            return {row["url"] for row in csv.DictReader(f) if row.get("url")}
    except FileNotFoundError:
        return set()


def _append_csv(rows):
    is_new = not os.path.exists(KO_CSV_FILE)
    with open(KO_CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=KO_FIELDNAMES)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


# ── ES 유틸 ───────────────────────────────────────

def _ensure_index(index_name, use_nori=True):
    """인덱스가 없으면 생성. use_nori=False 이면 standard analyzer 사용."""
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
                    "type":      "custom",
                    "tokenizer": "nori_tokenizer",
                    "filter":    ["lowercase"],
                }
            }
        }

    mapping = {
        "settings": settings,
        "mappings": {
            "properties": {
                "doc_id":       {"type": "keyword"},
                "lang":         {"type": "keyword"},
                "url":          {"type": "keyword"},
                "title":        {"type": "text", "analyzer": analyzer},
                "content":      {"type": "text", "analyzer": analyzer},
                "published_at": {
                    "type":   "date",
                    "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time||epoch_millis"
                },
                "collected_at": {
                    "type":   "date",
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
    """Bulk API로 일괄 색인. doc_id 없으면 UUID 자동 생성."""
    if not rows:
        print(f"[ES] '{index_name}' 색인할 신규 데이터 없음")
        return

    lines = []
    for row in rows:
        doc_id = row.get("doc_id") or str(uuid.uuid4())
        meta   = {"index": {"_index": index_name, "_id": doc_id}}
        doc    = {
            "doc_id":       doc_id,
            "lang":         row.get("lang", ""),
            "url":          row.get("url", ""),
            "title":        row.get("title", ""),
            "content":      row.get("content", ""),
            "published_at": row.get("published_at", ""),
            "collected_at": row.get("collected_at", ""),
        }
        lines.append(meta)
        lines.append(doc)

    ndjson = "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n"
    res = requests.post(
        f"{ES_HOST}/_bulk",
        data=ndjson.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
    )

    if res.status_code == 200:
        result   = res.json()
        items    = result.get("items", [])
        ok_cnt   = sum(1 for i in items if i.get("index", {}).get("result") in ("created", "updated"))
        fail_cnt = len(items) - ok_cnt
        print(f"[ES] '{index_name}' 색인 완료: 성공 {ok_cnt}건 / 실패 {fail_cnt}건")
    else:
        print(f"[ES] Bulk 실패: {res.status_code} {res.text[:300]}")


# ── 한국어 수집 잡 ────────────────────────────────

def run_ko_crawl(label):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*55}")
    print(f"[KO 스케줄] {label} 수집 시작 ({now})")
    print(f"{'='*55}")
    start = time.time()

    hankyung_rows = hankyungCrawl.run()
    naver_rows    = naverCrawl.run()

    # CSV 기준 중복 제거
    existing_urls = _load_existing_urls()
    print(f"[KO 통합] 기존 누적: {len(existing_urls)}건")

    seen = set(existing_urls)
    new_rows = []
    for row in naver_rows + hankyung_rows:   # 네이버 우선
        url = row.get("url", "")
        if url and url not in seen:
            seen.add(url)
            new_rows.append(row)

    total = len(naver_rows) + len(hankyung_rows)
    print(f"[KO 통합] 신규: {len(new_rows)}건 / 중복 제거: {total - len(new_rows)}건")

    # CSV 저장
    _append_csv(new_rows)
    print(f"[KO 통합] CSV 저장 완료 → {KO_CSV_FILE}")

    # ES 색인
    _ensure_index(KO_INDEX, use_nori=True)
    _bulk_index(KO_INDEX, new_rows)

    print(f"[KO 스케줄] {label} 종료 (소요: {time.time()-start:.1f}초)\n")


# ── 영문 수집 잡 ──────────────────────────────────

def run_en_crawl(label):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*55}")
    print(f"[EN 스케줄] {label} 수집 시작 ({now})")
    print(f"{'='*55}")
    start = time.time()

    google_rows = googleCrawl.run()
    yahoo_rows  = yahooCrawl.run()

    # 이번 회차 내 중복 제거 (Google 우선)
    seen, new_rows = set(), []
    for row in google_rows + yahoo_rows:
        url = row.get("url", "")
        if url and url not in seen:
            seen.add(url)
            new_rows.append(row)

    total = len(google_rows) + len(yahoo_rows)
    print(f"[EN 통합] 수집: {len(new_rows)}건 / 중복 제거: {total - len(new_rows)}건")

    # ES 색인만 (CSV 없음)
    _ensure_index(EN_INDEX, use_nori=False)
    _bulk_index(EN_INDEX, new_rows)

    print(f"[EN 스케줄] {label} 종료 (소요: {time.time()-start:.1f}초)\n")


# ── 스케줄 등록 및 실행 ───────────────────────────

def main():
    print("=" * 55)
    print("  통합 크롤링 스케줄러 시작")
    print("=" * 55)

    for run_time, label in KO_SCHEDULES:
        schedule.every().day.at(run_time).do(run_ko_crawl, label=label)
        print(f"  [KO] {run_time} - {label}")

    for run_time, label in EN_SCHEDULES:
        schedule.every().day.at(run_time).do(run_en_crawl, label=label)
        print(f"  [EN] {run_time} - {label}")

    print("\n[스케줄러] 대기 중... (종료: Ctrl+C)\n")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
