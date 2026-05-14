"""
keywordRouter.py
GET /api/keyword?lang=ko

[ 응답 구조 ]
{
  "top7"           : [ { rank, keyword, count, week_avg, change }, ... ],
  "weekly_trend"   : { dates, lines: [ { keyword, data }, ... ] },
  "keyword_network": { nodes: [ { keyword, count } ], edges: [ { source, target, weight } ] },
  "hot_news"       : [
    {
      "keyword" : "반도체",
      "article" : { title, tendency, tend_score, url },
      "strength": { total, strongest, related: [ { keyword, count, strength } ] }
    },
    ... (7개)
  ]
}
"""

from datetime import date, timedelta
from itertools import combinations

from fastapi import APIRouter, HTTPException

from dataStorage.elasticSearch.es import getEs, ANALYZE_DATA_IDX, NEWS_KO_IDX, NEWS_EN_IDX
from logs.logger import getLogger
from router.commonFunc import ok, getDocIds

logger = getLogger("system")
router = APIRouter(prefix="/api", tags=["keyword"])
# ================================================================
# ES msearch 쿼리 조립
# ================================================================
def buildMsearch(doc_ids_today: list, doc_ids_week: list, top20_words: list) -> list:
    """
    쿼리 5개 (A B C D E)
    doc_ids_today/week : news_ko/en 에서 미리 수집한 doc_id 목록
    top20_words        : 쿼리 D·E 에서 필터로 사용할 Top20 키워드
    """
    filter_today = [{"terms": {"doc_id": doc_ids_today}}]
    filter_week  = [{"terms": {"doc_id": doc_ids_week}}]

    # 쿼리 D — Top20 키워드 포함 기사의 keywords 배열
    query_d_filter = filter_today.copy()
    if top20_words:
        query_d_filter.append({"terms": {"keywords": top20_words}})

    # 쿼리 E — keyword별 최신 기사 + 연관 키워드 강도
    by_keyword_agg = {
        "by_keyword": {
            "terms": {
                "field"  : "keywords",
                "size"   : 100,
                **({"include": top20_words} if top20_words else {})
            },
            "aggs": {
                "related_keywords": {
                    "terms": {"field": "keywords", "size": 20}
                },
                "latest_article": {
                    "top_hits": {
                        "size"   : 1,
                        "sort"   : [{"tend_score": {"order": "desc"}}],
                        "_source": ["title", "tendency", "tend_score", "url"]
                    }
                }
            }
        }
    }

    searches = [
        # A — 오늘 keyword 집계 (1번, 3번, 4번, 5번)
        {},
        {"query": {"bool": {"filter": filter_today}}, "size": 0,
         "aggs": {"keywords": {"terms": {"field": "keywords", "size": 100}}}},

        # B — 7일 keyword 집계 (1번, 5번)
        {},
        {"query": {"bool": {"filter": filter_week}}, "size": 0,
         "aggs": {"keywords": {"terms": {"field": "keywords", "size": 100}}}},

        # C — 7일 날짜별 × 키워드별 집계 (3번)
        # analyze에 published_at 없음 → doc_id 기준으로 날짜별 분리 불가
        # → news_ko/en에서 날짜별 doc_id 묶음을 별도 조회 후 키워드 집계
        {},
        {"query": {"bool": {"filter": filter_week}}, "size": 0,
         "aggs": {
             "keywords_week": {
                 "terms": {"field": "keywords", "size": 20}
             }
         }},

        # D — Top20 키워드 포함 기사의 keywords 배열 (4번)
        {},
        {"query": {"bool": {"filter": query_d_filter}},
         "size" : 200,
         "_source": ["keywords"]},

        # E — keyword별 최신기사 + 연관 키워드 강도 (2번, 5번)
        {},
        {"query": {"bool": {"filter": filter_today}}, "size": 0,
         "aggs": by_keyword_agg},
    ]
    return searches


