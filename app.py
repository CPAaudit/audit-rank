import streamlit as st
import utils
import database
import time

# [Page Config]
st.set_page_config(page_title="Audit Rank | Home", page_icon="🏹", layout="wide")
utils.local_css()

def main():
    database.init_db()
    
    # Session State Init
    if 'username' not in st.session_state: st.session_state.username = None
    if 'user_role' not in st.session_state: st.session_state.user_role = None
    if 'exp' not in st.session_state: st.session_state.exp = 0.0
    if 'level' not in st.session_state: st.session_state.level = 1
    if 'solved_questions' not in st.session_state: st.session_state.solved_questions = set()
    if 'last_quiz_params' not in st.session_state: st.session_state.last_quiz_params = {}
    
    st.title("Audit Rank 🏹")
    
    # --- Login / Signup ---
    if not st.session_state.username:
        tab_login, tab_signup = st.tabs(["로그인", "회원가입"])
        
        with tab_login:
            with st.form("login_form"):
                uid = st.text_input("ID")
                upw = st.text_input("PW", type="password")
                if st.form_submit_button("로그인", type="primary", use_container_width=True):
                    user = database.verify_user(uid, upw)
                    if user:
                        st.session_state.username = user['username']
                        st.session_state.user_role = user['role']
                        st.session_state.level = user['level']
                        st.session_state.exp = user['exp']
                        st.success(f"환영합니다, {user['username']}님!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("ID 또는 비밀번호가 잘못되었습니다.")
                        
        with tab_signup:
            with st.form("signup_form"):
                new_uid = st.text_input("새 ID")
                new_upw = st.text_input("새 PW", type="password")
                new_upw_chk = st.text_input("PW 확인", type="password")
                
                if st.form_submit_button("회원가입"):
                    if not new_uid or not new_upw:
                        st.error("ID와 PW를 입력해주세요.")
                    elif new_upw != new_upw_chk:
                        st.error("비밀번호가 일치하지 않습니다.")
                    else:
                        if database.create_user(new_uid, new_upw):
                            st.success("가입 완료! 로그인 탭에서 로그인해주세요.")
                        else:
                            st.error("이미 존재하는 ID입니다.")
                            
    else:
        # --- Dashboard (Logged In) ---
        username = st.session_state.username
        role = st.session_state.user_role
        role_name = utils.ROLE_NAMES.get(role, role)
        
        st.markdown(f"""
        <div style="background-color: #3B4252; padding: 25px; border-radius: 12px; margin-bottom: 30px; border-left: 5px solid #88C0D0;">
            <h2 style="margin:0;">환영합니다, {username}님! 👋</h2>
            <p style="margin-top:10px; font-size:1.1rem; color:#D8DEE9;">
                현재 등급: <span style="color:#A3BE8C; font-weight:bold;">{role_name}</span> | 
                레벨: <span style="color:#EBCB8B; font-weight:bold;">{st.session_state.level}</span>
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # Navigation Cards
        c1, c2, c3 = st.columns(3)
        
        with c1:
            st.markdown("""
            <div class="card">
                <h3>📝 실전 훈련</h3>
                <p>실제 시험처럼 문제를 풀고 AI 채점과 피드백을 받아보세요.</p>
            </div>
            """, unsafe_allow_html=True)
            st.page_link("pages/1_📝_실전_훈련.py", label="훈련 시작하기", icon="🚀", use_container_width=True)
            
        with c2:
            st.markdown("""
            <div class="card">
                <h3>🏆 랭킹</h3>
                <p>다른 학습자들과 경쟁하며 동기를 부여받으세요.</p>
            </div>
            """, unsafe_allow_html=True)
            st.page_link("pages/2_🏆_랭킹.py", label="랭킹 확인하기", icon="🥇", use_container_width=True)
            
        with c3:
            st.markdown("""
            <div class="card">
                <h3>👤 내 정보</h3>
                <p>학습 통계와 오답 노트를 확인하고 약점을 보완하세요.</p>
            </div>
            """, unsafe_allow_html=True)
            st.page_link("pages/3_👤_내_정보.py", label="내 정보 바로가기", icon="📊", use_container_width=True)

        # Admin Link
        if role == 'ADMIN':
            st.divider()
            st.subheader("관리자 메뉴")
            st.page_link("pages/9_🛠️_관리자.py", label="관리자 페이지 이동", icon="🛠️")
            
        # Logout
        st.divider()
        if st.button("로그아웃", type="secondary"):
            st.session_state.username = None
            st.session_state.user_role = None
            st.rerun()

if __name__ == "__main__":
    main()
