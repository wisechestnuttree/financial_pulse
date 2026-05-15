import re
import warnings
import time
import threading
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup
from elasticsearch import Elasticsearch
from selenium.webdriver.common.by import By
from dateutil import parser

# 유틸리티 로직 임포트
from utils.crawlerUtils import generate_hash_id, managed_driver
from utils.cleaningUtils import KoNewsCleaner

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

total_processed_count = 0
counter_lock = threading.Lock()


# process_batch_ko 함수 내 적재 로직 수정
def process_batch_ko(targets, thread_id, total_target_count, es, batch_collected_at):
    global total_processed_count
    with managed_driver() as driver:
        for item in targets:
            try:
                # 1. 발행일 검증
                raw_pub = item.get('pub_str', '').strip()
                if not raw_pub or not re.search(r'\d{1,2}:\d{2}', raw_pub):
                    continue

                try:
                    parsed_dt = parser.parse(raw_pub)
                    parsed_dt = parsed_dt.replace(tzinfo=KST) if parsed_dt.tzinfo is None else parsed_dt.astimezone(KST)
                    published_at = parsed_dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    continue

                # 2. URL 및 타이틀 정규화
                pure_url = item['url'].split('?')[0].split('#')[0].strip()
                pure_title = item['title'].strip()
                doc_id = generate_hash_id(pure_url, pure_title)

                if es.exists(index=INDEX_NAME, id=doc_id):
                    continue

                # 3. 본문 수집
                driver.get(item['url'])
                time.sleep(1.2)  # 속도 조절

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

                cleaned_content = KoNewsCleaner.clean(content)
                if not cleaned_content or not KoNewsCleaner.is_valid(cleaned_content, pure_title):
                    continue

                # 4. 데이터 적재 (매핑에 정의된 7개 필드만 정확히 포함)
                doc = {
                    "doc_id": doc_id,
                    "url": pure_url,
                    "lang": "ko",
                    "title": pure_title,
                    "content": cleaned_content,
                    "published_at": published_at,
                    "collected_at": batch_collected_at
                }

                # 전송 시도
                es.index(index=INDEX_NAME, id=doc_id, document=doc)

                with counter_lock:
                    total_processed_count += 1
                    print(f"[KO] ({total_processed_count}/{total_target_count}) 성공: {pure_title[:20]}...")

            except Exception as e:
                # 에러 로그 확인용 (필요시 주석 해제)
                # print(f"에러 발생: {e}")
                continue

def fetch_list(target_date):
    all_targets = []
    print(f"--- {target_date} 목록 수집 시작 ---")

    # [1] 네이버 금융
    print(f"[{target_date}] 네이버 금융 수집 중...")
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
            print(f"네이버 수집 에러 (Page {page}): {e}")
            break

    # [2] 한국경제
    print(f"[{target_date}] 한국경제 수집 중...")
    hk_date = target_date.replace("-", ".")
    for kw in TARGET_KEYWORDS:
        print(f"  > 키워드 '{kw}' 검색 중...", end="\r")
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
                print(f"한경 수집 에러 ({kw}, Page {page}): {e}")
                break
    print(f"\n[{target_date}] 목록 수집 완료. 총 {len(all_targets)}건 발견.")
    return all_targets


def run_standalone_ko(start_date=None, end_date=None):
    try:
        es = Elasticsearch(ES_URL)
        if not es.ping():
            print("ES 서버에 연결할 수 없습니다. URL을 확인하세요.")
            return
    except Exception as e:
        print(f"ES 연결 시도 중 에러: {e}")
        return

    global total_processed_count
    if not start_date: start_date = datetime.now(KST).strftime('%Y-%m-%d')
    if not end_date: end_date = start_date

    s_dt = datetime.strptime(start_date, '%Y-%m-%d')
    e_dt = datetime.strptime(end_date, '%Y-%m-%d')

    curr = s_dt
    while curr <= e_dt:
        target_day = curr.strftime('%Y-%m-%d')
        batch_collected_at = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        total_processed_count = 0

        raw_list = fetch_list(target_day)

        seen_titles = set()
        unique_list = []
        for it in raw_list:
            title_key = re.sub(r'[^a-zA-Z0-9가-힣]', '', it['title']).lower()
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_list.append(it)

        total_len = len(unique_list)
        print(f"[{target_day}] 중복 제거 후 최종 대상: {total_len}건")

        if unique_list:
            chunk_size = (total_len // MAX_WORKERS) + 1
            chunks = [unique_list[i:i + chunk_size] for i in range(0, total_len, chunk_size)]
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                for i, chunk in enumerate(chunks):
                    executor.submit(process_batch_ko, chunk, i, total_len, es, batch_collected_at)

        print(f"--- {target_day} 작업 종료 ---")
        curr += timedelta(days=1)
        time.sleep(2)


if __name__ == "__main__":
    run_standalone_ko()