# ================================================================
# 번호별 조립 함수
# ================================================================
def buildTop7(res_a: dict, res_b: dict) -> list:
    buckets = res_a.get("aggregations", {}).get("keywords", {}).get("buckets", [])

    ranked = [
        {
            "keyword": b["key"],
            "count"  : b["doc_count"],
        }
        for b in buckets
    ]

    ranked.sort(key=lambda x: x["count"], reverse=True)
    return [{"rank": i + 1, **item} for i, item in enumerate(ranked[:7])]


def buildStrength(res_e: dict, top7_words: list, total_map: dict) -> dict:
    """
    2번 — 연관 강도 계기판
    top7_words : Top7 키워드 리스트
    total_map  : { keyword: today_count }
    반환: { keyword: { total, strongest, related: [...] } }
    """
    result = {}
    buckets = res_e.get("aggregations", {}).get("by_keyword", {}).get("buckets", [])

    for b in buckets:
        kw = b["key"]
        if kw not in top7_words:
            continue

        total    = total_map.get(kw, b["doc_count"])
        rel_bkts = b.get("related_keywords", {}).get("buckets", [])

        # 자기 자신 제거
        related = [
            {
                "keyword" : r["key"],
                "count"   : r["doc_count"],
                "strength": round(r["doc_count"] / total * 100, 1) if total else 0.0,
            }
            for r in rel_bkts if r["key"] != kw
        ][:3]  # Top3

        result[kw] = {
            "total"    : total,
            "strongest": related[0]["keyword"] if related else None,
            "related"  : related,
        }

    return result


def buildWeeklyTrend(res_a: dict, res_c: dict, es, news_index: str, today: str, week_ago: str) -> dict:
    """
    3번 — 주간 트렌드 추이 (Top5 키워드 × 7일)
    analyze에 published_at 없으므로 날짜별로 news_ko/en → doc_id 수집 후 각 날짜 키워드 집계
    """
    from datetime import datetime, timedelta as td

    top5_words = [
        b["key"]
        for b in res_a.get("aggregations", {}).get("keywords", {}).get("buckets", [])[:5]
    ]

    # 7일치 날짜 리스트 생성
    start = datetime.fromisoformat(week_ago)
    end   = datetime.fromisoformat(today)
    dates = [(start + td(days=i)).strftime("%Y-%m-%d") for i in range((end - start).days + 1)]

    lines_map = {kw: [0] * len(dates) for kw in top5_words}

    for day_idx, day_str in enumerate(dates):
        # 해당 날짜의 doc_id 수집
        day_ids = getDocIds(es, news_index, day_str, day_str)
        if not day_ids:
            continue

        # 해당 날짜 doc_id로 keyword 집계
        day_res = es.search(
            index = "analyze",
            body  = {
                "query": {"bool": {"filter": [{"terms": {"doc_id": day_ids}}]}},
                "size" : 0,
                "aggs" : {"keywords": {"terms": {"field": "keywords", "size": 20}}}
            }
        )
        kw_map = {
            b["key"]: b["doc_count"]
            for b in day_res.get("aggregations", {}).get("keywords", {}).get("buckets", [])
        }
        for kw in top5_words:
            lines_map[kw][day_idx] = kw_map.get(kw, 0)

    return {
        "dates": dates,
        "lines": [{"keyword": kw, "data": lines_map[kw]} for kw in top5_words],
    }


