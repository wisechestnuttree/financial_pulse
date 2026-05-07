
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

HEADERS = {"User-Agent": "Mozilla/5.0"}


def clean(text):
    return re.sub(r"\s+", " ", str(text)).strip() if text else ""


def get_soup(url):
    res = requests.get(url, headers=HEADERS, timeout=15)
    res.raise_for_status()
    return BeautifulSoup(res.text, "html.parser")


def create_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=opts)


def get_content(url):
    driver = create_driver()
    try:
        driver.get(url)
        elements = driver.find_elements(By.CSS_SELECTOR, "#dic_area")
        return clean(elements[0].text) if elements else ""
    finally:
        driver.quit()


def crawl_list_page(page_no, today):
    url = f"https://finance.naver.com/news/mainnews.naver?date={today}&page={page_no}"
    driver = create_driver()
    results = []

    try:
        driver.get(url)
        articles = driver.find_elements(By.CSS_SELECTOR, "li.block1 dd.articleSubject a")
        dates = driver.find_elements(By.CSS_SELECTOR, "li.block1 .wdate")

        for i, article in enumerate(articles):
            naver_url = article.get_attribute("href")
            if not naver_url:
                continue
            results.append({
                "title": clean(article.text),
                "naver_url": naver_url.strip(),
                "published_at": clean(dates[i].text) if i < len(dates) else ""
            })
    finally:
        driver.quit()

    return results


def crawl_all_list(today):
    all_items = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(crawl_list_page, p, today) for p in range(1, 11)]
        for f in as_completed(futures):
            all_items.extend(f.result())

    seen, unique = set(), []
    for item in all_items:
        if item["naver_url"] not in seen:
            seen.add(item["naver_url"])
            unique.append(item)
    return unique


def crawl_detail(item, collected_at):
    soup = get_soup(item["naver_url"])

    origin_tag = soup.select_one(".media_end_head_origin_link")
    origin_url = origin_tag.get("href", "").strip() if origin_tag else item["naver_url"]

    return {
        "doc_id": "",
        "lang": "ko",
        "url": origin_url,
        "title": item["title"],
        "content": get_content(item["naver_url"]),
        "published_at": item["published_at"],
        "collected_at": collected_at
    }


def crawl_all_detail(items, collected_at):
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(crawl_detail, item, collected_at) for item in items]
        for i, f in enumerate(as_completed(futures), 1):
            results.append(f.result())
            if i % 10 == 0:
                print(f"[네이버] 상세 수집: {i}/{len(items)}건")
    return results


def run():
    # ★ 호출 시점마다 날짜를 새로 계산 (스케줄러 다음날 실행 시 날짜 고정 버그 수정)
    today = datetime.now().strftime("%Y-%m-%d")
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("[네이버] 목록 수집 시작")
    news_list = crawl_all_list(today)
    print(f"[네이버] 목록 수집 완료: {len(news_list)}건")

    print("[네이버] 상세 수집 시작")
    results = crawl_all_detail(news_list, collected_at)
    print(f"[네이버] 상세 수집 완료: {len(results)}건")

    return results
