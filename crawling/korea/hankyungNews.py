import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

HEADERS = {"User-Agent": "Mozilla/5.0"}
CONTENT_SELECTORS = ["#articletxt", "#newsView", "#article-body", "#articleBody", "#content"]


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


def get_content(url, selectors):
    driver = create_driver()
    try:
        driver.get(url)
        for sel in selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            if elements:
                return clean(elements[0].text)
        return ""
    finally:
        driver.quit()


def crawl_list_page(page_no, today):
    url = (
        "https://search.hankyung.com/search/news?"
        "query=%EA%B2%BD%EC%A0%9C&sort=DATE%2FDESC%2CRANK%2FDESC&period=DATE&area=ALL"
        f"&sdate={today}&edate={today}&exact=&include=&except=&hk_only=&page={page_no}"
    )
    soup = get_soup(url)
    results = []

    for item in soup.select(".article li"):
        title_tag = item.select_one(".tit")
        link_tag = item.select_one(".txt_wrap a")
        date_tag = item.select_one(".date_time")

        if not title_tag or not link_tag:
            continue

        article_url = link_tag.get("href", "").strip()
        if not article_url:
            continue

        results.append({
            "title": clean(title_tag.get_text()),
            "url": article_url,
            "published_at": clean(date_tag.get_text()) if date_tag else ""
        })

    return results


def crawl_all_list(today):
    all_items = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(crawl_list_page, p, today) for p in range(1, 11)]
        for f in as_completed(futures):
            all_items.extend(f.result())

    seen, unique = set(), []
    for item in all_items:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique


def crawl_content(item, collected_at):
    return {
        "doc_id": "",
        "lang": "ko",
        "url": item["url"],
        "title": item["title"],
        "content": get_content(item["url"], CONTENT_SELECTORS),
        "published_at": item["published_at"],
        "collected_at": collected_at
    }


def crawl_all_content(items, collected_at):
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(crawl_content, item, collected_at) for item in items]
        for i, f in enumerate(as_completed(futures), 1):
            results.append(f.result())
            if i % 10 == 0:
                print(f"[한국경제] 본문 수집: {i}/{len(items)}건")
    return results


def run():
    # ★ 호출 시점마다 날짜를 새로 계산 (스케줄러 다음날 실행 시 날짜 고정 버그 수정)
    today = datetime.now().strftime("%Y.%m.%d")
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("[한국경제] 목록 수집 시작")
    news_list = crawl_all_list(today)
    print(f"[한국경제] 목록 수집 완료: {len(news_list)}건")

    print("[한국경제] 본문 수집 시작")
    results = crawl_all_content(news_list, collected_at)
    print(f"[한국경제] 본문 수집 완료: {len(results)}건")

    return results