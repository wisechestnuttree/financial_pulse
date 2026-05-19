"""
searchRouter.py
GET /api/search?keyword=삼성전자

[ 데이터 소스 ]
- ES : analyze 인덱스 (msearch 3개 쿼리 + 필요 시 추가 쿼리 1번)

[ 응답 구조 ]
{
  "keyword": "삼성전자",
  "overall": {
    "pos": 62.5, "neg": 17.9, "total": 240,
    "label": "긍정", "score": 0.72
  },
  "sectors": [
    { "sector": "반도체", "pos": 69.7, "neg": 20.2, "total": 89, "relevance": 37.1 },
    ...
  ],
  "articles": [
    { "title", "tendency", "tend_score", "url", "sector", "rank": "primary" },
    ...  (최대 8개)
  ]
}
"""

from fastapi import APIRouter, HTTPException, Request

from dataStorage.elasticSearch.es import getEs, ANALYZE_DATA_IDX, NEWS_KO_IDX, NEWS_EN_IDX
from logs.logger import getLogger
from router.commonFunc import ok, translateSector, getDocIds, translateSectorToEn

logger   = getLogger("system")
u_logger = getLogger("user")
router   = APIRouter(prefix="/api", tags=["search"])


# ================================================================
# 공통 should 필터 생성
# ================================================================
def buildShouldFilter(keyword: str) -> dict:
    """
    검색어 기반 ES should 필터 생성

    keyword : 검색어 (예: "삼성전자")
    처리     : 제목/키워드/NER 5개 필드에 OR 조건으로 검색
    반환     : ES bool should 필터 딕셔너리

    검색 필드
    - title       : 기사 제목 (match — 형태소 분석)
    - keywords    : ML 추출 키워드 (term — 정확히 일치)
    - ner.company : 기업/기관명 (term)
    - ner.person  : 인물명 (term)
    - ner.region  : 지역/국가명 (term)
    """
    sector_en = translateSectorToEn(keyword)
    return {
        "should": [
            {"match": {"title": keyword}},
            {"term": {"keywords": keyword}},
            {"term": {"ner.company": keyword}},
            {"term": {"ner.person": keyword}},
            {"term": {"ner.region": keyword}},
            {"term": {"sector": sector_en}},
        ],
        "minimum_should_match": 1
    }


# ================================================================
# ES msearch 쿼리 조립
# ================================================================
def buildMsearch(doc_ids: list, keyword: str) -> list:
    """
    검색 결과에 필요한 ES msearch 쿼리 목록 생성

    쿼리 순서     : A B C
    A : should 필터 + tendency 집계 + tend_score 평균  → 1번(전체 분위기)
    B : should 필터 + sector × tendency 중첩 집계      → 2번(연관 분야별 비교)
    C : should 필터 + tend_score 내림차순 기사 8개      → 3번(관련 뉴스 1순위)

    doc_ids : news_ko/en 에서 미리 수집한 오늘 날짜 doc_id 목록
    keyword : 검색어
    반환     : [ {헤더}, {바디}, ... ] msearch 형식 리스트
    """
    should_filter = buildShouldFilter(keyword)

    base_filter = [
        {"terms": {"doc_id": doc_ids}},
        {"bool" : should_filter},
    ]

    sector_agg = {
        "sector_breakdown": {
            "terms": {"field": "sector", "size": 7},
            "aggs" : {
                "tendency_breakdown": {
                    "terms": {"field": "tendency", "size": 3}
                }
            }
        }
    }

    searches = [
        # A — 전체 분위기 (1번)
        {},
        {
            "query": {"bool": {"filter": base_filter}},
            "size" : 0,
            "aggs" : {
                "tendency"  : {"terms": {"field": "tendency",   "size": 3}},
                "avg_score" : {"avg"  : {"field": "tend_score"}},
            }
        },

        # B — 연관 분야별 긍/부정 비교 (2번)
        {},
        {
            "query": {"bool": {"filter": base_filter}},
            "size" : 0,
            "aggs" : sector_agg
        },

        # C — 관련 뉴스 1순위 8개 (3번)
        {},
        {
            "query"  : {"bool": {"filter": base_filter}},
            "size"   : 8,
            "sort"   : [{"tend_score": {"order": "desc"}}],
            "_source": ["doc_id", "title", "tendency", "tend_score",
                        "url", "published_at", "keywords", "sector"],
        },
    ]
    return searches


