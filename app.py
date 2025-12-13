import streamlit as st
import concurrent.futures
import json
import random
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import google.generativeai as genai
import re
import database
import pandas as pd
import time
from streamlit_option_menu import option_menu

# [설정] 기본 설정
st.set_page_config(page_title="회계감사 랭크", page_icon="🏹", layout="wide")

# [상수] 등급 정의 및 표시명
ROLE_NAMES = {
    'GUEST': '유예생 (비회원)',
    'MEMBER': '공인회계사 (무료)',
    'PRO': '등록공인회계사 (유료)',
    'ADMIN': '관리자'
}

# [한글 폰트 설정] (Matplotlib)
# 시스템에 설치된 폰트 중 하나를 선택 (Windows: Malgun Gothic, Mac: AppleGothic, Linux: NanumGothic)
import platform
system_name = platform.system()
if system_name == 'Windows':
    font_path = "c:/Windows/Fonts/malgun.ttf"
elif system_name == 'Darwin':
    font_path = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
else:
    # Linux/Streamlit Cloud 환경 대비 (나눔고딕 설치 가정)
    font_path = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"

# 폰트가 없을 경우 기본 폰트 사용 (한글 깨짐 방지용 폰트 설정은 환경에 따라 추가 조치 필요)
try:
    font_prop = fm.FontProperties(fname=font_path)
    plt.rc('font', family=font_prop.get_name())
except:
    pass # 폰트 파일을 찾지 못하면 기본값 사용

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

local_css()

# --- 데이터 로드 함수 (기존과 동일) ---
def load_db():
    data = []
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
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
                match = re.search(r'(\d+(?:-\d+)?)', c_str)
                if match: 
                    raw_chap = f"ch{match.group(1)}"
                else: 
                    raw_chap = f"ch{nums[0]}"
                q['chapter'] = chapter_map.get(raw_chap, raw_chap)
            q['standard'] = str(q['standard'])
        return data
    except Exception as e:
        st.error(f"데이터 로드 중 오류: {str(e)}")
        return []

def load_reference_text(standard_code):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "data", "references", f"{standard_code}.md")
    try:
        with open(file_path, "r", encoding="utf-8") as f: return f.read()
    except: return "참고 기준서 없음"

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
                    
                    # [Mapping] ch1~2 -> {ch1: ch1~2, ch2: ch1~2}
                    if '~' in short_code:
                        try:
                            # ch1~2 -> prefix='ch', start=1, end=2
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
    cand = [q for q in data if q['part'] == part and (chapter=="전체" or q['chapter']==chapter) and (standard=="전체" or q['standard']==standard) and q['question']['title'] not in exclude_titles]
    if not cand: return [] # 문제 없음
    if len(cand) <= num_questions: return cand
    return random.sample(cand, num_questions)

def get_chapter_sort_key(name):
    if name == "전체": return (-1,)
    nums = re.findall(r'\d+', name)
    return tuple(map(int, nums)) if nums else (999,)

def get_standard_sort_key(code):
    if code == "전체": return -1
    try: return int(code)
    except: return 9999

# --- 채점 관련 함수 ---
def calculate_matched_count(user_ans, keywords):
    if not user_ans or not keywords: return 0
    # 띄어쓰기 무시를 위해 공백 제거 후 비교
    user_ans_norm = user_ans.replace(' ', '').lower()
    return sum(1 for kw in keywords if kw.replace(' ', '').lower() in user_ans_norm)

