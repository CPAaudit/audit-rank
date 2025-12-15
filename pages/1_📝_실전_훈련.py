import streamlit as st
import utils
import database
import concurrent.futures

# [초기 설정]
st.set_page_config(page_title="실전 훈련 | Audit Rank", page_icon="📝", layout="wide")
utils.local_css()

def main():
    if 'username' not in st.session_state or not st.session_state.username:
        st.warning("로그인이 필요합니다.")
        st.stop()

    st.title("📝 실전 훈련")
    
    # DB Load (Cached in utils)
    db_data = utils.load_db()
    user_role = st.session_state.user_role
    
    # State Init
    if 'app_state' not in st.session_state: st.session_state.app_state = 'SETUP'
    if 'solved_questions' not in st.session_state: st.session_state.solved_questions = set()
    if 'last_quiz_params' not in st.session_state: st.session_state.last_quiz_params = {}

    # --- SETUP STATE ---
    if st.session_state.app_state == 'SETUP':
        hierarchy, name_map, _, _ = utils.load_structure()
        counts = utils.get_counts(db_data)
        
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1: 
            def fmt_part(x): return f"{x} ({counts['parts'].get(x, 0)})"
            sel_part = st.selectbox("Part", sorted(list(hierarchy.keys())), format_func=fmt_part)
            
        with c2: 
            chap_opts = ["전체"] + sorted(list(hierarchy[sel_part].keys()), key=utils.get_chapter_sort_key)
            def fmt_chap(x): return "전체" if x == "전체" else f"{name_map.get(x, x)} ({counts['chapters'].get(x, 0)})"
            sel_chap = st.selectbox("Chapter", chap_opts, format_func=fmt_chap)
            
        with c3:
            if sel_chap == "전체":
                stds = set()
                for c in hierarchy[sel_part]: stds.update(hierarchy[sel_part][c])
                std_opts = ["전체"] + sorted(list(stds), key=utils.get_standard_sort_key)
            else:
                std_opts = ["전체"] + sorted(hierarchy[sel_part][sel_chap], key=utils.get_standard_sort_key)
            def fmt_std(x): return "전체" if x == "전체" else f"{x} ({counts['standards'].get(x, 0)})"
            sel_std = st.selectbox("Standard", std_opts, format_func=fmt_std)
            
        # [난이도 접근 제어]
        st.write("")
        st.subheader("문항 수 선택")
        
        diff_levels = {
            "초급 (1문제)": 1,
            "중급 (3문제)": 3,
            "고급 (5문제)": 5
        }
        if user_role == 'ADMIN': diff_levels["전체 (All)"] = 9999
        
        options = list(diff_levels.keys())
        if user_role in ['GUEST', 'MEMBER']:
            st.info(f"💡 현재 등급({utils.ROLE_NAMES[user_role]})은 '중급'까지만 선택 가능합니다.")
            selectable_options = options[:2] 
        else:
            selectable_options = options
            
        sel_diff = st.selectbox("문항 수", selectable_options)
        
        if st.button("훈련 시작 🚀", type="primary", use_container_width=True):
            cnt = diff_levels[sel_diff]
            # Pass solved_questions as exclude_titles
            quiz_list = utils.get_quiz_set(db_data, sel_part, sel_chap, sel_std, cnt, st.session_state.solved_questions)
            if not quiz_list:
                st.error("해당 조건의 문제가 없습니다. (또는 이미 모든 문제를 풀었습니다.)")
            else:
                st.session_state.quiz_list = quiz_list
                st.session_state.answers = {q['question']['title']: "" for q in quiz_list}
                st.session_state.app_state = 'SOLVING'
                st.session_state.last_quiz_params = {
                    'part': sel_part,
                    'chapter': sel_chap,
                    'standard': sel_std,
                    'count': cnt
                }
                st.rerun()

    # --- SOLVING STATE ---
    elif st.session_state.app_state == 'SOLVING':
        with st.form("ans_form"):
            for idx, q in enumerate(st.session_state.quiz_list):
                st.markdown(f"<div class='question-box'>{q['question']['description']}</div>", unsafe_allow_html=True)
                st.session_state.answers[q['question']['title']] = st.text_area(f"답안 {idx+1}", height=100, label_visibility="collapsed")
            
            if st.form_submit_button("제출", type="primary", use_container_width=True):
                try: api_key = st.secrets["GOOGLE_API_KEY"]
                except: st.error("API Key 설정 필요"); return
                
                results = [None]*len(st.session_state.quiz_list)
                
                def task(i, q, ans):
                    ev = utils.grade_with_ai_model(q['question']['description'], ans, q['answer_data'], q['standard'], api_key)
                    return i, {"q": q, "ans": ans, "eval": ev}
                
                with st.spinner("채점 및 분석 중..."):
                    with concurrent.futures.ThreadPoolExecutor() as exc:
                        futures = [exc.submit(task, i, q, st.session_state.answers[q['question']['title']]) for i, q in enumerate(st.session_state.quiz_list)]
                        for f in concurrent.futures.as_completed(futures):
                            i, res = f.result()
                            results[i] = res
                            
                            if user_role != 'GUEST':
                                database.save_quiz_result(st.session_state.username, res['q']['standard'], res['eval']['score'])
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
                
                # Exp Update
                total_s = sum(r['eval']['score'] for r in results)
                st.session_state.exp += total_s
                st.session_state.level = 1 + int(st.session_state.exp // 100)
                if user_role != 'GUEST':
                    database.update_progress(st.session_state.username, st.session_state.level, st.session_state.exp)
                
                # Mark as solved
                for q in st.session_state.quiz_list:
                    st.session_state.solved_questions.add(q['question']['title'])

                st.session_state.app_state = 'REVIEW'
                st.rerun()

    # --- REVIEW STATE ---
    elif st.session_state.app_state == 'REVIEW':
        if 'results' not in st.session_state or not st.session_state.results:
            st.error("결과 데이터가 없습니다.")
            st.session_state.app_state = 'SETUP'
            st.rerun()
            
        res = st.session_state.results[st.session_state.review_idx]
        q_data, u_ans, ev = res['q'], res['ans'], res['eval']
        
        # Navigation
        c1, c2, c3 = st.columns([1, 4, 1])
        if c1.button("◀") and st.session_state.review_idx > 0:
            st.session_state.review_idx -= 1; st.rerun()
        c2.markdown(f"<h4 style='text-align:center;'>문제 {st.session_state.review_idx+1} / {len(st.session_state.results)}</h4>", unsafe_allow_html=True)
        if c3.button("▶") and st.session_state.review_idx < len(st.session_state.results)-1:
            st.session_state.review_idx += 1; st.rerun()
            
        # Content
        c_left, c_right = st.columns([2, 1])
        with c_left:
            st.info(f"Q. {q_data['question']['description']}")
            u_ans_fmt = u_ans.replace('\n', '<br>')
            st.markdown(f"**내 답안:** <div style='background-color: #4C566A; padding: 10px; border-radius: 5px;'>{u_ans_fmt}</div>", unsafe_allow_html=True)
            
            m_ans = q_data['answer_data']['model_answer']
            if isinstance(m_ans, list):
                m_ans_str = "<br>• ".join(m_ans)
                m_ans_str = "• " + m_ans_str
            else:
                m_ans_str = m_ans.replace('\n', '<br>')
                
            st.markdown(f"##### 💡 {q_data['question']['title']}")
            st.markdown(f"""
            <div style="background-color: #3B4252; padding: 15px; border-radius: 10px; border-left: 5px solid #A3BE8C; margin-top: 5px;">
                <div style="color: #A3BE8C; font-weight: bold; margin-bottom: 5px;">✅ 모범 답안</div>
                <div style="color: #ECEFF4; line-height: 1.6;">{m_ans_str}</div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("### 🤖 AI 피드백")
            st.success(ev['evaluation'])
            
        with c_right:
            st.pyplot(utils.draw_target(ev['score']), use_container_width=True)
            st.markdown(f"### 점수: {ev['score']}")
            
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
                params = st.session_state.last_quiz_params
                new_quiz = utils.get_quiz_set(db_data, params['part'], params['chapter'], params['standard'], params['count'], st.session_state.solved_questions)
                
                if not new_quiz:
                    st.warning("🎉 해당 조건의 모든 문제를 다 풀었습니다!")
                else:
                    st.session_state.quiz_list = new_quiz
                    st.session_state.answers = {q['question']['title']: "" for q in new_quiz}
                    st.session_state.app_state = 'SOLVING'
                    st.rerun()
                    
        with c_btn2:
            if st.button("🏠 종료 및 홈으로", use_container_width=True):
                st.session_state.app_state = 'SETUP'
                st.switch_page("app.py")

if __name__ == "__main__":
    main()
