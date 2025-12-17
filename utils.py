import streamlit as st
import json
import os
import re
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import google.generativeai as genai
import random
import time

# [상수] 등급 정의 및 표시명
ROLE_NAMES = {
    'GUEST': '유예생 (비회원)',
    'MEMBER': '공인회계사 (무료)',
    'PRO': '등록공인회계사 (유료)',
    'ADMIN': '관리자'
}

# [한글 폰트 설정] (Matplotlib)
import platform
system_name = platform.system()
font_path = "c:/Windows/Fonts/malgun.ttf" if system_name == 'Windows' else "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
if system_name == 'Darwin': font_path = "/System/Library/Fonts/AppleSDGothicNeo.ttc"

try:
    font_prop = fm.FontProperties(fname=font_path)
    plt.rc('font', family=font_prop.get_name())
except:
    pass 

def local_css():
    st.markdown("""
    <style>
        .stApp { background-color: #2E3440; color: #ECEFF4; }
        .card { background-color: #3B4252; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2); margin-bottom: 20px; border: 1px solid #434C5E; }
        h1, h2, h3, h4, h5, h6 { color: #ECEFF4 !important; }
        p, div, label, span { color: #D8DEE9 !important; }
        .metric-value { font-size: 2rem; font-weight: bold; color: #88C0D0; }
        .metric-label { font-size: 1rem; color: #D8DEE9; }
        .question-box { background-color: #434C5E; padding: 20px; border-radius: 10px; border-left: 5px solid #88C0D0; margin-bottom: 25px; font-size: 1.1rem; color: #ECEFF4; line-height: 1.6; }
        div.stButton > button { background-color: #5E81AC; color: #ECEFF4; border-radius: 8px; border: none; padding: 12px 24px; font-weight: 600; width: 100%; transition: all 0.3s ease; }
        div.stButton > button:hover { background-color: #81A1C1; color: #ffffff; box-shadow: 0 4px 12px rgba(94, 129, 172, 0.4); }
        .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] { background-color: #4C566A !important; color: #ECEFF4 !important; border: 1px solid #434C5E !important; }
    </style>
    """, unsafe_allow_html=True)

@st.cache_data(ttl=3600)
def load_structure():
    hierarchy, name_map, part_code_map, chapter_map = {}, {}, {}, {}
    current_part = None
    base_dir = os.path.dirname(os.path.abspath(__file__))
    structure_path = os.path.join(base_dir, 'data', 'references', 'structure.md')
    try:
        with open(structure_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                part_match = re.match(r'^##\s*(PART\s*\d+.*)', line, re.IGNORECASE)
                if part_match:
                    raw_part = part_match.group(1).strip()
                    raw_part = re.sub(r'^PART\s+(\d+)', r'PART\1', raw_part, flags=re.IGNORECASE)
                    short_p_match = re.match(r'^(PART\d+)', raw_part, re.IGNORECASE)
                    if short_p_match: part_code_map[short_p_match.group(1).upper()] = raw_part
                    current_part = raw_part
                    hierarchy[current_part] = {}
                    continue
                chapter_match = re.match(r'^-\s*\*\*(ch[\d~-]+.*?)\*\*:\s*(.+)', line, re.IGNORECASE)
                if chapter_match and current_part:
                    full_name = chapter_match.group(1).strip()
                    code_match = re.match(r'^(ch[\d~-]+)', full_name, re.IGNORECASE)
                    short_code = code_match.group(1).lower() if code_match else full_name
                    name_map[short_code] = full_name
                    hierarchy[current_part][short_code] = [s.strip() for s in chapter_match.group(2).split(',')]
                    
                    if '~' in short_code:
                        try:
                            prefix = re.match(r'^([a-zA-Z]+)', short_code).group(1)
                            rng = re.findall(r'\d+', short_code)
                            if len(rng) >= 2:
                                start, end = int(rng[0]), int(rng[1])
                                for i in range(start, end + 1):
                                    chapter_map[f"{prefix}{i}"] = short_code
                        except: pass
                    else:
                        chapter_map[short_code] = short_code
    except: pass
    return hierarchy, name_map, part_code_map, chapter_map

@st.cache_data(ttl=3600)
def load_db():
    data = []
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'data')
    try:
        _, _, part_code_map, chapter_map = load_structure()
        for filename in os.listdir(data_dir):
            if filename.startswith('questions_PART') and filename.endswith('.json'):
                file_path = os.path.join(data_dir, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    part_data = json.load(f)
                    data.extend(part_data)
        for q in data:
            p_str = str(q.get('part', ''))
            p_match = re.search(r'(?:PART\s*)?(\d+)', p_str, re.IGNORECASE)
            if p_match:
                part_num = f"PART{p_match.group(1)}"
                q['part'] = part_code_map.get(part_num, f"PART{p_match.group(1)}")
            c_str = str(q['chapter'])
            nums = re.findall(r'\d+', c_str)
            if nums:
                # chapter normalization
                match = re.search(r'(\d+(?:-\d+)?)', c_str)
                if match: 
                    raw_chap = f"ch{match.group(1)}"
                else: 
                    raw_chap = f"ch{nums[0]}"
                q['chapter'] = chapter_map.get(raw_chap, raw_chap)
            q['standard'] = str(q['standard'])
        return data
    except Exception as e:
        return []

@st.cache_data(ttl=3600)
def load_reference_text(standard_code):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "data", "references", f"{standard_code}.md")
    try:
        with open(file_path, "r", encoding="utf-8") as f: return f.read()
    except: return "참고 기준서 없음"

