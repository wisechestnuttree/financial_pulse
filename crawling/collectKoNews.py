import queue
import re
import warnings
import time
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
from elasticsearch import Elasticsearch
from selenium.webdriver.common.by import By
from dateutil import parser

# 유틸리티 로직 임포트
from utils.crawlerUtils import generateHashId, managedDriver
from utils.cleaningUtils import KoNewsCleaner
from logs.logger import getLogger

logger = getLogger("crawl")

# [설정]
ES_URL = 'http://100.88.143.23:9200'
INDEX_NAME = 'news_ko'
MAX_WORKERS = 2
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}
TARGET_KEYWORDS = ["경제", "금융", "증시", "산업", "부동산"]

KST = timezone(timedelta(hours=9))
warnings.filterwarnings("ignore", category=parser.UnknownTimezoneWarning)

# 통계 집계용 전역 카운터 및 락 설정
counter_lock = threading.Lock()
stats = {
    "total_target": 0,
    "success": 0,
    "skip_date_missing": 0,  # 날짜미달
    "skip_date_parse_fail": 0,  # 날짜파싱실패
    "skip_duplicate": 0,  # 중복기사
    "skip_short_content": 0,  # 본문길이미달 (수집실패 포함)
    "skip_invalid": 0  # 유효성탈락
}


def news_worker_ko(task_queue, thread_id, batch_collected_at, es):
    """
    미리 한국어 브라우저를 1개 켜두고, 큐가 빌 때까지
    브라우저 종료 없이 driver.get()만 반복하는 작업자 스레드
    """
    time.sleep(thread_id * 2)
    logger.info(f"[Thread-{thread_id}] 한국어 브라우저 인스턴스 초기화 및 가동 시작.")

    with managedDriver() as driver:
        while True:
            try:
                # 큐에서 작업 가져오기 (비어있으면 바로 Empty 예외 발생 후 탈출)
                item = task_queue.get_nowait()
            except queue.Empty:
                break

            try:
                # 1. 발행일 검증 (가드레일 1: 날짜미달)
                raw_pub = item.get('pub_str', '').strip()
                if not raw_pub or not re.search(r'\d{1,2}:\d{2}', raw_pub):
                    with counter_lock:
                        stats["skip_date_missing"] += 1
                    continue

                # 날짜 파싱 (가드레일 1-2: 날짜파싱실패)
                try:
                    parsed_dt = parser.parse(raw_pub)
                    parsed_dt = parsed_dt.replace(tzinfo=KST) if parsed_dt.tzinfo is None else parsed_dt.astimezone(KST)
                    published_at = parsed_dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    with counter_lock:
                        stats["skip_date_parse_fail"] += 1
                    continue

                # 2. URL 및 타이틀 정규화
                pure_url = item['url'].split('?')[0].split('#')[0].strip()
                pure_title = item['title'].strip()
                doc_id = generateHashId(pure_url, pure_title)

                # 가드레일 2: 중복기사 (ES 존재 여부 체크)
                if es.exists(index=INDEX_NAME, id=doc_id):
                    with counter_lock:
                        stats["skip_duplicate"] += 1
                    continue

                # 3. 본문 수집
                driver.get(item['url'])
                time.sleep(1.2)  # 페이지 로딩 대기 선언치 유지

                source_type = item.get('source_type', 'hankyung')
                selectors = {
                    "naver": ["#dic_area", "#articeBody", "#newsct_article", "#contents"],
                    "hankyung": ["#articletxt", "#newsView", "#article-body", "#content"]
                }

                content = ""
                target_selectors = selectors.get(source_type, selectors["hankyung"])
                for sel in target_selectors:
                    elements = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elements and elements[0].text.strip():
                        content = elements[0].text.strip()
                        break

                # 가드레일 3: 본문길이미달 (텍스트가 아예 없거나 너무 짧은 경우)
                if not content or len(content.strip()) < 150:
                    with counter_lock:
                        stats["skip_short_content"] += 1
                    continue

                # 가드레일 4: 유효성탈락 (KoNewsCleaner 기준 미달)
                cleaned_content = KoNewsCleaner.clean(content)
                if not cleaned_content or not KoNewsCleaner.isValid(cleaned_content, pure_title):
                    with counter_lock:
                        stats["skip_invalid"] += 1
                    continue

                # 4. 데이터 적재 (모든 가드레일 통과 시)
                doc = {
                    "doc_id": doc_id,
                    "url": pure_url,
                    "lang": "ko",
                    "title": pure_title,
                    "content": cleaned_content,
                    "published_at": published_at,
                    "collected_at": batch_collected_at
                }

                es.index(index=INDEX_NAME, id=doc_id, document=doc)

                with counter_lock:
                    stats["success"] += 1

            except Exception as e:
                # 개별 기사 처리 중 터진 순수 시스템 예외/통신 에러만 개별 로그로 남김
                logger.error(f"[Thread-{thread_id}] 기사 처리 중 예외 발생 (수집 스킵): {e}")
            finally:
                task_queue.task_done()

    logger.info(f"[Thread-{thread_id}] 할당된 모든 한국어 큐 소진. 브라우저 종료.")


