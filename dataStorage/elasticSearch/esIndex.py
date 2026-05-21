from dataStorage.elasticSearch.es import getEs, LOG_INDICES, ALL_LOG_IDX, NEWS_EN_IDX, NEWS_KO_IDX, ANALYZE_DATA_IDX

# ================================================================
# 로그 인덱스 매핑 (logs_crawl, logs_ml, logs_system, logs_user, logs_all)
LOG_MAPPING = {
    "settings": {
        "number_of_shards": 3,      # 데이터를 3개 샤드로 분산 저장

        "number_of_replicas": 1     # 복제본 1개
    },
    "mappings": {
        "properties": {
            "log_id": {"type": "keyword"}       # UUID - 검색용
            , "timestamp": {"type": "date"}     # 로그 발생 시각 - 범위 검색, 정렬용
            , "subject": {"type": "keyword"}    # 주제 (crawl/ml/system/user) - 검색용
            , "level": {"type": "keyword"}      # 로그 레벨 (INFO/WARNING/ERROR) - 필터용
            , "message": {"type": "text"}       # 로그 메시지 - 상세 검색용
            , "extra": {"type": "object", "dynamic": True}  # 자유 필드 - 단계별로 다른 데이터 저장
            # extra 예시:
            # crawl: {"batch_id": "...", "crawl_cnt": 500, "url": "..."}
            # ml:    {"doc_id": "...", "tend_score": 0.95}
            # system:{"batch_id": "...", "diff": 2}
        }
    }
}