def grade_with_ai_model(q_text, u_ans, a_data, std_code, api_key):
    if not u_ans or len(u_ans.strip()) < 2: return {"score": 0.0, "evaluation": "답안 미작성"}
    
    # 1. [1차 채점] 키워드 개수 확인 (4개 이상)
    keywords = a_data.get('keywords', [])
    matched_count = calculate_matched_count(u_ans, keywords)
    
    if matched_count < 3:
        return {
            "score": 0.0, 
            "evaluation": f"📉 키워드가 부족합니다. (현재 {matched_count}개 / 최소 3개 필요)\n핵심 키워드를 포함하여 다시 작성해주세요."
        }
    
    # [Context Optimization] 키워드 매칭률에 따라 기준서 로드 여부 결정 (채점 점수에는 영향 X)
    ratio = matched_count / len(keywords) if keywords else 0
    if ratio >= 0.5:
        ref_text = "기준서 참고 생략 (키워드 매칭률 50% 이상 - 사용자 지식 충분)"
    else:
        try:
            raw_ref_text = load_reference_text(std_code)
            ref_text = raw_ref_text[:50000] if raw_ref_text else "관련 기준서 내용 없음"
        except Exception:
            ref_text = "기준서 로드 실패"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')

        model_answer = a_data.get('model_answer', "")
        if isinstance(model_answer, list):
             model_answer_str = "\n".join(model_answer)
        else:
             model_answer_str = str(model_answer)

        # 2. [2차 채점] AI 100% 채점 (10점 만점)
        sys_prompt = f"""
        당신은 회계감사 답안 채점관입니다. 
        사용자는 1차 키워드 검사(4개 이상 포함)를 통과했습니다.
        제공된 모범답안 또는 회계감사 기준서를 기준으로 사용자 답안을 평가하여 10점 만점으로 점수를 매기세요.

        [채점 기준: 전문용어 정밀성]
        1. **전문용어 사용 필수**: 모범답안 또는 기준서상의 정확한 용어를 사용했는지 엄격하게 확인하십시오.
        2. **유의어 감점**: 의미가 통하더라도 '정확한 용어'가 아니면 감점하십시오. (예: '중요한 왜곡표시' 대신 '돈 오류'라고 쓰면 감점)
        3. 문맥과 논리가 정확해야 합니다.
        4. 점수는 0점에서 10점 사이의 정수 점수입니다.

        [입력 데이터]
        - 문제: {q_text}
        - 사용자 답안: {u_ans}
        - 모범 답안: {model_answer_str}
        - 회계감사 기준서: {ref_text}

        [출력 형식]
        반드시 마크다운 태그 없이 순수 **JSON 포맷**으로만 출력하시오.
        {{
            "score": 0 ~ 10 사이의 숫자,
            "feedback": "부족한 점: [내용]\\n\\n잘한 점: [내용] (100자 이내)"
        }}
        """
        res = model.generate_content(sys_prompt)
        ai_res = json.loads(res.text.replace('```json', '').replace('```', '').strip())
        
        # Pure AI Score
        final_score = float(ai_res.get('score', 0))
        final_eval = ai_res.get('feedback', '피드백 없음')
        
        return {"score": round(final_score, 1), "evaluation": final_eval}
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
    """스킬 분석 차트 (데이터 개수에 따라 Radar 또는 Bar)"""
    labels = list(stats.keys())
    values = list(stats.values())
    
    if not labels: return None

    # 데이터가 3개 미만이면 Horizontal Bar Chart
    if len(labels) < 3:
        fig, ax = plt.subplots(figsize=(5, 3))
        y_pos = np.arange(len(labels))
        ax.barh(y_pos, values, align='center', color='#88C0D0')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, color='#D8DEE9')
        ax.invert_yaxis()  # labels read top-to-bottom
        ax.set_xlabel('Score', color='#D8DEE9')
        ax.set_xlim(0, 10)
        
        # Style
        ax.set_facecolor('#2E3440')
        fig.patch.set_facecolor('#2E3440')
        ax.spines['bottom'].set_color('#4C566A')
        ax.spines['top'].set_color('#4C566A') 
        ax.spines['left'].set_color('#4C566A')
        ax.spines['right'].set_color('#4C566A')
        ax.tick_params(axis='x', colors='#D8DEE9')
        ax.tick_params(axis='y', colors='#D8DEE9')
        return fig

    # Radar Chart
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
    
    # Style
    ax.spines['polar'].set_color('#4C566A')
    ax.grid(color='#4C566A', linestyle='--')
    ax.set_facecolor('#2E3440')
    fig.patch.set_facecolor('#2E3440')
    
    return fig

