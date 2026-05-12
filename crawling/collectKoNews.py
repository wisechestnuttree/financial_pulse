import re
import time
import warnings
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from elasticsearch import Elasticsearch
from selenium.webdriver.common.by import By
from dateutil import parser

# 유틸리티 로직 임포트
from crawling.actions.crawlUtil import getDriver, generateHashId
from crawling.actions.cleaningUtil import KoNewsCleaner

# [설정]
ES_URL = 'http://100.88.143.23:9200'
INDEX_NAME = 'news_ko'
MAX_WORKERS = 2  # 학원 서버 사양 고려
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}
# --- 검색 키워드 ---
TARGET_KEYWORDS = ["경제", "금융", "증시", "산업", "부동산"]

warnings.filterwarnings("ignore", category=parser.UnknownTimezoneWarning)

# 전역 카운터 및 락
total_processed_count = 0
counter_lock = threading.Lock()


def processBatchKo(targets, thread_id, total_target_count, es, collected_at):
    global total_processed_count

    # 1. crawler_utils에서 managed_driver 임포트
    from crawling.actions.crawlUtil import managedDriver

    print(f"[Thread-{thread_id}] 브라우저 가동 (담당 {len(targets)}건)")

    # 2. with 문을 통해 정상/비정상 종료 시 무조건 quit() 되도록 보장
    with managedDriver() as driver:
        for item in targets:
            try:
                if not item.get('title') or not item.get('url'):
                    continue

                pure_url = item['url'].split('?')[0].split('#')[0].strip()
                pure_title = item['title'].strip()
                doc_id = generateHashId(pure_url, pure_title)

                # 중복 체크
                if es.exists(index=INDEX_NAME, id=doc_id):
                    continue

                driver.get(item['url'])
                time.sleep(1.5)

                selectors = {
                    "naver": ["#dic_area", "#articeBody", "#newsct_article", "#contents"],
                    "hankyung": ["#articletxt", "#newsView", "#article-body", "#content"]
                }

                content = ""
                source_type = item.get('source_type', 'hankyung')
                target_selectors = selectors.get(source_type, selectors["hankyung"])

                for sel in target_selectors:
                    elements = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elements and elements[0].text.strip():
                        content = elements[0].text.strip()
                        break

                # 4. 클리닝 및 유효성 검사
                cleaned_content = KoNewsCleaner.clean(content)
                if not cleaned_content or not KoNewsCleaner.isValid(cleaned_content, pure_title):
                    continue

                # 5. 데이터 적재
                doc = {
                    "doc_id": doc_id,
                    "url": pure_url,
                    "lang": "ko",
                    "title": pure_title,
                    "content": cleaned_content,
                    "published_at": item['pub_str'],
                    "collected_at": collected_at
                }

                es.index(index=INDEX_NAME, id=doc_id, document=doc)

                with counter_lock:
                    total_processed_count += 1
                    print(f"[KO] 성공: ({total_processed_count}/{total_target_count}) {pure_title[:30]}...")

            except Exception:
                # 개별 기사 에러 시 다음 기사로 스킵 (드라이버는 유지)
                continue

def fetchList(target_date):
    all_targets = []
    print(f"--- {target_date} 뉴스 검색 시작 ---")

    # [1] 네이버 금융 주요뉴스
    for page in range(1, 6):
        try:
            url = f"https://finance.naver.com/news/mainnews.naver?date={target_date}&page={page}"
            res = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.select("li.block1")
            for item in items:
                anchor = item.select_one("dd.articleSubject a")
                if anchor:
                    all_targets.append({
                        "title": anchor.get_text().strip(),
                        "url": "https://finance.naver.com" + anchor.get("href"),
                        "pub_str": f"{target_date}T09:00:00",
                        "source_type": "naver"
                    })
        except:
            break

    # [2] 한국경제 5대 키워드 검색
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
                    if title_tag and link_tag:
                        all_targets.append({
                            "title": title_tag.get_text().strip(),
                            "url": link_tag.get("href"),
                            "pub_str": f"{target_date}T09:00:00",
                            "source_type": "hankyung"
                        })
            except:
                break

    return all_targets


def runStandaloneKo(start_date=None, end_date=None):
    es = Elasticsearch(ES_URL)
    global total_processed_count

    if not start_date: start_date = datetime.now().strftime('%Y-%m-%d')
    if not end_date: end_date = start_date

    s_dt = datetime.strptime(start_date, '%Y-%m-%d')
    e_dt = datetime.strptime(end_date, '%Y-%m-%d')

    curr = s_dt
    while curr <= e_dt:
        target_day = curr.strftime('%Y-%m-%d')
        collected_at = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        total_processed_count = 0

        raw_list = fetchList(target_day)

        # 제목 기준 중복 제거 (정규화 강화)
        seen_titles = set()
        unique_list = []
        for it in raw_list:
            # 특수문자 제외하고 제목 비교
            title_key = re.sub(r'[^a-zA-Z0-9가-힣]', '', it['title']).lower()
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_list.append(it)

        total_len = len(unique_list)
        print(f"분석 대상: 총 {total_len}건 (중복 제거 완료)")

        if unique_list:
            chunk_size = (total_len // MAX_WORKERS) + 1
            chunks = [unique_list[i:i + chunk_size] for i in range(0, total_len, chunk_size)]

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                for i, chunk in enumerate(chunks):
                    executor.submit(processBatchKo, chunk, i, total_len, es, collected_at)

        print(f"--- {target_day} 작업 완료 ---")
        curr += timedelta(days=1)
        time.sleep(2)


if __name__ == "__main__":
    # 1. 오늘 날짜만 수집
    runStandaloneKo()

    # 2. 기간 지정 수집 예시 (주석 해제 후 사용)
    # run_standalone_ko(start_date="2026-05-01", end_date="2026-05-10")