def get_counts(data):
    counts = { 'parts': {}, 'chapters': {}, 'standards': {} }
    for q in data:
        p, c, s = q.get('part', ''), q.get('chapter', ''), q.get('standard', '')
        if p: counts['parts'][p] = counts['parts'].get(p, 0) + 1
        if c: counts['chapters'][c] = counts['chapters'].get(c, 0) + 1
        if s: counts['standards'][s] = counts['standards'].get(s, 0) + 1
    return counts

def get_quiz_set(data, part, chapter, standard, num_questions, exclude_titles=None):
    if exclude_titles is None: exclude_titles = set()
    # Filter candidates first
    cand = [q for q in data 
            if q['part'] == part 
            and (chapter=="전체" or q['chapter']==chapter) 
            and (standard=="전체" or q['standard']==standard) 
            and q['question']['title'] not in exclude_titles]
    
    if not cand: return []
    if len(cand) <= num_questions: return cand
    return random.sample(cand, num_questions)

def get_chapter_sort_key(name):
    if name == "전체": return (-1,)
    nums = re.findall(r'\d+', name)
    return tuple(map(int, nums)) if nums else (999,)

def get_standard_sort_key(code):
    if code == "전체": return -1
    if code == "Ethics": return 100
    if code == "law": return 110
    try: return int(code)
    except: return 9999

def calculate_matched_count(user_ans, keywords):
    if not user_ans or not keywords: return 0
    user_ans_norm = user_ans.replace(' ', '').lower()
    return sum(1 for kw in keywords if kw.replace(' ', '').lower() in user_ans_norm)