# --- 화면 렌더링 함수 ---

def render_curriculum(db_data):
    st.title("📚 학습 커리큘럼")
    hierarchy, name_map, _, _ = load_structure()
    
    # Efficient Lookup Map
    # map[part][chapter][standard] = [questions...]
    content_map = {}
    for q in db_data:
        p = q.get('part', 'Unknown')
        c = q.get('chapter', 'Unknown')
        s = str(q.get('standard', 'Unknown'))
        
        if p not in content_map: content_map[p] = {}
        if c not in content_map[p]: content_map[p][c] = {}
        if s not in content_map[p][c]: content_map[p][c][s] = []
        content_map[p][c][s].append(q)

    # 렌더링
    for part in sorted(hierarchy.keys()):
        # Part Expander
        with st.expander(f"📌 {part}", expanded=False):
            # Sort Chapters (ch1, ch2...)
            chapters = sorted(hierarchy[part].keys(), key=get_chapter_sort_key)
            
            for ch in chapters:
                st.markdown(f"### {name_map.get(ch, ch)}")
                
                # Standards in this chapter
                standards = hierarchy[part][ch]
                
                for std in standards:
                    # Fetch questions for this P-C-S
                    questions = content_map.get(part, {}).get(ch, {}).get(std, [])
                    
                    st.markdown(f"**기준서 {std}** ({len(questions)} 문제)")
                    
                    if not questions:
                        st.caption("   (등록된 핵심 문제 없음)")

def render_ranking():
    st.title("🏆 랭킹 (Leaderboard)")
    df = database.get_leaderboard_data()
    if not df.empty:
        # 등급 표시명 변환
        # 등급 표시명 변환
        df['role'] = df['role'].map(ROLE_NAMES).fillna(df['role'])
        # 컬럼명 한글 변환 for better UX
        df = df.rename(columns={'username': '이름', 'role': '등급', 'level': '레벨', 'exp': '경험치'})
        st.dataframe(df[['이름', '등급', '레벨', '경험치']], use_container_width=True, hide_index=True)
    else:
        st.info("랭킹 데이터가 없습니다.")

