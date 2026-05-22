"""
spikeRouter.py
GET /api/spike?lang=ko

[ 응답 구조 ]
{
  "overall": {
    "pos": 62.5, "neg": 17.9, "neu": 19.6, "total": 240,
    "by_sector": [ { sector, pos, neg, neu, total }, ... ]
  },
  "sector_changes": [
    {
      "sector"  : "AI",
      "today"   : { pos, neg, neu, total },
      "week_avg": { pos, neg, neu, total },
      "change"  : { pos, neg },
      "articles": [ { title, tendency, tend_score, url, published_at, keywords }, ... ]
    },
    ...
  ]
}
"""

from fastapi import APIRouter, HTTPException
from datetime import date, timedelta
from dataStorage.elasticSearch.es import getEs, ANALYZE_DATA_IDX, NEWS_KO_IDX, NEWS_EN_IDX
from logs.logger import getLogger
from router.commonFunc import ok, translateSector, getDocIds, getTodayRange

logger = getLogger("system")
router = APIRouter(prefix="/api", tags=["spike"])

# ================================================================
# 공통 유틸
# ================================================================
def calcSectorRatios(buckets: list) -> dict:
    """
    ES sector × tendency 집계 결과 → 섹터별 긍/부정 비율 딕셔너리 변환
    buckets  : ES sector_breakdown.buckets
    처리      : 섹터명 한글 변환(translateSector) + 긍/부정 비율 계산
    반환      : { "IT/기술": { pos, neg, total, _pos_count, _neg_count }, ... }
    _pos/neg_count : buildOverall() 전체 합산용 내부 값 (응답 미포함)
    """
    result = {}
    for b in buckets:
        sector = b.get("key", "")
        counts = {"positive": 0, "negative": 0}
        for td in b.get("tendency_breakdown", {}).get("buckets", []):
            if td["key"] in counts:
                counts[td["key"]] = td["doc_count"]
        total = b.get("doc_count", 0)
        result[translateSector(sector)] = {
            "pos"  : round(counts["positive"] / total * 100, 1) if total else 0.0,
            "neg"  : round(counts["negative"] / total * 100, 1) if total else 0.0,
            "total": total,
            # 내부 계산용 (응답에는 포함 안 함)
            "_pos_count": counts["positive"],
            "_neg_count": counts["negative"],
        }
    return result


# ================================================================
# ES msearch 쿼리 조립
# ================================================================
def buildMsearch(doc_ids_today: list, doc_ids_week: list) -> list:
    """급등 기사 분석에 필요한 ES msearch 쿼리 목록 생성
    쿼리 순서     : A B C
    A : 오늘 sector × tendency       → 1번(종합 성향), 2번(변화량)
    B : 7일  sector × tendency       → 2번(평소 대비 비교)
    C : 오늘 섹터별 기사 Top5         → 3번(급등 기사 목록)
    doc_ids_today : 오늘 날짜 기사의 doc_id 목록
    doc_ids_week  : 최근 7일 기사의 doc_id 목록
    반환           : [ {헤더}, {바디}, ... ] msearch 형식 리스트"""
    filter_today = [{"terms": {"doc_id": doc_ids_today}}]
    filter_week  = [{"terms": {"doc_id": doc_ids_week}}]

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
        # A — 오늘 sector × tendency (1번, 2번)
        {},
        {"query": {"bool": {"filter": filter_today}}, "size": 0, "aggs": sector_agg},

        # B — 7일 sector × tendency (2번)
        {},
        {"query": {"bool": {"filter": filter_week}}, "size": 0, "aggs": sector_agg},

        # C — 섹터별 top_hits 5개 (3번)
        {},
        {
            "query": {"bool": {"filter": filter_today}},
            "size" : 0,
            "aggs" : {
                "sector_breakdown": {
                    "terms": {"field": "sector", "size": 7},
                    "aggs" : {
                        "top_articles": {
                            "top_hits": {
                                "size"   : 5,
                                "sort"   : [{"tend_score": {"order": "desc"}}],
                                "_source": [
                                    "title", "tendency", "tend_score",
                                    "url", "published_at", "keywords"
                                ]
                            }
                        }
                    }
                }
            }
        },
    ]
    return searches


# ================================================================
# 번호별 조립 함수
# ================================================================
def buildOverall(res_a: dict) -> dict:
    """
    급등 기사 종합 성향 반환 (1번)
    res_a   : msearch 쿼리 A 응답 (오늘 sector × tendency)
    처리     : 전체 섹터 긍/부정 합산 → 전체 비율 계산
    반환     : overall { pos, neg, total, by_sector }, today_ratios (buildSectorChanges 전달용)
    사용처   : spike.html 상단 종합 점수 + 긍/부정 막대
    """
    buckets      = res_a.get("aggregations", {}).get("sector_breakdown", {}).get("buckets", [])
    today_ratios = calcSectorRatios(buckets)

    # 전체 합산
    total_pos = sum(r["_pos_count"] for r in today_ratios.values())
    total_neg = sum(r["_neg_count"] for r in today_ratios.values())
    total_all = total_pos + total_neg

    by_sector = [
        {
            "sector": translateSector(sector),
            "pos"   : r["pos"],
            "neg"   : r["neg"],
            "total" : r["total"],
        }
        for sector, r in today_ratios.items()
    ]

    return {
        "pos"      : round(total_pos / total_all * 100, 1) if total_all else 0.0,
        "neg"      : round(total_neg / total_all * 100, 1) if total_all else 0.0,
        "total"    : total_all,
        "by_sector": by_sector,
    }, today_ratios


