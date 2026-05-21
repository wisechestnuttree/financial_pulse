import queue
import re
import warnings
import time
import datetime as dt
import threading
from datetime import datetime
from urllib.parse import quote
import feedparser
import requests
from elasticsearch import Elasticsearch
from dateutil import parser

# 유틸리티 로직 임포트 (좀비 프로세스 정리는 managed_driver 내부의 atexit 등이 담당)
from crawling.utils.crawlerUtils import extractContentWithJs, generateHashId, managedDriver
from crawling.utils.cleaningUtils import NewsCleaner
from logs.logger import getLogger

logger = getLogger("crawl")

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

# 통계 집계용 전역 카운터 및 락 설정
# total_processed_count = 0
counter_lock = threading.Lock()
stats = {
    "total_target": 0,
    "success": 0,
    "skip_date_missing": 0,     # 날짜미달
    "skip_date_parse_fail": 0,  # 날짜파싱실패
    "skip_duplicate": 0,        # 중복기사
    "skip_short_content": 0,    # 본문길이미달
    "skip_invalid": 0           # 유효성탈락
}

def newsWorker(task_queue, thread_id, batch_collected_at, es):
    """
    미리 브라우저를 1개만 켜두고, 큐가 빌 때까지
    브라우저 종료 없이 driver.get()만 반복하는 작업자 스레드
    """
    # 스레드 간 완벽한 격리를 위해 시작 시점에만 살짝 시차를 둡니다.
    time.sleep(thread_id * 2)
    logger.info(f"[Thread-{thread_id}] 브라우저 인스턴스 초기화 및 가동 시작.", extra={"action": "newsWorker"})

    # 브라우저를 '딱 한 번만' 켭니다.
    with managedDriver() as driver:
        while True:
            try:
                # 큐에서 작업 가져오기 (기다리지 않고 바로 없으면 Empty 예외 발생)
                target = task_queue.get_nowait()
            except queue.Empty:
                # 큐에 더 이상 처리할 기사가 없으면 스레드 종료 (브라우저 자동 닫힘)
                break

            try:
                raw_pub = target.get('raw_published', '').strip()
                published_at = None

                # [필터링 및 날짜 파싱 로직]
                has_time = re.search(r'\d{1,2}:\d{2}', raw_pub)
                is_relative = "ago" in raw_pub.lower()
                if not (has_time or is_relative):
                    with counter_lock:
                        stats["skip_date_missing"] += 1
                    continue  # task_done() 제거: 이제 무조건 finally가 처리합니다.

                # (날짜 가공 파트)
                if is_relative:
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
                    try:
                        parsed_dt = parser.parse(raw_pub)
                        if parsed_dt.tzinfo is None:
                            parsed_dt = parsed_dt.replace(tzinfo=dt.timezone(dt.timedelta(hours=-4)))
                        published_at = parsed_dt.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        time_match = re.search(r'(\d{1,2}):(\d{2})', raw_pub)
                        if time_match:
                            hr, mn = map(int, time_match.groups())
                            ny_dt = datetime.now(KST).replace(hour=hr, minute=mn, second=0)
                            published_at = (ny_dt + dt.timedelta(hours=13)).strftime('%Y-%m-%d %H:%M:%S')

                if not published_at:
                    with counter_lock:
                        stats["skip_date_parse_fail"] += 1
                    continue  # task_done() 제거

                # URL 정제 및 중복 체크
                clean_url = target['url'].split('?')[0].split('#')[0].strip()
                doc_id = generateHashId(clean_url, target['title'])

                if es.exists(index=INDEX_NAME, id=doc_id):
                    with counter_lock:
                        stats["skip_duplicate"] += 1
                    continue  # task_done() 제거

                # 핵심: 이미 켜져 있는 driver를 그대로 재사용하여 get() 호출
                driver.get(target['url'])
                time.sleep(3)  # 페이지 로딩 대기
                content = extractContentWithJs(driver, title=target['title'])

                if not content or len(content.strip()) < 150:
                    with counter_lock:
                        stats["skip_short_content"] += 1
                    continue  # task_done() 제거

                clean_content = NewsCleaner.clean(content)
                if not NewsCleaner.isValid(clean_content, target['title']):
                    with counter_lock:
                        stats["skip_invalid"] += 1
                    continue  # task_done() 제거

                # 데이터 적재
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

                with counter_lock:
                    stats["success"] += 1

            except Exception as e:
                logger.error(f"[Thread-{thread_id}] 기사 처리 중 에러 발생 (수집 스킵): {e}", extra={"action": "newsWorker", "err_msg": str(e)})

            finally:
                # 성공하든, 중간에 어떤 사유로 튕기든 무조건 이 작업이 끝났음을 큐에 알리기.
                task_queue.task_done()

    logger.info(f"[Thread-{thread_id}] 할당된 모든 큐 소진. 브라우저 종료.", extra={"action": "newsWorker"})


def runCollector(start_str=None, end_str=None):
    global stats
    is_today_mode = not start_str
    if is_today_mode:
        start_str = datetime.now(KST).strftime('%Y-%m-%d')
    if not end_str:
        end_str = start_str

    start_date = datetime.strptime(start_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_str, '%Y-%m-%d')

    current = start_date
    while current <= end_date:
        # 매 날짜별 통계 초기화
        for key in stats:
            stats[key] = 0

        target_day = current.strftime('%Y-%m-%d')
        batch_collected_at = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

        logger.info(f"--- {target_day} 목록 수집 시작 ---")

        all_targets = []
        for kw in TARGET_KEYWORDS:
            logger.info(f"[{target_day}] Google News 검색 중: {kw}...")
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
            except Exception as e:
                logger.warning(f"[{target_day}] RSS 피드 수집 실패 ({kw}): {e}")
                continue

        logger.info(f"[{target_day}] 목록 수집 완료. 총 {len(all_targets)}건 발견.")

        seen_titles = set()
        unique_targets = []
        for it in all_targets:
            title_key = re.sub(r'[^a-z0-9]', '', it['title'].lower())
            if title_key not in seen_titles and len(it['title']) > 5:
                seen_titles.add(title_key)
                unique_targets.append(it)

        stats["total_target"] = len(unique_targets)
        logger.info(f"[{target_day}] 중복 제거 후 최종 대상: {stats['total_target']}건")

        if unique_targets:
            task_queue = queue.Queue()
            for target in unique_targets:
                task_queue.put(target)

            threads = []
            for i in range(MAX_WORKERS):
                t = threading.Thread(
                    target=newsWorker,
                    args=(task_queue, i, batch_collected_at, es)
                )
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

        # 모든 스레드 종료 후 최종 가드레일 통계 리포트 출력
        logger.info(f"================ [{target_day}] 수집 프로세스 최종 리포트 ================")
        logger.info(f" 총 분석 대상 기사 : {stats['total_target']} 건")
        logger.info(f" 최종 적재 성공 : {stats['success']} 건")
        logger.info(f" 가드레일 필터링 내역:")
        logger.info(f" [날짜 미달] : {stats['skip_date_missing']} 건")
        logger.info(f" [날짜 파싱 실패] : {stats['skip_date_parse_fail']} 건")
        logger.info(f" [중복 뉴스] : {stats['skip_duplicate']} 건")
        logger.info(f" [본문 길이 미달] : {stats['skip_short_content']} 건")
        logger.info(f" [텍스트 유효성 탈락] : {stats['skip_invalid']} 건")

        current += dt.timedelta(days=1)


if __name__ == "__main__":
    runCollector()