# ================================================================
# 번호별 조립 함수
# ================================================================
def buildOverall(res_a: dict) -> dict:
    """
    검색어 기준 전체 분위기 반환 (1번)

    res_a   : msearch 쿼리 A 응답 (tendency 집계 + tend_score 평균)
    처리     : 긍/부정 기사 수 집계 → 비율 계산 → 라벨 결정
    반환     : { pos, neg, total, label, score }
    사용처   : 검색 결과 상단 "전체 분위기" 카드
    """
    buckets   = res_a.get("aggregations", {}).get("tendency",  {}).get("buckets", [])
    avg_score = res_a.get("aggregations", {}).get("avg_score", {}).get("value", 0.0) or 0.0

    counts = {"positive": 0, "negative": 0}
    for b in buckets:
        if b["key"] in counts:
            counts[b["key"]] = b["doc_count"]
    total = sum(counts.values())

    if total == 0:
        return {"pos": 0.0, "neg": 0.0, "total": 0, "label": "중립", "score": 0.0}

    pos = round(counts["positive"] / total * 100, 1)
    neg = round(counts["negative"] / total * 100, 1)
    return {
        "pos"  : pos,
        "neg"  : neg,
        "total": total,
        "label": "긍정" if pos >= neg else "부정",
        "score": round(avg_score, 4),
    }


def buildSectors(res_b: dict, total: int) -> tuple:
    """
    연관 분야별 긍/부정 비교 반환 (2번)

    res_b   : msearch 쿼리 B 응답 (sector × tendency 집계)
    total   : 전체 기사 수 (relevance 계산용 — buildOverall total 재사용)
    처리     : 섹터별 긍/부정 비율 + 전체 대비 연관도(relevance) 계산
    정렬     : doc_count 내림차순
    반환     : sectors 리스트, top3_sectors 리스트 (2순위 기사 필터용)
    사용처   : 검색 결과 "연관 분야별 비교" 섹터 막대 차트
    """
    buckets = res_b.get("aggregations", {}).get("sector_breakdown", {}).get("buckets", [])
    sectors = []

    for b in buckets:
        sector  = translateSector(b.get("key", ""))
        s_total = b.get("doc_count", 0)
        counts  = {"positive": 0, "negative": 0}
        for td in b.get("tendency_breakdown", {}).get("buckets", []):
            if td["key"] in counts:
                counts[td["key"]] = td["doc_count"]

        sectors.append({
            "sector"    : sector,
            "pos"       : round(counts["positive"] / s_total * 100, 1) if s_total else 0.0,
            "neg"       : round(counts["negative"] / s_total * 100, 1) if s_total else 0.0,
            "total"     : s_total,
            "relevance" : round(s_total / total * 100, 1) if total else 0.0,
        })

    # relevance 내림차순 정렬
    sectors.sort(key=lambda x: x["relevance"], reverse=True)
    top3_sectors = [s["sector"] for s in sectors[:3]]
    return sectors, top3_sectors


def buildArticles(res_c: dict, top3_sectors: list, doc_ids: list,
                  keyword: str, es) -> list:
    """
    관련 뉴스 최대 8개 반환 (3번)

    res_c        : msearch 쿼리 C 응답 (1순위 기사 최대 8개)
    top3_sectors : buildSectors() 에서 받은 연관도 Top3 섹터 (2순위 필터용)
    doc_ids      : 오늘 날짜 doc_id 목록 (2순위 쿼리 필터용)
    keyword      : 검색어 (2순위 쿼리 should 필터용)
    es           : ES 클라이언트 (2순위 추가 쿼리 + url 보강용)

    처리
    1. 1순위 기사 수집 (tend_score 내림차순)
    2. 8개 미달 시 Top3 섹터 기반 2순위 기사 추가 조회
    3. doc_id → news_ko/en 순으로 url 보강 (_fetchUrl)
    4. rank 태그 부여 (primary / secondary)

    반환  : [ { title, tendency, tend_score, url, sector, rank }, ... ] 최대 8개
    주의  : es 객체 직접 사용 → 반드시 try 블록 안(es.close() 전)에서 호출
    사용처 : 검색 결과 "관련 뉴스" 기사 목록
    """
    first_hits  = res_c.get("hits", {}).get("hits", [])
    first_ids   = [h.get("_source", {}).get("doc_id") or h.get("_id") for h in first_hits]
    first_count = len(first_hits)

    articles = []

    # ── 1순위 기사 처리 ───────────────────────────────────────
    for h in first_hits:
        source = h.get("_source", {})
        doc_id = h.get("_id") or source.get("doc_id")
        source["url"]  = _fetchUrl(es, doc_id)
        source["sector"] = translateSector(source.get("sector", ""))
        source["rank"] = "primary"
        articles.append(source)

    # ── 2순위 기사 추가 (1순위 8개 미달 시) ─────────────────
    if first_count < 8 and top3_sectors:
        need   = 8 - first_count
        should = buildShouldFilter(keyword)
        second_res = es.search(
            index = ANALYZE_DATA_IDX,
            body  = {
                "query": {
                    "bool": {
                        "filter"  : [
                            {"terms": {"doc_id": doc_ids}},
                            {"terms": {"sector": top3_sectors}},
                            {"bool" : should},
                        ],
                        "must_not": [{"terms": {"doc_id": first_ids}}],
                    }
                },
                "size"   : need,
                "sort"   : [{"tend_score": {"order": "desc"}}],
                "_source": ["doc_id", "title", "tendency", "tend_score",
                            "url", "published_at", "keywords", "sector"],
            }
        )
        for h in second_res.get("hits", {}).get("hits", []):
            source = h.get("_source", {})
            doc_id = h.get("_id") or source.get("doc_id")
            source["url"]  = _fetchUrl(es, doc_id)
            source["sector"] = translateSector(source.get("sector", ""))
            source["rank"] = "secondary"
            articles.append(source)

    return articles


