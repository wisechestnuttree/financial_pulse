import pandas as pd
import torch
import os
import numpy as np
import json
from datetime import datetime
from torch.utils.data import Dataset, DataLoader
from transformers import BertTokenizer, BertForSequenceClassification
from torch.optim import AdamW
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from tqdm import tqdm

# === [ 1. 공통 설정 ] ===
MAX_LEN = 256
BATCH_SIZE = 16
EPOCHS = 3
LEARNING_RATE = 2e-5
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

configs = [
    {
        "lang": "ko",
        "model_name": "klue/bert-base",
        "csv_path": "train_data_ko_5000.csv",
        "save_path": "./model_news_ko"
    },
    {
        "lang": "en",
        "model_name": "bert-base-uncased",
        "csv_path": "train_data_en_5000.csv",
        "save_path": "./model_news_en"
    }
]


# === [ 2. 데이터셋 클래스 ] ===
class NewsDataset(Dataset):
    def __init__(self, texts, labels, tokenizer, max_len):
        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self): return len(self.texts)

    def __getitem__(self, i):
        encoding = self.tokenizer(
            str(self.texts[i]),
            add_special_tokens=True,
            max_length=self.max_len,
            padding='max_length',
            truncation=True,
            return_tensors='pt'
        )
        return {
            'input_ids': encoding['input_ids'].flatten(),
            'attention_mask': encoding['attention_mask'].flatten(),
            'labels': torch.tensor(self.labels[i], dtype=torch.long)
        }


# === [ 3. 버전 관리 함수 ] ===
def get_next_version_info(save_path):
    """기존 JSON의 model_name(sector_vX)을 읽어 다음 버전을 계산"""
    version_file = os.path.join(save_path, "model_version.json")

    if not os.path.exists(version_file):
        return "sector_v1"

    try:
        with open(version_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            # "sector_v1"에서 숫자 부분만 추출하여 +1
            current_model_name = data.get("model_name", "sector_v0")
            current_ver = int(current_model_name.split('_v')[-1])
            next_ver = current_ver + 1
            return f"sector_v{next_ver}"
    except Exception as e:
        print(f"⚠️ 버전 읽기 실패(새로 시작): {e}")
        return "sector_v1"


# === [ 4. 학습 메인 함수 ] ===
def train_model(config):
    if not os.path.exists(config['save_path']):
        os.makedirs(config['save_path'])

    # 차기 모델 버전 명칭 결정
    model_display_name = get_next_version_info(config['save_path'])

    print(f"\n🚀 [{config['lang'].upper()}] 학습 시작")
    print(f"📂 경로: {config['save_path']} | 🏷️ 적용될 모델명: {model_display_name}")

    if not os.path.exists(config['csv_path']):
        print(f"❌ 파일 없음: {config['csv_path']}, 건너뜁니다.")
        return

    # 1. 데이터 로드 및 라벨링
    df = pd.read_csv(config['csv_path'])
    df['text'] = df['title'].fillna('') + " [SEP] " + df['content'].fillna('')

    le = LabelEncoder()
    df['label'] = le.fit_transform(df['sector'].fillna('기타'))
    num_labels = len(le.classes_)

    # 인퍼런스 시 사용할 클래스 정보 저장
    np.save(f"{config['save_path']}/classes.npy", le.classes_)

    # 2. 토크나이저 및 데이터 준비
    tokenizer = BertTokenizer.from_pretrained(config['model_name'])
    train_texts, val_texts, train_labels, val_labels = train_test_split(
        df['text'].tolist(), df['label'].tolist(), test_size=0.1, stratify=df['label'], random_state=42
    )

    train_loader = DataLoader(
        NewsDataset(train_texts, train_labels, tokenizer, MAX_LEN),
        batch_size=BATCH_SIZE,
        shuffle=True
    )

    # 3. 모델 구축
    model = BertForSequenceClassification.from_pretrained(config['model_name'], num_labels=num_labels).to(DEVICE)
    optimizer = AdamW(model.parameters(), lr=LEARNING_RATE)

    # 4. 학습 루프
    for epoch in range(EPOCHS):
        model.train()
        progress_bar = tqdm(train_loader, desc=f"{model_display_name} Epoch {epoch + 1}/{EPOCHS}")
        for batch in progress_bar:
            optimizer.zero_grad()
            input_ids = batch['input_ids'].to(DEVICE)
            attention_mask = batch['attention_mask'].to(DEVICE)
            labels = batch['labels'].to(DEVICE)

            outputs = model(input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs.loss
            loss.backward()
            optimizer.step()
            progress_bar.set_postfix({'loss': f"{loss.item():.4f}"})

    # 5. 모델 저장 및 버전 파일 생성
    model.save_pretrained(config['save_path'])
    tokenizer.save_pretrained(config['save_path'])

    version_info = {
        "model_name": model_display_name,
        "train_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "classes": le.classes_.tolist()
    }

    with open(f"{config['save_path']}/model_version.json", "w", encoding="utf-8") as f:
        json.dump(version_info, f, ensure_ascii=False, indent=4)

    print(f"🎯 [{config['lang'].upper()}] {model_display_name} 저장 완료!\n")

    # 메모리 정리
    del model
    torch.cuda.empty_cache()


# === [ 5. 실행 ] ===
if __name__ == "__main__":
    if torch.cuda.is_available():
        print(f"✅ GPU 사용 중: {torch.cuda.get_device_name(0)}")

    for cfg in configs:
        train_model(cfg)

    print("\n✨ 모든 언어 모델의 학습 및 버전 업데이트가 완료되었습니다!")