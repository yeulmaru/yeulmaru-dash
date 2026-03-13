import streamlit as st

def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        pw = st.text_input("비밀번호를 입력하세요", type="password")
        if pw == st.secrets.get("password", ""):
            st.session_state.authenticated = True
            st.rerun()
        elif pw:
            st.error("비밀번호가 틀렸습니다")
        st.stop()
