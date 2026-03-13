import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.data_loader import load_yearly_performance, load_detailed_management
from utils.charts import COLORS, apply_common_layout

st.set_page_config(page_title="연간 운영실적", page_icon="📊", layout="wide")

from utils.auth import check_password
check_password()

st.title("📊 연간 운영실적 (2012~)")

yearly_df = load_yearly_performance()
detail_df = load_detailed_management()

if yearly_df is None or detail_df is None:
    st.error("데이터를 정상적으로 불러오지 못했습니다")
    st.stop()

st.subheader("📈 연간 공연 실적 추이")

if all(col in yearly_df.columns for col in ['기간', '공연횟수', '관람인원']):
    fig1 = go.Figure()

    fig1.add_trace(go.Bar(
        x=yearly_df['기간'],
        y=yearly_df['공연횟수'],
        name="공연횟수",
        marker_color=COLORS['secondary'],
        yaxis='y'
    ))

    fig1.add_trace(go.Scatter(
        x=yearly_df['기간'],
        y=yearly_df['관람인원'],
        name="관람인원",
        mode='lines+markers',
        marker=dict(color=COLORS['primary']),
        yaxis='y2'
    ))

    fig1.update_layout(
        xaxis=dict(title="연도"),
        yaxis=dict(title="공연횟수", side='left', showgrid=False),
        yaxis2=dict(title="관람인원", side='right', overlaying='y', showgrid=False),
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(0,0,0,0)'),
        barmode='group'
    )
    fig1 = apply_common_layout(fig1)
    st.plotly_chart(fig1, use_container_width=True)

st.markdown("---")

st.subheader("🔍 세부 실적 분석")

if not detail_df.empty and '연도' in detail_df.columns:
    # 연도 컬럼을 정수로 변환 후 정렬 (float/NaN 제거)
    valid_years = detail_df['연도'].dropna()
    valid_years = valid_years[valid_years > 0]
    year_list = ['전체'] + sorted([int(y) for y in valid_years.unique()], reverse=True)
    selected_year = st.selectbox("연도 선택", year_list)

    if selected_year != '전체':
        filtered_df = detail_df[detail_df['연도'] == selected_year]
    else:
        filtered_df = detail_df

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**🎭 장르별 분포**")
        if '장르' in filtered_df.columns:
            genre_df = filtered_df['장르'].value_counts().reset_index()
            genre_df.columns = ['장르', '건수']
            fig2 = px.pie(genre_df, values='건수', names='장르', hole=0.4)
            fig2 = apply_common_layout(fig2)
            st.plotly_chart(fig2, use_container_width=True)

    with col_right:
        st.markdown("**📈 사업구분별 분석**")
        if '사업구분' in filtered_df.columns and '공연구분' in filtered_df.columns:
            biz_df = filtered_df.groupby(['사업구분', '공연구분']).size().reset_index(name='건수')
            fig3 = px.bar(biz_df, x='사업구분', y='건수', color='공연구분', barmode='stack')
            fig3 = apply_common_layout(fig3)
            st.plotly_chart(fig3, use_container_width=True)

    st.markdown("---")

    st.markdown("### 📋 상세 데이터 테이블")

    col_f1, col_f2, col_f3 = st.columns(3)

    with col_f1:
        mon_list = ['전체'] + sorted(filtered_df['월'].dropna().unique().tolist()) if '월' in filtered_df.columns else ['전체']
        sel_month = st.selectbox("월 선택", mon_list)
    with col_f2:
        g_list = ['전체'] + sorted(filtered_df['장르'].dropna().unique().tolist()) if '장르' in filtered_df.columns else ['전체']
        sel_genre = st.selectbox("장르 선택", g_list)
    with col_f3:
        p_list = ['전체'] + sorted(filtered_df['공연명'].dropna().unique().tolist()) if '공연명' in filtered_df.columns else ['전체']
        sel_perf = st.selectbox("공연명 선택", p_list)

    table_df = filtered_df.copy()
    if sel_month != '전체' and '월' in table_df.columns:
        table_df = table_df[table_df['월'] == sel_month]
    if sel_genre != '전체' and '장르' in table_df.columns:
        table_df = table_df[table_df['장르'] == sel_genre]
    if sel_perf != '전체' and '공연명' in table_df.columns:
        table_df = table_df[table_df['공연명'] == sel_perf]

    st.dataframe(table_df, use_container_width=True, height=400)

    csv = table_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 CSV 다운로드",
        data=csv,
        file_name='yeulmaru_details.csv',
        mime='text/csv',
    )