def grade_with_ai_model(q_text, u_ans, a_data, std_code, api_key):
    if not u_ans or len(u_ans.strip()) < 2: return {"score": 0.0, "evaluation": "답안 미작성"}
    
    keywords = a_data.get('keywords', [])
    matched_count = calculate_matched_count(u_ans, keywords)
    
    if matched_count < 3:
        return {
            "score": 0.0, 
            "evaluation": f"📉 키워드가 부족합니다. (현재 {matched_count}개 / 최소 3개 필요)\n핵심 키워드를 포함하여 다시 작성해주세요."
        }
    
    # 기준서 참고 로직 제거 (사용자 요청: 모범답안 위주 채점 & 속도 향상)
    ref_text = "기준서 참고 생략 (모범답안 기준 채점)"

    # Retry Logic Configuration
    max_retries = 3
    base_delay = 2  # seconds

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')

        model_answer = a_data.get('model_answer', "")
        if isinstance(model_answer, list):
             model_answer_str = "\n".join(model_answer)
        else:
             model_answer_str = str(model_answer)

        sys_prompt = f"""
        당신은 회계감사 답안 채점관입니다. 
        사용자는 1차 키워드 검사(4개 이상 포함)를 통과했습니다.
        **제공된 모범답안**을 기준으로 사용자 답안을 평가하여 10점 만점으로 점수를 매기세요.
        (속도 향상을 위해 회계감사 기준서 원문 대조는 생략합니다.)

        [채점 기준: 전문용어 정밀성]
        1. **전문용어 사용 필수**: 모범답안상의 정확한 용어를 사용했는지 확인하십시오.
        2. **유의어 감점**: 의미가 통하더라도 '정확한 용어'가 아니면 감점하십시오.
        3. 문맥과 논리가 정확해야 합니다.
        4. 점수는 0점에서 10점 사이의 정수 점수입니다.

        [입력 데이터]
        - 문제: {q_text}
        - 사용자 답안: {u_ans}
        - 모범 답안: {model_answer_str}
        
        [출력 형식]
        반드시 마크다운 태그 없이 순수 **JSON 포맷**으로만 출력하시오.
        {{
            "score": 0 ~ 10 사이의 숫자,
            "feedback": "부족한 점: [내용]\\n\\n잘한 점: [내용] (100자 이내)"
        }}
        """
        
        for attempt in range(max_retries):
            try:
                res = model.generate_content(sys_prompt)
                ai_res = json.loads(res.text.replace('```json', '').replace('```', '').strip())
                
                final_score = float(ai_res.get('score', 0))
                final_eval = ai_res.get('feedback', '피드백 없음')
                
                return {"score": round(final_score, 1), "evaluation": final_eval}
            
            except Exception as e:
                if "504" in str(e) or "Deadline Exceeded" in str(e) or "429" in str(e):
                    if attempt < max_retries - 1:
                        time.sleep(base_delay * (2 ** attempt)) # Exponential backoff
                        continue
                raise e # Re-raise if not a retryable error or max retries reached

    except Exception as e: 
        return {"score": 0.0, "evaluation": f"AI 채점 실패: {str(e)}"}

def draw_target(score):
    fig, ax = plt.subplots(figsize=(4, 4))
    colors = ['white']*2 + ['black']*2 + ['blue']*2 + ['red']*2 + ['gold']*2
    for r, c in zip(range(10, 0, -1), colors):
        ax.add_artist(plt.Circle((0, 0), r, facecolor=c, edgecolor='gray', linewidth=0.5))
    base_dist = 10.0 - score
    angle = np.random.uniform(0, 2*np.pi)
    dist = max(0, base_dist + np.random.uniform(-0.1, 0.1))
    ax.plot(dist*np.cos(angle), dist*np.sin(angle), 'X', color='lime', markersize=10, markeredgecolor='black')
    ax.set_xlim(-11, 11); ax.set_ylim(-11, 11); ax.axis('off')
    return fig

def draw_skill_chart(stats):
    labels = list(stats.keys())
    values = list(stats.values())
    
    if not labels: return None

    if len(labels) < 3:
        fig, ax = plt.subplots(figsize=(5, 3))
        y_pos = np.arange(len(labels))
        ax.barh(y_pos, values, align='center', color='#88C0D0')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, color='#D8DEE9')
        ax.invert_yaxis()
        ax.set_xlabel('Score', color='#D8DEE9')
        ax.set_xlim(0, 10)
        
        ax.set_facecolor('#2E3440')
        fig.patch.set_facecolor('#2E3440')
        ax.spines['bottom'].set_color('#4C566A') 
        ax.spines['top'].set_color('#4C566A') 
        ax.spines['left'].set_color('#4C566A')
        ax.spines['right'].set_color('#4C566A')
        ax.tick_params(axis='x', colors='#D8DEE9')
        ax.tick_params(axis='y', colors='#D8DEE9')
        return fig

    num_vars = len(labels)
    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
    values += values[:1]
    angles += angles[:1]
    
    fig, ax = plt.subplots(figsize=(4, 4), subplot_kw=dict(polar=True))
    ax.fill(angles, values, color='#88C0D0', alpha=0.25)
    ax.plot(angles, values, color='#88C0D0', linewidth=2)
    ax.set_yticklabels([])
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, color='#ECEFF4')
    
    ax.spines['polar'].set_color('#4C566A')
    ax.grid(color='#4C566A', linestyle='--')
    ax.set_facecolor('#2E3440')
    fig.patch.set_facecolor('#2E3440')
    
    return fig
