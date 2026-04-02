import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.data_loader import load_25_performance
from utils.charts import COLORS, apply_common_layout

st.set_page_config(page_title="2025 공연사업 실적", page_icon="💰", layout="wide")

from utils.auth import check_password
check_password()

st.title("💰 2025 공연사업 실적")

st.cache_data.clear()
df = load_25_performance()

if df is None or df.empty:
    st.error("데이터를 정상적으로 불러오지 못했습니다. `25공연` 시트의 형식을 확인해주세요.")
    st.stop()

# ── KPI 계산 ──
tot_budget = df['예산'].sum() if '예산' in df.columns else 0
tot_expense = df['지출'].sum() if '지출' in df.columns else 0
tot_revenue = df['매출'].sum() if '매출' in df.columns else 0
tot_audience = df['총관인원'].sum() if '총관인원' in df.columns else 0
tot_diff = tot_revenue - tot_expense
tot_profit_rate = (tot_diff / tot_expense * 100) if tot_expense != 0 else 0
diff_color = COLORS['primary'] if tot_diff >= 0 else COLORS['danger']

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 상단 KPI 메트릭
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("총 예산", f"{int(round(tot_budget / 10000)):,}만원")
col2.metric("총 지출", f"{int(round(tot_expense / 10000)):,}만원")
col3.metric("총 매출", f"{int(round(tot_revenue / 10000)):,}만원")
col4.metric("총 관객수", f"{int(tot_audience):,}명")

# 수익율 + 차액 색상 표시
diff_sign = "+" if tot_diff >= 0 else ""
col5.markdown(
    f"""<div style="font-size:14px;color:#AAA;">전체 수익율</div>
    <div style="font-size:24px;font-weight:700;">{tot_profit_rate:.1f}%</div>
    <div style="font-size:13px;color:{diff_color};font-weight:600;">
    차액 {diff_sign}{int(round(tot_diff / 10000)):,}만원</div>""",
    unsafe_allow_html=True,
)

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 공연별 예산·지출·매출 비교 (그룹 막대)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.subheader("📊 공연별 예산·지출·매출 비교")

if all(col in df.columns for col in ['공연명', '예산', '지출', '매출']):
    chart1 = df[['공연명', '예산', '지출', '매출', '차액']].copy()
    for c in ['예산', '지출', '매출', '차액']:
        chart1[c + '_만'] = (chart1[c] / 10000).round(0).astype(int)

    fig1 = go.Figure()
    fig1.add_trace(go.Bar(
        name='예산', x=chart1['공연명'], y=chart1['예산_만'],
        marker_color=COLORS['neutral'],
        hovertemplate='%{x}<br>예산: %{y:,}만원<extra></extra>',
    ))
    fig1.add_trace(go.Bar(
        name='지출', x=chart1['공연명'], y=chart1['지출_만'],
        marker_color=COLORS['danger'],
        customdata=chart1['차액_만'],
        hovertemplate='%{x}<br>지출: %{y:,}만원<br>차액: %{customdata:,}만원<extra></extra>',
    ))
    fig1.add_trace(go.Bar(
        name='매출', x=chart1['공연명'], y=chart1['매출_만'],
        marker_color=COLORS['primary'],
        customdata=chart1['차액_만'],
        hovertemplate='%{x}<br>매출: %{y:,}만원<br>차액: %{customdata:,}만원<extra></extra>',
    ))
    fig1.update_layout(
        barmode='group',
        xaxis_title="", yaxis_title="금액 (만원)",
        xaxis_tickangle=-45,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )
    fig1 = apply_common_layout(fig1)
    fig1.update_layout(margin=dict(l=20, r=20, t=60, b=100))
    st.plotly_chart(fig1, use_container_width=True)

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 하단: 도넛 + 수익율 랭킹
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
col_left, col_right = st.columns(2)

# ── 카테고리별 관객 비율 도넛 ──
with col_left:
    st.subheader("🍩 카테고리별 관객 비율")
    if '카테고리' in df.columns and '총관인원' in df.columns:
        cat_audience = df.groupby('카테고리')['총관인원'].sum().reset_index()
        cat_audience = cat_audience[cat_audience['총관인원'] > 0]

        donut_colors = [COLORS['primary'], COLORS['secondary'], COLORS['danger'], COLORS['neutral']]
        fig2 = px.pie(
            cat_audience, values='총관인원', names='카테고리', hole=0.45,
            color_discrete_sequence=donut_colors,
        )
        fig2.update_traces(
            textinfo='label+percent',
            textfont_size=13,
            hovertemplate='%{label}<br>관객: %{value:,}명<br>비율: %{percent}<extra></extra>',
        )
        fig2 = apply_common_layout(fig2)
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("카테고리 또는 총관인원 데이터가 없습니다.")

# ── 수익율 랭킹 수평 막대 ──
with col_right:
    st.subheader("📈 수익율 랭킹")
    if '수익율' in df.columns and '공연명' in df.columns:
        rank_df = df[['공연명', '수익율']].copy()
        rank_df = rank_df.sort_values('수익율', ascending=True)

        bar_colors = [COLORS['primary'] if v >= 0 else COLORS['danger'] for v in rank_df['수익율']]

        fig3 = go.Figure()
        fig3.add_trace(go.Bar(
            x=rank_df['수익율'], y=rank_df['공연명'],
            orientation='h',
            marker_color=bar_colors,
            text=[f"{v:.1f}%" for v in rank_df['수익율']],
            textposition='auto',
            hovertemplate='%{y}<br>수익율: %{x:.1f}%<extra></extra>',
        ))
        fig3.add_vline(x=0, line_dash="dash", line_color="white", line_width=1)
        fig3.update_layout(xaxis_title="수익율 (%)", yaxis_title="")
        fig3 = apply_common_layout(fig3)
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("수익율 데이터가 없습니다.")
