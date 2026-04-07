import streamlit as st

st.set_page_config(page_title="공연현황", page_icon="🎭", layout="wide")

from utils.auth import check_password
check_password()

st.title("🎭 공연현황")
st.info("🚧 준비중입니다. 곧 돌아올게요.")
