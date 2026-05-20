import json
import os


def sort_json(filename):
    if not os.path.exists(filename):
        # 여기가 안 뜨면 파일 경로를 못 찾는 겁니다.
        print(f"❌ [에러] 파일을 찾을 수 없습니다: {filename}")
        return

    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)

    sorted_items = sorted(
        data.items(),
        key=lambda item: (not item[0].startswith("candidate_"), item[0])
    )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write("{\n")
        for i, (key, value) in enumerate(sorted_items):
            list_str = json.dumps(value, ensure_ascii=False)
            line = f'  "{key}": {list_str}'
            if i < len(sorted_items) - 1:
                line += ","
            f.write(line + "\n")
        f.write("}")




if __name__ == "__main__":
    # 1. 파일의 절대 경로를 구합니다 (이게 가장 안전합니다)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.join(current_dir, 'dictionary')

    print(f"DEBUG: 현재 실행 스크립트 위치 -> {current_dir}")
    print(f"DEBUG: 탐색 중인 dictionary 폴더 -> {base_dir}")
    print(f"정렬 완료!")

    files = ["person.json", "company.json"]
    for file in files:
        full_path = os.path.join(base_dir, file)
        sort_json(full_path)