def buildSectorChanges(today_ratios: dict, res_b: dict, res_c: dict,
                       es=None, news_index: str = None) -> list:
    """
    섹터별 긍/부정률 변화(2번) + 급등 기사 목록(3번) 병합 반환
    today_ratios : buildOverall() 에서 받은 오늘 섹터별 비율
    res_b        : msearch 쿼리 B 응답 (7일 sector × tendency)
    res_c        : msearch 쿼리 C 응답 (오늘 섹터별 기사 Top5)
    es           : ES 클라이언트 (news_ko/en url 보강용)
    news_index   : news_ko 또는 news_en
    정렬          : abs(pos 변화량) 내림차순
    반환          : [ { sector, today, week_avg, change, articles }, ... ]
    주의          : es.get() 사용 → 반드시 try 블록 안(es.close() 전)에서 호출
    사용처        : spike.html 섹터 카드 클릭 → 해당 섹터 기사 목록
    """

    # 7일 섹터 비율
    week_buckets = res_b.get("aggregations", {}).get("sector_breakdown", {}).get("buckets", [])
    week_ratios  = calcSectorRatios(week_buckets)

    # 섹터별 기사 목록 (3번)
    article_buckets = res_c.get("aggregations", {}).get("sector_breakdown", {}).get("buckets", [])
    sector_articles = {}
    for b in article_buckets:
        sector = translateSector(b["key"])
        hits = b.get("top_articles", {}).get("hits", {}).get("hits", [])
        articles = []
        for h in hits:
            source = h.get("_source", {})
            doc_id = h.get("_id") or source.get("doc_id")
            # doc_id로 news_ko/en에서 url 조회
            if doc_id and es and news_index:
                try:
                    news_res = es.get(index=news_index, id=doc_id, _source=["url"])
                    source["url"] = news_res.get("_source", {}).get("url")
                except:
                    pass
            articles.append(source)
        sector_articles[sector] = articles

    # 2번 변화량 계산 후 3번 기사 병합
    sector_changes = []
    for sector, today in today_ratios.items():
        week         = week_ratios.get(sector, {"pos": 0.0, "neg": 0.0, "total": 0})
        week_avg_total = round(week["total"] / 7, 1)

        sector_changes.append({
            "sector"  : sector,
            "today"   : {
                "pos"  : today["pos"],
                "neg"  : today["neg"],
                "total": today["total"],
            },
            "week_avg": {
                "pos"  : week["pos"],
                "neg"  : week["neg"],
                "total": week_avg_total,
            },
            "change"  : {
                "pos": round(today["pos"] - week["pos"], 1),
                "neg": round(today["neg"] - week["neg"], 1),
            },
            "articles": sector_articles.get(sector, []),
        })

    # abs(pos_change) 내림차순 정렬
    sector_changes.sort(key=lambda x: abs(x["change"]["pos"]), reverse=True)
    return sector_changes


# ================================================================
# 급등 기사 분석 엔드포인트
# ================================================================
@router.get("/spike")
def getSpikeReport(lang: str = "ko"):
    """
    급등 기사 분석 전체 데이터 조회
    GET /api/spike?lang=ko  (lang=en → 미국 기사 조회)
    데이터 소스 : ES analyze (msearch A~C)
    처리 순서   : news doc_id 수집 → msearch → buildOverall → buildSectorChanges
    반환        : overall, sector_changes
    주의 : buildSectorChanges 는 es 직접 사용
           → 반드시 try 블록 안(es.close() 전)에서 호출
           today/week_ago 는 테스트용 고정값 → 운영 시 date.today() 로 교체
    """
    start, end = getTodayRange(lang)
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    news_index = NEWS_KO_IDX if lang == "ko" else NEWS_EN_IDX
    es = getEs()
    try:
        doc_ids_today = getDocIds(es, news_index, start, end)
        doc_ids_week = getDocIds(es, news_index, week_ago, end)

        if not doc_ids_today:
            logger.warning("오늘 기사 없음 — 빈 데이터 반환", extra={
                "action": "doc_ids_empty",
                "index" : news_index,
                "date"  : end,
            })

        searches  = buildMsearch(doc_ids_today, doc_ids_week)
        ms_result = es.msearch(index=ANALYZE_DATA_IDX, body=searches)
        responses = ms_result.get("responses", [])

        if len(responses) < 3:
            raise ValueError(f"msearch 응답 부족: {len(responses)}개")

        res_a, res_b, res_c = responses[:3]

        # ← try 블록 안으로 이동 (es.close() 전에 실행)
        overall, today_ratios = buildOverall(res_a)
        sector_changes = buildSectorChanges(today_ratios, res_b, res_c,
                                            es=es, news_index=news_index)

    except Exception as e:
        logger.error("급등 기사 분석 조회 오류", extra={
            "action" : "spike_fetch_fail",
            "lang"   : lang,
            "err_msg": str(e),
        })
        raise HTTPException(status_code=500, detail="데이터 조회 중 오류가 발생했습니다.")
    finally:
        es.close()

    logger.info("급등 기사 분석 조회 성공", extra={
        "action"      : "spike_fetch",
        "lang"        : lang,
        "date"        : end,
        "sector_cnt"  : len(sector_changes),
    })

    return ok("급등 기사 분석 조회 성공", {
        "overall"       : overall,
        "sector_changes": sector_changes,
    })
