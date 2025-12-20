
import streamlit as st
import utils
import database
import json

# [초기 설정]
st.set_page_config(page_title="내 정보 | Audit Rank", page_icon="👤", layout="wide")
utils.local_css()

def main():
    if 'username' not in st.session_state or not st.session_state.username:
        st.warning("로그인이 필요합니다.")
        st.stop()
        
    st.title("📊 학습 대시보드 (Dashboard)")
    username = st.session_state.username
    role = st.session_state.user_role
    
    is_paid_or_admin = role in ['PRO', 'ADMIN']
    
    # Stats Load
    stats = database.get_user_stats(username)
    import pandas as pd
    df_all = pd.DataFrame()  # quiz_history 테이블 제거됨
    
    # Header
    c_profile, c_metrics = st.columns([1, 2])
    
    with c_profile:
        st.markdown(f"""
        <div style="background-color: #3B4252; padding: 20px; border-radius: 12px; border: 1px solid #434C5E; text-align: center;">
            <img src="https://api.dicebear.com/7.x/avataaars/svg?seed={username}" width="100" style="border-radius: 50%; margin-bottom: 10px;">
            <div style="font-size: 1.5rem; font-weight: bold; color: #ECEFF4;">{username}</div>
            <div style="font-size: 0.9rem; color: #D8DEE9; margin-bottom: 5px;">{utils.ROLE_NAMES.get(role, role)}</div>
            <div style="background-color: #5E81AC; color: white; padding: 4px 12px; border-radius: 15px; display: inline-block; font-size: 0.8rem;">
                Lv. {st.session_state.level}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
    with c_metrics:
        total_xp = stats['total_score']
        total_solved = len(df_all) if not df_all.empty else 0
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

    tab_dash, tab_notes, tab_hist = st.tabs(["📊 분석 & 차트", "📝 오답 노트", "📜 전체 이력"])

    with tab_dash:
        if df_all.empty:
            st.info("아직 데이터가 충분하지 않습니다. 문제를 풀어보세요!")
        else:
            db_data = utils.load_db()
            std_map = {}
            for q in db_data:
                std_map[q['standard']] = {'part': q['part'], 'chapter': q['chapter']}
            
            df_all['part'] = df_all['standard_code'].map(lambda x: std_map.get(x, {}).get('part', 'Unknown'))
            df_all['chapter'] = df_all['standard_code'].map(lambda x: std_map.get(x, {}).get('chapter', 'Unknown'))
            
            c_chart1, c_chart2 = st.columns(2)
            
            with c_chart1:
                st.subheader("🎯 영역별 강점 분석")
                part_scores = df_all.groupby('part')['score'].mean().to_dict()
                fig_skill = utils.draw_skill_chart(part_scores)
                if fig_skill: st.pyplot(fig_skill, use_container_width=True)
                else: st.info("데이터 부족")
                
            with c_chart2:
                st.subheader("📅 최근 성취도")
                recent_df = df_all.sort_values("created_at").tail(10)
                st.line_chart(recent_df, x='created_at', y='score', color='#5E81AC')
            
            st.subheader("💊 집중 보완이 필요한 챕터")
            chap_avg = df_all.groupby('chapter')['score'].mean().sort_values().head(3)
            for ch, sc in chap_avg.items():
                st.markdown(f"- **{ch}**: 평균 {sc:.1f}점")

    with tab_notes:
        if not is_paid_or_admin:
            st.warning("🔒 오답 노트는 '등록공인회계사' 전용 기능입니다.")
        else:
            notes_df = database.get_user_review_notes(username)
            if notes_df.empty:
                st.info("오답 노트가 비어있습니다.")
            else:
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

if __name__ == "__main__":
    main()
