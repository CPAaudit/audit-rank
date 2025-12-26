import streamlit as st
import database
import utils
import json

# [초기 설정]
st.set_page_config(page_title="오답노트 | Audit Rank", page_icon="📓", layout="wide")
utils.local_css()

def main():
    if 'username' not in st.session_state or not st.session_state.username:
        st.warning("로그인이 필요합니다.")
        st.stop()
        
    username = st.session_state.username
    role = st.session_state.user_role
    is_paid_or_admin = role in ['PRO', 'ADMIN']
    
    st.title("📓 오답 노트")
    
    if not is_paid_or_admin:
        st.warning("🔒 오답 노트는 '등록공인회계사' 전용 기능입니다.")
        st.info("문제 풀기에서 저장한 오답 노트를 이곳에서 복습할 수 있습니다.")
        return

    # Load Notes (Pass user_id if available)
    notes_df = database.get_user_review_notes(username, user_id=st.session_state.get('user_id'))
    
    if notes_df.empty:
        st.info("저장된 오답 노트가 없습니다. '문제 풀기'에서 오답 노트를 저장해보세요!")
        return

    # Preprocess
    notes_df['part'] = notes_df['part'].fillna('Unknown')
    notes_df['chapter'] = notes_df['chapter'].fillna('Unknown')
    
    parts = sorted(notes_df['part'].unique())
    
    for part in parts:
        with st.expander(f"📂 {part}", expanded=False):
            part_df = notes_df[notes_df['part'] == part]
            chapters = sorted(part_df['chapter'].unique(), key=utils.get_chapter_sort_key)
            
            for chap in chapters:
                st.markdown(f"**[{chap}]**")
                chap_df = part_df[part_df['chapter'] == chap]
                
                for idx, row in chap_df.iterrows():
                    m_ans = row['model_answer']
                    if not m_ans: m_ans = "데이터 없음"
                    
                    # Model Answer Formatting
                    if isinstance(m_ans, list):
                            m_ans_str = "• " + "<br>• ".join(m_ans)
                    elif isinstance(m_ans, str) and m_ans.startswith('['):
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

                    with st.expander(f"[{row['standard_code']}] {row['question_title']} (점수: {row['score']})"):
                        st.markdown(f"**Q. {row['question_description']}**")
                        
                        # User Answer
                        u_ans = row['user_answer'] if row['user_answer'] else "(내용 없음)"
                        st.markdown(f"""
                        <div style="background-color: #4C566A; padding: 10px; border-radius: 5px; margin-bottom: 10px;">
                            <span style="color: #D8DEE9; font-size: 0.9em;">✍️ 내 답안:</span><br>
                            {u_ans}
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Explanation / Model Answer
                        if row.get('explanation'):
                                st.info(f"💡 해설: {row['explanation']}")
                        
                        st.markdown(f"""
                        <div style="background-color: #3B4252; padding: 10px; border-radius: 5px; border-left: 4px solid #A3BE8C;">
                            <span style="color: #A3BE8C; font-weight: bold;">✅ 모범 답안</span><br>
                            {m_ans_str}
                        </div>
                        """, unsafe_allow_html=True)
                        
                        st.caption(f"작성일: {row['created_at']}")
                        
                        if st.button("삭제", key=f"del_note_{row['id']}"):
                            database.delete_review_note(row['id'])
                            st.rerun()

if __name__ == "__main__":
    main()
