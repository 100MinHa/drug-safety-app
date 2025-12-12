from flask import Flask, render_template, request, session, redirect, url_for
import requests
import os
import urllib.parse
from dotenv import load_dotenv

load_dotenv() 

# -------------------------- ⚠️ API 및 키 설정 ⚠️ --------------------------
SERVICE_KEY = os.environ.get('DRUG_API_KEY') 
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY') 
SEARCH_API_URL = "http://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList"

# -------------------------- ⚠️ 성분 매핑 사전 ⚠️ --------------------------
DRUG_INGREDIENT_MAP = {
    "타이레놀": "아세트아미노펜",
    "게보린": "이소프로필안티피린",
    "판콜에이": "아세트아미노펜",
    "아스피린": "아세틸살리실산",
    "이지엔6": "이부프로펜",
    "부루펜": "이부프로펜",
    "아세트아미노펜": "아세트아미노펜",
    "이부프로펜": "이부프로펜",
    "나프록센": "나프록센",
}
# ----------------------------------------------------------------------

# -------------------------- ⚠️ Flask 앱 설정 ⚠️ --------------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY 

if not SECRET_KEY:
    print("오류: FLASK_SECRET_KEY가 .env 파일에서 로드되지 않았습니다. 세션 기능(복용 약 저장)을 사용할 수 없습니다.")
# ----------------------------------------------------------------------


# --- 데이터 처리 헬퍼 함수 ---
def safe_extract(item, key):
    """API 응답 항목을 안전하게 추출하고, HTML 태그를 제거합니다."""
    value = item.get(key)
    if value is None or str(value).lower() in ('none', 'null', ''):
        return '정보 없음'
    # HTML 태그 (<p>, </p>) 제거
    return str(value).replace('<p>', '').replace('</p>', '').strip()


def extract_drug_info(item, search_term):
    """단일 API 응답 항목에서 정보 추출만 수행합니다. (성분 포함)"""
    drug_info = {
        "효과": safe_extract(item, 'efcyQesitm'),
        "투약량": safe_extract(item, 'useMethodQesitm'),
        "주의사항": safe_extract(item, 'atpnWarnQesitm'),
        "병용금기": safe_extract(item, 'intrcQesitm'),
        "성분": safe_extract(item, 'mainItemIngr'),
        "약품명": item.get('itemName', search_term),
        "itemSeq": item.get('itemSeq')
    }
    return drug_info


def perform_search(params, original_drug_name, multiple_results=False):
    """API 호출 및 데이터 추출을 수행하는 헬퍼 함수"""
    try:
        response = requests.get(SEARCH_API_URL, params=params)
        response.raise_for_status()
        
        try:
            search_data = response.json()
        except requests.exceptions.JSONDecodeError:
            print(f"API 오류: 응답이 유효한 JSON 형식이 아닙니다. 응답 시작: {response.text[:100]}...")
            return None 

        if search_data.get('header', {}).get('resultCode') not in ('00', '0') or \
           'body' not in search_data or 'items' not in search_data['body'] or not search_data['body']['items']:
            return None 
            
        items = search_data['body']['items']

        if multiple_results:
            result_list = []
            for item in items:
                result_list.append(extract_drug_info(item, original_drug_name))
            return result_list
        else:
            return [extract_drug_info(items[0], original_drug_name)]

    except Exception as e:
        print(f"API 호출 중 오류 발생: {e}")
        return None

# -------------------------- 🛑 디버깅 출력 포함 🛑 --------------------------
def search_drug_info(drug_name):
    
    if not SERVICE_KEY:
        print("오류: API 키(DRUG_API_KEY)가 .env 파일에서 로드되지 않았습니다.")
        return None

    encoded_drug_name = urllib.parse.quote(drug_name)

    # 1단계: itemName 검색
    params_item_name = {
        'serviceKey': SERVICE_KEY, 'itemName': encoded_drug_name, 'type': 'json', 'numOfRows': '3' 
    }
    drug_info_list = perform_search(params_item_name, drug_name, multiple_results=True)
    if drug_info_list:
        print(f"--- 1단계 (itemName) 검색 성공: {len(drug_info_list)}개 결과 ---")
        print("\n=== [1단계] API 병용금기 정보 전문 디버깅 시작 ===")
        for i, info in enumerate(drug_info_list):
            print(f"--- 결과 {i+1} ({info['약품명']})의 병용금기 정보 ---")
            print(f"정보: {info['병용금기']}")
        print("=== API 병용금기 정보 디버깅 종료 ===\n")
        return drug_info_list

    # 2단계: ingrName 검색
    params_ingr_name = {
        'serviceKey': SERVICE_KEY, 'ingrName': encoded_drug_name, 'type': 'json', 'numOfRows': '3'
    }
    drug_info_list = perform_search(params_ingr_name, drug_name, multiple_results=True)
    if drug_info_list:
        print(f"--- 2단계 (ingrName) 검색 성공: {len(drug_info_list)}개 결과 ---")
        print("\n=== [2단계] API 병용금기 정보 전문 디버깅 시작 ===")
        for i, info in enumerate(drug_info_list):
            print(f"--- 결과 {i+1} ({info['약품명']})의 병용금기 정보 ---")
            print(f"정보: {info['병용금기']}")
        print("=== API 병용금기 정보 디버깅 종료 ===\n")
        return drug_info_list
    
    return None

