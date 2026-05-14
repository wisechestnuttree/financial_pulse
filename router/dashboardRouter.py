"""
dashboardRouter.py
GET /api/dashboard?lang=ko

[ 데이터 소스 ]
- ES  : dataStorage.elasticSearch.es 의 getEs(), ANALYZE_DATA_IDX 사용
- DB  : dataStorage.mariaDb.db 의 getConn() 사용 (경제지표)
- CSV : korea_schedule.csv (경제 일정)

[ 응답 구조 ]
{
  "tendency"       : { pos, neg, neu, total, label },
  "top_keyword"    : { keyword, count },
  "pos_keyword"    : { keyword, count, ratio },
  "neg_keyword"    : { keyword, count, ratio },
  "hot_issues"     : [ { keyword, count, week_avg, change }, ... ],
  "spike_analysis" : [ { sector, today, week_avg, change }, ... ],
  "market_tendency": { pos, neg, neu, pos_count, neg_count, neu_count, total },
  "sector_tendency": [ { sector, pos, neg, neu, total }, ... ],
  "eco_indicators" : [ { country, label, date, actual, forecast, previous }, ... ],
  "eco_schedule"   : [ { date, event, importance }, ... ]
}
"""
import pandas as pd
from fastapi import APIRouter, HTTPException

from dataStorage.elasticSearch.es import * # getEs, ANALYZE_DATA_IDX, NEWS_KO_IDX, NEWS_EN_IDX
from dataStorage.mariaDb.db import getConn
from logs.logger import getLogger
from router.commonFunc import ok, translateSector, getDocIds

logger = getLogger("system")
router = APIRouter(prefix="/api", tags=["dashboard"])

SCHEDULE_CSV = "korea_schedule.csv"

# ================================================================
# 공통 유틸
# ================================================================
def calcRatios(buckets: list) -> dict:
    """tendency buckets → { pos, neg, neu, total }"""
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for b in buckets:
        if b.get("key") in counts:
            counts[b["key"]] = b.get("doc_count", 0)
    total = sum(counts.values())
    if total == 0:
        return {"pos": 0.0, "neg": 0.0, "neu": 0.0, "total": 0}
    return {
        "pos"  : round(counts["positive"] / total * 100, 1),
        "neg"  : round(counts["negative"] / total * 100, 1),
        "total": total,
    }


def calcSectorRatios(buckets: list) -> dict:
    """sector × tendency_breakdown → { sector: { pos, neg, neu, total } }"""
    result = {}
    for b in buckets:
        sector  = b.get("key", "")
        td_bkts = b.get("tendency_breakdown", {}).get("buckets", [])
        ratios  = calcRatios(td_bkts)
        ratios["total"] = b.get("doc_count", 0)
        result[translateSector(sector)]  = ratios
    return result


def tendencyLabel(pos: float, neg: float) -> str:
    return "긍정" if pos >= neg else "부정"


# ================================================================
# ES msearch 쿼리 조립
# ================================================================
def buildMsearch(doc_ids_today: list, doc_ids_week: list) -> list:
    """
    msearch body 리스트 반환 (헤더 + 바디 쌍)
    쿼리 순서: A B C D E F G
    doc_ids_today/week : news_ko/en 에서 미리 수집한 doc_id 목록
    """
    filter_today = [{"terms": {"doc_id": doc_ids_today}}]
    filter_week  = [{"terms": {"doc_id": doc_ids_week}}]
    filter_today_pos = filter_today + [{"term": {"tendency": "positive"}}]
    filter_today_neg = filter_today + [{"term": {"tendency": "negative"}}]

    sector_agg = {
        "sector_breakdown": {
            "terms": {"field": "sector",   "size": 7},
            "aggs" : {
                "tendency_breakdown": {
                    "terms": {"field": "tendency", "size": 3}
                }
            }
        }
    }

    searches = [
        # A — 오늘 tendency (1번, 7번)
        {},
        {"query": {"bool": {"filter": filter_today}}, "size": 0,
         "aggs": {"tendency": {"terms": {"field": "tendency", "size": 3}}}},

        # B — 오늘 keyword (2번, 5번)
        {},
        {"query": {"bool": {"filter": filter_today}}, "size": 0,
         "aggs": {"keywords": {"terms": {"field": "keywords", "size": 20}}}},

        # C — 7일 keyword (5번)
        {},
        {"query": {"bool": {"filter": filter_week}}, "size": 0,
         "aggs": {"keywords": {"terms": {"field": "keywords", "size": 20}}}},

        # D — 오늘 긍정 keyword (3번)
        {},
        {"query": {"bool": {"filter": filter_today_pos}}, "size": 0,
         "aggs": {"keywords": {"terms": {"field": "keywords", "size": 1}}}},

        # E — 오늘 부정 keyword (4번)
        {},
        {"query": {"bool": {"filter": filter_today_neg}}, "size": 0,
         "aggs": {"keywords": {"terms": {"field": "keywords", "size": 1}}}},

        # F — 오늘 sector × tendency (6번, 8번)
        {},
        {"query": {"bool": {"filter": filter_today}}, "size": 0, "aggs": sector_agg},

        # G — 7일 sector × tendency (6번)
        {},
        {"query": {"bool": {"filter": filter_week}}, "size": 0, "aggs": sector_agg},
    ]
    return searches


