import json
import os

# 🚨 단독으로 쓰였을 때 '절대' 개체명이 될 수 없는 단어들만 엄선
# '이사'나 '대표'처럼 본명/사명과 겹칠 수 있는 위험한 단어는 아예 제외했습니다.
STOP_WORDS = {
    "회장", "부회장", "사장", "부사장", "전무", "상무", "총수", "의장",
    "그룹", "회사", "기업", "법인", "지주회사", "계열사", "이사",
    "ceo", "cfo", "cto", "coo", "inc", "corp", "ltd", "llc", "company"
}

def clean_dictionary(input_filename, output_filename):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(current_dir, input_filename)
    output_path = os.path.join(current_dir, output_filename)

    if not os.path.exists(input_path):
        print(f"❌ 파일을 찾을 수 없습니다: {input_filename}")
        return

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cleaned_data = {}
    removed_count = 0

    # 비교 속도를 높이기 위해 소문자 set 사전 구성
    stop_words_lower = {w.lower() for w in STOP_WORDS}

    for rep_key, aliases in data.items():
        new_aliases = []
        for alias in aliases:
            # 공백을 제거한 단독 일치 비교 (예: " Inc " -> "inc" -> 매칭)
            alias_clean = alias.strip().lower()

            # 정확히 단독으로 일치하는 경우만 제외 (포함된 것은 유지)
            if alias_clean in stop_words_lower:
                # 💡 안전장치: 단독 일치하더라도 대표명(Key) 자체라면 지우지 않음
                if alias.strip() == rep_key.strip():
                    new_aliases.append(alias)
                else:
                    removed_count += 1
                continue

            # 포함된 단어("삼성그룹", "구글 LLC")는 필터를 통과하여 안전하게 보존됨
            new_aliases.append(alias)

        # 만약 모든 별칭이 지워졌다면 대표명이라도 넣어둠
        if not new_aliases:
            new_aliases = [rep_key]

        cleaned_data[rep_key] = new_aliases

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(cleaned_data, f, ensure_ascii=False, indent=4)

    print(f"✅ 클렌징 완료! ({input_filename} -> {output_filename})")
    print(f"🗑️ 정확히 단독 일치하여 삭제된 불필요한 별칭: {removed_count}개\n")


if __name__ == "__main__":
    # 안전하게 테스트해볼 수 있도록 출력 파일명을 분리했습니다.
    clean_dictionary('final_person_wiki.json', 'clean_person_wiki.json')
    clean_dictionary('final_company_wiki.json', 'clean_company_wiki.json')