def render_profile(db_data):
    st.title("📊 학습 대시보드 (Dashboard)")
    username = st.session_state.username
    role = st.session_state.user_role
    
    # [권한 체크] 유예생/공인회계사(비/무료)는 일부 기능 제한
    is_paid_or_admin = role in ['PRO', 'ADMIN']
    
    # 통계 데이터 로드
    stats = database.get_user_stats(username)
    df_all = database.get_user_history_df(username)
    
    # 1. 헤더 섹션 (Header)
    c_profile, c_metrics = st.columns([1, 2])
    
    with c_profile:
        st.markdown(f"""
        <div style="background-color: #3B4252; padding: 20px; border-radius: 12px; border: 1px solid #434C5E; text-align: center;">
            <img src="https://api.dicebear.com/7.x/avataaars/svg?seed={username}" width="100" style="border-radius: 50%; margin-bottom: 10px;">
            <div style="font-size: 1.5rem; font-weight: bold; color: #ECEFF4;">{username}</div>
            <div style="font-size: 0.9rem; color: #D8DEE9; margin-bottom: 5px;">{ROLE_NAMES.get(role, role)}</div>
            <div style="background-color: #5E81AC; color: white; padding: 4px 12px; border-radius: 15px; display: inline-block; font-size: 0.8rem;">
                Lv. {st.session_state.level}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
    with c_metrics:
        # 주요 지표 계산
        total_xp = stats['total_score']
        total_solved = len(df_all) if not df_all.empty else 0
        
        # XP Progress (단순화: 레벨당 100XP 가정)
        current_level_xp = total_xp % 100
        progress_pct = int(current_level_xp)
        
        st.markdown(f"""
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
            <div style="background-color: #3B4252; padding: 15px; border-radius: 10px; border: 1px solid #434C5E;">
                <div style="color: #D8DEE9; font-size: 0.9rem;">Total XP</div>
                <div style="color: #88C0D0; font-size: 1.8rem; font-weight: bold;">{total_xp:.0f}</div>
                <div style="width: 100%; background-color: #4C566A; height: 6px; border-radius: 3px; margin-top: 5px;">
                    <div style="width: {progress_pct}%; background-color: #88C0D0; height: 6px; border-radius: 3px;"></div>
                </div>
                <div style="text-align: right; font-size: 0.7rem; color: #D8DEE9; margin-top: 2px;">{progress_pct}% to Lv.{st.session_state.level+1}</div>
            </div>
            <div style="background-color: #3B4252; padding: 15px; border-radius: 10px; border: 1px solid #434C5E;">
                <div style="color: #D8DEE9; font-size: 0.9rem;">Questions Solved</div>
                <div style="color: #ECEFF4; font-size: 1.8rem; font-weight: bold;">{total_solved}</div>
            </div>
            <div style="background-color: #3B4252; padding: 15px; border-radius: 10px; border: 1px solid #434C5E;">
                <div style="color: #D8DEE9; font-size: 0.9rem;">Status</div>
                <div style="color: #EBCB8B; font-size: 1.8rem; font-weight: bold;">Active</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.write("")
    st.write("")

    # 2. 탭 콘텐츠
    tab_dash, tab_notes, tab_hist = st.tabs(["📊 분석 & 차트", "📝 오답 노트", "📜 전체 이력"])

    with tab_dash:
        if df_all.empty:
            st.info("아직 데이터가 충분하지 않습니다. 문제를 풀어보세요!")
        else:
            # 매핑 준비
            std_map = {}
            for q in db_data:
                std_map[q['standard']] = {'part': q['part'], 'chapter': q['chapter']}
            
            df_all['part'] = df_all['standard_code'].map(lambda x: std_map.get(x, {}).get('part', 'Unknown'))
            df_all['chapter'] = df_all['standard_code'].map(lambda x: std_map.get(x, {}).get('chapter', 'Unknown'))
            
            c_chart1, c_chart2 = st.columns(2)
            
            with c_chart1:
                st.subheader("🎯 영역별 강점 분석 (Skill Analysis)")
                # Part별 평균 점수 산출
                part_scores = df_all.groupby('part')['score'].mean().to_dict()
                fig_skill = draw_skill_chart(part_scores)
                if fig_skill: st.pyplot(fig_skill, use_container_width=True)
                else: st.info("데이터 부족")
                
            with c_chart2:
                st.subheader("📅 최근 성취도")
                # 최근 10개 추이 line chart
                recent_df = df_all.sort_values("created_at").tail(10)
                st.line_chart(recent_df, x='created_at', y='score', color='#5E81AC')
            
            # 약점 분석
            st.subheader("💊 집중 보완이 필요한 챕터 (Weakest Chapters)")
            chap_avg = df_all.groupby('chapter')['score'].mean().sort_values().head(3)
            for ch, sc in chap_avg.items():
                st.markdown(f"- **{ch}**: 평균 {sc:.1f}점")

    with tab_notes:
        if not is_paid_or_admin:
            st.warning("🔒 오답 노트는 '등록공인회계사(유료회원)' 전용 기능입니다.")
        else:
            notes_df = database.get_user_review_notes(username)
            if notes_df.empty:
                st.info("오답 노트가 비어있습니다.")
            else:
                # [Group by Part -> Chapter]
                # 1. Sort for consistent display
                notes_df['part'] = notes_df['part'].fillna('Unknown')
                notes_df['chapter'] = notes_df['chapter'].fillna('Unknown')
                
                # Hierarchy: Part -> Chapter -> Question
                # Get unique parts
                parts = sorted(notes_df['part'].unique())
                
                for part in parts:
                    with st.expander(f"📂 {part}", expanded=False):
                        part_df = notes_df[notes_df['part'] == part]
                        chapters = sorted(part_df['chapter'].unique(), key=get_chapter_sort_key)
                        
                        for chap in chapters:
                            st.markdown(f"**[{chap}]**")
                            chap_df = part_df[part_df['chapter'] == chap]
                            
                            for idx, row in chap_df.iterrows():
                                # Model Answer formatting
                                m_ans = row['model_answer']
                                if not m_ans: m_ans = "데이터 없음"
                                
                                # Check if it's a list string representation or just string
                                if isinstance(m_ans, list):
                                     m_ans_str = "• " + "<br>• ".join(m_ans)
                                elif isinstance(m_ans, str) and m_ans.startswith('['):
                                     # Try parsing if it looks like a list
                                     try:
                                         parsed = json.loads(m_ans.replace("'", '"'))
                                         if isinstance(parsed, list):
                                             m_ans_str = "• " + "<br>• ".join(parsed)
                                         else:
                                             m_ans_str = str(m_ans).replace('\n', '<br>')
                                     except:
                                         m_ans_str = str(m_ans).replace('\n', '<br>')
                                else:
                                     m_ans_str = str(m_ans).replace('\n', '<br>')

                                with st.expander(f"[{row['standard_code']}] {row['title']} (점수: {row['score']})"):
                                    st.markdown(f"**Q. {row['question']}**")
                                    st.markdown(f"**내 답안:** {row['explanation']}")
                                    st.markdown(f"<div style='background-color:#2E3440; padding:10px; border-radius:5px; margin-top:5px;'>✅ {m_ans_str}</div>", unsafe_allow_html=True)
                                    st.caption(f"작성일: {row['created_at']}")
                                    if st.button("삭제", key=f"del_note_{row['id']}"):
                                        database.delete_review_note(row['id'])
                                        st.rerun()

    with tab_hist:
        if df_all.empty:
            st.info("기록이 없습니다.")
        else:
            st.dataframe(df_all[['standard_code', 'score', 'created_at']].sort_values('created_at', ascending=False), use_container_width=True, hide_index=True)

def render_admin():
    st.title("🛠️ 관리자 페이지")
    
    st.subheader("회원 관리")
    users = database.get_all_users()
    
    # 데이터프레임 표시 (비밀번호 제외)
    st.dataframe(users[['username', 'role', 'level', 'exp', 'created_at']], use_container_width=True)
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        target_user = st.selectbox("등급 변경 대상", users['username'].unique())
    with c2:
        new_role = st.selectbox("변경할 등급", list(ROLE_NAMES.keys()))
        
    if st.button("등급 변경 적용"):
        if target_user == '준영2':
            st.error("최고 관리자의 등급은 변경할 수 없습니다.")
        else:
            database.update_user_role(target_user, new_role)
            st.success(f"{target_user}님의 등급이 {ROLE_NAMES[new_role]}로 변경되었습니다.")
            time.sleep(1)
            st.rerun()

def render_quiz(db_data):
    st.title("📝 실전 훈련")
    user_role = st.session_state.user_role
    
    if st.session_state.app_state == 'SETUP':
        # [설정]
        hierarchy, name_map, _, _ = load_structure()
        counts = get_counts(db_data)
        
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1: 
            # Part: 이름 + (개수)
            def fmt_part(x):
                return f"{x} ({counts['parts'].get(x, 0)})"
            sel_part = st.selectbox("Part", sorted(list(hierarchy.keys())), format_func=fmt_part)
            
        with c2: 
            # Chapter: Full Name + (개수)
            chap_opts = ["전체"] + sorted(list(hierarchy[sel_part].keys()), key=get_chapter_sort_key)
            def fmt_chap(x):
                if x == "전체": return "전체"
                return f"{name_map.get(x, x)} ({counts['chapters'].get(x, 0)})"
            sel_chap = st.selectbox("Chapter", chap_opts, format_func=fmt_chap)
            
        with c3:
            # Standard: 번호 + (개수)
            if sel_chap == "전체":
                stds = set()
                for c in hierarchy[sel_part]: stds.update(hierarchy[sel_part][c])
                std_opts = ["전체"] + sorted(list(stds), key=get_standard_sort_key)
            else:
                std_opts = ["전체"] + sorted(hierarchy[sel_part][sel_chap], key=get_standard_sort_key)
                
            def fmt_std(x):
                if x == "전체": return "전체"
                return f"{x} ({counts['standards'].get(x, 0)})"
            sel_std = st.selectbox("Standard", std_opts, format_func=fmt_std)
            
        # [난이도 접근 제어]
        st.write("")
        st.subheader("난이도 선택")
        
        diff_levels = {
            "초급 (1문제)": 1,
            "중급 (3문제)": 3,
            "고급 (5문제)": 5
        }
        
        if user_role == 'ADMIN':
            diff_levels["전체 (All)"] = 9999
        
        # 권한에 따른 옵션 활성화/비활성화
        # GUEST/MEMBER: 중급까지만 가능
        # PRO/ADMIN: 모두 가능
        
        options = list(diff_levels.keys())
        if user_role in ['GUEST', 'MEMBER']:
            st.info(f"💡 현재 등급({ROLE_NAMES[user_role]})은 '중급'까지만 선택 가능합니다.")
            selectable_options = options[:2] # 초급, 중급
        else:
            selectable_options = options # 전체
            
        sel_diff = st.selectbox("문항 수", selectable_options)
        
        if st.button("훈련 시작 🚀", type="primary", use_container_width=True):
            cnt = diff_levels[sel_diff]
            quiz_list = get_quiz_set(db_data, sel_part, sel_chap, sel_std, cnt, st.session_state.solved_questions)
            if not quiz_list:
                st.error("해당 조건의 문제가 없습니다. (또는 이미 모든 문제를 풀었습니다.)")
            else:
                st.session_state.quiz_list = quiz_list
                st.session_state.answers = {q['question']['title']: "" for q in quiz_list}
                st.session_state.app_state = 'SOLVING'
                # [설정 저장] 추가 풀기를 위해 현재 설정 저장
                st.session_state.last_quiz_params = {
                    'part': sel_part,
                    'chapter': sel_chap,
                    'standard': sel_std,
                    'count': cnt
                }
                st.rerun()

    elif st.session_state.app_state == 'SOLVING':
        with st.form("ans_form"):
            for idx, q in enumerate(st.session_state.quiz_list):
                st.markdown(f"<div class='question-box'>{q['question']['description']}</div>", unsafe_allow_html=True)
                st.session_state.answers[q['question']['title']] = st.text_area(f"답안 {idx+1}", height=100, label_visibility="collapsed")
            if st.form_submit_button("제출", type="primary", use_container_width=True):
                # 채점 로직
                try: api_key = st.secrets["GOOGLE_API_KEY"]
                except: st.error("API Key 설정 필요"); return
                
                results = [None]*len(st.session_state.quiz_list)
                
                def task(i, q, ans):
                    ev = grade_with_ai_model(q['question']['description'], ans, q['answer_data'], q['standard'], api_key)
                    return i, {"q": q, "ans": ans, "eval": ev}
                
                with st.spinner("채점 및 분석 중..."):
                    with concurrent.futures.ThreadPoolExecutor() as exc:
                        futures = [exc.submit(task, i, q, st.session_state.answers[q['question']['title']]) for i, q in enumerate(st.session_state.quiz_list)]
                        for f in concurrent.futures.as_completed(futures):
                            i, res = f.result()
                            results[i] = res
                            
                            # [결과 저장] GUEST 제외
                            if user_role != 'GUEST':
                                database.save_quiz_result(st.session_state.username, res['q']['standard'], res['eval']['score'])
                                
                                # [오답노트 자동 저장] 유료/관리자 전용 & 5점 이하
                                if user_role in ['PRO', 'ADMIN'] and res['eval']['score'] <= 5.0:
                                    database.save_review_note(
                                        st.session_state.username, 
                                        res['q']['part'],
                                        res['q']['chapter'],
                                        res['q']['standard'],
                                        res['q']['question']['title'],
                                        res['q']['question']['description'],
                                        res['q']['answer_data']['model_answer'],
                                        res['ans'],
                                        res['eval']['score']
                                    )

                st.session_state.results = results
                st.session_state.review_idx = 0
                
                # 경험치 업데이트
                total_s = sum(r['eval']['score'] for r in results)
                st.session_state.exp += total_s
                st.session_state.level = 1 + int(st.session_state.exp // 100)
                if user_role != 'GUEST':
                    database.update_progress(st.session_state.username, st.session_state.level, st.session_state.exp)
                
                # [중복 방지] 풀이 완료된 문제 제목 저장
                for q in st.session_state.quiz_list:
                    st.session_state.solved_questions.add(q['question']['title'])

                st.session_state.app_state = 'REVIEW'
                st.rerun()

    elif st.session_state.app_state == 'REVIEW':
        res = st.session_state.results[st.session_state.review_idx]
        q_data, u_ans, ev = res['q'], res['ans'], res['eval']
        
        # 네비게이션
        c1, c2, c3 = st.columns([1, 4, 1])
        if c1.button("◀") and st.session_state.review_idx > 0:
            st.session_state.review_idx -= 1; st.rerun()
        c2.markdown(f"<h4 style='text-align:center;'>문제 {st.session_state.review_idx+1} / {len(st.session_state.results)}</h4>", unsafe_allow_html=True)
        if c3.button("▶") and st.session_state.review_idx < len(st.session_state.results)-1:
            st.session_state.review_idx += 1; st.rerun()
            
        # 내용 표시
        c_left, c_right = st.columns([2, 1])
        with c_left:
            st.info(f"Q. {q_data['question']['description']}")
            # 사용자 답안 줄바꿈 처리
            u_ans_fmt = u_ans.replace('\n', '<br>')
            st.markdown(f"**내 답안:** <div style='background-color: #4C566A; padding: 10px; border-radius: 5px;'>{u_ans_fmt}</div>", unsafe_allow_html=True)
            
            
            # 모범 답안 처리 (리스트 대응 및 줄바꿈)
            m_ans = q_data['answer_data']['model_answer']
            if isinstance(m_ans, list):
                m_ans_str = "<br>• ".join(m_ans)
                m_ans_str = "• " + m_ans_str
            else:
                m_ans_str = m_ans.replace('\n', '<br>')
                
            # [수정] 모범답안 위에 Title 표시
            st.markdown(f"##### 💡 {q_data['question']['title']}")
            
            st.markdown(f"""
            <div style="background-color: #3B4252; padding: 15px; border-radius: 10px; border-left: 5px solid #A3BE8C; margin-top: 5px;">
                <div style="color: #A3BE8C; font-weight: bold; margin-bottom: 5px;">✅ 모범 답안</div>
                <div style="color: #ECEFF4; line-height: 1.6;">{m_ans_str}</div>
            </div>
            """, unsafe_allow_html=True)

            # [AI 피드백 이동]
            st.markdown("### 🤖 AI 피드백")
            st.success(ev['evaluation'])
            
        with c_right:
            st.pyplot(draw_target(ev['score']), use_container_width=True)
            st.markdown(f"### 점수: {ev['score']}")
            
            # [오답노트 수동 저장] 유료/관리자만 가능
            if user_role in ['PRO', 'ADMIN']:
                if st.button("오답노트 저장"):
                    database.save_review_note(
                        st.session_state.username, 
                        q_data['part'],
                        q_data['chapter'],
                        q_data['standard'],
                        q_data['question']['title'],
                        q_data['question']['description'],
                        q_data['answer_data']['model_answer'],
                        u_ans, 
                        ev['score']
                    )
                    st.toast("저장되었습니다.")
            elif user_role == 'MEMBER':
                st.caption("🔒 오답노트 저장 불가 (유료 전용)")

        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button("🔄 추가 문제 풀기 (설정 유지)", use_container_width=True):
                # 저장된 사양으로 문제 다시 로드 (exclude 적용)
                params = st.session_state.last_quiz_params
                new_quiz = get_quiz_set(db_data, params['part'], params['chapter'], params['standard'], params['count'], st.session_state.solved_questions)
                
                if not new_quiz:
                    st.warning("🎉 해당 조건의 모든 문제를 다 풀었습니다! (더 이상 중복되지 않는 문제가 없습니다)")
                else:
                    st.session_state.quiz_list = new_quiz
                    st.session_state.answers = {q['question']['title']: "" for q in new_quiz}
                    st.session_state.app_state = 'SOLVING'
                    st.rerun()
                    
        with c_btn2:
            if st.button("🏠 종료 및 홈으로", use_container_width=True):
                st.session_state.app_state = 'SETUP'
                st.rerun()

def main():
    database.init_db()
    
    if 'username' not in st.session_state: st.session_state.username = None
    if 'user_role' not in st.session_state: st.session_state.user_role = None
    if 'app_state' not in st.session_state: st.session_state.app_state = 'SETUP'
    if 'exp' not in st.session_state: st.session_state.exp = 0.0
    if 'level' not in st.session_state: st.session_state.level = 1
    
    # [설정] 중복 방지용 상태
    if 'solved_questions' not in st.session_state: st.session_state.solved_questions = set()
    if 'last_quiz_params' not in st.session_state: st.session_state.last_quiz_params = {}

    with st.sidebar:
        st.title("Audit Rank 🏹")
        if not st.session_state.username:
            tab_login, tab_signup = st.tabs(["로그인", "회원가입"])
            
            with tab_login:
                with st.form("login_form"):
                    uid = st.text_input("ID")
                    upw = st.text_input("PW", type="password")
                    if st.form_submit_button("로그인", use_container_width=True):
                        user = database.login_user(uid, upw)
                        if user:
                            st.session_state.username = user[0]
                            st.session_state.user_role = user[2]
                            st.session_state.level = user[3]
                            st.session_state.exp = user[4]
                            st.rerun()
                        else: st.error("로그인 실패: ID/PW를 확인하세요.")

            with tab_signup:
                with st.form("signup_form"):
                    new_uid = st.text_input("ID", key="su_uid")
                    new_upw = st.text_input("PW", type="password", key="su_upw")
                    new_upw_cf = st.text_input("PW 확인", type="password", key="su_upw_cf")
                    
                    if st.form_submit_button("회원가입", use_container_width=True):
                        if new_upw != new_upw_cf:
                            st.error("비밀번호가 일치하지 않습니다.")
                        elif len(new_uid) < 2 or len(new_upw) < 4:
                            st.error("ID 2자 이상, PW 4자 이상 입력하세요.")
                        else:
                            success = database.register_user(new_uid, new_upw)
                            if success:
                                st.success("가입 성공! 로그인 탭에서 로그인해주세요.")
                            else:
                                st.error("이미 존재하는 ID입니다.")
            if st.button("비회원 시작"):
                st.session_state.username = "Guest"
                st.session_state.user_role = "GUEST"
                st.rerun()
        else:
            st.info(f"{st.session_state.username}님 ({ROLE_NAMES[st.session_state.user_role]})")
            
            # 메뉴 구성
            menu_opts = ["실전 훈련", "랭킹", "내 정보", "커리큘럼"]
            if st.session_state.user_role == 'ADMIN':
                menu_opts.append("관리자 페이지")
                
            sel = option_menu("Menu", menu_opts, icons=['pencil', 'trophy', 'person', 'book', 'gear'], menu_icon="cast", default_index=0)
            
            if st.button("로그아웃"):
                st.session_state.clear()
                st.rerun()

    # 메인 라우팅
    if not st.session_state.username:
        st.markdown("### 👋 회계감사 마스터를 위한 여정")
        st.info("왼쪽 사이드바에서 로그인해주세요.")
        return

    db_data = load_db()
    if sel == "실전 훈련": render_quiz(db_data)
    elif sel == "랭킹": render_ranking()
    elif sel == "내 정보": render_profile(db_data)
    elif sel == "커리큘럼": render_curriculum(db_data)
    elif sel == "관리자 페이지" and st.session_state.user_role == 'ADMIN': render_admin()

if __name__ == "__main__":
    main()
