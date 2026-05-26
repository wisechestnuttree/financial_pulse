"""
crawlSchedular.py
통합 크롤링 스케줄러

[ 스케줄 ]
한국어 뉴스 : 07:30 / 11:30 / 18:30 / 23:59
영문 뉴스   : 07:30 / 21:00
경제지표    : 23:30 (1회)

[ 저장 대상 ]
한국어 : ES news_ko 인덱스
영문   : ES news_en 인덱스
경제지표: DB economicIndicator 테이블
"""
import signal
import sys
import threading
import time
from functools import wraps
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from crawling.collectKoNews import runStandalone
from crawling.collectEnNews import runCollector
from crawling.collectEconomic import dailyJob
from crawling.utils.reCrawlUtils import runRetryCrawl
from machineLearning.run import run
from logs.logger import getLogger

KO_SCHEDULES = [
    ("07:30", "새벽 마감"),
    ("11:30", "오전 흐름"),
    ("18:30", "초판"),
    ("23:59", "하루 마감"),
]

EN_SCHEDULES = [
    ("01:10", "미국 장 중간 흐름"),
    ("06:10", "미국 장 마감·한국 장 개장 직전"),
    ("21:00", "미국 장 개장 직전"),
]

ECONOMIC_SCHEDULE = ("23:30", "경제지표 수집")

RECOLLECTION_NEWS = ("03:00", "누락 기사 재수집 by 관리자")

logger = getLogger("system")


# =========================
# Locks
# =========================
ko_lock = threading.Lock()
en_lock = threading.Lock()
eco_lock = threading.Lock()
re_lock = threading.Lock()


def guarded(lock, job_name):
    def decorator(func):
        @wraps(func)
        def wrapper():
            if lock.locked():
                logger.warning(f"{job_name} already running. skipped.")
                return

            with lock:
                start = time.time()
                logger.info(f"{job_name} started")

                try:
                    func()
                    elapsed = time.time() - start
                    logger.info(f"{job_name} completed ({elapsed:.1f}s)")
                except Exception as e:
                    logger.exception(f"{job_name} failed: {e}")

        return wrapper
    return decorator


# =========================
# Wrapped Jobs
# =========================
@guarded(ko_lock, "KO Collector")
def runKo():
    runStandalone()
    run("ko")


@guarded(en_lock, "EN Collector")
def runEn():
    runCollector()
    run("en")


@guarded(eco_lock, "Economic Collector")
def runEco():
    dailyJob()

@guarded(re_lock, "RECOLLECTION Collector")
def runRe():
    runRetryCrawl()

# =========================
# Scheduler
# =========================
scheduler = BackgroundScheduler(
    timezone=ZoneInfo("Asia/Seoul")
)

def addJobs(test_mode=False):
    job_defaults = {
        'trigger': 'cron',
        'max_instances': 1,
        'coalesce': True,
        'misfire_grace_time': 600
    }

    # 1. 정기 스케줄 등록
    # KO 뉴스
    for t, label in [("07:30", "새벽"), ("11:30", "오전"), ("18:30", "초판"), ("23:59", "마감")]:
        h, m = map(int, t.split(":"))
        scheduler.add_job(runKo, hour=h, minute=m, id=f"ko_{label}", **job_defaults)

    # EN 뉴스
    for t, label in [("01:10", "중간 흐름"), ("06:10", "장마감"), ("21:00", "개장전")]:
        h, m = map(int, t.split(":"))
        scheduler.add_job(runEn, hour=h, minute=m, id=f"en_{label}", **job_defaults)

    # 경제지표
    scheduler.add_job(runEco, hour=23, minute=30, id="eco_daily", **job_defaults)

    # 재크롤링
    scheduler.add_job(runRe, hour=3, minute=00, id="reColl", **job_defaults)

    # 2. 실시간 테스팅 모드 (실행 시 즉시 모든 작업 테스트)
    if test_mode:
        logger.info("testing: 3초 후 경제지표 → 10분 후 한국 → 30분 후 미국")
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        scheduler.add_job(runEco, trigger='date', run_date=now + timedelta(seconds=3), id='test_eco')
        scheduler.add_job(runKo, trigger='date', run_date=now + timedelta(minutes=10), id='test_ko')
        scheduler.add_job(runEn, trigger='date', run_date=now + timedelta(minutes=40), id='test_en')



def listener(event):
    if event.exception:
        logger.error(f"Job crashed: {event.job_id}")
    else:
        logger.info(f"Job finished: {event.job_id}")


scheduler.add_listener(
    listener,
    EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
)


def shutdownHandler(signum, frame):
    logger.info("Scheduler shutting down...")
    scheduler.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdownHandler)
    signal.signal(signal.SIGTERM, shutdownHandler)
    addJobs(test_mode=True)

    logger.info("Financial Pulse Scheduler Started")
    scheduler.start()