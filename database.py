import streamlit as st
from supabase import create_client
import pandas as pd
from datetime import datetime

# 1. Supabase 연결 초기화
def init_db():
    try:
        url = st.secrets["SUPABASE"]["URL"]
        key = st.secrets["SUPABASE"]["KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Supabase Connection Error: {e}")
        return None

# --- Auth & User Management ---

def login_user(email, password):
    """로그인 처리 (Supabase Auth)"""
    try:
        client = init_db()
        # 1. Auth Login
        res = client.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            if res.session:
                st.session_state['sb_session'] = res.session
            return _get_combined_profile(client, res.user)
    except Exception as e:
        print(f"Login Error: {e}")
        return None
    return None

def register_user(email, password, username):
    """회원가입 처리 (Supabase Auth + Public Profile)"""
    try:
        client = init_db()
        
        # 0. Check Username Duplication (Public Table)
        if _check_username_exists(client, username):
            return "USERNAME_EXISTS"

        # 1. Auth Sign Up
        res = client.auth.sign_up({
            "email": email, 
            "password": password,
            "options": {
                "data": {"username": username} # Store in metadata too
            }
        })
        
        if res.user:
            if res.session:
                st.session_state['sb_session'] = res.session
            # 2. Create Public Profile
            # Note: valid user ID is available only if email is confirmed or auto-confirmed.
            # We assume auto-confirm for dev, otherwise we need to handle "check email" flow.
            # We try to insert into users table.
            if res.user.identities and len(res.user.identities) > 0:
                 _create_public_profile(client, res.user.id, email, username)
                 return "SUCCESS"
            else:
                 # If email confirmation is required, user.identities might be empty until confirmed?
                 # Actually identity object is usually present.
                 # If "Email confirmation required", we still return SUCCESS but tell user to check email.
                 return "CHECK_EMAIL"
            return "SUCCESS"
    except Exception as e:
        print(f"Register Error: {e}")
        return f"ERROR: {str(e)}"
    return "ERROR"

def login_with_oauth(provider):
    """OAuth 로그인 URL 생성"""
    try:
        client = init_db()
        # Construct callback URL. 
        # Local: http://localhost:8501
        # Cloud: https://your-app.streamlit.app
        # We need to rely on the URL set in Supabase Console, but we can pass 'redirect_to'.
        # For now let's try to detect or ask user. Assuming localhost for dev or standard cloud.
        # Streamlit doesn't easily give current public URL.
        # We will use the redirect URL configured in Supabase.
        
        res = client.auth.sign_in_with_oauth({
            "provider": provider,
            "options": {
                "redirect_to": f"{st.secrets['SUPABASE']['REDIRECT_URL']}" if 'REDIRECT_URL' in st.secrets['SUPABASE'] else None
            }
        })
        return res.url
    except Exception as e:
        print(f"OAuth Error: {e}")
        return None

def exchange_code_for_session(code):
    """Callback code exchange"""
    try:
        client = init_db()
        res = client.auth.exchange_code_for_session({"auth_code": code})
        if res.user:
            # Check/Create Profile
            profile = _get_combined_profile(client, res.user)
            if not profile:
                # First time social login -> Create Profile
                # Use metadata or email prefix as default username
                meta = res.user.user_metadata
                username = meta.get('name') or meta.get('full_name') or res.user.email.split('@')[0]
                # Ensure unique
                base_name = username
                cnt = 1
                while _check_username_exists(client, username):
                    username = f"{base_name}_{cnt}"
                    cnt += 1
                
                _create_public_profile(client, res.user.id, res.user.email, username)
                return _get_combined_profile(client, res.user)
            return profile
    except Exception as e:
        print(f"Exchange Error: {e}")
    return None

def _check_username_exists(client, username):
    res = client.table("users").select("username").eq("username", username).execute()
    return len(res.data) > 0

def _create_public_profile(client, user_id, email, username):
    # Public Profile Creation with strict Auth ID linking
    new_user = {
        "id": user_id,
        "username": username,
        "role": "MEMBER",
        "level": 1,
        "exp": 0,
        # "email": email # Add if schema supports
    }
    # Try inserting.
    try:
        client.table("users").insert(new_user).execute()
    except Exception as e:
        print(f"Profile Creation Error: {e}")

def _get_combined_profile(client, auth_user):
    # Robust profile fetching via Auth ID (UUID)
    try:
        # Prmary: Match by UUID (Foreign Key)
        res = client.table("users").select("*").eq("id", auth_user.id).execute()
        if res.data:
            profile = res.data[0]
            return {
                "username": profile['username'],
                "role": profile.get('role', 'MEMBER'),
                "level": profile.get('level', 1),
                "exp": profile.get('exp', 0),
                "email": auth_user.email,
                "auth_id": auth_user.id
            }
    except Exception as e:
        print(f"Profile Fetch Error: {e}")
    
    # Fallback/Legacy: If UUID match fails (e.g. migration lag), try username
    # This might be removed later for stricter security.
    username = auth_user.user_metadata.get('username')
    if not username:
        username = auth_user.email.split('@')[0] 

    try:
        res = client.table("users").select("*").eq("username", username).execute()
        if res.data:
            profile = res.data[0]
            # Consider auto-healing (fixing the ID) here if needed
            return {
                "username": profile['username'],
                "role": profile.get('role', 'MEMBER'),
                "level": profile.get('level', 1),
                "exp": profile.get('exp', 0),
                "email": auth_user.email,
                "auth_id": auth_user.id
            }
    except: pass
    
    # If really no profile found, return default
    return {
        "username": username,
        "role": "MEMBER",
        "level": 1,
        "exp": 0,
        "email": auth_user.email,
        "auth_id": auth_user.id
    }