# ================================================================
# 한국 기사 수집 인덱스 매핑 (news_ko)
# - nori 형태소 분석기 적용 (decompound_mode: mixed)
# - doc_id_setting 파이프라인으로 doc_id 자동 생성
# - content는 검색 제외 (index: false) -> 용량 절약
NEWS_KO_MAPPING = {
    "settings": {
        "index.default_pipeline": "doc_id_setting",  # doc_id 자동 생성 파이프라인
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "tokenizer": {
                "nori_mixed": {
                    "type": "nori_tokenizer",
                    "decompound_mode": "mixed"  # 복합어를 원형 + 분해형 동시 저장
                }
            },
            "analyzer": {
                "korean_analyzer": {
                    "type": "custom",
                    "tokenizer": "nori_mixed"
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "doc_id": {"type": "keyword"},  # 기사 고유 ID
            "url": {"type": "keyword"},     # 기사 원문 링크
            "title": {
                "type": "text",
                "analyzer": "korean_analyzer"   # 한국어 형태소 분석
            },
            "content": {
                "type": "text",
                "index": False              # 본문은 검색 제외 (저장만)
            },
            "lang": {"type": "keyword"},
            "published_at": {
                "type": "date",
                "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time||epoch_millis"
            },
            "collected_at": {
                "type": "date",
                "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time||epoch_millis"
            }
        }
    }
}

# ================================================================
# 미국 기사 수집 인덱스 매핑 (news_en)
# - standard 분석기 적용 (영어 기본 분석기)
# - doc_id_setting 파이프라인으로 doc_id 자동 생성
NEWS_EN_MAPPING = {
    "settings": {
        "index.default_pipeline": "doc_id_setting",
        "number_of_shards": 1,
        "number_of_replicas": 0
    },
    "mappings": {
        "properties": {
            "doc_id": {"type": "keyword"},
            "url": {"type": "keyword"},
            "title": {
                "type": "text",
                "analyzer": "standard"  # 영어 기본 분석기
            },
            "content": {
                "type": "text",
                "index": False
            },
            "lang": {"type": "keyword"},
            "published_at": {
                "type": "date",
                "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time||epoch_millis"
            },
            "collected_at": {
                "type": "date",
                "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time||epoch_millis"
            }
        }
    }
}

# ================================================================
# ML 분석 결과 인덱스 매핑 (analyze)
# - title, processed_content: 한국어/영어 동시 분석 (멀티필드)
# - ner: company, person, region 구조화
# - model_ver: 모델별 버전 계층화 관리
ANALYZE_MAPPING = {
    "settings": {
        "index.default_pipeline": "doc_id_setting",
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "tokenizer": {
                "nori_mixed": {
                    "type": "nori_tokenizer",
                    "decompound_mode": "mixed"
                }
            },
            "analyzer": {
                "korean_analyzer": {
                    "type": "custom",
                    "tokenizer": "nori_mixed"
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "doc_id": {"type": "keyword"},  # news_ko/en 과 연결되는 기사 고유 ID
            "lang": {"type": "keyword"},

            # 멀티필드: 영어(standard) + 한국어(korean_analyzer) 동시 분석
            # title.ko, processed_content.ko 로 한국어 검색 가능
            "title": {
                "type": "text",
                "analyzer": "standard",
                "fields": {
                    "ko": {"type": "text", "analyzer": "korean_analyzer"}
                }
            },
            "processed_content": {
                "type": "text",
                "analyzer": "standard",
                "fields": {
                    "ko": {"type": "text", "analyzer": "korean_analyzer"}
                }
            },

            "sector": {"type": "keyword"},      # 기사 주제 대분류 (7분류)
            "keywords": {"type": "keyword"},    # 기사 키워드 목록
            "tendency": {"type": "keyword"},    # 성향 (긍정/부정/중립)
            "tend_score": {"type": "float"},    # 성향 점수

            # 모델 버전 계층화 관리
            # 각 분석 단계별 사용 모델 버전을 독립적으로 관리
            "model_ver": {
                "properties": {
                    "preprocess": {"type": "keyword"},  # 전처리/NER 모델 (예: spacy_v3.7)
                    "keywords": {"type": "keyword"},    # 키워드 추출 모델 (예: KeyBERT_v1)
                    "sentiment": {"type": "keyword"},   # 감성 분석 모델 (예: FinBERT_v2)
                    "sector": {"type": "keyword"}       # 섹터 분류 모델 (예: ZeroShot_v1)
                }
            },

            # NER 결과 구조화
            # company, person, region 으로 네이밍 통일
            "ner": {
                "properties": {
                    "company": {"type": "keyword"}, # 기업/기관명
                    "person": {"type": "keyword"},  # 인물명
                    "region": {"type": "keyword"}   # 지역/국가명
                }
            }
        }
    }
}

def createAllIndices():
    """
    서버 시작 시 필요한 모든 인덱스를 한 번에 생성
    - 이미 존재하는 인덱스는 SKIP (덮어쓰지 않음)
    - 생성: 로그 5개 + news_ko + news_en + analyze (+ search )= 총 8(9)개
    """
    es = getEs()

    # 로그 인덱스 5개 생성

    for index in LOG_INDICES + [ALL_LOG_IDX]:
        if not es.indices.exists(index=index):
            es.indices.create(index=index, body=LOG_MAPPING)
            print(f"[CREATE] {index}")
        else:
            print(f"[SKIP]   {index}")

    # 뉴스/분석/검색 인덱스 3(4)개 생성
    for index, mapping in [
        (NEWS_KO_IDX, NEWS_KO_MAPPING)          # 한국 기사 원문
        , (NEWS_EN_IDX, NEWS_EN_MAPPING)        # 미국 기사 원문
        , (ANALYZE_DATA_IDX, ANALYZE_MAPPING)   # ML 분석 결과
        # , (SEARCH_IDX,  SEARCH_MAPPING)       # 검색용
    ]:
        if not es.indices.exists(index=index):
            es.indices.create(index=index, body=mapping)
            print(f"[CREATE] {index}")
        else:
            print(f"[SKIP]   {index}")

    es.close()

'''
# ================================================================
# 검색 인덱스 매핑 (search)
# - analyze 완료 후 사용자 검색용으로 최적화
# - 검색/필터에 필요한 필드만 선별하여 저장
SEARCH_MAPPING = {
    "settings": {
        "number_of_shards":   1,
        "number_of_replicas": 0
    },
    "mappings": {
        "properties": {
            "doc_id":       {"type": "keyword"},    # 기사 고유 ID
            "lang":         {"type": "keyword"},    # 언어 (ko/en)
            "sector":       {"type": "keyword"},    # 기사 주제 대분류
            "url":          {"type": "keyword"},    # 기사 주소
            "title":        {"type": "text"},       # 기사 제목 - 전문 검색용
            "published_at": {
                "type":   "date",
                "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time||epoch_millis"
            },
            "company":    {"type": "keyword"},  # ner.company → 검색 필터용
            "person":     {"type": "keyword"},  # ner.person  → 검색 필터용
            "region":     {"type": "keyword"},  # ner.region  → 검색 필터용
            "keywords":   {"type": "keyword"},  # 기사 키워드  → 검색 필터용
            "tendency":   {"type": "keyword"},  # 성향
            "tend_score": {"type": "float"}     # 성향 점수
        }
    }
}

# ES 인덱스 생성시 doc_id 생성을 위한 엘라스틱 서치 내 파이프 라인 생성 방법

# 1. ES 내에서 아래 명령문 입력시 'doc_id_setting' 라는 파이프라인 생성

    PUT _ingest/pipeline/doc_id_setting
    {
      "description": "최초 생성 시의 _id만 doc_id에 저장하고 이후 수정 불가",
      "processors": [
        {
          "set": {
            "field": "doc_id",
            "copy_from": "_id",
            "if": "ctx.doc_id == null",
            "description": "doc_id가 비어있을 때만 _id값을 복사함"
          }
        }
      ]
    }

# 실제 인덱스 생성시 파이프라인을 세팅값으로 설정 예시

PUT /your_index_name
{
  "settings": {
    "index.default_pipeline": "doc_id_setting"  // 이 인덱스는 무조건 이 파이프라인을 거침
  },
  "mappings": {
    "properties": {
      "doc_id": { "type": "keyword" },
      "your_data": { "type": "text" }
    }
  }
}

# 이런 식으로 작성시 doc_id가 없으면 자동으로 doc_id(es에서 생성된 난수 id 기반) 생성됨
'''