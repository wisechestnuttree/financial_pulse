import time
import json
import os
import numpy as np
import torch
from elasticsearch import Elasticsearch, helpers
from transformers import BertTokenizer, BertForSequenceClassification
from tqdm import tqdm

# === [ 설정 ] ===
ES_URL = "http://100.88.143.23:9200/"
TARGET_INDEX = "analyze"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
MAX_LEN = 256

es = Elasticsearch(ES_URL)

MODEL_CONFIGS = {
    "ko": "./model_news_ko",
    "en": "./model_news_en"
}


def load_inference_resources(lang):
    path = MODEL_CONFIGS[lang]
    if not os.path.exists(path):
        return None, None, None, None

    with open(f"{path}/model_version.json", "r", encoding="utf-8") as f:
        v_info = json.load(f)

    model_ver_name = v_info.get('model_name', 'unknown_v')
    classes = np.load(f"{path}/classes.npy", allow_pickle=True)
    tokenizer = BertTokenizer.from_pretrained(path)
    model = BertForSequenceClassification.from_pretrained(path).to(DEVICE)
    model.eval()
    return model, tokenizer, classes, model_ver_name


def predict(title, content, model, tokenizer, classes):
    text = f"{title} [SEP] {content}"
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=MAX_LEN,
        padding='max_length'
    ).to(DEVICE)

    with torch.no_grad():
        outputs = model(**inputs)
        idx = torch.argmax(outputs.logits, dim=1).item()

    # [추가] 사용이 끝난 텐서 명시적 삭제 및 메모리 확보
    del inputs, outputs
    return classes[idx]


def run_sector_sync():
    print("--- 분석 및 데이터 동기화 시작 ---")
    for lang in ["ko", "en"]:
        origin_index = f"news_{lang}"
        model, tokenizer, classes, model_ver_tag = load_inference_resources(lang)

        if model is None:
            print(f"[SKIP] {lang.upper()} 모델 경로가 없습니다.")
            continue

        # 전체 개수 확인 (tqdm total 설정을 위함)
        try:
            total_count = es.count(index=origin_index)['count']
        except:
            total_count = None

        # 원본 인덱스 스캔
        query = {
            "_source": ["title", "content"],
            "query": {"match_all": {}}
        }
        scan = helpers.scan(es, index=origin_index, query=query, size=200)

        actions = []
        # tqdm으로 실시간 진행 바 출력
        for doc in tqdm(scan, total=total_count, desc=f"Processing {lang.upper()}"):
            source = doc['_source']
            fixed_id = doc['_id']

            title = source.get('title', '')
            content = source.get('content', '')
            if not content: continue

            # 1. 섹터 예측
            pred_sector = predict(title, content, model, tokenizer, classes)

            # 2. 계층형 필드 구성 (Strict 매핑 완벽 대응)
            # 2. 계층형 필드 구성 (스키마 구조에 100% 매칭)
            update_doc = {
                "doc_id": fixed_id,
                "title": title,
                "lang": lang,
                "sector": pred_sector,

                # [핵심] 점(.) 표기법을 사용하면 다른 하위 필드(keywords 등)를 건드리지 않습니다.
                "model_ver.sector": model_ver_tag
            }

            actions.append({
                "_op_type": "update",
                "_index": TARGET_INDEX,
                "_id": fixed_id,
                "doc": update_doc,
                "doc_as_upsert": True
            })

            if len(actions) >= 200:
                helpers.bulk(es, actions)
                actions = []

        if actions:
            helpers.bulk(es, actions)

        print(f"[{lang.upper()}] 작업 완료")

    print("--- 모든 작업 완료 ---")


if __name__ == "__main__":
    start_time = time.time()
    run_sector_sync()
    end_time = time.time()
    print(f"소요 시간: {round(end_time - start_time, 2)}초")