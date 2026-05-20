import json
import os
import time
from google import genai

class NormalizationManager:
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)
        self.model_id = "gemini-2.5-flash"  # 최신 안정화 모델 사용

        self.file_map = {
            'person': 'norm_person.json',
            'company': 'norm_companies.json',
            'keyword': 'norm_keywords.json',
            'region': 'norm_region.json'
        }

        self.category_dicts = {cat: {} for cat in self.file_map}
        self.load_all()

    def load_all(self):
        for category, filename in self.file_map.items():
            if os.path.exists(filename):
                try:
                    with open(filename, 'r', encoding='utf-8') as f:
                        self.category_dicts[category] = json.load(f)
                except:
                    pass

    def fetch_new_matches(self, category, topic_description):
        current_dict = self.category_dicts.get(category, {})
        print(f"\n🎯 [{category.upper()}] 정규화 사전 구축 중... (현재: {len(current_dict)}개)")

        existing_keys = list(current_dict.keys())

        # 1. 카테고리별 상세 지침 (최신화된 로직 적용)
        specific_instruction = ""
        if category == 'company':
            specific_instruction = """
            - **조직 및 주체 통합**: 민간 기업뿐만 아니라 'G7', 'G20', 'UN' 등 국제 협의체와 '연준(Fed)', '재무부' 같은 정책 기관을 모두 포함하라.
            - **영문 약어 브릿징**: KeyBERT가 추출할 법한 'G7', 'Fed', 'ECB', 'IMF', 'NVDA' 등을 한국어 표준 명칭으로 매핑하라.
            - **중의성 제거**: 'Bank', 'Apple' 처럼 일반 명사와 겹칠 위험이 있는 단어는 고유 명칭이 확실할 때만 수집하라.
            - **매핑 예시**: {"G7": "주요 7개국", "Fed": "연준", "NVIDIA": "엔비디아", "IMF": "국제통화기금"}
            """
        elif category == 'keyword':
            specific_instruction = """
            - **순수 경제 개념/테마**: '인플레이션', '양적완화', '엔캐리 트레이드' 등 현상과 이론 중심의 용어만 추출하라.
            - **상태어 배제**: '상승', '하락', '폭등', '전망' 등 방향성을 나타내는 일반 동사/명사는 키로 쓰지 마라.
            - **매핑 예시**: {"CPI": "소비자물가수준", "Bull Market": "강세장", "Short Selling": "공매도", "Oil Prices": "유가"}
            """
        elif category == 'person':
            specific_instruction = """
            - **단축어/성(Last Name) 단독 사용 금지**: "핑크", "fink", "브라운", "brown" 처럼 색상/일반명사와 겹치는 단축 키는 **절대** 생성하지 마라.
            - **풀네임 원칙**: "래리 핑크", "제롬 파월", "Donald Trump" 처럼 오해의 소지가 없는 확실한 조합만 매핑하라.
            - **매핑 예시**: {"Larry Fink": "래리 핑크", "Powell": "제롬 파월", "Trump": "도널드 트럼프"}
            """
        elif category == 'region':
            specific_instruction = """
            - **순수 지정학적 위치**: 국가명, 대륙명, 주요 도시명 위주로 구성하라. (협의체나 기관은 'company'로 이동)
            - **약어 통합**: '美', '中', 'USA', 'UK' 등을 한국어 표준 국명으로 통합하라.
            - **매핑 예시**: {"USA": "미국", "UK": "영국", "China": "중국", "NYC": "뉴욕"}
            """

        # 2. 통합 프롬프트 생성 (수집 원칙 강화)
        prompt = f"""
        너는 금융 데이터 정규화 및 엔티티 브릿지 전문가야. 
        KeyBERT 모델이 추출한 파편화된 단어들을 **'하나의 한국어 대표 명칭'**으로 통합하는 사전을 만든다.

        주제: {topic_description}

        ### [수집 원칙: 데이터 순도 100% 보장] ###
        1. **중의성 원천 봉쇄**: 일반 명사(색상, 감정, 상태, 동사)와 겹칠 가능성이 1%라도 있는 키(Key)는 **무조건 제외**하라.
           - **절대 금지**: "핑크", "pink", "fink", "brown", "사과", "상승", "폭락", "오늘", "사람"
        2. **N:1 한국어 수렴**: 영문 풀네임, 티커, 국문 약어를 '한국어 표준어 풀네임' 하나로 매핑하라.
        3. **영문 브릿지 필수**: 영문 뉴스 처리용 KeyBERT가 뽑을 법한 영문 엔티티를 한국어 표준명으로 연결하라.
        4. **최소 길이 및 고유성**: 키(Key)는 최소 2글자 이상이어야 하며, 단독으로 사용 시 금융 문맥의 고유 명사임이 확실해야 한다.

        ### [카테고리별 가이드라인] ###
        {specific_instruction}

        ### [출력 필수 지시사항] ###
        - **경고**: 성(Last Name)이나 색상명 단독 키(예: "핑크")를 생성하여 데이터를 오염시키지 마라. 애매하면 생성하지 않는 것이 원칙이다.
        - 중복 제외: 아래 리스트에 이미 있는 키는 생성하지 마라.
        {existing_keys[:800]}
        - 설명 없이 순수한 JSON ({{"변형표기": "한국어대표어"}}) 형식으로 최소 100개 이상 출력하라.
        """

        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt
            )
            raw_text = response.text.strip()

            start, end = raw_text.find('{'), raw_text.rfind('}')
            if start != -1 and end != -1:
                ai_data = json.loads(raw_text[start:end + 1])

                # 자기 자신과 같은 값(매핑 불필요) 제외 및 소문화 처리
                new_only = {
                    k.strip(): v for k, v in ai_data.items()
                    if k.strip().lower() not in [ek.lower() for ek in existing_keys] and k.strip() != v.strip()
                }

                if new_only:
                    self.save_to_file(category, new_only)
                    print(f">> 완료: {len(new_only)}개의 고유 명칭 추가.")
                else:
                    print(">> 새로운 데이터가 없습니다.")
            else:
                print(">> JSON 형식을 찾을 수 없습니다.")

        except Exception as e:
            print(f">> 에러 발생: {e}")
            time.sleep(5)

    def save_to_file(self, category, new_data):
        filename = self.file_map[category]
        data = self.category_dicts[category]
        data.update(new_data)

        # 가독성을 위해 대표어(Value) 기준으로 정렬
        sorted_data = dict(sorted(data.items(), key=lambda item: (item[1], item[0])))

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(sorted_data, f, ensure_ascii=False, indent=2)

        self.category_dicts[category] = sorted_data


if __name__ == "__main__":
    API_KEY = ""
    manager = NormalizationManager(API_KEY)

    # 태스크 정의 (G7 등 조직 중심의 가이드 반영)
    task_list = [
        ('person', '글로벌 정치인, 중앙은행 총재, 주요 기업 CEO 성명 및 확실한 한국어 풀네임'),
        ('company', '글로벌 상장사, 국제 기구(G7, IMF 등), 정책 기관(Fed) 명칭의 한국어 통일'),
        ('region', '국가명, 주요 경제 허브 도시, 지정학적 영토 명칭의 한국어 통일'),
        ('keyword', '금융 지표, 정책 용어, 경제 테마 및 영문 경제 약어의 한국어 표준화')
    ]

    for i in range(3):
        print(f"\n--- {i + 1}회차 정규화 사전 수집 시작 ---")
        for cat, topic in task_list:
            manager.fetch_new_matches(cat, topic)
            time.sleep(3)

    print(f"\n✅ 정규화 사전 업데이트가 완료되었습니다.")