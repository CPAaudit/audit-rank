import streamlit as st
import concurrent.futures
import json
import random
import os
import matplotlib.pyplot as plt
import numpy as np
import google.generativeai as genai
import re
import database
import pandas as pd
import importlib
import time
importlib.reload(database)

# [설정] 기본 설정
st.set_page_config(page_title="회계감사 랭크", page_icon="🏹", layout="wide")

# [스타일]
# [스타일]
def local_css():
    st.markdown("""
    <style>
        .stTextArea textarea { height: 150px; }
        .score-box { padding: 20px; border-radius: 10px; text-align: center; font-weight: bold; font-size: 24px; color: white; }
        .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
            background-color: #212529 !important;
            color: #f8f9fa !important;
        }
        .question-box {
            background-color: #343a40;
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #495057;
            margin-bottom: 20px;
            color: #f8f9fa;
        }
    </style>
    """, unsafe_allow_html=True)

local_css()

# [설정] 커리큘럼 데이터
# [설정] 커리큘럼 데이터 (Removed: Use load_structure() instead)

# API Key


# [기능 1] 데이터 로드 및 정규화
# @st.cache_data (Disabled for debugging/data sync)
def load_db():
    data = []
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    
    try:
        # Load structure first to get canonical names
        _, _, part_code_map = load_structure()
        
        # Load all questions_PART*.json files
        for filename in os.listdir(data_dir):
            if filename.startswith('questions_PART') and filename.endswith('.json'):
                file_path = os.path.join(data_dir, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    part_data = json.load(f)
                    data.extend(part_data)
        
        if not data:
            st.error("데이터 파일을 찾을 수 없습니다. (data/questions_PART*.json)")
            return []
            
        for q in data:
            # Robust PART normalization
            p_str = str(q.get('part', ''))
            # Extract PART number (e.g., "PART1", "PART 1", "1")
            p_match = re.search(r'(?:PART\s*)?(\d+)', p_str, re.IGNORECASE)
            if p_match:
                part_num = f"PART{p_match.group(1)}"
                # Map to canonical name if exists, else use constructed PART#
                q['part'] = part_code_map.get(part_num, f"PART{p_match.group(1)}")
            
            c_str = str(q['chapter'])
            nums = re.findall(r'\d+', c_str)
            if nums:
                match = re.search(r'(\d+(?:-\d+)?)', c_str)
                if match:
                    q['chapter'] = f"ch{match.group(1)}"
                else:
                    q['chapter'] = f"ch{nums[0]}"
            
            q['standard'] = str(q['standard'])
            
        return data
    except Exception as e:
        st.error(f"데이터 로드 중 오류 발생: {str(e)}")
        return []

def load_reference_text(standard_code):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "data", "references", f"{standard_code}.md")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "참고 기준서 파일을 찾을 수 없습니다."

