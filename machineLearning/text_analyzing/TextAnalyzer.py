import gc
import re
import os
import json
import torch
from kiwipiepy import Kiwi
from sklearn.feature_extraction.text import CountVectorizer
from elasticsearch import Elasticsearch, helpers
from keybert import KeyBERT
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
from flashtext import KeywordProcessor
from keybert.backend import SentenceTransformerBackend
from sklearn.metrics.pairwise import cosine_similarity
from transformers import pipeline

class TextAnalyzer:
    def __init__(self):
        self.dict_path = os.path.join(os.path.dirname(__file__), 'dictionary')

        # 1. 기존 ko/en 사전 로드 (self.data_store 초기화)
        self.data_store = {}
        files = {'ko': 'ko_dictionary.json', 'en': 'en_dictionary.json'}

        for lang, filename in files.items():
            file_path = os.path.join(self.dict_path, filename)
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.data_store[lang] = json.load(f)
            else:
                # [수정] noise_phrases 키 추가
                self.data_store[lang] = {'noise': [], 'noise_phrases': [], 'whitelist': []}

            # [A] 단어 단위 노이즈 (SpaCy 분석 후 단어 필터링용 - 기존 로직 호환)
            noise_words = self.data_store[lang].get('noise', [])

            # [B] 문구 단위 노이즈 (원문 정규식 폭격용)
            noise_phrases = self.data_store[lang].get('noise_phrases', [])
            # 긴 문구부터 매칭되도록 길이순 정렬 (충돌 방지)
            sorted_phrases = sorted(noise_phrases, key=len, reverse=True)
            pattern_str = '|'.join([re.escape(p) for p in sorted_phrases])

            # 언어별 할당
            if lang == 'ko':
                self.finance_noise_ko = set(noise_words)
                self.compiled_phrases_ko = re.compile(f'({pattern_str})', re.IGNORECASE) if pattern_str else None
            else:
                self.finance_noise_en = set(noise_words)
                self.compiled_phrases_en = re.compile(f'({pattern_str})', re.IGNORECASE) if pattern_str else None

        # 2. company, person, regions.json 로드
        self.entity_data = {}
        for fname in ['company.json', 'person.json', 'regions.json']:
            cat = fname.replace('.json', '')
            path = os.path.join(self.dict_path, fname)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    self.entity_data[cat] = json.load(f)
            else:
                self.entity_data[cat] = {}

        self.org_blacklist = {
            "white house", "united nations", "european union", "european commission",
            "government", "congress", "senate", "house of representatives",
            "reuters", "bloomberg", "ap", "bbc", "cnn", "nbc", "fox", "cnbc", "yahoo finance", "the new york times"
        }

        # 3. 데이터 구조 및 FlashText 프로세서 초기화
        self.keyword_category_map = {}
        self.person_normalization_dict = {}
        self.keyword_processor = KeywordProcessor()
        self.all_entity_aliases = set()

        self.kp_reg_ko = KeywordProcessor(case_sensitive=False)
        self.kp_comp_ko = KeywordProcessor(case_sensitive=False)
        self.kp_pers_ko = KeywordProcessor(case_sensitive=False)
        self.kp_reg_en = KeywordProcessor(case_sensitive=False)
        self.kp_comp_en = KeywordProcessor(case_sensitive=False)
        self.kp_pers_en = KeywordProcessor(case_sensitive=False)

        # 4. 사전 데이터 매핑
        for cat, data in self.entity_data.items():
            for rep, aliases in data.items():
                if rep.startswith("candidate_"): continue

                ko_rep, en_rep = rep, rep
                is_rep_ko = bool(re.search(r'[가-힣]', rep))
                if is_rep_ko:
                    en_cands = [a for a in aliases if not re.search(r'[가-힣]', a)]
                    if en_cands: en_rep = en_cands[0].upper() if len(en_cands[0]) <= 3 else en_cands[0].title()
                else:
                    ko_cands = [a for a in aliases if re.search(r'[가-힣]', a)]
                    if ko_cands: ko_rep = ko_cands[0]

                for alias in aliases:
                    self.keyword_category_map[alias] = cat
                    if cat == 'person': self.person_normalization_dict[alias] = rep
                    self.keyword_processor.add_keyword(alias)
                    self.all_entity_aliases.add(alias.lower())

                    if cat == 'company':
                        self.kp_comp_ko.add_keyword(alias, ko_rep)
                        self.kp_comp_en.add_keyword(alias, en_rep)
                    elif cat == 'person':
                        self.kp_pers_ko.add_keyword(alias, ko_rep)
                        self.kp_pers_en.add_keyword(alias, en_rep)
                    elif cat == 'regions':
                        self.kp_reg_ko.add_keyword(alias, ko_rep)
                        self.kp_reg_en.add_keyword(alias, en_rep)

        # 5. 화이트리스트 로드
        self.finance_whitelist_ko = set(self.data_store['ko'].get('whitelist', []))
        self.finance_whitelist_en = set([w.lower() for w in self.data_store['en'].get('whitelist', [])])

        # 6. 모델 로드 및 나머지 초기화
        self.es = Elasticsearch(['http://100.88.143.23:9200'])
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.kiwi = Kiwi(model_type='largest')
        self._init_permanent_words(self.finance_whitelist_ko, self.finance_whitelist_en)
        self.st_model_ko = SentenceTransformer('snunlp/KR-FinBERT-SC', device=self.device)
        self.st_model_en = SentenceTransformer('ProsusAI/finbert', device=self.device)
        self.kw_model = KeyBERT(model=SentenceTransformerBackend(self.st_model_ko))

        # [수정] 모델 로드 로직
        self.device = 0 if torch.cuda.is_available() else -1

        # 한국어: KLUE-BERT NER (또는 파인튜닝 모델명)
        self.ner_ko = pipeline(
            "ner", model="klue/bert-base", aggregation_strategy="simple", device=self.device
        )
        # 영어: dslim/bert-base-NER
        self.ner_en = pipeline(
            "ner", model="dslim/bert-base-NER", aggregation_strategy="simple", device=self.device
        )

        # 16비트 정밀도 적용 (6GB VRAM 최적화)
        if torch.cuda.is_available():
            self.ner_ko.model.half()
            self.ner_en.model.half()

        self.VER_PREPROCESS = "spacy_kiwi_v3.0"
        self.VER_KEYWORDS = "dual_finbert_v8.0"

    def _init_permanent_words(self, ko_perm_set, en_perm_set):
        self.all_survive_ko = ko_perm_set
        self.survive_ko_no_space = {w.replace(" ", ""): w for w in ko_perm_set}
        self.all_survive_en = {w.lower() for w in en_perm_set}

        # [수정] 오직 초기화 목적의 코드만 남기고 불필요한 로직 제거
        for word in self.all_survive_ko:
            try:
                self.kiwi.add_user_word(word, "NNP", score=10)
            except:
                continue

    def kiwi_tokenizer(self, text):
        bad_suffix = re.compile(r'(보단|만큼|마저|조차|까지|부터|보다)$')
        noise_regex = re.compile(
            r'(https?://|\.com|\.tv|\.org|\.net|/privacy-policy|document\.|getelementbyid|gettime|script|δ|analytics|cookie|footer|header|window\.)',
            re.IGNORECASE)
        special_char_regex = re.compile(r'[·….,_/~%&+=?º:{}\[\]"\'\\]')

        custom_words = self.kiwi.extract_words(text, min_cnt=1, min_score=0.25)

        for word, _, _, score in custom_words:
            if noise_regex.search(word) or special_char_regex.search(word):
                continue
            if len(word) > 1 and not bad_suffix.search(word):
                if word not in self.dynamic_words:
                    try:
                        self.kiwi.add_user_word(word, 'NNP', score=score)
                        self.dynamic_words.add(word)
                    except:
                        continue

        josa_pattern = re.compile(r'(보단|보다|만큼|마저|조차|까지|부터|하고|이랑|으로|로서|로써|에서|이며|여서)$')
        tokens = self.kiwi.tokenize(text)
        result = []
        finance_suffixes = ('권', '업', '액', '율', '론', '핀', '테크', '프리', '펀딩')
        exception_ju_list = {'지주', '우주', '맥주', '입주', '수주', '발주', '선주'}

        for i, t in enumerate(tokens):
            form, tag = t.form, t.tag
            if tag == 'NNP':
                if i > 0 and tokens[i - 1].tag == 'NNP':
                    if result:
                        prev_nnp = result.pop()
                        combined = prev_nnp + form
                        if combined not in self.finance_noise_ko: result.append(combined)
                else:
                    if len(form) >= 2 and form not in self.finance_noise_ko: result.append(form)
                continue
            elif tag == 'NNG':
                if len(form) >= 3: form = josa_pattern.sub('', form)
                if form in self.finance_noise_ko or len(form) <= 1: continue
                if form in self.finance_whitelist_ko or form.endswith(finance_suffixes):
                    result.append(form)
                elif len(form) >= 3:
                    is_stock_noise = form.endswith('주') and not any(ex in form for ex in exception_ju_list)
                    if not is_stock_noise: result.append(form)
                elif form in exception_ju_list:
                    result.append(form)
        return list(dict.fromkeys(result))

    def en_tokenizer(self, text):
        # 1. 노이즈 제거 (기존 로직 유지)
        if self.compiled_phrases_en:
            text = self.compiled_phrases_en.sub(' ', text)

        noise_patterns = [
            r'\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})\b',
            r'\b((jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\.\-]*\d{1,2}(st|nd|rd|th)?,?[\s\.\-]*\d{0,4})\b',
            r'\b(\d{1,2}(st|nd|rd|th)?[\s\.\-]*of[\s\.\-]*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)\b',
            r'\b(\d{4}\s*(to|until|-)\s*\d{4})\b',
            r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            r'\b(day\s+\d+)\b',
            r'\b(q[1-4](\s+\d{4})?)\b',
            r'\b(statistics explained|cookies policy page|website addresses|new york times|wall street journal|financial times|voice of america|bloomberg news|all rights reserved)\b',
            r'(voa|bloomberg|marketwatch|nbc|fox40|nexstar|fortune)\s*(\-|news|media|corp|inc|broadcast|daily)?',
            r'\b(trump)\s+\d\.\d\b',
            r'(@\w+|twitter\s+@\w+|\w+\.(com|eu|org|net)|europa\.eu)',
            r'\b(deep|mark|current|value|et|year|date|copyright)\b'
        ]

        for pattern in noise_patterns:
            text = re.sub(pattern, ' ', text, flags=re.IGNORECASE)

        text = re.sub(r'(\n|\r|\||•)', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # 2. 결과 리스트 초기화
        result = []

        # 3. 모델 기반 엔티티 추출 (이미 _extract_ner에서 수행하지만,
        #    en_tokenizer에서도 후보를 뽑아야 한다면 pipeline을 활용)
        #    모델은 'text' 전체를 입력으로 받음.
        ner_results = self.ner_en(text)

        # BERT 결과로 뽑힌 엔티티들을 PROPN으로 간주
        for ent in ner_results:
            word = ent['word'].strip()
            # 노이즈 체크
            if word.lower() not in self.finance_noise_en and len(word) > 2:
                result.append(f"{word}::PROPN")

        # 4. 일반 단어 처리 (사전 기반 화이트리스트 매칭)
        # spaCy의 POS Tagging이 없으므로, 사전(Whitelist)에 있는 단어만 NOUN으로 처리
        words = text.split()
        for w in words:
            cleaned = re.sub(r'[^\w\s]', '', w)
            if len(cleaned) > 2:
                # 화이트리스트에 있는 명사만 선별
                if cleaned.lower() in self.finance_whitelist_en:
                    result.append(f"{cleaned}::NOUN")
                # 화이트리스트에 없어도 사전에 등록된 엔티티라면 후보로 추가
                elif cleaned.lower() in self.all_entity_aliases:
                    result.append(f"{cleaned}::PROPN")

        return list(dict.fromkeys(result))

    def _extract_ner(self, content, lang):
        # 1. FlashText 사전 기반 추출
        ner_results = {"company": [], "person": [], "region": []}

        if lang == 'ko':
            ner_results["company"] = list(dict.fromkeys(self.kp_comp_ko.extract_keywords(content)))
            ner_results["person"] = list(dict.fromkeys(self.kp_pers_ko.extract_keywords(content)))
            ner_results["region"] = list(dict.fromkeys(self.kp_reg_ko.extract_keywords(content)))
        else:
            ner_results["company"] = list(dict.fromkeys(self.kp_comp_en.extract_keywords(content)))
            ner_results["person"] = list(dict.fromkeys(self.kp_pers_en.extract_keywords(content)))
            ner_results["region"] = list(dict.fromkeys(self.kp_reg_en.extract_keywords(content)))

        # 2. BERT 모델 추론 (모델이 알아서 합쳐서 줍니다)
        target_ner = self.ner_ko if lang == 'ko' else self.ner_en
        ner_raw = target_ner(content[:2000])

        # 3. 모델 결과 통합
        for ent in ner_raw:
            label = ent['entity_group']
            text = ent['word'].strip()

            # [핵심] 병합 실패한 토큰 파편은 여기서 걸러냅니다.
            if '##' in text or len(text) < 2:
                continue

            # 레이블에 맞춰 결과값 추가
            if label in ['ORG', 'B-ORG', 'I-ORG', 'corporation']:
                if text not in ner_results["company"]:
                    ner_results["company"].append(text)
            elif label in ['PER', 'B-PER', 'I-PER', 'person']:
                if text not in ner_results["person"]:
                    ner_results["person"].append(text)

        return ner_results

    # [핵심 추가] 기존 spaCy 로직의 필터링 함수화
    def _is_valid_company(self, text, lang, results):
        # 1. 길이 및 기본 필터링
        if text in results["company"] or len(text) < 2: return False

        # 2. 기호 및 쓰레기 문자 제거
        text_clean = text.replace('\\', '').replace('"', '').replace('^', '')
        text_clean = re.sub(r'\s+', ' ', text_clean)
        text_clean = re.sub(r'^[^a-zA-Z가-힣0-9]+|[^a-zA-Z0-9가-힣]+$', '', text_clean)

        # 3. 영어 정관사 제거
        if lang == 'en':
            text_clean = re.sub(r'^(the|a|an)\s+', '', text_clean, flags=re.IGNORECASE)
            if len(text_clean) <= 3 or len(text_clean) > 35: return False
        else:
            if len(text_clean) > 20: return False

        # 4. 숫자/주가/티커 심볼 차단
        if re.match(r'^[\+\-\=]?\s*\d+[\d\,\.]*\s*\%?$', text_clean): return False
        if not re.search(r'[a-zA-Z가-힣]', text_clean): return False
        if lang == 'ko' and re.search(r'(로부터|에서|가|를|을|은|는|의|과|와|로|으로)$', text_clean): return False
        if re.match(r'^[A-Z]{1,5}$', text_clean): return False

        # 5. 언론사/광고/학교/정부/도메인 파편 차단
        noise_pattern = r'(?i)(Photo\/?|News|Live|Advertisement|Scroll|Reuters|Bloomberg|CNBC|Journal|Insider|MarketWatch|School|University|Univ|Government|Gov|\.com|\.net|\.org)'
        if re.search(noise_pattern, text_clean): return False

        # 6. 노이즈 세트 및 블랙리스트 대조
        text_lower = text_clean.lower()
        if text_lower in self.finance_noise_ko if lang == 'ko' else self.finance_noise_en: return False
        if text_lower in self.org_blacklist: return False

        return True

    def _is_valid_person(self, text, lang):
        # 1. 기호 및 쓰레기 문자 제거
        text_raw = text.replace('\\', '').replace('"', '').replace('^', '')
        text_raw = re.sub(r'\s+', ' ', text_raw)
        text_raw = re.sub(r'^[^a-zA-Z가-힣0-9]+|[^a-zA-Z가-힣0-9]+$', '', text_raw)

        # 2. 영어 정관사 제거
        if lang == 'en':
            text_raw = re.sub(r'^(the|a|an)\s+', '', text_raw, flags=re.IGNORECASE)

        # 3. 숫자 포함 또는 특수기호로 시작하면 제외
        if re.search(r'\d', text_raw) or re.match(r'^[\+\-\%]', text_raw):
            return False

        # 4. 길이 제한 (영어 4자 이상, 한국어 2자 이상)
        if lang == 'en' and len(text_raw) <= 3: return False
        if lang == 'ko' and len(text_raw) <= 1: return False

        # 5. 이름 정규화 체크 (이미 사전/후보군에 있는지 확인)
        text_lower = text_raw.lower()
        if text_lower in self.person_normalization_dict or text_raw in self.person_normalization_dict:
            return True

        # 6. 추가 필터링 (불필요한 직함 등)
        # 만약 모델이 이름인 줄 알고 뽑았는데 사실 직함(예: '팀장')이라면 여기서 걸러집니다.
        if text_raw in ['팀장', '기자', '앵커', '연구원']: return False

        return True

    def add_candidate(self, cat, term):
        return
        # data = self.entity_data.get(cat, {})
        # term_lower = term.lower()
        #
        # # 1. 중복 확인 (소문자로 철저하게 대조)
        # exists = False
        # for rep, alias_list in data.items():
        #     clean_rep = rep.replace("candidate_", "").lower()
        #     if term_lower == clean_rep or term_lower in [a.lower() for a in alias_list]:
        #         exists = True
        #         break
        #
        # # 2. 중복이 없다면 추가
        # if not exists:
        #     candidate_key = f"candidate_{term}"  # Key는 대소문자 살려서 (예: candidate_Trump)
        #     if candidate_key not in data:
        #         data[candidate_key] = [term_lower]  # 💡 Alias는 무조건 소문자로 저장 (예: ["trump"])
        #
        #         # 파일에 즉시 덮어쓰기
        #         json_path = os.path.join(self.dict_path, f"{cat}.json")
        #         with open(json_path, 'w', encoding='utf-8') as f:
        #             json.dump(data, f, ensure_ascii=False, indent=4)
        #
        #         sort_json(json_path)

    def run_analysis(self, target_langs=['ko', 'en']):
        ko_vectorizer = CountVectorizer(tokenizer=self.kiwi_tokenizer, token_pattern=None)
        en_vectorizer = CountVectorizer(tokenizer=self.en_tokenizer, token_pattern=None)
        batch_size = 8

        for lang in target_langs:
            index_name = f"news_{lang}"

            # [수정] nlp_ko/nlp_en을 삭제하고 ner_ko/ner_en으로 교체
            # 단, 이 변수들은 실제 NER 추출에 사용되므로 구조를 살짝 맞춥니다.
            ner_model = self.ner_ko if lang == 'ko' else self.ner_en

            target_model = self.st_model_ko if lang == 'ko' else self.st_model_en
            vectorizer = ko_vectorizer if lang == 'ko' else en_vectorizer

            # 해당 언어 전용 모델로 교체
            self.kw_model.model = SentenceTransformerBackend(target_model)

            scan = helpers.scan(self.es, index=index_name, query={"query": {"match_all": {}}}, size=500,
                                _source=["content", "title"])

            batch_docs = []
            for doc in tqdm(scan, desc=f"Processing {lang.upper()}"):
                content = doc['_source'].get('content', '')
                title = doc['_source'].get('title', '')
                if not content or len(content) < 10: continue

                # [수정] 이제는 spaCy 객체 전달 없이 content 바로 전달
                ner_results = self._extract_ner(content, lang)

                batch_docs.append({
                    "id": doc['_id'],
                    "content": f"{title}. {content}",
                    "ner": ner_results,
                    "lang": lang
                })

                if len(batch_docs) >= batch_size:
                    self.process_and_save(batch_docs, vectorizer)
                    batch_docs = []
                    self.clear_memory()

            if batch_docs:
                self.process_and_save(batch_docs, vectorizer)
                self.clear_memory()

    def process_and_save(self, docs, vectorizer=None):
        actions = []

        job_titles = {
            '기자', '특파원', '연구원', '위원', '팀장', '교수', '작가', '배상', '리포터',
            '앵커', '수석연구위원', '선임연구원', '연구위원', '그래픽', '영상취재', '영상편집',
            '애널리스트', '이코노미스트', '팀', '인터뷰', '뉴스', '사진',
        }

        for d in docs:
            try:
                # [추가] 원문에서 역슬래시(\) 및 특수 이스케이프 문자 정제
                d['content'] = re.sub(r'\\+', '', d['content'])  # 역슬래시(\) 제거
                d['content'] = d['content'].replace('"', '')  # 남은 따옴표 필요없다면 정제 (선택사항)

                # ---------------------------------------------------------------------------------
                # [핵심 수정] 언어별 토큰화 및 후보군(candidates) 추출 분기
                # ---------------------------------------------------------------------------------
                nnp_candidates = []  # 한국어 가중치 로직 조건 분기 유지를 위해 상단 선언
                found_words = []
                en_pos_map = {}  # 영어 단어별 실제 원본 품사 태그를 저장할 딕셔너리

                if d['lang'] == 'ko':
                    # ==========================================
                    # 1. 한국어 전용 파이프라인 (고속 사전 매칭 적용)
                    # ==========================================

                    # 형태소 분석 우선 수행
                    tokens = self.kiwi.tokenize(d['content'])
                    num_tokens = len(tokens)

                    # 💡 핵심 수정: 추출된 명사/고유명사 포맷들을 set으로 변환
                    token_forms_set = {t.form for t in tokens if t.tag in ('NNP', 'NNG')}

                    # 💡 O(1) 계열의 세트 연산 및 딕셔너리 조회를 통한 고속 교집합 매칭
                    for form in token_forms_set:
                        if form in self.all_survive_ko:
                            found_words.append(form)
                        elif form in self.survive_ko_no_space:
                            found_words.append(self.survive_ko_no_space[form])

                    forbidden_indices = set()
                    for i in range(num_tokens):
                        if tokens[i].form in job_titles:
                            for j in range(max(0, i - 5), min(num_tokens, i + 2)):
                                forbidden_indices.add(j)

                    valid_tokens = [
                        t.form for t in tokens
                        if t.form not in self.finance_noise_ko and len(t.form) > 1
                    ]

                    valid_set = set(valid_tokens)
                    extra_nng_candidates = []
                    idx = 0
                    common_surnames = ('김', '이', '박', '최', '정', '강', '조', '윤', '장', '임', '한', '오', '서', '신', '권', '황',
                                       '안')

                    while idx < num_tokens:
                        t = tokens[idx]
                        is_forbidden = idx in forbidden_indices

                        if idx + 1 < num_tokens and t.tag in ('NNP', 'NNG') and tokens[idx + 1].tag in ('NNP', 'NNG'):
                            has_nnp = (t.tag == 'NNP' or tokens[idx + 1].tag == 'NNP')

                            if has_nnp:
                                is_human_name = (
                                        t.tag == 'NNP' and
                                        ((len(t.form) in (2, 3, 4) and t.form.startswith(common_surnames)) or (
                                                t.form in self.all_survive_ko))
                                )

                                if is_human_name:
                                    pass
                                else:
                                    combined_nnp = t.form
                                    current_end = t.end
                                    next_idx = idx + 1
                                    has_nnp_broken = False

                                    while next_idx < num_tokens:
                                        next_token = tokens[next_idx]

                                        if next_token.tag not in ('NNP', 'NNG'):
                                            break

                                        if current_end != next_token.start:
                                            break

                                        if next_token.form in self.finance_noise_ko:
                                            has_nnp_broken = True
                                            break

                                        combined_nnp += next_token.form
                                        current_end = next_token.end
                                        next_idx += 1

                                    if not has_nnp_broken and combined_nnp != t.form and len(combined_nnp) > 2:
                                        if combined_nnp not in self.finance_noise_ko:
                                            nnp_candidates.append(combined_nnp)
                                        idx = next_idx
                                        continue

                        if t.tag == 'NNG':
                            if t.form in self.finance_noise_ko or len(t.form) <= 1:
                                idx += 1
                                continue

                            combined_nng = t.form
                            current_end = t.end
                            next_idx = idx + 1
                            has_broken = False

                            while next_idx < num_tokens:
                                next_token = tokens[next_idx]

                                if next_token.tag != 'NNG':
                                    break

                                if current_end != next_token.start:
                                    break

                                if next_token.form in self.finance_noise_ko or len(next_token.form) <= 1:
                                    has_broken = True
                                    break

                                combined_nng += next_token.form
                                current_end = next_token.end
                                next_idx += 1

                            if not has_broken and combined_nng != t.form and len(combined_nng) >= 3:
                                if combined_nng not in self.finance_noise_ko:
                                    extra_nng_candidates.append(combined_nng)
                                idx = next_idx
                                continue

                        if t.tag == 'NNP' and t.form not in self.finance_noise_ko:
                            if len(t.form) == 2 and t.form.startswith(common_surnames):
                                if t.form not in self.all_survive_ko:
                                    idx += 1
                                    continue

                            is_protected = any(t.form in fw.replace(" ", "") for fw in found_words)
                            if not is_forbidden or is_protected:
                                nnp_candidates.append(t.form)

                        idx += 1

                    nng_candidates = [
                                         t.form for t in tokens
                                         if t.tag == 'NNG' and len(t.form) >= 3 and t.form in valid_set
                                     ] + extra_nng_candidates

                    raw_candidates = list(set(nnp_candidates + nng_candidates + found_words))
                    candidates = list(dict.fromkeys([c.replace(" ", "") for c in raw_candidates if c]))

                else:
                    raw_en_candidates = self.en_tokenizer(d['content'])
                    candidates = []

                    for raw in raw_en_candidates:
                        if "::" in raw:
                            word_part, pos_part = raw.split("::", 1)
                            candidates.append(word_part)
                            en_pos_map[word_part.lower()] = pos_part
                        else:
                            candidates.append(raw)

                if not candidates:
                    final_keywords = []
                else:
                    target_model = self.st_model_ko if d['lang'] == 'ko' else self.st_model_en
                    doc_emb = target_model.encode([d['content']])
                    cand_embs = target_model.encode(candidates)
                    distances = cosine_similarity(doc_emb, cand_embs)[0]

                    weighted_scores = []
                    for kw, score in zip(candidates, distances):
                        # 💡 1. 기본 텍스트 추출 및 빈 값 방어
                        kw = kw.text if hasattr(kw, 'text') else str(kw)
                        if not kw:
                            continue

                        # 💡 2. 소문자 변환 전 원형 고유명사 판별 선제 획득
                        is_originally_propn = kw.isupper() or (len(kw) > 0 and kw[0].isupper()) or " " in kw
                        kw_lower = kw.lower()

                        # 💡 3. 영어 전용 노이즈 필터링 및 소문자화 적용
                        if d['lang'] == 'en':
                            kw = kw_lower
                            # Q4, N98 등 숫자 파편 및 찌꺼기 패스
                            if re.match(r'^(?![Qq])[A-Za-z]{1,2}\d', kw): continue
                            if re.match(r'^[\d.,\s]+$', kw): continue
                            if kw in self.finance_noise_en: continue

                        # 💡 4. 언어별 생존 단어장 (Permanent Words) 매칭
                        survive_set = self.all_survive_ko if d['lang'] == 'ko' else self.all_survive_en
                        is_special = any(kw in fw.replace(" ", "") for fw in survive_set) or kw in survive_set

                        # 💡 5. 가중치 로직 분기
                        if d['lang'] == 'ko':
                            if is_special:
                                final_score = score + 0.5
                            elif kw in nnp_candidates:
                                final_score = score + 0.1
                            else:
                                final_score = score - 0.15

                        else:  # d['lang'] == 'en'
                            is_en_whitelist = kw in self.finance_whitelist_en
                            is_entity = kw in self.all_entity_aliases  # 회사/인물/지역 사전 포함 여부
                            actual_pos = en_pos_map.get(kw, 'PROPN')

                            # 진짜 고유명사 확인 (소문자화 이전의 원형 기반)
                            is_real_propn = (actual_pos == 'PROPN' and is_originally_propn)

                            # 💡 킬스위치: 화이트리스트도, 엔티티도, 고유명사도, 생존단어도 아니면 탈락!
                            if not is_en_whitelist and not is_entity and not is_real_propn and not is_special:
                                continue

                            if is_special or is_en_whitelist or is_entity:
                                final_score = score + 0.5
                            elif is_real_propn:
                                final_score = score + 0.15
                            else:
                                final_score = score * 0.001

                        # 💡 6. 정상적으로 통과한 키워드만 리스트에 추가
                        weighted_scores.append((kw, final_score))

                    # 7. 정렬 및 중복 제거 (기존 로직 이어짐)
                    sorted_kws = sorted(weighted_scores, key=lambda x: (x[1], len(x[0])), reverse=True)
                    final_keywords = []

                    for kw, score in sorted_kws:
                        if len(final_keywords) >= 15:
                            break
                        if score <= 0.0:
                            continue

                        # 1. 한국어 접사 제거
                        if d['lang'] == 'ko':
                            cleaned_kw = re.sub(r'(의|해|는|은|이|가|를|을)$', '', kw) if len(kw) > 2 else kw
                        else:
                            cleaned_kw = kw

                        # 2. [수정] 사전 대조 후 존재할 때만 정규화 (치환)
                        normalized_kw = cleaned_kw

                        # 💡 기사 언어(ko/en)에 따라 사용할 번역기(프로세서) 선택
                        if d['lang'] == 'ko':
                            procs = [self.kp_reg_ko, self.kp_comp_ko, self.kp_pers_ko]
                        else:
                            procs = [self.kp_reg_en, self.kp_comp_en, self.kp_pers_en]

                        # 지역/회사/인물 순으로 사전에 있는지 체크 후 치환
                        for proc in procs:
                            matches = proc.extract_keywords(cleaned_kw)
                            if matches:
                                # 매칭된 대표 단어로 변경 (첫 번째 매칭 결과 사용)
                                normalized_kw = matches[0]
                                break  # 하나라도 치환되면 종료

                        match_target = normalized_kw.replace(" ", "")
                        if len(match_target) < 2:
                            continue

                        # 3. 중복 및 포함 관계 처리 (이제 normalized_kw를 기준으로 수행)
                        is_redundant = False
                        to_replace_indices = []

                        for i, existing in enumerate(final_keywords):
                            existing_target = existing.replace(" ", "")

                            if d['lang'] == 'en':
                                match_compare = match_target.lower()
                                existing_compare = existing_target.lower()
                            else:
                                match_compare = match_target
                                existing_compare = existing_target

                            if match_compare in existing_compare or existing_compare in match_compare:
                                if len(match_compare) > len(existing_compare):
                                    to_replace_indices.append(i)
                                else:
                                    is_redundant = True
                                    break

                        if is_redundant:
                            continue

                        if to_replace_indices:
                            for index in sorted(to_replace_indices, reverse=True):
                                final_keywords.pop(index)
                            final_keywords.append(normalized_kw)
                        else:
                            if normalized_kw not in final_keywords:
                                final_keywords.append(normalized_kw)

                    print(f" ID: {d['id']} | 키워드 : {final_keywords[:10]}")

                actions.append({
                    "_op_type": "update",
                    "_index": "analyze",
                    "_id": d['id'],
                    "doc": {
                        "doc_id": d['id'],
                        "keywords": final_keywords,
                        "ner": d['ner'],
                        "lang": d['lang'],
                        "model_ver": {
                            "keywords": self.VER_KEYWORDS,
                            "preprocess": self.VER_PREPROCESS
                        }
                    },
                    "doc_as_upsert": True
                })

            except Exception as e:
                print(f"Error in doc loop (Skipping ID {d.get('id', 'Unknown')}): {e}")
                continue

        if actions:
            try:
                helpers.bulk(self.es, actions)
            except Exception as e:
                print(f"ES Bulk Error: {e}")

    def clear_memory(self):
        gc.collect()
        if self.device == "cuda": torch.cuda.empty_cache()

if __name__ == "__main__":
    analyzer = TextAnalyzer()
    analyzer.run_analysis(target_langs=['en'])