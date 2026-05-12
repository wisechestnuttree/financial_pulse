from elasticsearch import Elasticsearch

ES_ADDRESS = 'http://100.88.143.23:9200'    # ES 서버 주소
# http://100.88.143.23:5601/app/home#/

LOG_INDICES = [ # 각 주제(crawl, ml, system, user)별로 로그를 분리
    "logs_crawl",    # 크롤링 관련 로그
    "logs_ml",       # ML 처리 관련 로그
    "logs_system",   # 시스템 관련 로그
    "logs_user"      # 사용자 관련 로그
]
ALL_LOG_IDX = "logs_all"    # 전체 로그 통합 index
NEWS_KO_IDX = "news_ko"     # 한국 기사 저장 index
NEWS_EN_IDX = "news_en"     # 미국 기사 저장 index
ANALYZE_DATA_IDX = "analyze" # ML 처리 결과 저장 index
# SEARCH_IDX = "search"     # 검색에 사용할 index (필요하면 생성 , 없어도 상관 없어 보여서 "일단 주석")

def getEs():
    '''
    ES 객체 반환 ( 사용 이후 close() 필요 )
    :return: ES 객체
    '''
    return Elasticsearch(ES_ADDRESS)