# ================================================================
# 번호별 조립 함수
# ================================================================
def buildTendency(res_a: dict):
    """1번 tendency + 7번 market_tendency"""
    buckets = res_a.get("aggregations", {}).get("tendency", {}).get("buckets", [])
    counts  = {"positive": 0, "negative": 0, "neutral": 0}
    for b in buckets:
        if b["key"] in counts:
            counts[b["key"]] = b["doc_count"]
    total = sum(counts.values())

    if total == 0:
        base = {"pos": 0.0, "neg": 0.0, "neu": 0.0, "total": 0}
    else:
        base = {
            "pos"  : round(counts["positive"] / total * 100, 1),
            "neg"  : round(counts["negative"] / total * 100, 1),
            "total": total,
        }

    tendency = {**base, "label": tendencyLabel(base["pos"], base["neg"])}
    market_tendency = {**base,
                       "pos_count": counts["positive"],
                       "neg_count": counts["negative"]  }
    return tendency, market_tendency


def buildTopKeyword(res_b: dict) -> dict:
    """2번 — 노출도 1위 키워드"""
    buckets = res_b.get("aggregations", {}).get("keywords", {}).get("buckets", [])
    if not buckets:
        return {"keyword": None, "count": 0}
    return {"keyword": buckets[0]["key"], "count": buckets[0]["doc_count"]}


def buildPosNegKeyword(res_d: dict, res_e: dict, total: int):
    """3번 긍정 / 4번 부정 1위 키워드"""
    def extract(res):
        bkts = res.get("aggregations", {}).get("keywords", {}).get("buckets", [])
        if not bkts:
            return {"keyword": None, "count": 0, "ratio": 0.0}
        kw, cnt = bkts[0]["key"], bkts[0]["doc_count"]
        return {"keyword": kw, "count": cnt,
                "ratio": round(cnt / total * 100, 1) if total else 0.0}
    return extract(res_d), extract(res_e)


def buildHotIssues(res_b: dict, res_c: dict) -> list:
    """5번 — 오늘의 핫이슈 (변화량 상위 6개, 10% 이상)"""
    today_map = {b["key"]: b["doc_count"]
                 for b in res_b.get("aggregations", {}).get("keywords", {}).get("buckets", [])}
    week_map  = {b["key"]: b["doc_count"] / 7
                 for b in res_c.get("aggregations", {}).get("keywords", {}).get("buckets", [])}

    issues = []
    for kw, today_cnt in today_map.items():
        week_avg = week_map.get(kw, 0)
        if week_avg == 0:
            continue
        change = round((today_cnt - week_avg) / week_avg * 100, 1)
        if change >= 10:
            issues.append({
                "keyword" : kw,
                "count"   : today_cnt,
                "week_avg": round(week_avg, 1),
                "change"  : change,
            })

    issues.sort(key=lambda x: x["change"], reverse=True)
    return issues[:6]


def buildSpikeAndSector(res_f: dict, res_g: dict):
    """6번 spike_analysis + 8번 sector_tendency"""
    today_ratios = calcSectorRatios(
        res_f.get("aggregations", {}).get("sector_breakdown", {}).get("buckets", [])
    )
    week_ratios = calcSectorRatios(
        res_g.get("aggregations", {}).get("sector_breakdown", {}).get("buckets", [])
    )

    spike_analysis = []
    for sector, today in today_ratios.items():
        week         = week_ratios.get(sector, {"pos": 0.0, "neg": 0.0, "neu": 0.0, "total": 0})
        week_avg_total = round(week["total"] / 7, 1)
        spike_analysis.append({
            "sector"  : sector,
            "today"   : today,
            "week_avg": {**week, "total": week_avg_total},
            "change"  : {
                "pos": round(today["pos"] - week["pos"], 1),
                "neg": round(today["neg"] - week["neg"], 1),
            },
        })
    spike_analysis.sort(key=lambda x: abs(x["change"]["pos"]), reverse=True)

    sector_tendency = [
        {"sector": s, **r} for s, r in today_ratios.items()
    ]
    return spike_analysis, sector_tendency


