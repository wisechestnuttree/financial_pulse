import hashlib
import atexit
from contextlib import contextmanager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.chromium.options import ChromiumOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from logs.logger import getLogger

logger = getLogger("system")

# 클리닝 유틸 임포트
from .cleaningUtils import NewsCleaner

# [성능 최적화] 서비스 객체 전역 선언
CHROME_SERVICE = Service(ChromeDriverManager().install())

# 생성된 드라이버들을 추적하기 위한 리스트 (비상용)
_active_drivers = []


def cleanupAllDrivers():
    if not _active_drivers:
        return

    logger.info(f"[정리] 남아있는 드라이버 {len(_active_drivers)}개를 닫습니다.")
    while _active_drivers:
        driver = _active_drivers.pop()
        try:
            driver.service.process.kill()  # 단순 quit()보다 더 강력한 프로세스 킬
            driver.quit()
        except:
            pass


# 파이썬 프로세스 종료 시 자동 실행 등록 (비정상 종료 대비)
atexit.register(cleanupAllDrivers)


def getDriver(timeout=10):
    """드라이버 생성 및 추적 리스트 등록"""
    options = ChromiumOptions()
    options.page_load_strategy = 'eager'
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_experimental_option("prefs", {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.fonts": 2
    })
    options.add_argument(
        'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    driver = webdriver.Chrome(service=CHROME_SERVICE, options=options)

    # 봇 감지 우회
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
    })

    driver.set_page_load_timeout(timeout)

    # 추적 리스트에 추가
    _active_drivers.append(driver)
    return driver


@contextmanager
def managedDriver():
    """
    with문(Context Manager)을 위한 래퍼 함수.
    정상 종료 및 예외 발생 시 자동으로 quit() 호출 보장.
    """
    driver = getDriver()
    try:
        yield driver
    finally:
        if driver in _active_drivers:
            _active_drivers.remove(driver)
        try:
            driver.quit()
        except:
            pass


def extractContentWithJs(driver, title=""):
    """
    본문 영역 우선 탐색 + JS 범용 추출 로직
    """
    # [1단계] 제목 기반 사전 필터링

    if not NewsCleaner.isValid("", title):
        return ""

    try:
        # 대기 시간을 3초로 단축 (eager 모드 효율 극대화)
        WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.TAG_NAME, "p")))
    except:
        pass

    # [2단계] 보강된 본문 추출 JS (Container 기반)
    js_script = """
    var res = [];
    var seen = new Set();

    // 뉴스 사이트별 주요 본문 컨테이너 후보
    var selectors = [
        'article', 'main', '.article-body', '.story-content', 
        '.entry-content', '[itemprop="articleBody"]', '#main-content', '.content'
    ];

    let bestContainer = null;
    let maxLen = 0;

    document.querySelectorAll(selectors.join(',')).forEach(el => {
        let length = el.innerText.length;
        if(length > maxLen) {
            maxLen = length;
            bestContainer = el;
        }
    });

    // 컨테이너를 찾으면 그 안에서만, 못 찾으면 전체에서 추출
    let target = (bestContainer && maxLen > 200) ? bestContainer : document.body;

    // p태그 및 본문 블록 요소들 수집
    let elements = target.querySelectorAll('p, div[class*="article-text"], div[class*="story-block"], section');

    elements.forEach(el => {
        var txt = el.innerText.replace(/\\s+/g, ' ').trim();
        // 중복 및 너무 짧은 텍스트(광고/버튼 등) 필터링
        if(txt.length > 55 && !seen.has(txt)) {
            res.push(txt);
            seen.add(txt);
        }
    });

    return res.join('\\n\\n');
    """

    try:
        raw_content = driver.execute_script(js_script)
    except:
        return ""

    # [3단계] 정밀 클리닝
    cleaned_content = NewsCleaner.clean(raw_content)

    # [4단계] 최종 품질 검수 (본문 미달 시 실패 처리)
    if not NewsCleaner.isValid(cleaned_content, title):
        return ""

    return cleaned_content


def generateHashId(url, title):
    """중복 방지용 고유 ID 생성"""
    clean_url = url.split('?')[0].split('#')[0].strip()
    raw_str = f"{clean_url}{title.strip()}"
    return hashlib.md5(raw_str.encode()).hexdigest()