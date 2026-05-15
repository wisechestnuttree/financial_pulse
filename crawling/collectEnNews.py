import re
import warnings
import time
import datetime as dt
import threading
from datetime import datetime
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
import feedparser
import requests
from elasticsearch import Elasticsearch
from dateutil import parser

# 유틸리티 로직 임포트 (좀비 프로세스 정리는 managed_driver 내부의 atexit 등이 담당)
from utils.crawlerUtils import extract_content_with_js, generate_hash_id, managed_driver
from utils.cleaningUtils import NewsCleaner

# [설정]
INDEX_NAME = 'news_en'
ES_URL = 'http://100.88.143.23:9200'
TARGET_KEYWORDS = [
    "US Economy", "Federal Reserve", "Interest Rates",
    "Nasdaq Composite", "S&P 500", "Monetary Policy",
    "Inflation CPI", "Wall Street"
]
MAX_WORKERS = 2
es = Elasticsearch(ES_URL)

# 한국 표준시(KST) 설정
KST = dt.timezone(dt.timedelta(hours=9))

warnings.filterwarnings("ignore", category=parser.UnknownTimezoneWarning)

total_processed_count = 0
counter_lock = threading.Lock()


# ---------------------------------------------------------------------------

def process_batch(targets, thread_id, total_target_count, batch_collected_at):
    """기사 1건마다 ES에 즉시 적재 (뉴욕 시간 강제 변환 및 상대 시간 계산)"""
    global total_processed_count
    local_success_count = 0

    # managed_driver가 생성, 추적 리스트 등록, 종료(quit)를 모두 알아서 처리함
    with managed_driver() as driver:
        for target in targets:
            try:
                raw_pub = target.get('raw_published', '').strip()
                published_at = None

                # [필터링] 10 hours ago 형태거나 시:분(HH:mm)이 포함되어 있어야 함 (B 제거)
                has_time = re.search(r'\d{1,2}:\d{2}', raw_pub)
                is_relative = "ago" in raw_pub.lower()

                if not (has_time or is_relative):
                    continue  # 시분 정보가 없는 데이터는 버림

                # [날짜 가공]
                try:
                    if is_relative:
                        # 1. '10 hours ago' 형태 처리
                        num_match = re.search(r'\d+', raw_pub)
                        if not num_match: continue
                        num = int(num_match.group())
                        now_kst = datetime.now(KST)

                        if "hour" in raw_pub:
                            published_at_dt = now_kst - dt.timedelta(hours=num)
                        elif "minute" in raw_pub:
                            published_at_dt = now_kst - dt.timedelta(minutes=num)
                        elif "day" in raw_pub:
                            published_at_dt = now_kst - dt.timedelta(days=num)
                        else:
                            published_at_dt = now_kst
                        published_at = published_at_dt.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        # 2. 절대 시간 파싱 시도
                        try:
                            parsed_dt = parser.parse(raw_pub)
                            if parsed_dt.tzinfo is None:
                                # 타임존 없으면 뉴욕(EDT) 간주 후 KST 변환 (+13)
                                parsed_dt = parsed_dt.replace(tzinfo=dt.timezone(dt.timedelta(hours=-4)))
                            published_at = parsed_dt.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            # 파싱 에러 시 시:분 추출하여 뉴욕 시간 강제 적용
                            time_match = re.search(r'(\d{1,2}):(\d{2})', raw_pub)
                            if time_match:
                                hr, mn = map(int, time_match.groups())
                                ny_dt = datetime.now(KST).replace(hour=hr, minute=mn, second=0)
                                published_at = (ny_dt + dt.timedelta(hours=13)).strftime('%Y-%m-%d %H:%M:%S')

                except Exception:
                    continue

                if not published_at:
                    continue

                # 3. URL 정제 및 ID 생성
                clean_url = target['url'].split('?')[0].split('#')[0].strip()
                doc_id = generate_hash_id(clean_url, target['title'])

                if es.exists(index=INDEX_NAME, id=doc_id):
                    continue

                # 4. 본문 수집
                driver.get(target['url'])
                time.sleep(3)
                content = extract_content_with_js(driver, title=target['title'])

                if not content or len(content.strip()) < 150:
                    continue

                clean_content = NewsCleaner.clean(content)
                if not NewsCleaner.is_valid(clean_content, target['title']):
                    continue

                # 5. 데이터 적재
                doc = {
                    "doc_id": doc_id,
                    "url": clean_url,
                    "lang": "en",
                    "title": target['title'],
                    "content": clean_content,
                    "published_at": published_at,
                    "collected_at": batch_collected_at
                }

                es.index(index=INDEX_NAME, id=doc_id, document=doc)

                local_success_count += 1
                with counter_lock:
                    total_processed_count += 1
                    print(f"[EN] ({total_processed_count}/{total_target_count}) 성공: '{target['title'][:30]}...'")

            except Exception:
                continue

    return local_success_count


def run_collector(start_str=None, end_str=None):
    global total_processed_count
    is_today_mode = not start_str
    if is_today_mode:
        start_str = datetime.now(KST).strftime('%Y-%m-%d')
    if not end_str:
        end_str = start_str

    start_date = datetime.strptime(start_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_str, '%Y-%m-%d')

    current = start_date
    while current <= end_date:
        total_processed_count = 0
        target_day = current.strftime('%Y-%m-%d')
        batch_collected_at = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

        print(f"\n--- {target_day} 목록 수집 시작 ---")

        all_targets = []
        for kw in TARGET_KEYWORDS:
            print(f"[{target_day}] Google News 검색 중: {kw}...")
            query_str = f"{kw}"
            if not is_today_mode:
                query_str += f" after:{target_day} before:{(current + dt.timedelta(days=1)).strftime('%Y-%m-%d')}"

            rss_url = f"https://news.google.com/rss/search?q={quote(query_str)}&hl=en-US&gl=US&ceid=US:en"

            try:
                resp = requests.get(rss_url, timeout=10)
                feed = feedparser.parse(resp.content)
                for e in feed.entries:
                    all_targets.append({
                        "title": e.title,
                        "url": e.link,
                        "raw_published": e.get('published', '')
                    })
            except:
                continue

        print(f"[{target_day}] 목록 수집 완료. 총 {len(all_targets)}건 발견.")

        seen_titles = set()
        unique_targets = []
        for it in all_targets:
            title_key = re.sub(r'[^a-z0-9]', '', it['title'].lower())
            if title_key not in seen_titles and len(it['title']) > 5:
                seen_titles.add(title_key)
                unique_targets.append(it)

        print(f"[{target_day}] 중복 제거 후 최종 대상: {len(unique_targets)}건")

        total_len = len(unique_targets)
        if unique_targets:
            chunk_size = (total_len // MAX_WORKERS) + 1
            chunks = [unique_targets[i:i + chunk_size] for i in range(0, total_len, chunk_size)]
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exc:
                futures = [exc.submit(process_batch, c, i, total_len, batch_collected_at) for i, c in enumerate(chunks)]
                for f in as_completed(futures): f.result()

        current += dt.timedelta(days=1)


if __name__ == "__main__":
    run_collector()