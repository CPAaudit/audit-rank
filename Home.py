import streamlit as st
import utils
import database
import time

# [Page Config]
st.set_page_config(page_title="Audit Rank | Home", page_icon="🏹", layout="wide")
utils.local_css()

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
    if 'user_id' not in st.session_state: st.session_state.user_id = None
    if 'user_role' not in st.session_state: st.session_state.user_role = None
    if 'exp' not in st.session_state: st.session_state.exp = 0.0
    if 'level' not in st.session_state: st.session_state.level = 1
    if 'solved_questions' not in st.session_state: st.session_state.solved_questions = set()
    if 'last_quiz_params' not in st.session_state: st.session_state.last_quiz_params = {}
    
    # [OAuth Callback Handling] - REMOVED

    st.title("Audit Rank 🏹")
    
    # --- Login / Signup ---
    if not st.session_state.username:
        tab_login, tab_signup = st.tabs(["로그인", "회원가입"])
        
        with tab_login:
            st.subheader("이메일로 로그인")
            with st.form("login_form"):
                email = st.text_input("이메일 (Email)")
                upw = st.text_input("비밀번호 (PW)", type="password")
                
                if st.form_submit_button("로그인", type="primary", use_container_width=True):
                    user = database.login_user(email, upw)
                    if user:
                        st.session_state.username = user['username']
                        st.session_state.user_id = user.get('auth_id')
                        st.session_state.user_role = user.get('role', 'MEMBER')
                        st.session_state.level = user.get('level', 1)
                        st.session_state.exp = user.get('exp', 0)
                        st.success(f"환영합니다, {user['username']}님!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("이메일 또는 비밀번호가 잘못되었습니다.")


        with tab_signup:
            st.warning("⚠️ 기존 ID 사용자는 이메일로 새로 가입해야 합니다.")
            with st.form("signup_form"):
                new_email = st.text_input("이메일 (Email)")
                new_username = st.text_input("닉네임 (Username)")
                new_upw = st.text_input("비밀번호 (PW)", type="password")
                new_upw_chk = st.text_input("비밀번호 확인", type="password")
                
                if st.form_submit_button("회원가입"):
                    if not new_email or not new_upw or not new_username:
                        st.error("모든 항목을 입력해주세요.")
                    elif new_upw != new_upw_chk:
                        st.error("비밀번호가 일치하지 않습니다.")
                    else:
                        res = database.register_user(new_email, new_upw, new_username)
                        if res == "SUCCESS":
                            st.success("가입 완료! 로그인 탭에서 로그인해주세요. (이메일 확인이 필요할 수 있습니다)")
                        elif res == "CHECK_EMAIL":
                            st.success("가입 접수 완료! 이메일함을 확인하여 인증 링크를 클릭해주세요.")
                        elif res == "USERNAME_EXISTS":
                            st.error("이미 사용 중인 닉네임입니다.")
                        else:
                            st.error(f"회원가입 오류: {res}")
                            
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
                <h3>📝 문제 풀기</h3>
                <p>실제 시험처럼 문제를 풀고 AI 채점과 피드백을 받아보세요.</p>
            </div>
            """, unsafe_allow_html=True)
            st.page_link("pages/1_📝_문제_풀기.py", label="문제 풀기 시작", icon="🚀", use_container_width=True)
            
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
        if st.session_state.user_role == 'ADMIN':
            st.divider()
            st.subheader("관리자 메뉴")
            st.page_link("pages/9_⚙️_관리자.py", label="관리자 페이지 이동", icon="⚙️")
            
        # Logout (Clear Session)
        st.divider()
        if st.button("로그아웃", type="secondary"):
            st.session_state.username = None
            st.session_state.user_id = None
            st.session_state.user_role = None
            # Do we need to sign out from Supabase client too? 
            # Client usually handles it, but creating new client instance clears local state mostly in Streamlit context.
            # Explicit sign out is good practice but not strictly mandatory for simple token based auth in Streamlit session.
            # client.auth.sign_out() # Optional
            st.rerun()

if __name__ == "__main__":
    main()
