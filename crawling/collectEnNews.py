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

# 유틸리티 로직 임포트
from crawling.actions.crawlUtil import  getDriver, extractContentWithJS, generateHashId
from crawling.actions.cleaningUtil import NewsCleaner

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

warnings.filterwarnings("ignore", category=parser.UnknownTimezoneWarning)

# 전역 카운터 및 락
total_processed_count = 0
counter_lock = threading.Lock()


def processBatch(targets, thread_id, total_target_count):
    """기사 1건마다 ES에 즉시 적재하는 로직 (자원 해제 보강)"""
    global total_processed_count
    local_success_count = 0

    print(f"[Thread-{thread_id}] 브라우저 가동 (담당 {len(targets)}건)")

    # 1. managed_driver를 사용하여 with 블록 종료 시 무조건 quit 호출
    from crawling.actions.crawlUtil import managedDriver

    with managedDriver() as driver:
        driver.set_page_load_timeout(25)

        for target in targets:
            try:
                # 1. URL 정제 및 ID 생성
                clean_url = target['url'].split('?')[0].split('#')[0].strip()
                doc_id = generateHashId(clean_url, target['title'])

                # 2. 중복 체크 (ES 서버 레벨)
                if es.exists(index=INDEX_NAME, id=doc_id):
                    continue

                # 3. 본문 수집
                driver.get(target['url'])
                time.sleep(3)

                content = extractContentWithJS(driver, title=target['title'])

                # 4. 본문 길이 및 클리닝 검증
                if not content or len(content.strip()) < 150:
                    continue

                clean_content = NewsCleaner.clean(content)
                if not NewsCleaner.isValid(clean_content, target['title']):
                    continue

                # 5. 데이터 준비
                doc = {
                    "doc_id": doc_id,
                    "url": clean_url,
                    "lang": "en",
                    "title": target['title'],
                    "content": clean_content,
                    "published_at": datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                    "collected_at": datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
                }

                # 6. ES 개별 적재
                es.index(index=INDEX_NAME, id=doc_id, document=doc)

                local_success_count += 1
                with counter_lock:
                    total_processed_count += 1
                    print(f"[EN] 성공: ({total_processed_count}/{total_target_count}) {target['title'][:30]}...")

            except Exception:
                # 개별 기사 처리 중 에러가 나도 다음 기사로 진행 (드라이버는 유지)
                continue

    # with 블록을 나가는 순간 driver.quit()이 자동 호출됩니다.
    return local_success_count


def runCollector(start_str=None, end_str=None):

    is_today_mode = not start_str
    if is_today_mode:
        start_str = datetime.now().strftime('%Y-%m-%d')
    if not end_str:
        end_str = start_str

    start_date = datetime.strptime(start_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_str, '%Y-%m-%d')

    current = start_date
    while current <= end_date:
        target_day = current.strftime('%Y-%m-%d')
        next_day = (current + dt.timedelta(days=1)).strftime('%Y-%m-%d')
        all_targets = []

        print(f"--- {target_day} 뉴스 검색 시작 ---")
        for kw in TARGET_KEYWORDS:
            query_str = f'"{kw}"'
            if not is_today_mode:
                query_str += f" after:{target_day} before:{next_day}"

            rss_url = f"https://news.google.com/rss/search?q={quote(query_str)}&hl=en-US&gl=US&ceid=US:en"

            try:
                resp = requests.get(rss_url, timeout=10)
                feed = feedparser.parse(resp.content)
                for e in feed.entries:
                    all_targets.append({"title": e.title, "url": e.link})
            except:
                continue

        # 제목 기준 중복 제거
        seen_titles = set()
        unique_targets = []
        for it in all_targets:
            title_key = re.sub(r'[^a-zA-Z0-9가-힣]', '', it['title']).lower()
            if title_key not in seen_titles and len(it['title']) > 5:
                seen_titles.add(title_key)
                unique_targets.append(it)

        total_len = len(unique_targets)
        print(f"분석 대상: 총 {total_len}건 (중복 제거 완료)")

        if unique_targets:
            chunk_size = (total_len // MAX_WORKERS) + 1
            chunks = [unique_targets[i:i + chunk_size] for i in range(0, total_len, chunk_size)]

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exc:
                futures = [exc.submit(processBatch, c, i, total_len) for i, c in enumerate(chunks)]
                for f in as_completed(futures):
                    f.result()

        print(f"--- {target_day} 작업 완료 ---")
        current += dt.timedelta(days=1)


if __name__ == "__main__":
    # --- 날짜 지정 사용 방법 ---

    # 1. 오늘 날짜만 수집할 때:
    runCollector()

    # 2. 특정 하루만 수집할 때:
    # run_collector(start_str="2026-05-01")

    # 3. 특정 기간 범위를 수집할 때 (예: 5월 1일 ~ 5월 5일):
    #run_collector(start_str="2026-05-01", end_str="2026-05-05")