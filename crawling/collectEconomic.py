"""
collectEconomic.py
매일 23:30 실행 — 한국/미국 경제지표 수집 후 DB 저장

[ 수집 지표 8개 ]
미국     : 소비자물가지수 (CPI) / GDP 성장률 / 실업률 / 비농업 고용수
대한민국 : 경상수지 / GDP 성장률 / 실업률 / 소비자물가지수

[ 사이트 기본값 ]
한국/미국이 기본 선택 — 영국/중국만 해제하면 됨
→ crawlCalendar() 한 번으로 양국 동시 수집

[ 구조 ]
crawlUtil.py 의 managedDriver() 사용 — with 블록 종료 시 driver.quit() 자동 보장
"""

import time
from datetime import date

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from dataStorage.mariaDb.db import getConn
from crawling.utils.crawlerUtils import managedDriver
from logs.logger import getLogger

logger = getLogger("crawl")

# ================================================================
# 상수 — 지표명 매핑 (사이트 표기 → DB 저장명)
# ================================================================
KEYWORD_MAP = {
    "비농업 고용"                  : ("미국",     "비농업 고용수"),
    "GDP 성장률 최종"              : ("미국",     "GDP 성장률"),
    "소비자물가지수 (CPI) (전월비)": ("미국",     "소비자물가지수 (CPI)"),
    "경상수지"                     : ("대한민국", "경상수지"),
    "GDP 성장률 속보치 (전분기비)" : ("대한민국", "GDP 성장률"),
}

UNEMPLOYMENT_KW = "실업률"
EXCLUDE_KWS     = ["U-6 실업률", "근원", "계절"]
MAX_PAGE        = 5


# ================================================================
# Selenium 공통 유틸
# ================================================================
def jsClick(driver, el, label=""):
    """
    JS 기반 클릭 실행

    el    : 클릭할 WebElement
    label : 로그 출력용 설명
    """
    driver.execute_script("arguments[0].click();", el)
    if label:
        logger.info(f"클릭: {label}")
    time.sleep(0.5)


def jsClickBy(driver, wait, by, selector, label=""):
    """
    셀렉터로 요소 탐색 후 JS 클릭

    wait     : WebDriverWait 객체
    by       : By.CSS_SELECTOR 등
    selector : CSS/ID 셀렉터 문자열
    label    : 로그 출력용 설명
    """
    el = wait.until(EC.presence_of_element_located((by, selector)))
    jsClick(driver, el, label)


def clickPage(driver, wait, page_num):
    """
    페이징 버튼 클릭

    page_num : 이동할 페이지 번호
    반환      : 성공 True / 실패(페이지 없음) False
    """
    try:
        paging = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".paging")))
        for link in paging.find_elements(By.TAG_NAME, "a"):
            if link.text.strip() == str(page_num):
                jsClick(driver, link, f"{page_num}페이지")
                return True
        return False
    except Exception as e:
        logger.warning("페이지 이동 실패")
        return False


# ================================================================
# 현재 페이지에서 대상 행 추출
# ================================================================
def extractFromPage(driver) -> list:
    """
    현재 페이지에서 경제지표 데이터 추출

    반환 : [ { country, indicator, actual, previous }, ... ]
    조건 : actual(실제값) 있는 행만 수집, EXCLUDE_KWS 포함 행 제외
    """
    results  = []
    rows     = driver.find_elements(By.CSS_SELECTOR, "tr")

    for row in rows:
        cells    = row.find_elements(By.TAG_NAME, "td")
        if not cells:
            continue
        row_text = row.text.strip()
        if not row_text:
            continue

        if any(kw in row_text for kw in EXCLUDE_KWS):
            continue

        actual = cells[4].text.strip() if len(cells) > 4 else ""
        if not actual:
            continue

        previous     = cells[6].text.strip() if len(cells) > 6 else ""
        country_cell = cells[2].text.strip() if len(cells) > 2 else ""

        if UNEMPLOYMENT_KW in row_text:
            if "미국" in country_cell:
                results.append({"country": "미국",     "indicator": "실업률",
                                 "actual": actual, "previous": previous})
            elif "대한민국" in country_cell:
                results.append({"country": "대한민국", "indicator": "실업률",
                                 "actual": actual, "previous": previous})
            continue

        for site_kw, (country, save_name) in KEYWORD_MAP.items():
            if site_kw in row_text:
                results.append({"country": country, "indicator": save_name,
                                 "actual": actual, "previous": previous})
                break

    return results