# --- Existing Functions (Unchanged Logic) ---

def update_progress(username, level, exp):
    try:
        # Update based on username
        init_db().table("users").update({"level": level, "exp": exp}).eq("username", username).execute()
    except: pass

def save_review_note(username, title, user_answer, score, user_id=None):
    try:
        client = init_db()
        
        # Apply Auth Session if available
        if 'sb_session' in st.session_state and st.session_state.sb_session:
            try:
                client.auth.set_session(
                    st.session_state.sb_session.access_token, 
                    st.session_state.sb_session.refresh_token
                )
            except: pass # Session might be expired

        question_id = None
        
        # Look up Question ID
        if title:
            try:
                # If audit_questions is empty, this will fail to find ID, question_id remains None.
                # User is aware.
                q_res = client.table("audit_questions").select("id").eq("question_title", title).execute()
                if q_res.data:
                    question_id = q_res.data[0]['id']
            except: pass

        if question_id is None:
             st.warning(f"Warning: Question ID not found for title '{title}'. Note might be saved without link.")

        data = {
            # "username": username, # Removed: Column does not exist
            "user_id": user_id,
            "question_id": question_id,
            # "explanation" column renamed to "user_answer"
            "user_answer": user_answer, 
            "score": score,
            "created_at": datetime.now().isoformat()
        }
        client.table("review_notes").insert(data).execute()
        return True
    except Exception as e: 
        st.error(f"Save Note Error: {e}")
        print(f"Error: {e}")
        return False

def get_user_review_notes(username, user_id=None):
    try:
        client = init_db()
        
        # Resolve user_id if missing
        if not user_id and username:
            try:
                u_res = client.table("users").select("id").eq("username", username).execute()
                if u_res.data:
                    user_id = u_res.data[0]['id']
            except: pass
            
        if not user_id:
            # Cannot fetch notes without user_id
            return pd.DataFrame()

        # Join with audit_questions
        query = client.table("review_notes").select("*, audit_questions(*)").order("created_at", desc=True)
        query = query.eq("user_id", user_id)
             
        res = query.execute()
        data = res.data
        
        flattened = []
        for item in data:
            q = item.get('audit_questions') or {} 
            
            flat = item.copy()
            if 'audit_questions' in flat: del flat['audit_questions']
            
            # Map Question Data (from audit_questions)
            flat['part'] = q.get('part', 'Unknown/Deleted')
            flat['chapter'] = q.get('chapter', 'Unknown')
            flat['standard_code'] = q.get('standard', 'Unknown')
            flat['question_title'] = q.get('question_title', 'Unknown Title')
            flat['question_description'] = q.get('question_description', '(문제 내용 없음)')
            flat['model_answer'] = q.get('model_answer', [])
            flat['explanation'] = q.get('explanation', "해설 없음") # Official Explanation
            
            # item already has 'user_answer' (renamed from explanation in DB)
            # We ensure it's accessible as 'user_answer'
            # If the DB return key is 'user_answer', it's already in 'flat'.
            
            flattened.append(flat)
            
        return pd.DataFrame(flattened)
    except Exception as e: 
        print(f"Fetch Error: {e}")
        return pd.DataFrame()

def delete_review_note(note_id):
    try:
        init_db().table("review_notes").delete().eq("id", note_id).execute()
    except: pass

def update_user_role(username, new_role):
    try:
        init_db().table("users").update({"role": new_role}).eq("username", username).execute()
        return True
    except Exception as e:
        print(f"Role Update Error: {e}")
        return False

def fetch_all_questions():
    """Fetches all questions from the audit_questions table."""
    try:
        res = init_db().table("audit_questions").select("*").order("id", desc=False).execute()
        return res.data
    except Exception as e:
        print(f"Error fetching questions: {e}")
        return []

def add_question(data):
    """Inserts a new question into audit_questions."""
    try:
        init_db().table("audit_questions").insert(data).execute()
        return True
    except Exception as e:
        print(f"Add Question Error: {e}")
        return False

def update_question(q_id, data):
    """Updates an existing question."""
    try:
        # Prevent ID update just in case
        if 'id' in data: del data['id'] 
        init_db().table("audit_questions").update(data).eq("id", q_id).execute()
        return True
    except Exception as e:
        print(f"Update Question Error: {e}")
        return False

def delete_question(q_id):
    """Deletes a question."""
    try:
        init_db().table("audit_questions").delete().eq("id", q_id).execute()
        return True
    except Exception as e:
        print(f"Delete Question Error: {e}")
        return False


def get_leaderboard_data():
    try:
        res = init_db().table("users").select("username, role, level, exp").order("exp", desc=True).limit(10).execute()
        return pd.DataFrame(res.data)
    except: return pd.DataFrame()

def get_all_users():
    try:
        res = init_db().table("users").select("*").execute()
        return pd.DataFrame(res.data)
    except: return pd.DataFrame()

def get_user_stats(username):
    stats = {'total_score': 0}
    try:
        user_res = init_db().table("users").select("exp").eq("username", username).execute()
        if user_res.data:
            stats['total_score'] = user_res.data[0]['exp']
    except: pass
    return stats

# Alias
verify_user = login_user
create_user = register_user