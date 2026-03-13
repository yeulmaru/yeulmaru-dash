import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.data_loader import load_25_performance
from utils.charts import COLORS, apply_common_layout

st.set_page_config(page_title="2025 공연사업 실적", page_icon="💰", layout="wide")

st.title("💰 2025 공연사업 실적")

df = load_25_performance()

if df is None or df.empty:
    st.error("데이터를 정상적으로 불러오지 못했습니다. `25공연` 시트의 형식을 확인해주세요.")
    st.stop()

tot_budget = df['예산'].sum() if '예산' in df.columns else 0
tot_expense = df['지출'].sum() if '지출' in df.columns else 0
tot_revenue = df['매출'].sum() if '매출' in df.columns else 0
tot_audience = df['계'].sum() if '계' in df.columns else 0

tot_profit_rate = ((tot_revenue - tot_expense) / tot_expense * 100) if tot_expense != 0 else 0

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("총 예산", f"{int(tot_budget/10000):,}만원")
with col2:
    st.metric("총 지출", f"{int(tot_expense/10000):,}만원")
with col3:
    st.metric("총 매출", f"{int(tot_revenue/10000):,}만원")
with col4:
    st.metric("총 관객수", f"{int(tot_audience):,}명")
with col5:
    st.metric("전체 수익율", f"{tot_profit_rate:.1f}%")

st.markdown("---")

st.subheader("📊 공연별 예산·지출·매출 비교")
fig1 = go.Figure()
if all(col in df.columns for col in ['공연명', '예산', '지출', '매출']):
    fig1.add_trace(go.Bar(name='예산', x=df['공연명'], y=df['예산'], marker_color='gray'))
    fig1.add_trace(go.Bar(name='지출', x=df['공연명'], y=df['지출'], marker_color=COLORS['danger']))
    fig1.add_trace(go.Bar(name='매출', x=df['공연명'], y=df['매출'], marker_color=COLORS['primary']))
    fig1.update_layout(barmode='group', xaxis_title="공연명", yaxis_title="금액 (원)")
    fig1 = apply_common_layout(fig1)
    st.plotly_chart(fig1, use_container_width=True)

st.markdown("---")

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("🍩 카테고리별 관객 비율")
    if '카테고리' in df.columns and '계' in df.columns:
        cat_audience = df.groupby('카테고리')['계'].sum().reset_index()
        fig2 = px.pie(cat_audience, values='계', names='카테고리', hole=0.4)
        fig2.update_traces(marker=dict(colors=[COLORS['primary'], COLORS['secondary'], COLORS['danger'], COLORS['neutral']]))
        fig2 = apply_common_layout(fig2)
        st.plotly_chart(fig2, use_container_width=True)

with col_right:
    st.subheader("📈 수익율 랭킹")
    if '수익율1' in df.columns and '공연명' in df.columns:
        df_sorted = df.sort_values(by='수익율1', ascending=True)
        fig3 = go.Figure()
        
        colors = [COLORS['primary'] if val >= 0 else COLORS['danger'] for val in df_sorted['수익율1']]
        
        fig3.add_trace(go.Bar(
            x=df_sorted['수익율1'],
            y=df_sorted['공연명'],
            orientation='h',
            marker_color=colors,
            text=[f"{val:.1f}%" for val in df_sorted['수익율1']],
            textposition='auto'
        ))
        
        fig3.add_vline(x=0, line_dash="dash", line_color='white')
        fig3.update_layout(xaxis_title="수익율 (%)", yaxis_title="")
        fig3 = apply_common_layout(fig3)
        st.plotly_chart(fig3, use_container_width=True)
