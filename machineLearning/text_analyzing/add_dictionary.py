import json
import os
import time
from SPARQLWrapper import SPARQLWrapper, JSON

DATA_DIR = "dictionary"


# 💡 인물/기업에 맞춰 파일명을 인자로 받도록 수정합니다.
def get_file_paths(target_type):
    return (
        os.path.join(DATA_DIR, f"{target_type}.json"),
        os.path.join(DATA_DIR, f"last_page_{target_type}.txt")
    )


def get_last_page(checkpoint_file):
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, 'r') as f:
            content = f.read().strip()
            return int(content) if content else 0
    return 0


def save_last_page(page, checkpoint_file):
    with open(checkpoint_file, 'w') as f:
        f.write(str(page))


def load_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_data(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def add_entity(target_dict, canonical_name, new_aliases):
    existing = set(target_dict.get(canonical_name, []))
    combined = existing | set(new_aliases)
    target_dict[canonical_name] = sorted(list(combined))
    return target_dict


def run_scraper(target_type, query_template):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    data_file, checkpoint_file = get_file_paths(target_type)
    sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
    sparql.setTimeout(60)

    start_page = get_last_page(checkpoint_file)
    for page in range(start_page, start_page + 5):  # 5페이지씩 작업
        offset = page * 10
        print(f"\n🚀 [{target_type} | 페이지 {page + 1}] 시작 (OFFSET {offset})...")

        try:
            sparql.setQuery(query_template.format(offset=offset))
            sparql.setReturnFormat(JSON)
            results = sparql.query().convert()

            target_dict = load_data(data_file)
            count = 0
            for result in results["results"]["bindings"]:
                canonical_name = result["itemLabel"]["value"]
                alt_labels_str = result["altLabels"]["value"]
                alt_labels = alt_labels_str.split("|") if alt_labels_str else []
                new_aliases = [a.lower() for a in [canonical_name] + alt_labels if a]
                target_dict = add_entity(target_dict, canonical_name, new_aliases)
                count += 1

            save_data(target_dict, data_file)
            save_last_page(page + 1, checkpoint_file)
            print(f"✅ {target_type}: {count}건 처리 완료.")

        except Exception as e:
            print(f"⚠️ 요청 실패: {e}")
            break
        time.sleep(90)


if __name__ == "__main__":
    # 1. 인물 쿼리
    PERSON_QUERY = """SELECT ?itemLabel (GROUP_CONCAT(DISTINCT ?altLabel; separator="|") as ?altLabels) WHERE {{
      {{ ?item wdt:P106 wd:Q188094. }} UNION {{ ?item wdt:P106 wd:Q1676231. }}
      UNION {{ ?item wdt:P106 wd:Q11696. }} UNION {{ ?item wdt:P106 wd:Q661448. }}
      UNION {{ ?item wdt:P106 wd:Q188267. }}
      ?item rdfs:label ?itemLabel.
      OPTIONAL {{ ?item skos:altLabel ?altLabel . FILTER(LANG(?altLabel) = "en") }}
      FILTER(LANG(?itemLabel) = "en")
    }} GROUP BY ?itemLabel LIMIT 10 OFFSET {offset}"""

    # 2. 기업 쿼리
    COMPANY_QUERY = """SELECT ?itemLabel (GROUP_CONCAT(DISTINCT ?altLabel; separator="|") as ?altLabels) WHERE {{
      ?item wdt:P31 wd:Q4830485.
      ?item rdfs:label ?itemLabel.
      OPTIONAL {{ ?item skos:altLabel ?altLabel . FILTER(LANG(?altLabel) = "en") }}
      FILTER(LANG(?itemLabel) = "en")
    }} GROUP BY ?itemLabel LIMIT 10 OFFSET {offset}"""

    # 순차적으로 실행
    run_scraper("person", PERSON_QUERY)
    run_scraper("company", COMPANY_QUERY)