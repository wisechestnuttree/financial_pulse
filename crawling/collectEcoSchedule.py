"""
collectEcoSchedule.py
한경 경제캘린더에서 향후 경제 일정 수집 → korea_schedule.csv 저장

[ 수집 조건 ]
- 국가: 한국/미국만 (영국/중국 해제)
- 필터: 지표명 뒤에 Q, DEC, MAR 등 분기/월 표시가 있는 항목만
- 날짜 범위: 오늘 ~ 12/31

[ 저장 ]
- 파일: korea_schedule.csv
- 컬럼: date, event, importance, country
"""

import csv
import re
import time
from datetime import date

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from crawling.utils.crawlerUtils import managedDriver
from logs.logger import getLogger

logger = getLogger("crawl")

OUTPUT_CSV = "korea_schedule.csv"
MAX_PAGE   = 20

# 분기/월 표시 패턴 (Q1, Q2, DEC, MAR, Jan, Feb 등)
PERIOD_PATTERN = re.compile(
    r'\b(Q[1-4]|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec'
    r'|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC'
    r'|[A-Z]{3}\s*\d{2})\b'
)

# 중요도 매핑
IMPORTANCE_MAP = {
    "high"  : "high",
    "medium": "medium",
    "low"   : "low",
    "높음"  : "high",
    "보통"  : "medium",
    "낮음"  : "low",
}


def jsClick(driver, el, label=""):
    driver.execute_script("arguments[0].click();", el)
    if label:
        logger.info(f"클릭: {label}", extra={"action": "jsClick"})
    time.sleep(0.5)


def jsClickBy(driver, wait, by, selector, label=""):
    el = wait.until(EC.presence_of_element_located((by, selector)))
    jsClick(driver, el, label)


def setDateRange(driver, wait):
    """
    datepicker input에 JS로 날짜 직접 입력 후 조회 버튼 클릭
    시작일: 오늘, 종료일: 12/31
    """
    try:
        try:
            today_str = date.today().strftime("%Y-%m-%d")
            end_str = f"{date.today().year}-12-31"
            driver.execute_script(
                "document.getElementById('datepicker1').value = arguments[0];", today_str
            )
            driver.execute_script(
                "document.getElementById('datepicker2').value = arguments[0];", end_str
            )
            logger.info(f"날짜 설정 완료: {today_str} ~ {end_str}", extra={"action": "crawlEcoSchedule"})
        except Exception as e:
            logger.warning(f"날짜 설정 스킵: {e}", extra={"action": "crawlEcoSchedule"})
        time.sleep(0.5)

        # 조회 버튼 클릭 (.btn_wrap 안의 버튼 또는 submit)
        try:
            jsClickBy(driver, wait, By.CSS_SELECTOR, ".btn_wrap button", "조회 버튼")
        except:
            try:
                jsClickBy(driver, wait, By.CSS_SELECTOR, "button[type='submit']", "조회 버튼")
            except:
                jsClickBy(driver, wait, By.CSS_SELECTOR, ".btn_search", "조회 버튼")

        time.sleep(2)
        logger.info(f"날짜 범위 설정 완료: {today_str} ~ {end_str}", extra={"action": "setDateRange"})

    except Exception as e:
        logger.error(f"날짜 설정 오류: {e}", extra={"action": "setDateRange"})


def extractSchedule(driver) -> list:
    """
    현재 페이지에서 경제 일정 추출

    HTML 구조:
    tbody#tbody_data > tr
      th[scope=row] : 날짜 (YYYY-MM-DD 또는 MM-DD 형식)
      td            : 시간
      td            : (빈칸)
      td.tal_l      : 국가 (대한민국, 미국 등)
      td.tal_l      : 지표명 (예: 인플레이션율 (전월비) Dec)
      td            : 실제값
      td            : 예상값
      td            : 이전값
      ...

    반환: [ { date, event, importance, country }, ... ]
    조건: 지표명에 분기/월 표시(Q1, DEC 등)가 있는 항목만
    """
    results  = []
    cur_date = ""

    try:
        tbody = driver.find_element(By.ID, "tbody_data")
        rows  = tbody.find_elements(By.TAG_NAME, "tr")

        for row in rows:
            try:
                # 날짜 — th[scope=row]
                th_els = row.find_elements(By.CSS_SELECTOR, "th[scope=row]")
                if th_els:
                    date_txt = th_els[0].text.strip()
                    # YYYY-MM-DD 형식 추출
                    m = re.search(r"(\d{4}[-./]\d{1,2}[-./]\d{1,2})", date_txt)
                    if m:
                        cur_date = re.sub(r"[./]", "-", m.group(1))
                        parts    = cur_date.split("-")
                        cur_date = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"

                if not cur_date:
                    continue

                tds = row.find_elements(By.TAG_NAME, "td")
                if len(tds) < 4:
                    continue

                # tal_l 클래스 td들 추출 (국가, 지표명)
                tal_l = row.find_elements(By.CSS_SELECTOR, "td.tal_l")
                if len(tal_l) < 2:
                    continue

                country_txt = tal_l[0].text.strip()
                event_txt   = tal_l[1].text.strip()

                # 국가 판별
                if "대한민국" in country_txt:
                    country = "대한민국"
                elif "미국" in country_txt:
                    country = "미국"
                else:
                    continue

                # 지표명 분기/월 표시 필터링
                if not event_txt or not PERIOD_PATTERN.search(event_txt):
                    continue

                # 중요도 — star 이미지 개수 또는 클래스로 판별
                importance = "medium"
                try:
                    stars = row.find_elements(By.CSS_SELECTOR, "img[src*='star'], .star_on, span.star")
                    cnt   = len(stars)
                    if cnt >= 3:
                        importance = "high"
                    elif cnt == 2:
                        importance = "medium"
                    else:
                        importance = "low"
                except:
                    pass

                results.append({
                    "date"      : cur_date,
                    "event"     : event_txt,
                    "importance": importance,
                    "country"   : country,
                })

            except Exception as row_e:
                continue

    except Exception as e:
        logger.error(f"데이터 추출 오류: {e}", extra={"action": "extractSchedule"})

    return results