def fetch_list(target_date):
    all_targets = []
    logger.info(f"--- {target_date} 목록 수집 시작 ---")

    # [1] 네이버 금융
    logger.info(f"[{target_date}] 네이버 금융 목록 수집 중...")
    for page in range(1, 6):
        try:
            url = f"https://finance.naver.com/news/mainnews.naver?date={target_date}&page={page}"
            res = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.select("li.block1")
            for item in items:
                anchor = item.select_one("dd.articleSubject a")
                date_tag = item.select_one(".wdate")
                if anchor:
                    all_targets.append({
                        "title": anchor.get_text().strip(),
                        "url": "https://finance.naver.com" + anchor.get("href"),
                        "pub_str": date_tag.get_text().strip() if date_tag else "",
                        "source_type": "naver"
                    })
        except Exception as e:
            logger.error(f"네이버 수집 에러 (Page {page}): {e}")
            break

    # [2] 한국경제
    logger.info(f"[{target_date}] 한국경제 목록 수집 중...")
    hk_date = target_date.replace("-", ".")
    for kw in TARGET_KEYWORDS:
        for page in range(1, 6):
            try:
                url = (f"https://search.hankyung.com/search/news?query={kw}"
                       f"&sort=DATE%2FDESC%2CRANK%2FDESC&period=DATE&area=ALL"
                       f"&sdate={hk_date}&edate={hk_date}&page={page}")
                res = requests.get(url, headers=HEADERS, timeout=10)
                soup = BeautifulSoup(res.text, "html.parser")
                items = soup.select(".article li")
                if not items: break
                for item in items:
                    title_tag = item.select_one(".tit")
                    link_tag = item.select_one("a")
                    date_tag = item.select_one(".date_time")
                    if title_tag and link_tag:
                        all_targets.append({
                            "title": title_tag.get_text().strip(),
                            "url": link_tag.get("href"),
                            "pub_str": date_tag.get_text().strip() if date_tag else "",
                            "source_type": "hankyung"
                        })
            except Exception as e:
                logger.error(f"한경 수집 에러 ({kw}, Page {page}): {e}")
                break

    logger.info(f"[{target_date}] 목록 수집 완료. 총 {len(all_targets)}건 발견.")
    return all_targets


def run_standalone_ko(start_date=None, end_date=None):
    try:
        es = Elasticsearch(ES_URL)
        if not es.ping():
            logger.critical("ES 서버에 연결할 수 없습니다. URL을 확인하세요.")
            return
    except Exception as e:
        logger.critical(f"ES 연결 시도 중 에러: {e}")
        return

    global stats
    if not start_date: start_date = datetime.now(KST).strftime('%Y-%m-%d')
    if not end_date: end_date = start_date

    s_dt = datetime.strptime(start_date, '%Y-%m-%d')
    e_dt = datetime.strptime(end_date, '%Y-%m-%d')

    curr = s_dt
    while curr <= e_dt:
        # 매 날짜별 통계 데이터 초기화
        for key in stats:
            stats[key] = 0

        target_day = curr.strftime('%Y-%m-%d')
        batch_collected_at = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

        raw_list = fetch_list(target_day)

        seen_titles = set()
        unique_list = []
        for it in raw_list:
            title_key = re.sub(r'[^a-zA-Z0-9가-힣]', '', it['title']).lower()
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_list.append(it)

        stats["total_target"] = len(unique_list)
        logger.info(f"[{target_day}] 중복 제거 후 최종 대상: {stats['total_target']}건")

        if unique_list:
            # 1. 큐 객체 생성 및 데이터 탑재
            task_queue = queue.Queue()
            for target in unique_list:
                task_queue.put(target)

            # 2. 고정 스레드 풀 할당 및 가동
            threads = []
            for i in range(MAX_WORKERS):
                t = threading.Thread(
                    target=news_worker_ko,
                    args=(task_queue, i, batch_collected_at, es)
                )
                threads.append(t)
                t.start()

            # 3. 큐 작업이 전부 빌 때까지 메인 스레드 동기화 대기
            for t in threads:
                t.join()

        # [요청사항 반영] 하루 수집 완료 후 가드레일 통계 리포트 통합 출력
        logger.info(f"================ [{target_day}] 한국어 수집 프로세스 최종 리포트 ================")
        logger.info(f" 총 분석 대상 기사 : {stats['total_target']} 건")
        logger.info(f" 최종 적재 성공 : {stats['success']} 건")
        logger.info(f" 가드레일 필터링 내역:")
        logger.info(f" [날짜 미달] : {stats['skip_date_missing']} 건")
        logger.info(f" [날짜 파싱 실패] : {stats['skip_date_parse_fail']} 건")
        logger.info(f" [중복 뉴스] : {stats['skip_duplicate']} 건")
        logger.info(f" [본문 길이 미달] : {stats['skip_short_content']} 건")
        logger.info(f" [텍스트 유효성 탈락] : {stats['skip_invalid']} 건")

        logger.info(f"--- {target_day} 작업 종료 ---")
        curr += timedelta(days=1)
        time.sleep(2)


if __name__ == "__main__":
    # 다중 날짜 테스트도 안정적으로 지원합니다.
    run_standalone_ko("2026-05-11", "2026-05-18")