def load_structure():
    hierarchy = {}
    name_map = {}
    part_code_map = {}
    current_part = None
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    structure_path = os.path.join(base_dir, 'data', 'references', 'structure.md')

    try:
        with open(structure_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        for line in lines:
            line = line.strip()
            if not line: continue
            
            part_match = re.match(r'^##\s*(PART\s*\d+.*)', line, re.IGNORECASE)
            if part_match:
                raw_part = part_match.group(1).strip()
                # Normalize PART 1 -> PART1
                raw_part = re.sub(r'^PART\s+(\d+)', r'PART\1', raw_part, flags=re.IGNORECASE)
                
                # Extract short code for mapping (e.g. PART1)
                short_p_match = re.match(r'^(PART\d+)', raw_part, re.IGNORECASE)
                if short_p_match:
                    part_code_map[short_p_match.group(1).upper()] = raw_part
                
                current_part = raw_part
                hierarchy[current_part] = {}
                continue
                
            chapter_match = re.match(r'^-\s*\*\*(ch[\d-]+.*?)\*\*:\s*(.+)', line, re.IGNORECASE)
            if chapter_match and current_part:
                full_chapter_name = chapter_match.group(1).strip()
                code_match = re.match(r'^(ch\d+(?:-\d+)?)', full_chapter_name, re.IGNORECASE)
                if code_match:
                    short_code = code_match.group(1).lower()
                else:
                    short_code = full_chapter_name
                
                name_map[short_code] = full_chapter_name
                standards_str = chapter_match.group(2).strip()
                standards = [s.strip() for s in standards_str.split(',')]
                hierarchy[current_part][short_code] = standards
                
    except FileNotFoundError:
        st.error("구조 파일(data/references/structure.md)을 찾을 수 없습니다.")
        return {}, {}
        
    return hierarchy, name_map, part_code_map

def get_counts(data):
    counts = { 'parts': {}, 'chapters': {}, 'standards': {} }
    for q in data:
        p = str(q.get('part', '')).strip()
        c = str(q.get('chapter', '')).strip()
        s = str(q.get('standard', '')).strip()
        if p: counts['parts'][p] = counts['parts'].get(p, 0) + 1
        if c: counts['chapters'][c] = counts['chapters'].get(c, 0) + 1
        if s: counts['standards'][s] = counts['standards'].get(s, 0) + 1
    return counts

def get_quiz_set(data, part, chapter, standard, num_questions):
    candidates = [
        q for q in data 
        if q['part'] == part 
        and (chapter == "전체" or q['chapter'] == chapter)
        and (standard == "전체" or q['standard'] == standard)
    ]
    if len(candidates) <= num_questions:
        return candidates
    return random.sample(candidates, num_questions)

def get_chapter_sort_key(chapter_name):
    if chapter_name == "전체": return (-1, )
    numbers = re.findall(r'\d+', chapter_name)
    if not numbers: return (999, )
    return tuple(map(int, numbers))

def get_standard_sort_key(standard_code):
    if standard_code == "전체": return -1
    try: return int(standard_code)
    except: return 9999

    try: return int(standard_code)
    except: return 9999

# [기능 1.5] 키워드 채점 로직 (Python)
def calculate_score(user_ans, keywords):
    if not user_ans or not keywords:
        return 0.0
    
    user_ans_norm = user_ans.lower()
    match_count = 0
    
    for kw in keywords:
        # 간단한 포함 여부 확인 (필요시 형태소 분석기 도입 가능)
        if kw.lower() in user_ans_norm:
            match_count += 1
            
    if len(keywords) == 0:
        return 0.0
        
    return (match_count / len(keywords)) * 10.0

# [기능 2] AI 채점 로직
def grade_with_ai_model(question_text, user_ans, answer_data, standard_code, api_key):
    if not user_ans or len(user_ans.strip()) < 2:
        return {"score": 0.0, "evaluation": "답안이 작성되지 않았습니다."}

    # 1. Python Keyword Scoring
    base_score = calculate_score(user_ans, answer_data.get('keywords', []))
    
    # 2. AI Qualitative Assessment
    ref_text = load_reference_text(standard_code)
    # Limit ref_text length as requested
    ref_text_short = ref_text[:5000] if ref_text else ""

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')

        keywords_str = ", ".join(answer_data.get('keywords', []))
        
        sys_prompt = f"""
        당신은 회계감사 답안을 평가하는 채점관입니다. 빠른 시간 내에 채점해야 합니다.
        사용자 답안을 **[모범 답안]**, **[핵심 키워드]**, **[감사기준서 참고]**와 효율적으로 비교하여 채점하세요.

        다음 4가지 기준을 **내부적으로 평가**하여 점수(score)를 산출하세요 (JSON 출력에는 포함하지 마세요):
        1. **논리적 일치도 (상/중/하)**: 질문 의도 및 정답과의 논리적 부합 여부
        2. **키워드 정확성 (상/중/하)**: 
           - 상: 핵심 키워드 정확히 사용
           - 중: 유의어/유사한 표현 사용
           - 하: 반대/무관한 표현
        3. **키워드 포함도 (상/중/하)**: 핵심 키워드 포함 개수 및 빈도
        4. **문장의 완성도 **: 문장의 흐름이 자연스럽고 완결된 형태인지 여부

        **[JSON 출력 형식]**
        1. **score** (Number): 
           - 위 내부 평가를 종합한 10점 만점 점수(정수 단위)
        2. **feedback** (String): 
           - 반드시 다음 형식을 지켜서 줄바꿈을 포함해 작성:
             "부족한 점: [내용]\n\n잘한 점: [내용]"
           - 전체 길이는 100자 이내로 간결하게 작성.

        [문제] {question_text}
        [사용자 답안] {user_ans}
        [핵심 키워드] {answer_data.get('keywords', [])}
        [모범 답안] {answer_data['model_answer']}
        [감사기준서 참고] {ref_text_short}
        """
        
        response = model.generate_content(sys_prompt)
        text_res = response.text.replace('```json', '').replace('```', '').strip()
        ai_result = json.loads(text_res)
        
        # 3. Final Score Calculation (AI Driven)
        final_score = float(ai_result.get('score', 0.0))
            
        return {
            "score": round(final_score, 1), 
            "evaluation": ai_result.get('feedback', '피드백을 불러올 수 없습니다.')
        }
        
    except Exception as e:
        return {"score": 0.0, "evaluation": f"채점 오류: {str(e)}"}

# [기능 3] 시각화
def draw_target(score):
    fig, ax = plt.subplots(figsize=(4, 4))
    # 10 rings: 1-2 White, 3-4 Black, 5-6 Blue, 7-8 Red, 9-10 Gold
    colors = ['white', 'white', 'black', 'black', 'blue', 'blue', 'red', 'red', 'gold', 'gold']
    radii = list(range(10, 0, -1)) # 10, 9, ..., 1
    
    # Draw rings
    for r, c in zip(radii, colors):
        circle = plt.Circle((0, 0), r, facecolor=c, edgecolor='gray', linewidth=0.5)
        ax.add_artist(circle)
    
    # Draw 'X' ring (inner 10)
    ax.add_artist(plt.Circle((0, 0), 0.5, facecolor='none', edgecolor='gray', linewidth=0.5, linestyle='--'))

    # Calculate hit position based on score
    # Score 10 -> distance 0~1
    # Score 9 -> distance 1~2
    # ...
    # Score 0 -> distance 10~11 (Miss)
    
    # Invert score to get distance from center
    # Add random angle
    angle = np.random.uniform(0, 2 * np.pi)
    
    # Distance: 10 - score. 
    # e.g. score 10.0 -> dist 0.0
    # e.g. score 5.5 -> dist 4.5
    base_dist = 10.0 - score
    
    # Add slight randomness to distance to simulate spread within the score band
    # But keep it within reasonable bounds so 9.9 doesn't look like 8.0
    # Random jitter +/- 0.2
    jitter = np.random.uniform(-0.1, 0.1)
    final_dist = max(0, base_dist + jitter)
    
    # Plot hit marker
    ax.plot(final_dist * np.cos(angle), final_dist * np.sin(angle), 'X', color='lime', markersize=10, markeredgecolor='black', markeredgewidth=1)
    
    ax.set_xlim(-11, 11)
    ax.set_ylim(-11, 11)
    ax.axis('off')
    return fig

# [UI] 로그인 페이지 (제거됨 - 사이드바 로그인 사용)
# def login_page():
#     pass

# [화면 1] 홈 화면 렌더링
def render_home():
    st.title("회계감사 랭크 🏆")
    st.markdown("### 환영합니다! 회계감사 마스터가 되어보세요.")
    
    st.markdown("### 📚 학습 커리큘럼")
    hierarchy, name_map, _ = load_structure()
    
    # Sort parts if needed, though dictionary insertion order is usually preserved in recent Python
    sorted_parts = sorted(hierarchy.keys())
    
    for part in sorted_parts:
        chapters = hierarchy[part]
        with st.expander(part):
            # Sort chapters by code (ch1, ch2, ...)
            sorted_chapters = sorted(chapters.keys(), key=get_chapter_sort_key)
            for ch_code in sorted_chapters:
                full_name = name_map.get(ch_code, ch_code)
                standards = chapters[ch_code]
                st.markdown(f"- **{full_name}**: {', '.join(standards)}")

    st.divider()
    
    if st.button("🚀 훈련 시작하기 (Start Training)", use_container_width=True, type="primary"):
        st.session_state['current_page'] = "실전 훈련"
        st.rerun()

# [화면 3] 랭킹 화면 렌더링
def render_ranking():
    st.title("🏆 랭킹 (Leaderboard)")
    st.markdown("회계감사 마스터들의 명예의 전당입니다.")
    
    df_rank = database.get_leaderboard_data()
    
    if not df_rank.empty:
        # 상위 랭커 강조 (데이터가 있을 경우)
        col1, col2, col3 = st.columns(3)
        if len(df_rank) > 0:
            with col2:
                st.header("🥇 1등")
                st.subheader(df_rank.iloc[0]['사용자'])
                st.write(f"{df_rank.iloc[0]['총점']:.1f} 점")
        if len(df_rank) > 1:
            with col1:
                st.header("🥈 2등")
                st.subheader(df_rank.iloc[1]['사용자'])
                st.write(f"{df_rank.iloc[1]['총점']:.1f} 점")
        if len(df_rank) > 2:
            with col3:
                st.header("🥉 3등")
                st.subheader(df_rank.iloc[2]['사용자'])
                st.write(f"{df_rank.iloc[2]['총점']:.1f} 점")
    
    st.divider()
    st.dataframe(df_rank, use_container_width=True, hide_index=True)

# [화면 4] 내 정보 화면 렌더링
def render_profile():
    st.title("👤 내 정보 (My Profile)")
    username = st.session_state.get('username', 'Guest')
    stats = database.get_user_stats(username)
    
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://api.dicebear.com/7.x/avataaars/svg?seed=Felix", width=150)
    with col2:
        st.subheader(f"{username} 님")
        st.write(f"🌱 성장하는 감사인")
    
    st.divider()
    
    tab1, tab2 = st.tabs(["내 통계", "오답 노트"])
    
    with tab1:
        # 통계 메트릭
        m1, m2, m3 = st.columns(3)
        m1.metric("누적 점수", f"{stats['total_score']:.1f} 점")
        m2.metric("해결한 문제", f"{stats['solved_count']} 개")
        avg_score = stats['total_score'] / stats['solved_count'] if stats['solved_count'] > 0 else 0
        m3.metric("평균 점수", f"{avg_score:.1f} 점")
        
        st.subheader("📜 최근 풀이 기록")
        if stats['recent_history']:
            history_df = pd.DataFrame(stats['recent_history'], columns=['주제', '점수', '일시'])
            st.dataframe(history_df, use_container_width=True, hide_index=True)
        else:
            st.info("아직 풀이 기록이 없습니다.")
            
    with tab2:
        st.subheader("📝 오답 노트")
        
        if st.session_state.get('user_role') == 'GUEST':
            st.warning("🔒 회원 전용 기능입니다.")
        else:
            notes_df = database.get_user_review_notes(username)
            
            if notes_df.empty:
                st.info("오답 노트가 비어있습니다.")
            else:
                for index, row in notes_df.iterrows():
                    with st.expander(f"[{row['created_at']}] {row['question'][:30]}... (점수: {row['score']})"):
                        st.markdown(f"**문제:** {row['question']}")
                        st.info(f"**내 답안:** {row['answer']}")
                        st.markdown(f"**관련 기준서:** {row['standard_code']}")
                        
                        if st.button("🗑️ 삭제 (복습 완료)", key=f"del_note_{row['id']}"):
                            database.delete_review_note(row['id'])
                            st.toast("오답 노트에서 삭제되었습니다.")
                            st.rerun()

# [화면 2] 퀴즈 화면 렌더링
def render_quiz(db_data):
    st.title("📝 실전 훈련 (Competition)")
    
    # 퀴즈 로직

    # 퀴즈 로직
    hierarchy, name_map, _ = load_structure()
    counts = get_counts(db_data)

    if st.session_state.app_state == 'SETUP':
        st.subheader("🎯 훈련 코스 선택")
        c1, c2, c3 = st.columns(3)
        
        part_options = sorted(list(hierarchy.keys()))
        def format_part(x): return f"{x} ({counts['parts'].get(x, 0)})"
        with c1: sel_part = st.selectbox("Part", part_options, format_func=format_part)
        
        chap_list = sorted(list(hierarchy[sel_part].keys()), key=get_chapter_sort_key)
        chap_options = ["전체"] + chap_list
        def format_chap(x):
            if x == "전체": return f"전체 ({counts['parts'].get(sel_part, 0)})"
            full_name = name_map.get(x, x)
            return f"{full_name} ({counts['chapters'].get(x, 0)})"
        with c2: sel_chap = st.selectbox("Chapter", chap_options, format_func=format_chap)
        
        if sel_chap == "전체":
            all_stds = set()
            for ch in hierarchy[sel_part]: all_stds.update(hierarchy[sel_part][ch])
            std_options = ["전체"] + sorted(list(all_stds), key=get_standard_sort_key)
            def format_std(x):
                if x == "전체": return f"전체 ({counts['parts'].get(sel_part, 0)})"
                return f"{x} ({counts['standards'].get(x, 0)})"
        else:
            std_options = ["전체"] + sorted(hierarchy[sel_part][sel_chap], key=get_standard_sort_key)
            def format_std(x):
                if x == "전체": return f"전체 ({counts['chapters'].get(sel_chap, 0)})"
                return f"{x} ({counts['standards'].get(x, 0)})"
        with c3: sel_std = st.selectbox("Standard (기준서)", std_options, format_func=format_std)
        
        st.write("")
        # 난이도 설정
        user_role = st.session_state.get('user_role', 'MEMBER')
        difficulty_map = {}
        if user_role == 'GUEST':
            # GUEST can now access all levels
            difficulty_map = {"초급 (1문제)": 1, "중급 (3문제)": 3, "고급 (5문제)": 5}
            st.caption("� GUEST 모드: 모든 난이도가 개방되었습니다.")
        elif user_role == 'MEMBER':
            difficulty_map = {"초급 (1문제)": 1, "중급 (3문제)": 3}
            st.caption("🔒 고급 난이도는 PRO 등급 전용입니다.")
        else: # PRO
            difficulty_map = {"초급 (1문제)": 1, "중급 (3문제)": 3, "고급 (5문제)": 5}
            
        sel_diff = st.selectbox("난이도 선택", list(difficulty_map.keys()))
        st.session_state.num_questions = difficulty_map[sel_diff]
        st.write("")
        if st.button("Start Training 🚀", type="primary", use_container_width=True):
            st.session_state['saved_settings'] = {
                'part': sel_part, 'chapter': sel_chap, 'standard': sel_std,
                'num_questions': st.session_state.num_questions
            }
            quiz_list = get_quiz_set(db_data, sel_part, sel_chap, sel_std, st.session_state.num_questions)
            if not quiz_list:
                st.error("문제가 없습니다.")
            else:
                st.session_state.quiz_list = quiz_list
                st.session_state.answers = {q['question']['title']: "" for q in quiz_list}
                st.session_state.app_state = 'SOLVING'
                st.rerun()

    elif st.session_state.app_state == 'SOLVING':
        st.subheader("📝 답안 작성")
        with st.form("answer_form"):
            for idx, q in enumerate(st.session_state.quiz_list):
                st.markdown(f"""
                <div class="question-box">
                    <p>{q['question']['description']}</p>
                </div>
                """, unsafe_allow_html=True)
                st.session_state.answers[q['question']['title']] = st.text_area(
                    "답안을 입력하세요", key=f"input_{idx}", height=100, label_visibility="collapsed",
                    placeholder="여기에 답안을 작성하세요..."
                )
                st.write("")
            submitted = st.form_submit_button("제출", type="primary", use_container_width=True)

        if submitted:
            # API Key Load
            try:
                google_api_key = st.secrets["GOOGLE_API_KEY"]
            except KeyError:
                st.error("secrets.toml 파일에 GOOGLE_API_KEY 설정이 없습니다.")
                st.stop()

            results = [None] * len(st.session_state.quiz_list)

            def process_single_question(index, question_data, user_answer, specific_key):
                evaluation = grade_with_ai_model(
                    question_data['question']['description'], user_answer, 
                    question_data['answer_data'], question_data['standard'], specific_key
                )
                return index, { "q_data": question_data, "u_ans": user_answer, "eval": evaluation }

            with st.spinner(f"채점 중..."):
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    future_to_quiz = {}
                    for idx, q in enumerate(st.session_state.quiz_list):
                        future = executor.submit(
                            process_single_question, idx, q, 
                            st.session_state.answers[q['question']['title']], google_api_key
                        )
                        future_to_quiz[future] = idx
                        
                    for future in concurrent.futures.as_completed(future_to_quiz):
                        idx = future_to_quiz[future]
                        try:
                            _, res = future.result()
                            results[idx] = res
                            
                            # Save history
                            if st.session_state.get('user_role') != 'GUEST':
                                database.save_quiz_result(
                                    st.session_state['username'], 
                                    res['q_data']['standard'], 
                                    res['eval']['score']
                                )
                        except Exception as exc:
                            st.error(f"채점 중 오류 발생: {exc}")
            
            st.session_state.results = results
            st.session_state.review_idx = 0
            
            # Update Progress
            total_xp = sum(r['eval']['score'] for r in results if r)
            current_level = st.session_state.get('level', 1)
            current_exp = st.session_state.get('exp', 0.0)
            new_exp = current_exp + total_xp
            new_level = 1 + int(new_exp // 100)
            
            st.session_state.exp = new_exp
            st.session_state.level = new_level
            
            if st.session_state.get('user_role') != 'GUEST':
                database.update_progress(st.session_state['username'], new_level, new_exp)
            
            st.session_state.app_state = 'REVIEW'
            st.rerun()

    elif st.session_state.app_state == 'REVIEW':
        render_review(db_data)


        




        


# [화면 5] 결과 확인 화면 렌더링
def render_review(db_data):
    if 'results' not in st.session_state or not st.session_state.results:
        st.error("결과 데이터가 없습니다.")
        if st.button("돌아가기"):
            st.session_state.app_state = 'SETUP'
            st.rerun()
        return

    res_list = st.session_state.results
    curr = res_list[st.session_state.review_idx]
    score = curr['eval']['score']
    
    with st.container(border=True):
        c_header, c_nav = st.columns([3, 1])
        with c_header:
            st.subheader(f"📊 결과 확인 ({st.session_state.review_idx+1}/{len(res_list)})")
        with c_nav:
            c_prev, c_next = st.columns(2)
            with c_prev: 
                if st.button("◀", use_container_width=True) and st.session_state.review_idx > 0: 
                    st.session_state.review_idx -= 1; st.rerun()
            with c_next:
                if st.session_state.review_idx < len(res_list)-1:
                    if st.button("▶", use_container_width=True): 
                        st.session_state.review_idx += 1; st.rerun()

        if score >= 5.0: st.success(f"결과: 통과! (+{score} XP)")
        else: st.error(f"결과: 실패! (+{score} XP)")

        col_L, col_R = st.columns([2, 1])
        with col_L:
            st.subheader("❓ 문제와 당신의 답안")
            st.markdown(f"**문제:** {curr['q_data']['question']['description']}")
            st.info(f"**내 답안:** {curr['u_ans']}")
            st.subheader("💡 모범 답안")
            model_answers = curr['q_data']['answer_data']['model_answer']
            if isinstance(model_answers, list): formatted_answer = "\n".join([f"- {ans}" for ans in model_answers])
            else: formatted_answer = f"- {model_answers}"
            st.success(formatted_answer)
            st.subheader("🤖 AI 피드백")
            st.markdown(curr['eval']['evaluation'])
            with st.expander("📚 참고 기준서 보기"):
                st.markdown(f"**참조 기준서:** `{curr['q_data']['standard']}`")
        with col_R:
            st.pyplot(draw_target(score))
            st.markdown(f"""<div class="score-box">{score}점</div>""", unsafe_allow_html=True)
            
            st.write("")
            st.write("")
            if st.session_state.get('user_role') == 'GUEST':
                st.warning("🔒 GUEST는 오답 노트가 저장되지 않습니다.")
            else:
                if st.button("📂 오답 노트에 저장", key="save_note_btn"):
                    database.save_review_note(
                        st.session_state['username'],
                        curr['q_data']['standard'],
                        curr['q_data']['question']['description'],
                        curr['u_ans'],
                        score
                    )
                    st.toast("오답 노트에 추가되었습니다!", icon="📝")
    
    if st.session_state.review_idx == len(res_list) - 1:
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 같은 설정으로 재시작", use_container_width=True):
                settings = st.session_state.get('saved_settings')
                if settings:
                    quiz_list = get_quiz_set(db_data, settings['part'], settings['chapter'], settings['standard'], settings['num_questions'])
                    if not quiz_list: st.error("문제가 없습니다.")
                    else:
                        st.session_state.quiz_list = quiz_list
                        st.session_state.answers = {q['question']['title']: "" for q in quiz_list}
                        st.session_state.app_state = 'SOLVING'
                        st.rerun()
        with col2:
            if st.button("⏹️ 종료 (설정 화면으로)", use_container_width=True, type="primary"): 
                st.session_state.app_state = 'SETUP'; st.rerun()
def main():
    database.init_db()
    
    # 로그인 상태 확인
    if 'username' not in st.session_state:
        st.session_state['username'] = None

    with st.sidebar:
        st.title("Audit Rank")
        
        if not st.session_state['username']:
            # [Scenario A] 비로그인 상태: 로그인/회원가입 탭
            tab_login, tab_signup = st.tabs(["로그인", "회원가입"])
            
            with tab_login:
                with st.form("login_form"):
                    username = st.text_input("아이디 (Username)")
                    password = st.text_input("비밀번호 (Password)", type="password")
                    submit_login = st.form_submit_button("로그인", use_container_width=True)
                    
                    if submit_login:
                        user = database.login_user(username, password)
                        if user:
                            st.session_state['username'] = user[0]
                            # user[2] is role, user[3] is level, user[4] is xp
                            st.session_state['user_role'] = user[2]
                            st.session_state['level'] = user[3]
                            st.session_state['exp'] = user[4]
                            st.success(f"{username}님 환영합니다!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error("아이디 또는 비밀번호가 잘못되었습니다.")
            
            with tab_signup:
                st.warning("⛔ 현재 신규 회원가입이 일시적으로 중단되었습니다.")
                # with st.form("signup_form"):
                #     new_user = st.text_input("새 아이디")
                #     new_pass = st.text_input("새 비밀번호", type="password")
                #     new_pass_confirm = st.text_input("비밀번호 확인", type="password")
                #     submit_signup = st.form_submit_button("회원가입", use_container_width=True)
                    
                #     if submit_signup:
                #         if new_pass != new_pass_confirm:
                #             st.error("비밀번호가 일치하지 않습니다.")
                #         elif not new_user or not new_pass:
                #             st.error("모든 필드를 입력해주세요.")
                #         else:
                #             if database.create_user(new_user, new_pass):
                #                 st.success("가입 성공! 로그인 탭에서 로그인해주세요.")
                #             else:
                #                 st.error("이미 존재하는 아이디입니다.")

            st.divider()
            if st.button("비회원으로 시작하기 (Guest Mode)", use_container_width=True):
                st.session_state['username'] = "Guest"
                st.session_state['user_role'] = "GUEST"
                st.session_state['level'] = 1
                st.session_state['exp'] = 0.0
                st.success("게스트로 접속합니다.")
                time.sleep(0.5)
                st.rerun()
                                
        else:
            # [Scenario B] 로그인 상태
            username = st.session_state['username']
            role = st.session_state.get('user_role', 'MEMBER')
            
            # 등급 표시 (뱃지 스타일)
            if role == 'PRO' or role == 'ADMIN':
                st.success(f"👑 {username}님 ({role})")
            elif role == 'PAID':
                st.info(f"💎 {username}님 ({role})")
            elif role == 'GUEST':
                st.warning(f"👤 {username}님 ({role})")
            else:
                st.info(f"🌱 {username}님 ({role})")
            
            # 레벨/XP 표시
            current_level = st.session_state.get('level', 1)
            current_exp = st.session_state.get('exp', 0.0)
            
            st.metric("Level", f"Lv.{current_level}", f"{current_exp:.1f} XP")
            
            st.divider()
            
            # 네비게이션
            menu_options = ["홈", "실전 훈련", "랭킹", "내 정보"]
            try:
                current_index = menu_options.index(st.session_state.get('current_page', '홈'))
            except ValueError:
                current_index = 0
                
            selection = st.radio("메뉴 이동", menu_options, index=current_index, key="nav_radio")
            
            if selection != st.session_state.get('current_page'):
                st.session_state['current_page'] = selection
                st.rerun()
                
            st.divider()
            
            if st.button("로그아웃", use_container_width=True):
                st.session_state.clear()
                st.rerun()

    # [Main Area UI]
    if not st.session_state['username']:
        # 비로그인 상태 화면
        st.title("회계감사 랭크 (Audit Rank) 🏹")
        st.info("👈 왼쪽 사이드바에서 로그인 후 훈련을 시작하세요.")
        st.markdown("""
        ### 🌟 주요 기능
        - **실전 훈련**: 회계감사 기준서 기반의 퀴즈 풀이
        - **AI 채점**: Gemini AI를 활용한 정밀한 서술형 채점
        - **랭킹 시스템**: 다른 감사인들과의 실력 경쟁
        - **오답 노트**: 틀린 문제 복습 및 관리
        """)
    else:
        # 로그인 상태 화면 (기존 로직 유지)
        if 'exp' not in st.session_state: st.session_state.exp = 0.0
        if 'level' not in st.session_state: st.session_state.level = 1
        if 'app_state' not in st.session_state: st.session_state.app_state = 'SETUP'
        if 'current_page' not in st.session_state: st.session_state['current_page'] = "홈"
        
        # 레벨 계산 (단순 예시)
        st.session_state.level = 1 + int(st.session_state.exp // 100)
        
        db_data = load_db()
        
        # 라우팅
        if st.session_state['current_page'] == "홈":
            render_home()
        elif st.session_state['current_page'] == "실전 훈련":
            if not db_data: return
            render_quiz(db_data)
        elif st.session_state['current_page'] == "랭킹":
            render_ranking()
        elif st.session_state['current_page'] == "내 정보":
            render_profile()

if __name__ == "__main__":
    main()

