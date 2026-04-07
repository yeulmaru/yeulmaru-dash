import streamlit as st

from utils.charts import ACCENT_COLOR

st.set_page_config(
    page_title="GS칼텍스 예울마루 대시보드",
    page_icon="🎭",
    layout="wide"
)

from utils.auth import check_password
check_password()

st.sidebar.markdown("## 🎭 GS칼텍스 예울마루")
st.sidebar.markdown("---")
st.sidebar.markdown("운영실적 종합 대시보드")

st.title("🎭 GS칼텍스 예울마루 공연 대시보드")

st.markdown("""
### 환영합니다!
GS칼텍스 예울마루의 공연 운영실적 대시보드입니다.  
좌측 사이드바(사이드 메뉴)를 통해 원하는 보고서를 선택하여 시각화된 데이터를 확인하세요.

---

### 메뉴 안내
1. 📊 **실시간 판매현황**: 당일 판매 및 점유율 확인, 일별 판매 추이
2. 💰 **공연실적**: 2025년도 각 공연별 예산, 지출, 매출 및 수익률
3. 📈 **연간실적**: 2012년부터 현재까지의 연간/월별/장르별 세부 실적 통계

---
""")

st.markdown(f"""
<style>
/* Streamlit 메인 화면 테마에 네온 그린 강조 */
div.stButton > button:first-child {{
    background-color: #0E1117;
    border-color: {ACCENT_COLOR};
    color: {ACCENT_COLOR};
}}
div.stButton > button:first-child:hover {{
    background-color: {ACCENT_COLOR};
    color: #0E1117;
}}
</style>
""", unsafe_allow_html=True)
