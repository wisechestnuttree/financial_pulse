"""
reCrawlUtils.py
기존 해시 ID 생성 방식을 100% 유지하는 안전한 재크롤링 유틸리티
"""
import re
import time, json
from datetime import datetime, timezone, timedelta
from elasticsearch import Elasticsearch
from selenium.webdriver.common.by import By

# 기존 유틸리티 함수들을 '그대로' 임포트하여 유지
from crawling.utils.crawlerUtils import managedDriver, generateHashId, extractContentWithJs
from crawling.utils.cleaningUtils import KoNewsCleaner, NewsCleaner
from machineLearning.run import run as run_ml_pipeline
from logs.logger import getLogger

logger = getLogger("crawl")

ES_URL   = 'http://100.88.143.23:9200'
KST      = timezone(timedelta(hours=9))
KO_INDEX = "news_ko"
EN_INDEX = "news_en"

# ================================================================
# 중복 방어용 유틸리티: URL 기반 기존 문서 완전 삭제
# ================================================================
def _deleteExistingDocByUrl(es, index: str, url: str):
    """
    제목이 수정되어 다른 해시 ID가 생성되었을 경우를 대비해,
    기존에 같은 URL로 적재되어 있던 옛날 문서를 ES에서 찾아 지워버립니다.
    """
    try:
        # [1단계] 원본 인덱스에서 URL 검색하여 doc_id 추출
        search_query = {
            "query": {
                "term": {
                    "url": url
                }
            },
            "_source": ["doc_id"]
        }

        search_res = es.search(index=index, body=search_query)
        hits = search_res['hits']['hits']
        if not hits:
            return

        target_id = hits[0]['_source'].get('doc_id')
        total_deleted = 0

        # ================================================================
        # [2단계] 타겟 인덱스별로 각개격파 (매핑 간섭 원천 차단)
        # ================================================================

        # ① 원본 인덱스 (en_test 또는 ko_test) 삭제
        # 원본 인덱스는 이미 doc_id를 정확히 가지고 있으므로 term이나 match로 확실히 타격 가능
        res_orig = es.delete_by_query(
            index=index,
            body={"query": {"match_phrase": {"doc_id": target_id}}},
            refresh=True
        )
        total_deleted += res_orig.get("deleted", 0)

        # ② 문제의 test_anal 인덱스 단독 삭제
        # 묶어서 던지지 않고 오직 test_anal만 지정하여 독립된 쿼리로 타격합니다.
        res_anal = es.delete_by_query(
            index="test_anal",
            body={"query": {"match_phrase": {"doc_id": target_id}}},
            refresh=True
        )
        total_deleted += res_anal.get("deleted", 0)


        if total_deleted > 0:
            logger.info(f"기존 중복 문서 제거 완료 ({total_deleted}건)", extra={"url": url})
    except Exception as e:
        logger.warning(f"기존 중복 문서 검색/삭제 중 예외 (무시 가능): {e}")

# ================================================================
# 단일 URL 크롤링 (페이지 로드 후 실시간 ID 생성)
# ================================================================
def crawlSingleKo(driver, url: str, collected_at: str) -> dict | None:
    try:
        pure_url = url.split('?')[0].split('#')[0].strip()
        lowered_url = pure_url.lower()

        if "naver.com" in lowered_url:
            source_type = "naver"
        else:
            source_type = "hankyung"

        selectors = {
            "naver":    ["#dic_area", "#articeBody", "#newsct_article", "#contents"],
            "hankyung": ["#articletxt", "#newsView", "#article-body", "#content"]
        }

        # 1. 페이지 접속
        driver.get(url)
        time.sleep(1.5)

        # 2. [기존 ID 방식 유지의 핵심] 실시간 제목 추출
        try:
            title = driver.find_element(By.CSS_SELECTOR,
                "h2.media_end_head_headline, .article-header h1, h1.article-title, h3.news_ttl"
            ).text.strip()
        except:
            title = driver.title.strip()

        # 3. 본문 추출
        content = ""
        for sel in selectors.get(source_type, selectors["hankyung"]):
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            if elements and elements[0].text.strip():
                content = elements[0].text.strip()
                break

        if not content or len(content.strip()) < 150:
            return None

        cleaned = KoNewsCleaner.clean(content)
        if not cleaned or not KoNewsCleaner.isValid(cleaned, title):
            return None

        # 4. 🔥 기존 함수 그대로 사용 (수집한 제목과 URL 결합)
        doc_id = generateHashId(pure_url, title)

        return {
            "doc_id":       doc_id,
            "url":          pure_url,
            "lang":         "ko",
            "title":        title,
            "content":      cleaned,
            "published_at": collected_at,
            "collected_at": collected_at
        }
    except Exception as e:
        logger.error(f"한국어 단일 크롤링 실패: {e}", url= url)
        return None