# ================================================================
# 9번 — 경제지표 (DB)
# ================================================================
def getEcoIndicators() -> list:
    """
    economicIndicator 테이블에서 고정 8개 지표 최신값 조회
    """
    INDICATORS = [
        ("대한민국", "경상수지",             "경상수지 (전월비)"),
        ("대한민국", "실업률",               "실업률 (전월비)"),
        ("대한민국", "GDP 성장률",           "GDP 성장률 (전분기비)"),
        ("대한민국", "소비자물가지수",        "소비자물가지수 (전월비)"),
        ("미국",     "비농업 고용수",         "비농업 고용 (전월비)"),
        ("미국",     "실업률",               "실업률 (전월비)"),
        ("미국",     "GDP 성장률",           "GDP 성장률(전분기비)"),
        ("미국",     "소비자물가지수 (CPI)", "CPI"),
    ]

    conn   = getConn()
    result = []
    try:
        with conn.cursor() as cursor:
            for country, indicator, label in INDICATORS:
                cursor.execute("""
                    SELECT date, actual, previous
                    FROM   economicIndicator
                    WHERE  country = %s AND indicator = %s
                    ORDER  BY date DESC
                    LIMIT  1
                """, (country, indicator))
                row = cursor.fetchone()
                result.append({
                    "country" : country,
                    "label"   : label,
                    "date"    : str(row["date"])    if row else None,
                    "actual"  : row["actual"]       if row else None,
                    "previous": row["previous"]     if row else None,
                })
    finally:
        conn.close()

    return result


# ================================================================
# 10번 — 경제 일정 (CSV)
# ================================================================
def getEcoSchedule() -> list:
    try:
        df = pd.read_csv(SCHEDULE_CSV, encoding="utf-8-sig")
        df = df.where(pd.notnull(df), None)
        return df.to_dict(orient="records")
    except FileNotFoundError:
        logger.error(f"파일 없음: {SCHEDULE_CSV}")
        return []
    except Exception as e:
        logger.error(f"경제 일정 조회 오류: {e}")
        return []


# ================================================================
# 대시보드 엔드포인트
# ================================================================
@router.get("/dashboard")
def getDashboard(lang: str = "ko"):
    """
    GET /api/dashboard?lang=ko
    ES msearch 1번 왕복 + DB + CSV → JSON 한 방 반환
    """
    # today    = date.today().isoformat()
    # week_ago = (date.today() - timedelta(days=7)).isoformat()
    today = "2026-03-31"
    week_ago = "2026-03-24"

    # ── ES — news 인덱스에서 doc_id 수집 후 analyze msearch ────
    news_index = NEWS_KO_IDX if lang == "ko" else NEWS_EN_IDX
    es = getEs()
    try:
        doc_ids_today = getDocIds(es, news_index, today, today)
        doc_ids_week  = getDocIds(es, news_index, week_ago, today)

        searches  = buildMsearch(doc_ids_today, doc_ids_week)
        ms_result = es.msearch(index=ANALYZE_DATA_IDX, body=searches)
        responses = ms_result.get("responses", [])

        if len(responses) < 7:
            raise ValueError(f"msearch 응답 부족: {len(responses)}개")

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"ES 조회 오류: {e}")
        raise HTTPException(status_code=500, detail="데이터 조회 중 오류가 발생했습니다.")
    finally:
        es.close()

    res_a, res_b, res_c, res_d, res_e, res_f, res_g = responses[:7]

    # ── 번호별 조립 ─────────────────────────────────────────────
    tendency, market_tendency    = buildTendency(res_a)
    top_keyword                  = buildTopKeyword(res_b)
    pos_keyword, neg_keyword     = buildPosNegKeyword(res_d, res_e, tendency["total"])
    hot_issues                   = buildHotIssues(res_b, res_c)
    spike_analysis, sector_tendency = buildSpikeAndSector(res_f, res_g)
    eco_indicators               = getEcoIndicators()
    eco_schedule                 = getEcoSchedule()

    logger.info("대시보드 조회 성공", extra={"lang": lang, "date": today})

    return ok("대시보드 조회 성공", {
        "tendency"       : tendency,
        "top_keyword"    : top_keyword,
        "pos_keyword"    : pos_keyword,
        "neg_keyword"    : neg_keyword,
        "hot_issues"     : hot_issues,
        "spike_analysis" : spike_analysis,
        "market_tendency": market_tendency,
        "sector_tendency": sector_tendency,
        "eco_indicators" : eco_indicators,
        "eco_schedule"   : eco_schedule,
    })
