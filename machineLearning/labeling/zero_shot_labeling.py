import csv
import json
from concurrent.futures import ThreadPoolExecutor  # 이 줄이 반드시 있어야 합니다.
from google import genai
from google.genai import types
from elasticsearch import Elasticsearch

# [설정 영역]
API_KEY = "" # <제미나이 api 키 넣어야함. 코드는 유료계정을 사용해야하며 만개 작업시 900 원정도 소모
ES_URL = "http://192.168.0.129:9200/"
TARGET_COUNT = 5000
FETCH_LIMIT = 5500
BATCH_SIZE = 30
SECTORS = ["Tech", "Finance", "Industry", "Consumer", "Healthcare", "Mobility", "Macro & Policy"]
MAX_WORKERS = 5  # 병렬 처리 스레드 수 (속도 조절 핵심)

client = genai.Client(api_key=API_KEY)
MODEL_ID = "gemini-2.5-flash"


def get_safe_batch_prompt(news_items, lang='ko'):
    """사용자님의 산업 본질 우선 원칙 프롬프트 (원본 유지)"""
    items_str = ""
    for item in news_items:
        items_str += f"ID: {item['doc_id']}\nTitle: {item['title']}\nContent: {item['content'][:300]}\n---\n"

    if lang == 'ko':
        instructions = f"""금융 뉴스 분류 전문가로서 20개 기사의 섹터를 분류하세요.
**[중요: 산업 본질 우선 원칙]**
주식/시황 관련 뉴스라도, 해당 뉴스에서 언급된 '기업의 산업 분야'를 최우선 기준으로 삼으세요.

1. **Tech**: 반도체(삼성전자, 하이닉스 등), 소프트웨어, IT서비스, 모바일, 전자장비
2. **Finance**: 특정 기업 없이 '증시 전체(코스피/코스닥)' 시황이거나, 순수 금융업(은행, 보험, 증권, 카드, 핀테크) 소식만 해당함.
3. **Industry**: 조선, 방산, 건설, 기계, 물류, 철강, 에너지
4. **Consumer**: 유통, 소매, 식품, 뷰티, 엔터테인먼트, 가전
5. **Healthcare**: 제약, 바이오(셀트리온 등), 의료기기
6. **Mobility**: 자동차(현대차 등), 배터리/이차전지(에코프로 등), 항공
7. **Macro & Policy**: 금리, 환율, 정부 정책, 부동산, 노동

**[분류 예시]**
- '삼성전자 주가 급등' -> Tech (반도체 기업)
- '에코프로 공매도 논란' -> Mobility (배터리 기업)
- '코스피 하락 마감' -> Finance (시장 전체)"""
    else:
        instructions = f"""As a financial news expert, classify the sectors of 20 articles.
**[CRITICAL: Industry Essence Priority]**
Even if it's stock market news, prioritize the 'Industry Sector' of the company mentioned.

1. **Tech**: Semiconductors, Software, IT Services, Mobile
2. **Finance**: General market (KOSPI/NASDAQ) trends or pure financial services (Banking, Cards, Fintech) ONLY.
3. **Industry**: Shipbuilding, Defense, Construction, Steel, Energy
4. **Consumer**: Retail, Food, Beauty, Entertainment
5. **Healthcare**: Pharma, Bio, Medical Devices
6. **Mobility**: Automotive, Batteries, Aviation
7. **Macro & Policy**: Interest Rates, FX, Regulations, Economy

**[Examples]**
- 'Samsung stock soars' -> Tech
- 'EcoPro short selling' -> Mobility
- 'KOSPI closes lower' -> Finance"""

    return f"""{instructions}

[Category List]
{", ".join(SECTORS)}

[Articles to Classify]
{items_str}

[Response Guideline]
- Respond strictly in JSON list format.
- Each object must have only 'id' and 'sector' keys.
"""


def process_single_batch(batch_items, lang):
    """API 호출부만 별도 함수로 분리 (병렬 처리를 위해 필요)"""
    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=get_safe_batch_prompt(batch_items, lang=lang),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "sector": {"type": "string", "enum": SECTORS}
                        },
                        "required": ["id", "sector"]
                    }
                }
            )
        )
        return json.loads(response.text), batch_items
    except Exception as e:
        print(f"🚨 API 에러: {e}")
        return [], batch_items


def run_labeling():
    es = Elasticsearch(ES_URL)
    tasks = [
        {"index": "news_ko", "file": "train_data_ko_5000.csv", "lang": "ko"},
        {"index": "news_en", "file": "train_data_en_5000.csv", "lang": "en"}
    ]

    for task in tasks:
        print(f"--- [{task['index']}] ({task['lang']}) 산업 중심 재분류 시작 ---")

        query = {
            "query": {"function_score": {"query": {"match_all": {}}, "random_score": {}, "boost_mode": "replace"}},
            "size": FETCH_LIMIT,
            "_source": ["doc_id", "title", "content"]
        }

        try:
            res = es.search(index=task['index'], body=query)
            all_docs = [d['_source'] for d in res['hits']['hits']]
        except Exception as e:
            print(f"🚨 ES 조회 에러: {e}")
            continue

        batches = [all_docs[i:i + BATCH_SIZE] for i in range(0, len(all_docs), BATCH_SIZE)]

        with open(task['file'], "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["doc_id", "title", "content", "lang", "sector"])

            saved_count = 0

            # 병렬 처리 시작
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                # 미래의 응답들을 예약
                futures = [executor.submit(process_single_batch, b, task['lang']) for b in batches]

                for future in futures:
                    if saved_count >= TARGET_COUNT:
                        break

                    results, batch_items = future.result()
                    result_map = {str(r.get('id')): r.get('sector') for r in results}

                    for item in batch_items:
                        doc_id = str(item['doc_id'])
                        sector = result_map.get(doc_id)

                        if sector in SECTORS:
                            clean_content = item['content'].replace("\n", " ").replace("\r", " ").replace("\t", " ")
                            writer.writerow([doc_id, item['title'], clean_content, task['lang'], sector])
                            saved_count += 1
                            if saved_count >= TARGET_COUNT: break

                    print(f"[{task['lang'].upper()}] 누적 유효 데이터: {saved_count}/{TARGET_COUNT}")

    print("\n✅ 산업 중심 고순도 데이터셋 구축 완료!")


if __name__ == "__main__":
    run_labeling()