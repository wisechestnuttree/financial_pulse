import gc
import re
import os
import json
import torch
import numpy as np
from kiwipiepy import Kiwi
from elasticsearch import Elasticsearch, helpers
from keybert import KeyBERT
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
from flashtext import KeywordProcessor
from keybert.backend import SentenceTransformerBackend
from sklearn.metrics.pairwise import cosine_similarity
import spacy
from logs.logger import getLogger

logger = getLogger("ml")


class TextAnalyzer:
    def __init__(self):
        self.dict_path = os.path.join(os.path.dirname(__file__), 'dictionary')
        self.all_entity_aliases = set()
        self.kiwi = Kiwi()
        try:
            self.nlp_en = spacy.load("en_core_web_sm")
        except:
            os.system("python -m spacy download en_core_web_sm")
            self.nlp_en = spacy.load("en_core_web_sm")

        # =========================================================================
        #  [추가] 회사/인물 전용 하드코딩 불용어(Stopwords) 리스트
        # 사전에 쓰레기값이 들어있어도 여기서 무조건 차단합니다. 필요한 단어를 마음껏 추가하세요.
        # =========================================================================
        self.hard_noise_company = {
            "정부", "국회", "위원회", "법원", "검찰", "경찰", "청와대", "대통령실",
            "센터", "본부", "지점", "영업점", "사무소", "홈페이지", "게시판",
            "유튜브", "페이스북", "트위터", "인스타그램", "온라인", "오프라인",
            "기자", "특파원", "연구원", "팀", "관계자", "전문가", "한경", "매경",
            "뉴스", "연합뉴스", "이데일리", "조선일보", "동아일보", "중앙일보","로이터",
            "상법","증선위","신한자산운","한경DB","고대역폭메모리","HBM"

        }

        self.hard_noise_person = {
            "관계자", "전문가", "분석가", "대변인", "담당자", "책임자", "투자자", "소액주주",
            "네티즌", "누리꾼", "소비자", "고객", "저자", "독자", "팀장", "본부장", "위원장",
            "대통령", "총리", "장관", "의원", "교수", "연구원", "기자", "특파원", "리포터",
            "앵커", "애널리스트", "이코노미스트", "작전세력", "기관투자가", "외국인","이지만",
            "Ai","신중하",""
        }
        # =========================================================================

        self.data_store = {}
        files = {'ko': 'ko_dictionary.json', 'en': 'en_dictionary.json'}

        for lang, filename in files.items():
            file_path = os.path.join(self.dict_path, filename)
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.data_store[lang] = json.load(f)
            else:
                self.data_store[lang] = {'noise': [], 'noise_phrases': [], 'whitelist': []}

            noise_words = self.data_store[lang].get('noise', [])
            noise_phrases = self.data_store[lang].get('noise_phrases', [])
            sorted_phrases = sorted(noise_phrases, key=len, reverse=True)
            pattern_str = '|'.join([re.escape(p) for p in sorted_phrases])

            if lang == 'ko':
                self.finance_noise_ko = set(noise_words)
                self.compiled_phrases_ko = re.compile(f'({pattern_str})', re.IGNORECASE) if pattern_str else None
            else:
                self.finance_noise_en = set(noise_words)
                self.compiled_phrases_en = re.compile(f'({pattern_str})', re.IGNORECASE) if pattern_str else None

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
            "reuters", "bloomberg", "ap", "bbc", "cnn", "nbc", "fox", "cnbc", "yahoo finance", "the new york times",
            "로이터"
        }

        self.keyword_category_map = {}
        self.person_normalization_dict = {}
        self.normalization_dicts = {'company': {}, 'person': {}}
        self.all_entity_aliases_normalized = set()

        self.word_emb_cache_ko = {}
        self.word_emb_cache_en = {}

        self.kp_reg_ko = KeywordProcessor(case_sensitive=False)
        self.kp_reg_en = KeywordProcessor(case_sensitive=False)
        self.kp_comp_ko = KeywordProcessor(case_sensitive=False)
        self.kp_comp_en = KeywordProcessor(case_sensitive=False)
        self.kp_pers_ko = KeywordProcessor(case_sensitive=False)
        self.kp_pers_en = KeywordProcessor(case_sensitive=False)

        korean_chars = set(chr(i) for i in range(ord('가'), ord('힣') + 1))
        self.kp_reg_ko.non_word_boundaries.update(korean_chars)
        self.kp_comp_ko.non_word_boundaries.update(korean_chars)
        self.kp_pers_ko.non_word_boundaries.update(korean_chars)

        self.finance_whitelist_ko = set(self.data_store['ko'].get('whitelist', []))
        self.finance_whitelist_en = set([w.lower() for w in self.data_store['en'].get('whitelist', [])])

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

                if cat == 'regions':
                    for alias in aliases:
                        self.kp_reg_ko.add_keyword(alias, ko_rep)
                        self.kp_reg_en.add_keyword(alias, en_rep)
                        self.all_entity_aliases.add(alias.lower())
                    continue

                if cat == 'company':
                    self.kp_comp_ko.add_keyword(ko_rep, rep)
                    self.kp_comp_en.add_keyword(en_rep, rep)
                elif cat == 'person':
                    # 대표명만 매칭
                    self.kp_pers_ko.add_keyword(ko_rep, rep)
                    self.kp_pers_en.add_keyword(en_rep, rep)

                    # 대표명 자체만 normalization 등록
                    rep_key = rep.lower().replace(" ", "")
                    self.normalization_dicts['person'][rep_key] = rep
                    self.person_normalization_dict[rep_key] = rep

                    # 한글 대표명 붙여쓰기만 추가
                    if re.search(r'[가-힣]', rep):
                        self.normalization_dicts['person'][rep.replace(" ", "")] = rep
                        self.person_normalization_dict[rep.replace(" ", "")] = rep

        self.es = Elasticsearch(['http://100.88.143.23:9200'])
        self.device = 0 if torch.cuda.is_available() else -1
        self.VER_PREPROCESS = "spacy_kiwi_v13.0_1060_optimized"
        self.VER_KEYWORDS = "dual_finbert_v8.0"

        ko_perm_set = set(self.entity_data.get('company', {}).keys()) | \
                      set(self.entity_data.get('person', {}).keys()) | \
                      set(self.entity_data.get('regions', {}).keys()) | \
                      self.finance_whitelist_ko

        en_perm_set = set() | self.finance_whitelist_en
        for data in self.entity_data.values():
            for rep, aliases in data.items():
                en_perm_set.add(rep)
                for alias in aliases: en_perm_set.add(alias)

        self._init_permanent_words(ko_perm_set, en_perm_set)

    def _load_models(self, lang):
        logger.info(f"[{lang.upper()}] 모델 적재 시작...")
        if hasattr(self, 'st_model'):
            del self.st_model
            del self.kw_model
            self.clear_memory()

        model_name = 'snunlp/KR-FinBERT-SC' if lang == 'ko' else 'ProsusAI/finbert'
        self.st_model = SentenceTransformer(model_name, device="cuda" if self.device == 0 else "cpu")
        self.kw_model = KeyBERT(model=SentenceTransformerBackend(self.st_model))
        logger.info(f"[{lang.upper()}] 모델 적재 완료.")

    def _init_permanent_words(self, ko_perm_set, en_perm_set):
        self.all_survive_ko = ko_perm_set
        self.survive_ko_no_space = {w.replace(" ", ""): w for w in ko_perm_set}
        self.all_survive_en = {w.lower() for w in en_perm_set}

        if hasattr(self, 'kiwi') and self.all_survive_ko:
            tmp_dict_path = os.path.join(self.dict_path, 'kiwi_tmp_dict.txt')
            try:
                with open(tmp_dict_path, 'w', encoding='utf-8') as f:
                    for word in self.all_survive_ko:
                        f.write(f"{word}\tNNP\t10\n")
                self.kiwi.load_user_dictionary(tmp_dict_path)
            except Exception as e:
                logger.error(f"Kiwi user_dictionary load error: {e}")
            finally:
                if os.path.exists(tmp_dict_path):
                    os.remove(tmp_dict_path)

    def _extract_ner(self, content, lang, ko_tokens=None, en_doc=None):
        ner_results = {"company": [], "person": [], "region": []}
        candidate_results = {"company": [], "person": []}

        if lang == 'ko':
            ner_results["region"] = list(dict.fromkeys(self.kp_reg_ko.extract_keywords(content)))
            ner_results["company"] = list(dict.fromkeys(self.kp_comp_ko.extract_keywords(content)))
            ner_results["person"] = list(dict.fromkeys(self.kp_pers_ko.extract_keywords(content)))
        else:
            ner_results["region"] = list(dict.fromkeys(self.kp_reg_en.extract_keywords(content)))
            ner_results["company"] = list(dict.fromkeys(self.kp_comp_en.extract_keywords(content)))
            ner_results["person"] = list(dict.fromkeys(self.kp_pers_en.extract_keywords(content)))

        if lang == 'ko':
            tokens = ko_tokens if ko_tokens is not None else self.kiwi.tokenize(content)
            for token in tokens:
                if token.tag in ('NNP', 'NNG'):
                    self._apply_mapping(token.form, None, ner_results, candidate_results, 'ko')
        else:
            doc = en_doc if en_doc is not None else self.nlp_en(content)
            for ent in doc.ents:
                cat = "company" if ent.label_ == "ORG" else \
                    "person" if ent.label_ == "PERSON" else \
                        "region" if ent.label_ == "GPE" else None
                if cat and cat != 'region':
                    self._apply_mapping(ent.text, cat, ner_results, candidate_results, 'en')

        for cat in ner_results:
            ner_results[cat] = list(dict.fromkeys(ner_results[cat]))

        return ner_results, candidate_results

    def _extract_en_candidates(self, text, en_doc=None):
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

        result = []
        doc = en_doc if en_doc is not None else self.nlp_en(text)

        for ent in doc.ents:
            if ent.label_ in ["PERSON", "ORG", "GPE"] and len(ent.text) > 2:
                if ent.text.lower() not in self.finance_noise_en:
                    result.append(f"{ent.text}::PROPN")

        words = text.split()
        for w in words:
            cleaned = re.sub(r'[^\w\s]', '', w)
            if len(cleaned) > 2:
                cleaned_lower = cleaned.lower()
                if cleaned_lower in self.finance_whitelist_en:
                    result.append(f"{cleaned}::NOUN")
                elif cleaned_lower in self.all_entity_aliases:
                    result.append(f"{cleaned}::PROPN")

        return list(dict.fromkeys(result))

    def _apply_mapping(self, word, cat, ner_results, candidate_results, lang):
        # 1. 하드코딩 불용어(Stopwords) 필터링
        if word in self.hard_noise_company or word in self.hard_noise_person:
            return

        search_key = word.lower().replace(" ", "")

        # 2. 기존 사전 매핑 (회사/인물 우선 처리)
        found_cat = None
        if search_key in self.normalization_dicts['company']:
            found_cat = 'company'
        elif search_key in self.normalization_dicts['person']:
            found_cat = 'person'

        if found_cat:
            official_name = self.normalization_dicts[found_cat].get(search_key, word)
            if official_name not in ner_results[found_cat]:
                ner_results[found_cat].append(official_name)
            if found_cat in candidate_results:
                candidate_results[found_cat].append(official_name)
            return

        # 3. 사전 매핑이 안 된 경우 -> 기존 검증 로직 타기
        if not cat: return
        if cat == "region": return

        if cat == "company":
            # 기존 회사 검증 로직 유지
            if self._is_valid_company(word, lang, ner_results):
                ner_results["company"].append(word)
                candidate_results["company"].append(word)

        elif cat == "person":
            # 기존 인물 검증 로직 유지
            if self._is_valid_person(word, lang, ner_results):
                ner_results["person"].append(word)
                candidate_results["person"].append(word)

    def _is_valid_company(self, text, lang, current_ner_results):
        #  회사명 검증 단계에서도 불용어 필터링 적용
        if text in self.hard_noise_company: return False
        if text in current_ner_results["company"] or len(text) < 2: return False

        text_clean = text.replace('\\', '').replace('"', '').replace('^', '')
        text_clean = re.sub(r'\s+', ' ', text_clean)
        text_clean = re.sub(r'^[^a-zA-Z가-힣0-9]+|[^a-zA-Z0-9가-힣]+$', '', text_clean)

        if lang == 'en':
            text_clean = re.sub(r'^(the|a|an)\s+', '', text_clean, flags=re.IGNORECASE)
            if len(text_clean) <= 3 or len(text_clean) > 35: return False
        else:
            if len(text_clean) > 20: return False

        if re.match(r'^[\+\-\=]?\s*\d+[\d\,\.]*\s*\%?$', text_clean): return False
        if not re.search(r'[a-zA-Z가-힣]', text_clean): return False
        if lang == 'ko' and re.search(r'(로부터|에서|가|를|을|은|는|의|과|와|로|으로)$', text_clean): return False
        if re.match(r'^[A-Z]{1,5}$', text_clean): return False

        noise_pattern = r'(?i)(Photo\/?|News|Live|Advertisement|Scroll|Reuters|Bloomberg|CNBC|Journal|Insider|MarketWatch|School|University|Univ|Government|Gov|\.com|\.net|\.org)'
        if re.search(noise_pattern, text_clean): return False

        text_lower = text_clean.lower()
        target_noise = self.finance_noise_ko if lang == 'ko' else self.finance_noise_en
        if text_lower in target_noise: return False

        if text_lower in self.org_blacklist: return False
        return True

    def _is_valid_person(self, text, lang, current_ner_results):
        #  인물명 검증 단계에서도 불용어 필터링 적용
        if text in self.hard_noise_person: return False
        if text in current_ner_results["person"]: return False

        text_raw = text.replace('\\', '').replace('"', '').replace('^', '')
        text_raw = re.sub(r'\s+', ' ', text_raw)
        text_raw = re.sub(r'^[^a-zA-Z가-힣0-9]+|[^a-zA-Z가-힣0-9]+$', '', text_raw)

        if lang == 'en':
            text_raw = re.sub(r'^(the|a|an)\s+', '', text_raw, flags=re.IGNORECASE)

        if re.search(r'\d', text_raw) or re.match(r'^[\+\-\%]', text_raw):
            return False

        if lang == 'en' and len(text_raw) <= 3: return False
        if lang == 'ko' and len(text_raw) <= 1: return False

        bad_suffixes = ['기자', '앵커', '연구원', '팀장', '특파원', '위원', '본부장', '대변인', '교수']
        if any(text_raw.endswith(suffix) for suffix in bad_suffixes): return False
        if text_raw in bad_suffixes: return False

        return True

    def run_analysis(self, target_langs=['ko', 'en']):
        #  GTX 1060 환경을 고려하여 배치 사이즈 16 유지 (안정성)
        batch_size = 16
        for lang in target_langs:
            self._load_models(lang)

            index_name = f"news_{lang}"
            scan = helpers.scan(self.es, index=index_name, query={"query": {"match_all": {}}}, size=500,
                                _source=["content", "title"])

            batch_docs = []

            for doc in tqdm(scan, desc=f"Processing {lang.upper()}"):
                content = doc['_source'].get('content', '')
                title = doc['_source'].get('title', '')
                if not content or len(content) < 10:
                    continue

                full_text = re.sub(r'\\+', '', f"{title}. {content}").replace('"', '')

                ko_tokens = None
                en_doc = None
                if lang == 'ko':
                    ko_tokens = self.kiwi.tokenize(full_text)
                    ner_results, candidate_results = self._extract_ner(full_text, lang, ko_tokens=ko_tokens)
                else:
                    en_doc = self.nlp_en(full_text)
                    ner_results, candidate_results = self._extract_ner(full_text, lang, en_doc=en_doc)

                #  추출 결과에서 하드코딩 불용어 최종 필터링 적용
                ner_results["company"] = [c for c in ner_results["company"] if c not in self.hard_noise_company]
                ner_results["person"] = [p for p in ner_results["person"] if p not in self.hard_noise_person]

                batch_docs.append({
                    "id": doc['_id'],
                    "content": full_text,
                    "ko_tokens": ko_tokens,
                    "en_doc": en_doc,
                    "ner": ner_results,
                    "lang": lang
                })

                if len(batch_docs) >= batch_size:
                    self.process_and_save(batch_docs)
                    batch_docs = []

            if batch_docs:
                self.process_and_save(batch_docs)

            self.clear_memory()

    def process_and_save(self, docs):
        actions = []
        job_titles = {'기자', '특파원', '연구원', '위원', '팀장', '교수', '작가', '배상', '리포터',
                      '앵커', '수석연구위원', '선임연구원', '연구위원', '그래픽', '영상취재',
                      '영상편집', '애널리스트', '이코노미스트', '팀', '인터뷰', '뉴스', '사진'}

        person_block_titles = {'기자', '특파원', '앵커', '리포터', '그래픽', '영상취재', '영상편집'}
        common_surnames = ('김', '이', '박', '최', '정', '강', '조', '윤', '장', '임', '한', '오', '서', '신',
                           '권', '황', '안', '송', '류', '전', '홍', '고', '문', '양', '손', '배', '백', '허',
                           '남', '심', '노', '하', '곽', '성', '차', '주', '우', '구', '민', '진', '엄', '채',
                           '원', '천', '방', '공', '현')

        def looks_like_ko_person_name(name):
            if not name:
                return False

            name = name.strip()
            name_key = name.lower().replace(" ", "")

            if not re.match(r'^[가-힣]{2,4}$', name):
                return False

            if not name.startswith(common_surnames):
                return False

            # 일반 불용어/하드 불용어 제외
            if name in self.finance_noise_ko:
                return False
            if name in self.hard_noise_person or name in self.hard_noise_company:
                return False

            # 회사/지역 사전에 있는 것은 사람 후보에서 제외
            if name_key in self.normalization_dicts['company']:
                return False

            if self.kp_comp_ko.extract_keywords(name):
                return False

            if self.kp_reg_ko.extract_keywords(name):
                return False

            # 경제 whitelist는 사람 후보에서 제외
            if name in self.finance_whitelist_ko:
                return False

            return True

        #  [Pass 1] 문서 전처리 및 후보군 식별
        all_texts_to_encode = set()

        for d in docs:
            nnp_candidates, found_words, en_pos_map, candidates = [], [], {}, []

            try:
                d.setdefault('ner', {"company": [], "person": [], "region": []})
                d['content'] = re.sub(r'\\+', '', d['content']).replace('"', '')

                if d['lang'] == 'ko':
                    tokens = d.get('ko_tokens')
                    if tokens is None:
                        tokens = self.kiwi.tokenize(d['content'])

                    num_tokens = len(tokens)
                    token_forms_set = {t.form for t in tokens if t.tag in ('NNP', 'NNG')}

                    for form in token_forms_set:
                        if form in self.finance_noise_ko:
                            continue
                        if form in self.hard_noise_company or form in self.hard_noise_person:
                            continue

                        if form in self.all_survive_ko:
                            found_words.append(form)
                        elif form in self.survive_ko_no_space:
                            original = self.survive_ko_no_space[form]
                            if original not in self.finance_noise_ko:
                                found_words.append(original)

                    forbidden_indices = set()
                    for i in range(num_tokens):
                        if tokens[i].form in job_titles:
                            for j in range(max(0, i - 5), min(num_tokens, i + 2)):
                                forbidden_indices.add(j)

                    # ==========================================================
                    # 👤 PERSON 전용 후보 추출
                    # - 기자/앵커/특파원 등 작성자성 이름은 제외
                    # ==========================================================
                    person_name_candidates = []

                    for i, t in enumerate(tokens):
                        ...
                        # 기존 PERSON 후보 추출 코드
                        ...

                    # ==========================================================
                    # 👤 직함 기반 PERSON 후보 추가
                    # ==========================================================
                    person_title_pattern = re.compile(
                        r'(?:'
                        r'([가-힣]{2,4})\s*'
                        r'(대표|회장|부회장|사장|부사장|대표이사|의장|총재|원장|상무|전무|부장|이사|장관|차관|의원|위원장|교수|연구원)'
                        r'|'
                        r'(대표|회장|부회장|사장|부사장|대표이사|의장|총재|원장|상무|전무|부장|이사|장관|차관|의원|위원장|교수|연구원)\s*'
                        r'([가-힣]{2,4})'
                        r')'
                    )

                    for m in person_title_pattern.finditer(d['content']):
                        name = m.group(1) or m.group(4)

                        if looks_like_ko_person_name(name):
                            person_name_candidates.append(name)

                    person_name_candidates = list(dict.fromkeys(person_name_candidates))

                    person_candidate_results = {"company": [], "person": []}

                    for person_name in person_name_candidates:
                        self._apply_mapping(
                            person_name,
                            None,
                            d['ner'],
                            person_candidate_results,
                            'ko'
                        )

                    logger.info(f" 👤 PERSON 후보(raw): {person_name_candidates[:20]}")
                    logger.info(f" 👤 PERSON 사전매칭후: {d['ner']['person']}")

                    valid_tokens = [t.form for t in tokens if t.form not in self.finance_noise_ko and len(t.form) > 1]
                    valid_set = set(valid_tokens)
                    extra_nng_candidates = []
                    idx = 0

                    while idx < num_tokens:
                        t = tokens[idx]

                        if idx + 1 < num_tokens and t.tag in ('NNP', 'NNG') and tokens[idx + 1].tag in ('NNP', 'NNG'):
                            has_nnp = (t.tag == 'NNP' or tokens[idx + 1].tag == 'NNP')

                            if has_nnp:

                                combined_nnp, current_end, next_idx, has_nnp_broken = t.form, t.end, idx + 1, False

                                while next_idx < num_tokens:
                                    next_token = tokens[next_idx]

                                    if (
                                            next_token.tag not in ('NNP', 'NNG')
                                            or current_end != next_token.start
                                            or next_token.form in self.finance_noise_ko
                                    ):
                                        if next_token.tag in ('NNP',
                                                              'NNG') and next_token.form in self.finance_noise_ko:
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

                            combined_nng, current_end, next_idx, has_broken = t.form, t.end, idx + 1, False

                            while next_idx < num_tokens:
                                next_token = tokens[next_idx]

                                if (
                                        next_token.tag != 'NNG'
                                        or current_end != next_token.start
                                        or next_token.form in self.finance_noise_ko
                                        or len(next_token.form) <= 1
                                ):
                                    if next_token.tag == 'NNG' and (
                                            next_token.form in self.finance_noise_ko or len(next_token.form) <= 1
                                    ):
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

                            if not (len(t.form) == 2 and t.form.startswith(
                                    common_surnames) and t.form not in self.all_survive_ko):
                                if idx not in forbidden_indices or any(
                                        t.form in fw.replace(" ", "") for fw in found_words):
                                    nnp_candidates.append(t.form)

                        idx += 1

                    nng_candidates = [
                                         t.form for t in tokens
                                         if t.tag == 'NNG' and len(t.form) >= 3 and t.form in valid_set
                                     ] + extra_nng_candidates

                    raw_candidates = list(set(nnp_candidates + nng_candidates + found_words))
                    candidates = list(dict.fromkeys([c.replace(" ", "") for c in raw_candidates if c]))

                else:
                    raw_en_candidates = self._extract_en_candidates(d['content'], d.get('en_doc'))

                    for raw in raw_en_candidates:
                        if "::" in raw:
                            word_part, pos_part = raw.split("::", 1)
                            candidates.append(word_part)
                            en_pos_map[word_part.lower()] = pos_part
                        else:
                            candidates.append(raw)

                d['extracted_candidates'] = candidates
                d['nnp_candidates'] = nnp_candidates
                d['en_pos_map'] = en_pos_map

                if candidates:
                    all_texts_to_encode.add(d['content'])
                    all_texts_to_encode.update(candidates)

            except Exception as e:
                logger.error(f"Candidate Extraction Error ID {d.get('id', 'Unknown')}: {e}")
                continue

        #  [Pass 2] 1060 맞춤형 GPU 임베딩 일괄 계산
        docs_to_encode = []
        words_to_encode = set()
        lang_cache = self.word_emb_cache_ko if docs and docs[0]['lang'] == 'ko' else self.word_emb_cache_en

        for d in docs:
            docs_to_encode.append(d['content'])
            for c in d.get('extracted_candidates', []):
                if c not in lang_cache:
                    words_to_encode.add(c)

        doc_emb_dict = {}

        if docs_to_encode:
            doc_embeddings = self.st_model.encode(docs_to_encode, batch_size=8, convert_to_numpy=True)
            doc_emb_dict = {d['id']: emb for d, emb in zip(docs, doc_embeddings)}

        if words_to_encode:
            words_list = list(words_to_encode)
            word_embs = self.st_model.encode(words_list, batch_size=32, convert_to_numpy=True)

            for txt, emb in zip(words_list, word_embs):
                lang_cache[txt] = emb

        #  [Pass 3] 코사인 유사도 계산 및 최종 키워드 결정
        for d in docs:
            try:
                candidates = d.get('extracted_candidates', [])
                nnp_candidates = d.get('nnp_candidates', [])
                en_pos_map = d.get('en_pos_map', {})

                if not candidates:
                    final_keywords = []
                else:
                    valid_cands, valid_embs = [], []

                    for c in candidates:
                        if c in lang_cache:
                            valid_cands.append(c)
                            valid_embs.append(lang_cache[c])

                    if not valid_cands:
                        final_keywords = []
                    else:
                        doc_emb = doc_emb_dict[d['id']].reshape(1, -1)
                        cand_embs = np.array(valid_embs)
                        distances = cosine_similarity(doc_emb, cand_embs)[0]
                        weighted_scores = []

                        for kw, score in zip(valid_cands, distances):
                            is_originally_propn = kw.isupper() or (len(kw) > 0 and kw[0].isupper()) or " " in kw
                            kw_lower = kw.lower()

                            if d['lang'] == 'en':
                                kw = kw_lower
                                if re.match(r'^(?![Qq])[A-Za-z]{1,2}\d', kw):
                                    continue
                                if re.match(r'^[\d.,\s]+$', kw):
                                    continue
                                if kw in self.finance_noise_en:
                                    continue

                            survive_set = self.all_survive_ko if d['lang'] == 'ko' else self.all_survive_en
                            is_special = any(kw in fw.replace(" ", "") for fw in survive_set) or kw in survive_set

                            if d['lang'] == 'ko':
                                if is_special:
                                    final_score = score + 0.5
                                elif kw in nnp_candidates:
                                    final_score = score + 0.1
                                else:
                                    final_score = score - 0.15
                            else:
                                is_en_whitelist = kw in self.finance_whitelist_en
                                is_entity = kw in self.all_entity_aliases
                                actual_pos = en_pos_map.get(kw, 'PROPN')
                                is_real_propn = (actual_pos == 'PROPN' and is_originally_propn)

                                if not is_en_whitelist and not is_entity and not is_real_propn and not is_special:
                                    continue

                                if is_special or is_en_whitelist or is_entity:
                                    final_score = score + 0.5
                                elif is_real_propn:
                                    final_score = score + 0.15
                                else:
                                    final_score = score * 0.001

                            weighted_scores.append((kw, final_score))

                        sorted_kws = sorted(weighted_scores, key=lambda x: (x[1], len(x[0])), reverse=True)
                        final_keywords = []

                        for kw, score in sorted_kws:
                            if len(final_keywords) >= 15:
                                break
                            if score <= 0.0:
                                continue

                            if d['lang'] == 'ko':
                                cleaned_kw = re.sub(r'(의|해|는|은|이|가|를|을)$', '', kw) if len(kw) > 2 else kw
                            else:
                                cleaned_kw = kw

                            match_target = cleaned_kw.lower().replace(" ", "")
                            normalized_kw = cleaned_kw
                            found_cat_for_ner = None

                            if match_target in self.normalization_dicts['company']:
                                normalized_kw = self.normalization_dicts['company'][match_target]
                                found_cat_for_ner = 'company'
                            elif match_target in self.normalization_dicts['person']:
                                normalized_kw = self.normalization_dicts['person'][match_target]
                                found_cat_for_ner = 'person'
                            else:
                                reg_matches = (
                                    self.kp_reg_ko.extract_keywords(cleaned_kw)
                                    if d['lang'] == 'ko'
                                    else self.kp_reg_en.extract_keywords(cleaned_kw)
                                )
                                if reg_matches:
                                    normalized_kw = reg_matches[0]
                                    found_cat_for_ner = 'region'

                            if found_cat_for_ner and normalized_kw not in d['ner'][found_cat_for_ner]:
                                if found_cat_for_ner == 'company' and normalized_kw not in self.hard_noise_company:
                                    d['ner'][found_cat_for_ner].append(normalized_kw)
                                elif found_cat_for_ner == 'person' and normalized_kw not in self.hard_noise_person:
                                    d['ner'][found_cat_for_ner].append(normalized_kw)
                                elif found_cat_for_ner == 'region':
                                    d['ner'][found_cat_for_ner].append(normalized_kw)

                            # 최종 키워드 불용어 필터
                            if d['lang'] == 'ko':
                                if cleaned_kw in self.finance_noise_ko or normalized_kw in self.finance_noise_ko:
                                    continue
                                if cleaned_kw in self.hard_noise_company or normalized_kw in self.hard_noise_company:
                                    continue
                            else:
                                if cleaned_kw.lower() in self.finance_noise_en or normalized_kw.lower() in self.finance_noise_en:
                                    continue


                            if len(normalized_kw.replace(" ", "")) < 2:
                                continue

                            is_redundant = False
                            to_replace_indices = []

                            for i, existing in enumerate(final_keywords):
                                existing_target = existing.replace(" ", "")

                                if d['lang'] == 'en':
                                    match_compare = match_target
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

                logger.info(f"  기업 : {d['ner']['company']}")
                logger.info(f"  인물 : {d['ner']['person']}")
                logger.info(f"  키워드 : {final_keywords[:7]}")

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
                logger.error(f"Error in Score/Action loop (Skipping ID {d.get('id', 'Unknown')})",
                             extra={"action": "process_and_save", "err_msg": str(e)})
                continue

        if actions:
            try:
                helpers.bulk(self.es, actions)
            except Exception as e:
                logger.error(f"ES Bulk Error", extra={"action": "process_and_save", "err_msg": str(e)})

    def clear_memory(self):
        # 🔥 메모리 반환을 강제하여 CUDA OOM 방지
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

if __name__ == "__main__":
    analyzer = TextAnalyzer()
    analyzer.run_analysis(target_langs=['ko', 'en'])