# -------------------------- 🛑 병용금기 경고 로직 (강조 포함) 🛑 --------------------------

def check_contraindications(searched_drug_info_list, my_drugs):
    """
    등록된 약품명과 매핑된 성분명 키워드를 모두 사용하여 병용금기 정보를 검증하고,
    충돌 키워드를 강조하여 반환합니다.
    (my_drugs는 이제 딕셔너리 리스트입니다.)
    """
    warnings = []
    
    if not my_drugs:
        return warnings

    my_drug_keywords = set()
    for drug_item in my_drugs:
        drug_name = drug_item.get('name', '').lower()
        ingredient = drug_item.get('ingredient', '').lower()
        
        if drug_name:
             my_drug_keywords.add(drug_name)
        if ingredient != '성분 정보 없음':
             my_drug_keywords.add(ingredient)
    
    
    for searched_drug in searched_drug_info_list:
        
        contra_info_original = searched_drug['병용금기'] 
        contra_info_lower = contra_info_original.lower().strip() 
        
        if contra_info_lower == '정보 없음':
            continue

        for keyword in my_drug_keywords:
            if keyword in contra_info_lower:
                
                # 충돌이 발생한 약품명 또는 성분명 (UX 표시용)
                conflict_drug_name = keyword.capitalize()
                
                # 만약 성분 이름이라면, 표시 포맷을 변경
                if keyword in [v.lower() for v in DRUG_INGREDIENT_MAP.values()]:
                    conflict_drug_name = f"등록된 약 (성분: {keyword.upper()})"
                
                highlighted_info = contra_info_original
                
                # HTML 강조 적용 (대소문자 무시하면서 원본 보존)
                try:
                    start_index = contra_info_lower.index(keyword)
                    end_index = start_index + len(keyword)
                    
                    original_keyword = contra_info_original[start_index:end_index]
                    
                    highlighted_info = highlighted_info[:start_index] + f'<b>{original_keyword}</b>' + highlighted_info[end_index:]
                except ValueError:
                    pass


                warnings.append({
                    "searched_drug": searched_drug['약품명'],
                    "conflict_drug": conflict_drug_name,
                    "info": highlighted_info 
                })
                break 
    
    return warnings

# -------------------------- 🗺️ 라우팅 함수 🗺️ --------------------------

@app.route('/add_drug', methods=['POST'])
def add_drug():
    """사용자가 입력한 약을 세션에 저장합니다. (딕셔너리 리스트로 변경)"""
    
    raw_drug_input = request.form.get('my_drug_name')
    drug_to_add = raw_drug_input.strip() if raw_drug_input else ""
    
    if 'my_drugs' not in session:
        session['my_drugs'] = []
    
    if drug_to_add:
        # 성분 찾기: 맵에 없으면 '성분 정보 없음'으로 저장
        ingredient = DRUG_INGREDIENT_MAP.get(drug_to_add.capitalize(), "성분 정보 없음")
        
        new_drug_item = {
            "name": drug_to_add.capitalize(),
            "ingredient": ingredient
        }
        
        # 중복 체크: 이름만으로 중복 체크
        current_drugs_lower = [d['name'].lower() for d in session['my_drugs']]
        
        if new_drug_item['name'].lower() not in current_drugs_lower:
            session['my_drugs'].append(new_drug_item) 
            session.modified = True 
            
    return redirect(url_for('index'))

@app.route('/remove_drug/<drug_name>')
def remove_drug(drug_name):
    """세션에서 특정 약을 삭제합니다. (딕셔너리 리스트 처리로 변경)"""
    
    decoded_drug_name = urllib.parse.unquote(drug_name)
    
    if 'my_drugs' in session:
        # 이름으로 딕셔너리 찾아서 제거
        session['my_drugs'] = [
            d for d in session['my_drugs'] 
            if d['name'].lower() != decoded_drug_name.lower()
        ]
        session.modified = True 
    
    return redirect(url_for('index'))

@app.route('/clear_drugs')
def clear_drugs():
    """⚠️ 복용 약 목록 전체 초기화"""
    if 'my_drugs' in session:
        session.pop('my_drugs', None)
        session.modified = True
    return redirect(url_for('index'))


@app.route('/', methods=['GET', 'POST'])
def index():
    drug_name = None
    drug_info_list = None 
    warnings = [] 

    # my_drugs는 이제 [{'name': '타이레놀', 'ingredient': '아세트아미노펜'}, ...] 형태
    my_drugs = session.get('my_drugs', [])

    if request.method == 'POST':
        search_term = request.form.get('drug_name')
        
        if search_term:
            drug_name = search_term 
            drug_info_list = search_drug_info(search_term) 
            
            if drug_info_list:
                warnings = check_contraindications(drug_info_list, my_drugs)
            
    return render_template('index.html', 
                           drug_name=drug_name, 
                           drug_info_list=drug_info_list,
                           my_drugs=my_drugs,         
                           warnings=warnings)         


if __name__ == '__main__':
    app.run(debug=True)