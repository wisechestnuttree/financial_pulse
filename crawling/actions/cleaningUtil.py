import re


class NewsCleaner:
    """미국 뉴스(영어) 전용 클리너 - 한글 광고 및 정크 완전 차단 (강화판)"""

    @staticmethod
    def clean(text):
        if not text: return ""

        # 1. HTML 태그 및 URL 제거 (기존 유지)
        text = re.sub(r'<[^>]*>', '', text)
        text = re.sub(r'https?://\S+|www\.\S+', '', text)

        # 2. [필살] 한글 광고 제거 (기존 유지)
        text = re.sub(r'[ㄱ-ㅎ|ㅏ-ㅣ|가-힣]+', '', text)

        # 3. 영문 뉴스 하단/중간 정크 패턴 (추가 및 보강)
        en_junk_patterns = [
            # --- [추가] 기자 정보 및 날짜 바이라인 ---
            r'By\s+[a-zA-Z\s]+\s+[A-Z][a-z]+\s+\d+,\s+\d{4}.*',  # By Name May 8, 2026...
            r'\d+\s+min\s+read',  # 2 min read
            r'(AhmadArdity|Pixabay|Unsplash|Getty|Pexels)',  # 이미지 출처 파편
            r'What to know',  # UI 문구
            r'Make preferred on.*',  # UI 문구

            # --- [기존 패턴 유지] ---
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
            r'(Reporting|Writing|Editing|Additional reporting) by [^.\n]*',
            r'Sign up for (our|the) .*? newsletter.*',
            r'Subscribe to .*? for (more|daily) updates.*',
            r'Follow us on (Twitter|Facebook|LinkedIn|Instagram).*',
            r'©\s?\d{4}.*?All rights reserved\.?',
            r'Copyright\s?\d{4}.*?',
            r'Photo (by|credit):? [^.\n]*',
            r'Image (by|credit):? [^.\n]*',
            r'ADVERTISEMENT',
            r'Check out our latest.*?videos.*',
            r'Read (more|also):.*'
        ]

        for pattern in en_junk_patterns:
            # re.IGNORECASE를 추가하여 대소문자 관계없이 매칭
            text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)

        # 4. 특수문자 정리 (기존 유지)
        text = re.sub(r'[^a-zA-Z0-9\s.?!,\'\"-]', ' ', text)

        # 5. 공백 및 가독성 정리 (기존 유지)
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r'([.?!])\s+', r'\1\n\n', text)

        return text

    @staticmethod
    def isValid(text, title=""):
        # 서비스용 품질 검사 (기존 유지)
        stop_words = ["transcript", "earnings call", "live blog", "full text"]
        combined = (title + " " + (text if text else "")).lower()
        if any(word in combined for word in stop_words): return False

        if text:
            # 본문 길이 250자 미만은 제외 (기존 유지)
            if len(text.strip()) < 250: return False

            # [검증] 영어 알파벳 비중 검사 (기존 유지)
            alpha_count = len(re.findall(r'[a-zA-Z]', text))
            if alpha_count / len(text) < 0.7: return False
        return True


class KoNewsCleaner:
    """한국 뉴스 전용 클리너 (광고 및 기자정보 강력 제거)"""

    @staticmethod
    def clean(text):
        if not text: return ""

        # 1. HTML 태그 및 URL 제거
        text = re.sub(r'<[^>]*>', '', text)
        text = re.sub(r'https?://\S+|www\.\S+', '', text)

        # 2. 한국 뉴스 특유의 정크 패턴 (광고, 저작권, 기자 메일 등)
        ko_junk_patterns = [
            # 유튜브 및 외부 채널 유도 (안경찬 CP 등 직함 포함 패턴)
            r'.*자세한 내용과 영상은 유튜브 채널.*확인할 수 있습니다\.?',
            r'최신 영상에서 확인할 수 있습니다\.?',
            r'유튜브 채널\s?‘.*?’',

            # 자극적 홍보 문구
            r'주식 초고수는 지금.*',
            r'실시간 인기 주식.*',

            # 사진 및 이미지 출처 (괄호 포함)
            r'\(사진\s?=\s?.*?\)',
            r'\[사진\s?=\s?.*?\]',
            r'/사진\s?=\s?.*?\n',

            # 이메일 및 기자 정보
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
            r'\[.*?=.*?기자\]', r'\(.*?=.*?기자\)', r'기자\s?=\s?.*?\n',

            # 저작권 및 무단 전재
            r'저작권자\s?ⓒ.*', r'무단\s?전재\s?및\s?재배포\s?금지',
            r'Copyrights.*All rights reserved.*',
            r'재배포\s?금지.*',

            # 기타 파편
            r'▲.*?\n', r'▼.*?\n', r'▶.*?\n'
        ]

        for pattern in ko_junk_patterns:
            # MULTILINE 플래그를 써서 줄바꿈 뒤에 오는 문구도 잘 잡히게 함
            text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)

        # 3. 특수문자 정제
        text = re.sub(r'[^a-zA-Z0-9ㄱ-ㅣ가-힣\s.?!,\'\"-]', ' ', text)

        # 4. 공백 및 줄바꿈 정리
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r'([.?!])\s+', r'\1\n\n', text)

        return text

    @staticmethod
    def isValid(text, title=""):
        # 한국어 전용 거름망 (생중계, 포토뉴스 등 제외)
        stop_words = ["생중계", "포토", "영상", "부고", "인사", "오늘의 운세", "녹취록"]
        combined = (title + " " + (text if text else "")).lower()
        if any(word in combined for word in stop_words): return False

        if text:
            # 한글 기사는 내용 압축도가 높으므로 150자 이상이면 통과
            if len(text.strip()) < 150: return False
            if len(text) > 15000: return False
        return True