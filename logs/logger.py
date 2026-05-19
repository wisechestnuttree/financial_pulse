import uuid
import logging
from datetime import datetime, timezone, timedelta
from elasticsearch.helpers import bulk

KST = timezone(timedelta(hours=9))

# ================================================================
# ES Handler - logging 모듈과 ES를 연결하는 커스텀 핸들러
# logging.Handler를 상속받아 emit() 메서드에서 ES 저장 처리
class ESHandler(logging.Handler):
    """
    Python logging 모듈과 Elasticsearch를 연결하는 커스텀 핸들러
    - subject: 로그 주제 (crawl/ml/system/user)
    """
    def __init__(self, subject: str):
        super().__init__()
        self.subject = subject

    def emit(self, record: logging.LogRecord):
        """ 로그 발생 시 자동 호출
        - record       : logging 모듈이 넘겨주는 로그 정보
        - record.msg   : 로그 메시지
        - record.extra : 추가 데이터 (배치ID, URL 등)
        """
        try:
            from dataStorage.elasticSearch.es import getEs, ALL_LOG_IDX

            es = getEs()
            log_id = str(uuid.uuid4())
            timestamp = datetime.now(KST).isoformat()

            # extra 필드 추출
            # logging.LogRecord에 기본으로 붙는 필드 제거
            default_attrs = {
                "name", "msg", "args", "levelname", "levelno"
                , "pathname", "filename", "module", "exc_info"
                , "exc_text", "stack_info", "lineno", "funcName"
                , "created", "msecs", "relativeCreated", "thread"
                , "threadName", "processName", "process", "message","taskName"
            }
            extra = {
                k: v for k, v in record.__dict__.items()
                if k not in default_attrs
            }

            doc = {
                "log_id": log_id, "timestamp": timestamp, "subject": self.subject
                , "level": record.levelname, "message": record.getMessage(), "extra": extra
            }

            subject_index = f"logs_{self.subject}"

            # 두 인덱스에 동시 저장
            actions = [
                {"_op_type": "index", "_index": subject_index, "_id": log_id, "_source": doc}
                , {"_op_type": "index", "_index": ALL_LOG_IDX,  "_id": log_id, "_source": doc}
            ]
            bulk(es, actions)
            es.close()

        except Exception as e:
            # ES 저장 실패 시 콘솔에만 출력 (무한루프 방지)
            print(f"[ESHandler ERROR] ES 저장 실패: {e}")


# ================================================================
def getLogger(subject: str) -> logging.Logger:
    """ 서비스별 로거 생성 (subject별 로거 생성)
    - 콘솔 핸들러 + ES 핸들러 동시 등록
    - 동일 subject 로거는 재사용 (중복 핸들러 방지)

    사용법:
        logger = get_logger("crawl")
        logger.info("크롤링 시작", extra={"batch_id": "uuid-1234"})
        logger.error("크롤링 실패", extra={"url": "http://...", "reason": "timeout"})
    """
    logger = logging.getLogger(f"{subject}")

    # 이미 핸들러가 등록된 경우 재사용 (중복 방지)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    # [1] 콘솔 핸들러 - 개발 중 확인용
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        fmt   = "[%(levelname)s]     [%(name)s]: [%(message)s] %(asctime)s",
        datefmt= "%Y-%m-%d %H:%M:%S"
    ))

    # [2] ES 핸들러 - logViewer 조회용
    es_handler = ESHandler(subject=subject)
    es_handler.setLevel(logging.INFO)

    logger.addHandler(console_handler)
    logger.addHandler(es_handler)

    return logger