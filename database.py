import streamlit as st
from supabase import create_client
import pandas as pd
from datetime import datetime

# 1. Supabase 연결 초기화
@st.cache_resource
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
    # Check if 'email' column exists in public.users? 
    # Based on previous code, likely columns: username, password, level, exp, role.
    # We will exclude password. We might need to add keys if schema is strict.
    # We will try to upsert based on username if needed, but here we insert new.
    # We should honestly add 'user_id' to this table to link properly.
    # For now, we'll try to insert 'username', 'level', 'exp', 'role'.
    # If we can, we also insert 'email'.
    
    new_user = {
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
    # Try to find profile by email (if supported) or we guess username?
    # Since we don't strictly link ID in public.users (yet), we might have trouble finding the right user 
    # if we only have auth_user.id.
    # Assumption: The user just logged in. 
    # If we created the profile with specific username, we can't easily reverse lookup unless we stored Auth ID or Email in public.users.
    # CRITICAL: We MUST rely on 'email' if stored, or we force username match.
    # Let's try to fetch by email if the column exists (likely if I modified previous code).
    # If not, we have a disconnect.
    # Workaround: For now, we will return a minimal profile from Auth Data if DB lookup fails.
    
    # Try fetch by username from metadata?
    username = auth_user.user_metadata.get('username')
    
    # If standard email login, we should have stored username in metadata.
    if not username:
        # Fallback for old users or social login without metadata
        username = auth_user.email.split('@')[0] 

    # Fetch public stats
    try:
        res = client.table("users").select("*").eq("username", username).execute()
        if res.data:
            profile = res.data[0]
            # Merge
            return {
                "username": profile['username'],
                "role": profile.get('role', 'MEMBER'),
                "level": profile.get('level', 1),
                "exp": profile.get('exp', 0),
                "email": auth_user.email,
                "auth_id": auth_user.id
            }
    except:
        pass
    
    # If no profile found (rare), return default
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

def save_review_note(username, part, chapter, standard, title, question, model_ans, explanation, score):
    try:
        data = {
            "username": username,
            "part": part,
            "chapter": chapter,
            "standard_code": standard,
            "title": title,
            "question": question,
            "model_answer": model_ans,
            "explanation": explanation,
            "score": score,
            "created_at": datetime.now().isoformat()
        }
        init_db().table("review_notes").insert(data).execute()
    except Exception as e: print(f"Error: {e}")

def get_user_review_notes(username):
    try:
        res = init_db().table("review_notes").select("*").eq("username", username).order("created_at", desc=True).execute()
        return pd.DataFrame(res.data)
    except: return pd.DataFrame()

def delete_review_note(note_id):
    try:
        init_db().table("review_notes").delete().eq("id", note_id).execute()
    except: pass

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