def _fetchUrl(es, doc_id: str) -> str | None:
    """
    doc_id 로 news_ko → news_en 순으로 url 조회

    es     : ES 클라이언트
    doc_id : analyze 인덱스의 문서 ID
    처리    : news_ko 먼저 조회 → 없으면 news_en 시도
    반환    : url 문자열 또는 None (두 인덱스 모두 실패 시)
    """
    if not doc_id:
        return None
    for index in [NEWS_KO_IDX, NEWS_EN_IDX]:
        try:
            res = es.get(index=index, id=doc_id, _source=["url"])
            url = res.get("_source", {}).get("url")
            if url:
                return url
        except Exception:
            continue
    return None


# ================================================================
# 검색 엔드포인트
# ================================================================
@router.get("/search")
def getSearchResult(keyword: str, request: Request = None):
    """
    검색 결과 전체 데이터 조회

    GET /api/search?keyword=삼성전자  (lang 없이 한국/미국 동시 검색)

    데이터 소스 : ES analyze (msearch A~C + 필요 시 추가 쿼리 1번)
    처리 순서
    1. news_ko + news_en 양쪽 doc_id 합산
    2. msearch (쿼리 A~C) — should 필터로 검색어 매칭
    3. buildOverall   → 전체 분위기 + 평균 점수
    4. buildSectors   → 연관 분야별 비교
    5. buildArticles  → 관련 뉴스 (1순위 부족 시 2순위 추가)

    반환   : keyword, overall, sectors, articles
    주의   : buildArticles 는 es 직접 사용
             → 반드시 try 블록 안(es.close() 전)에서 호출
    """
    u_id = request.session.get("u_id") if request else None

    if not keyword or not keyword.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력해 주세요.")

    keyword = keyword.strip()
    today   = "2026-03-31"

    u_logger.info("검색 요청", extra={
        "action" : "search",
        "u_id"   : u_id,
        "keyword": keyword,
    })

    es = getEs()
    try:
        # news_ko + news_en 양쪽 doc_id 수집 후 합산
        doc_ids_ko = getDocIds(es, NEWS_KO_IDX, today, today)
        doc_ids_en = getDocIds(es, NEWS_EN_IDX, today, today)
        doc_ids    = list(set(doc_ids_ko + doc_ids_en))

        if not doc_ids:
            logger.warning("검색 대상 기사 없음", extra={
                "action": "search_empty",
                "u_id"  : u_id,
                "date"  : today,
            })
            return ok("검색 결과가 없습니다.", {
                "keyword" : keyword,
                "overall" : {"pos": 0.0, "neg": 0.0, "total": 0, "label": "긍정", "score": 0.0},
                "sectors" : [],
                "articles": [],
            })

        # msearch
        searches  = buildMsearch(doc_ids, keyword)
        ms_result = es.msearch(index=ANALYZE_DATA_IDX, body=searches)
        responses = ms_result.get("responses", [])

        if len(responses) < 3:
            raise ValueError(f"msearch 응답 부족: {len(responses)}개")

        res_a, res_b, res_c = responses[:3]

        # 번호별 조립 (es 사용 → try 블록 안에서 처리)
        overall               = buildOverall(res_a)
        sectors, top3_sectors = buildSectors(res_b, overall["total"])
        articles              = buildArticles(res_c, top3_sectors, doc_ids, keyword, es)

        # 결과 로그
        if overall["total"] == 0:
            u_logger.warning("검색 결과 없음", extra={
                "action" : "search_empty",
                "u_id"   : u_id,
                "keyword": keyword,
            })
        else:
            u_logger.info("검색 성공", extra={
                "action" : "search_success",
                "u_id"   : u_id,
                "keyword": keyword,
                "total"  : overall["total"],
                "ko_cnt" : len(doc_ids_ko),
                "en_cnt" : len(doc_ids_en),
            })

    except Exception as e:
        logger.error("검색 조회 오류", extra={
            "action" : "search_fail",
            "keyword": keyword,
            "err_msg": str(e),
        })
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="데이터 조회 중 오류가 발생했습니다.")
    finally:
        es.close()

    return ok("검색 결과 조회 성공", {
        "keyword" : keyword,
        "overall" : overall,
        "sectors" : sectors,
        "articles": articles,
    })
