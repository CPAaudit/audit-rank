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
        return None

supabase = init_db()

# --- 사용자 로그인 및 정보 관리 ---
def login_user(username, password):
    """로그인 처리"""
    try:
        res = supabase.table("users").select("*").eq("username", username).execute()
        if not res.data: return None # 유저 없음
        
        user = res.data[0]
        if user['password'] == password:
            return [user['username'], user['password'], user['role'], user['level'], user['exp']]
        else:
            return None # 비번 불일치
    except Exception:
        return None

def register_user(username, password):
    """회원가입 처리"""
    try:
        # 중복 확인
        res = supabase.table("users").select("username").eq("username", username).execute()
        if res.data:
            return False # 이미 존재
            
        new_user = {
            "username": username, 
            "password": password, 
            "level": 1, 
            "exp": 0, 
            "role": "MEMBER"
        }
        supabase.table("users").insert(new_user).execute()
        return True
    except Exception:
        return False

def update_progress(username, level, exp):
    """경험치 저장"""
    try:
        supabase.table("users").update({"level": level, "exp": exp}).eq("username", username).execute()
    except Exception:
        pass

# --- 오답노트 관리 (수정됨: 내 답안 제외) ---
def save_review_note(username, part, chapter, standard, title, question, model_ans, explanation, score):
    """오답노트 저장"""
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
        supabase.table("review_notes").insert(data).execute()
    except Exception as e:
        print(f"Error: {e}")

def get_user_review_notes(username):
    """내 오답노트 조회"""
    try:
        res = supabase.table("review_notes").select("*").eq("username", username).order("created_at", desc=True).execute()
        return pd.DataFrame(res.data)
    except Exception:
        return pd.DataFrame()

def delete_review_note(note_id):
    """오답노트 삭제"""
    try:
        supabase.table("review_notes").delete().eq("id", note_id).execute()
    except Exception:
        pass
    
def get_leaderboard_data():
    """랭킹 조회"""
    try:
        res = supabase.table("users").select("username, role, level, exp").order("exp", desc=True).limit(10).execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame()

def get_all_users():
    """관리자용 유저 전체 조회"""
    try:
        res = supabase.table("users").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame()
        
def update_user_role(target_user, new_role):
    """관리자용 등급 변경"""
    try:
        supabase.table("users").update({"role": new_role}).eq("username", target_user).execute()
    except:
        pass

# --- 추가된 함수 (My Profile 및 통계용) ---
def save_quiz_result(username, standard, score):
    """퀴즈 결과 저장"""
    try:
        data = {
            "username": username,
            "standard_code": standard,
            "score": score,
            "created_at": datetime.now().isoformat()
        }
        supabase.table("quiz_history").insert(data).execute()
    except Exception as e:
        print(f"Save quiz error: {e}")

def get_user_stats(username):
    """사용자 통계 (Total XP, 최근 기록)"""
    stats = {'total_score': 0, 'recent_history': []}
    try:
        # 1. Total XP (users 테이블에서)
        user_res = supabase.table("users").select("exp").eq("username", username).execute()
        if user_res.data:
            stats['total_score'] = user_res.data[0]['exp']
            
        # 2. 최근 기록 (quiz_history 테이블에서)
        # 퀴즈 히스토리 테이블이 없으면 에러가 날 수 있으므로 try-except 처리
        hist_res = supabase.table("quiz_history").select("standard_code, score, created_at").eq("username", username).order("created_at", desc=True).limit(10).execute()
        
        if hist_res.data:
            for item in hist_res.data:
                # 날짜 포맷팅 (YYYY-MM-DD HH:MM)
                dt = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
                fmt_date = dt.strftime("%Y-%m-%d %H:%M")
                stats['recent_history'].append([item['standard_code'], item['score'], fmt_date])
                
    except Exception as e:
        print(f"Stats error: {e}")
        
    return stats

def get_user_history_df(username):
    """전체 학습 이력 (그래프용)"""
    try:
        res = supabase.table("quiz_history").select("*").eq("username", username).execute()
        return pd.DataFrame(res.data)
    except Exception:
        return pd.DataFrame()