def crawlSingleEn(driver, url: str, collected_at: str) -> dict | None:
    try:
        pure_url = url.split('?')[0].split('#')[0].strip()

        driver.get(url)
        time.sleep(3)

        # 1. 실시간 제목 추출
        try:
            title = driver.find_element(By.CSS_SELECTOR, "h1, h1.article-title, .headline").text.strip()
        except:
            title = driver.title.strip()

        content = extractContentWithJs(driver, title=title)
        if not content or len(content.strip()) < 150:
            return None

        cleaned = NewsCleaner.clean(content)
        if not NewsCleaner.isValid(cleaned, title):
            return None

        # 2. 🔥 기존 함수 그대로 사용
        doc_id = generateHashId(pure_url, title)

        return {
            "doc_id":       doc_id,
            "url":          pure_url,
            "lang":         "en",
            "title":        title,
            "content":      cleaned,
            "published_at": collected_at,
            "collected_at": collected_at
        }
    except Exception as e:
        logger.error(f"영문 단일 크롤링 실패: {e}", url= url)
        return None


# ================================================================
# 재크롤링 메인 함수
# ================================================================
def runRetryCrawl():
    from dataStorage.mariaDb.db import getConn

    conn = getConn()
    pending_items = []
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, url FROM retryQueue")
            pending_items = cursor.fetchall()
            logger.info(f"관리자 지정 재크롤링 시작 ({len(pending_items)} 개)")

        if not pending_items:
            logger.info("재크롤링 대상 없음")
            return
    except Exception:
        logger.warning("retry_queue 조회 실패")
        if conn: conn.close()
        return

    ko_items = []
    en_items = []
    for item in pending_items:
        url = item["url"]
        if "hankyung" in url or "naver" in url:
            ko_items.append(url)
        else:
            en_items.append(url)

    es = Elasticsearch(ES_URL)

    collected_at = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    target_date  = datetime.now(KST).strftime('%Y-%m-%d')

    has_ko_success = False
    has_en_success = False

    # [한국어 개별 크롤링 실행]
    if ko_items:
        with managedDriver() as driver:
            for k_url in ko_items:
                doc = crawlSingleKo(driver, k_url, collected_at)
                if doc:
                    # 💡 적재 전, 혹시나 제목이 바뀌어 존재할지 모를 옛날 버전을 지워 정합성 수호
                    _deleteExistingDocByUrl(es, KO_INDEX, doc["url"])
                    # 새로운 해시 ID로 깔끔하게 적재
                    es.index(index=KO_INDEX, id=doc["doc_id"], document=doc)
                    has_ko_success = True

    # [영문 개별 크롤링 실행]
    if en_items:
        with managedDriver() as driver:
            for e_url in en_items:
                doc = crawlSingleEn(driver, e_url, collected_at)
                if doc:
                    _deleteExistingDocByUrl(es, EN_INDEX, doc["url"])
                    es.index(index=EN_INDEX, id=doc["doc_id"], document=doc)
                    has_en_success = True

    es.close()

    # [기존 ML 파이프라인 일괄 재실행]
    # if has_ko_success:
    #     logger.info(f"[{target_date}] 한국어 ML 파이프라인 전체 재가동")
    #     run_ml_pipeline("ko")
    #
    # if has_en_success:
    #     logger.info(f"[{target_date}] 영문 ML 파이프라인 전체 재가동")
    #     run_ml_pipeline("en")

    # [큐 초기화]
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM retryQueue")
            logger.info(f"관리자 지정 재크롤링 완료 ({len(pending_items)} 개)")
            conn.commit()
    except Exception as e:
        logger.warning(f"재크롤링 대기열 초기화 실패: {e}")

    conn.close()



if __name__ == "__main__":
    runRetryCrawl()