def buildNetwork(res_a: dict, res_d: dict) -> dict:
    """4번 — 키워드 네트워크 (공출현 계산)"""
    top20_map = {
        b["key"]: b["doc_count"]
        for b in res_a.get("aggregations", {}).get("keywords", {}).get("buckets", [])[:20]
    }
    top20_set = set(top20_map.keys())

    # 공출현 카운트
    co_count = {}
    for hit in res_d.get("hits", {}).get("hits", []):
        kws = [k for k in hit.get("_source", {}).get("keywords", []) if k in top20_set]
        for pair in combinations(sorted(kws), 2):
            co_count[pair] = co_count.get(pair, 0) + 1

    # 2회 미만 제거
    edges = [
        {"source": s, "target": t, "weight": w}
        for (s, t), w in co_count.items() if w >= 2
    ]
    edges.sort(key=lambda x: x["weight"], reverse=True)

    # 엣지에 등장한 노드만 (고립 노드 제거)
    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    nodes = [
        {"keyword": kw, "count": cnt}
        for kw, cnt in top20_map.items() if kw in connected
    ]

    return {"nodes": nodes, "edges": edges}


def buildHotNews(res_e: dict, top7: list, strength_map: dict, es=None, news_index: str = None) -> list:
    article_map = {}
    for b in res_e.get("aggregations", {}).get("by_keyword", {}).get("buckets", []):
        kw   = b["key"]
        hits = b.get("latest_article", {}).get("hits", {}).get("hits", [])
        if hits:
            source = hits[0].get("_source", {})
            doc_id = hits[0].get("_id") or source.get("doc_id")

            # doc_id 로 news_ko/en 에서 url 조회
            if doc_id and es and news_index:
                try:
                    news_res = es.get(index=news_index, id=doc_id, _source=["url"])
                    source["url"] = news_res.get("_source", {}).get("url")
                except:
                    pass

            article_map[kw] = source

    result = []
    for item in top7:
        kw = item["keyword"]
        result.append({
            "keyword" : kw,
            "article" : article_map.get(kw),
            "strength": strength_map.get(kw),
        })
    return result


# ================================================================
# 키워드 트렌드 엔드포인트
# ================================================================
@router.get("/keyword")
def getKeywordTrend(lang: str = "ko"):
    """
    GET /api/keyword?lang=ko
    ES msearch 1번 왕복 → JSON 한 방 반환
    """
    # today    = date.today().isoformat()
    # week_ago = (date.today() - timedelta(days=7)).isoformat()
    today = "2026-03-31"
    week_ago = "2026-03-24"

    news_index = NEWS_KO_IDX if lang == "ko" else NEWS_EN_IDX
    es = getEs()
    try:
        doc_ids_today = getDocIds(es, news_index, today, today)
        doc_ids_week  = getDocIds(es, news_index, week_ago, today)

        searches  = buildMsearch(doc_ids_today, doc_ids_week, top20_words=[])
        ms_result = es.msearch(index=ANALYZE_DATA_IDX, body=searches)
        responses = ms_result.get("responses", [])

        if len(responses) < 5:
            raise ValueError(f"msearch 응답 부족: {len(responses)}개")

        res_a, res_b, res_c, res_d, res_e = responses[:5]

        top7       = buildTop7(res_a, res_b)
        top7_words = [item["keyword"] for item in top7]
        total_map  = {
            b["key"]: b["doc_count"]
            for b in res_a.get("aggregations", {}).get("keywords", {}).get("buckets", [])
        }

        strength_map    = buildStrength(res_e, top7_words, total_map)
        # buildWeeklyTrend — 날짜별 ES 추가 조회 (es 객체 try 블록 안에서 사용)
        weekly_trend    = buildWeeklyTrend(res_a, res_c, es, news_index, today, week_ago)
        keyword_network = buildNetwork(res_a, res_d)
        hot_news = buildHotNews(res_e, top7, strength_map, es=es, news_index=news_index)

    except Exception as e:
        logger.error(f"ES 조회 오류: {e}")
        raise HTTPException(status_code=500, detail="데이터 조회 중 오류가 발생했습니다.")
    finally:
        es.close()

    logger.info("키워드 트렌드 조회 성공", extra={"lang": lang, "date": today})

    return ok("키워드 트렌드 조회 성공", {
        "top7"            : top7,
        "weekly_trend"    : weekly_trend,
        "keyword_network" : keyword_network,
        "hot_news"        : hot_news,
    })