def clickPage(driver, wait, page_num) -> bool:
    try:
        paging = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".paging")))
        for link in paging.find_elements(By.TAG_NAME, "a"):
            if link.text.strip() == str(page_num):
                jsClick(driver, link, f"{page_num}페이지")
                time.sleep(2)
                return True
        return False
    except:
        return False


def crawlEcoSchedule() -> list:
    """
    경제캘린더 일정 크롤링 메인 함수
    """
    all_results = []

    with managedDriver() as driver:
        wait = WebDriverWait(driver, 15)
        try:
            driver.get("https://datacenter.hankyung.com/economic-calendar")
            time.sleep(4)

            # 날짜 설정 — iframe 밖에서 처리
            today_str = date.today().strftime("%Y-%m-%d")
            end_str = f"{date.today().year}-12-31"
            try:
                driver.execute_script(
                    "document.getElementById('datepicker1').value = arguments[0];", today_str
                )
                driver.execute_script(
                    "document.getElementById('datepicker2').value = arguments[0];", end_str
                )
                logger.info(f"날짜 설정: {today_str} ~ {end_str}", extra={"action": "crawlEcoSchedule"})
            except Exception as e:
                logger.warning(f"날짜 설정 스킵: {e}", extra={"action": "crawlEcoSchedule"})
            time.sleep(0.5)

            # 조회 버튼 클릭 (iframe 밖)
            try:
                btn = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".btn_wrap button")))
                jsClick(driver, btn, "조회 버튼")
                time.sleep(2)
            except Exception as e:
                logger.warning(f"조회 버튼 실패: {e}", extra={"action": "crawlEcoSchedule"})

            # iframe 진입
            iframe = wait.until(EC.presence_of_element_located((
                By.CSS_SELECTOR, "iframe[src*='zeroin.co.kr']"
            )))
            driver.switch_to.frame(iframe)
            logger.info("iframe 진입", extra={"action": "crawlEcoSchedule"})
            time.sleep(2)

            # 국가 필터 — 영국/중국 해제
            jsClickBy(driver, wait, By.CSS_SELECTOR, ".btn_nation.open_bodPop", "국가선택 열기")
            time.sleep(1)
            jsClickBy(driver, wait, By.ID, "cn", "중국 해제")
            jsClickBy(driver, wait, By.ID, "gb", "영국 해제")
            jsClickBy(driver, wait, By.CSS_SELECTOR, ".btn_popClose", "팝업 닫기")
            time.sleep(2)

            # 디버그 — tbody 구조 확인
            try:
                tbody = driver.find_element(By.ID, "tbody_data")
                rows = tbody.find_elements(By.TAG_NAME, "tr")
                print(f"tbody 찾음: {len(rows)}행")
                if rows:
                    print("첫 번째 행 HTML:")
                    print(rows[0].get_attribute("outerHTML")[:500])
            except Exception as e:
                print(f"tbody 못 찾음: {e}")
                # tbody 없으면 전체 소스 일부 출력
                print(driver.page_source[:2000])
            # 1페이지부터 순회
            for page in range(1, MAX_PAGE + 1):
                if page > 1:
                    if not clickPage(driver, wait, page):
                        logger.info(f"{page}페이지 없음 — 종료", extra={"action": "crawlEcoSchedule"})
                        break

                page_data = extractSchedule(driver)
                all_results.extend(page_data)
                logger.info(f"{page}페이지 수집: {len(page_data)}건", extra={
                    "action": "crawlEcoSchedule", "page": page
                })

                if not page_data:
                    break

        except Exception as e:
            logger.error(f"크롤링 오류: {e}", extra={"action": "crawlEcoSchedule"})
            import traceback; traceback.print_exc()

    return all_results


def saveToCSV(data: list):
    """
    수집 결과를 날짜순으로 정렬 후 CSV 저장
    """
    if not data:
        logger.warning("저장할 데이터 없음", extra={"action": "saveToCSV"})
        return

    # 중복 제거
    seen = set()
    unique = []
    for item in data:
        key = (item["date"], item["event"], item["country"])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # 날짜순 정렬
    unique.sort(key=lambda x: x["date"])

    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "event", "importance", "country"])
        writer.writeheader()
        writer.writerows(unique)

    logger.info(f"경제 지표 저장 완료: {len(unique)}건 → {OUTPUT_CSV}", extra={"action": "saveToCSV"})
    print(f"\n✅ {OUTPUT_CSV} 저장 완료 ({len(unique)}건)")
    for item in unique:
        print(f"  {item['date']} | {item['country']:6} | {item['importance']:6} | {item['event']}")


if __name__ == "__main__":
    print("경제 일정 크롤링 시작...")
    data = crawlEcoSchedule()
    print(f"수집 완료: {len(data)}건")
    saveToCSV(data)