# ================================================================
# [PART 1] 경제캘린더 — 한국/미국 동시 수집
# ================================================================
def crawlCalendar(today_str) -> list:
    """
    한경 경제캘린더에서 한국/미국 경제지표 동시 수집

    today_str : 오늘 날짜 (YYYY-MM-DD)
    처리       : 영국/중국 해제 → 1~MAX_PAGE 페이지 순회 → extractFromPage()
    반환       : [ { country, indicator, actual, previous }, ... ]
    주의       : managedDriver() 사용 → with 블록 종료 시 driver.quit() 자동 보장
    """
    results = []

    with managedDriver() as driver:
        wait = WebDriverWait(driver, 15)
        try:
            driver.get("https://datacenter.hankyung.com/economic-calendar")
            time.sleep(4)

            iframe = wait.until(EC.presence_of_element_located((
                By.CSS_SELECTOR, "iframe[src*='zeroin.co.kr']"
            )))
            driver.switch_to.frame(iframe)
            logger.info("경제캘린더 iframe 진입")

            # 국가 필터 — 영국/중국 해제
            jsClickBy(driver, wait, By.CSS_SELECTOR, ".btn_nation.open_bodPop", "국가선택 열기")
            time.sleep(1)
            jsClickBy(driver, wait, By.ID, "cn", "중국 해제")
            jsClickBy(driver, wait, By.ID, "gb", "영국 해제")
            jsClickBy(driver, wait, By.CSS_SELECTOR, ".btn_popClose", "팝업 닫기")
            time.sleep(1)

            for page in range(1, MAX_PAGE + 1):
                if not clickPage(driver, wait, page):
                    logger.info(f"[캘린더] {page}페이지 없음 — 순회 종료")
                    break
                time.sleep(2)
                page_results = extractFromPage(driver)
                results.extend(page_results)
                logger.info(f"[캘린더] {page}페이지 수집")

        except Exception as e:
            logger.warning(f"경제캘린더 크롤링 오류: {e}")
            import traceback; traceback.print_exc()

    return results


# ================================================================
# [PART 2] 한국 소비자물가지수 — 별도 페이지
# ================================================================
def crawlKRCpi() -> dict | None:
    """
    한경 지표 페이지에서 한국 소비자물가지수 수집

    반환 : { country, indicator, actual, previous } 또는 None
    주의 : managedDriver() 사용 → with 블록 종료 시 driver.quit() 자동 보장
    """
    result = None

    with managedDriver() as driver:
        wait = WebDriverWait(driver, 15)
        try:
            driver.get("https://datacenter.hankyung.com/indicators")
            time.sleep(4)

            for row in driver.find_elements(By.CSS_SELECTOR, "table tr"):
                cells   = row.find_elements(By.TAG_NAME, "td")
                if not cells:
                    continue

                name_el = cells[0].find_elements(By.TAG_NAME, "a")
                name    = name_el[0].text.strip() if name_el else cells[0].text.strip()

                if name == "소비자물가지수":
                    actual   = cells[3].text.strip() if len(cells) > 3 else ""
                    previous = cells[1].text.strip() if len(cells) > 1 else ""

                    if not actual:
                        break

                    result = {
                        "country"  : "대한민국",
                        "indicator": "소비자물가지수",
                        "actual"   : actual,
                        "previous" : previous,
                    }
                    logger.info("한국 CPI 수집 완료")
                    break

        except Exception as e:
            logger.warning("한국 CPI 크롤링 오류")
            import traceback; traceback.print_exc()

    return result


# ================================================================
# DB 저장 — REPLACE INTO (날짜+국가+지표명 기준 덮어쓰기)
# ================================================================
def saveToDB(today_str, data_list):
    """
    경제지표 DB 저장

    today_str : 오늘 날짜 (YYYY-MM-DD)
    data_list : [ { country, indicator, actual, previous }, ... ]
    처리       : REPLACE INTO — 같은 날짜+국가+지표명이면 덮어쓰기
    """
    if not data_list:
        logger.info("저장할 데이터 없음")
        return

    conn = getConn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS economicIndicator (
                    date      DATE         NOT NULL,
                    country   VARCHAR(20)  NOT NULL,
                    indicator VARCHAR(50)  NOT NULL,
                    actual    VARCHAR(20)  NOT NULL,
                    previous  VARCHAR(20),
                    UNIQUE KEY uq_date_country_indicator (date, country, indicator)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            for item in data_list:
                cursor.execute("""
                    REPLACE INTO economicIndicator (date, country, indicator, actual, previous)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    today_str,
                    item["country"],
                    item["indicator"],
                    item["actual"],
                    item.get("previous", "")
                ))

        conn.commit()
        logger.info("DB 저장 완료")

    except Exception as e:
        conn.rollback()
        logger.warning("DB 저장 오류")
    finally:
        conn.close()


# ================================================================
# 메인 작업 — 매일 23:30 실행 (crawlSchedular.py 에서 호출)
# ================================================================
def dailyJob():
    """
    경제지표 일일 수집 메인 함수

    처리 순서
    1. crawlCalendar() — 경제캘린더에서 한국/미국 지표 동시 수집
    2. crawlKRCpi()    — 한국 소비자물가지수 별도 수집
    3. saveToDB()      — 수집 결과 DB 저장
    """
    today_str = date.today().isoformat()

    logger.info("경제지표 수집 시작")

    all_data = []

    cal_data = crawlCalendar(today_str)
    all_data.extend(cal_data)
    logger.info("캘린더 수집 완료")

    kr_cpi = crawlKRCpi()
    if kr_cpi:
        all_data.append(kr_cpi)

    saveToDB(today_str, all_data)

    logger.info("경제지표 수집 전체 완료")


if __name__ == "__main__":
    dailyJob()
