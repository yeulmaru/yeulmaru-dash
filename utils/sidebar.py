import base64
from pathlib import Path
import streamlit as st


@st.cache_data
def _load_logo_b64():
    p = Path(__file__).resolve().parent.parent / "assets" / "logo_yeulmaru.png"
    if p.exists():
        return base64.b64encode(p.read_bytes()).decode()
    return None


def render_sidebar():
    """공통 사이드바: 로고 + 타이틀 + 커스텀 페이지 메뉴"""
    # 자동 생성 페이지 메뉴 숨김
    st.markdown(
        "<style>section[data-testid='stSidebarNav']{display:none!important}</style>",
        unsafe_allow_html=True,
    )

    logo_b64 = _load_logo_b64()
    if logo_b64:
        logo_html = (
            f'<img src="data:image/png;base64,{logo_b64}" '
            f'style="height:1.2em;vertical-align:middle;margin-right:6px;">'
        )
    else:
        logo_html = "🎭"

    with st.sidebar:
        st.markdown(
            f'<div style="margin-bottom:12px;">'
            f'<h3 style="margin:0 0 4px 0;">{logo_html} GS칼텍스 예울마루</h3>'
            f'<p style="color:#aaa;margin:0 0 12px 0;font-size:13px;">'
            f'운영실적 종합 대시보드</p>'
            f'<hr style="border-color:#333;margin:0 0 8px 0;"></div>',
            unsafe_allow_html=True,
        )
        st.page_link("app.py", label="공지 및 안내")
        st.page_link("pages/1_사업현황.py", label="사업현황")
        st.page_link("pages/3_연간현황.py", label="연간현황")
        st.page_link("pages/4_일일입력.py", label="일일입력")
