import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from utils.data_loader import load_yearly_performance, load_detailed_management
from utils.charts import COLORS, apply_common_layout

st.set_page_config(page_title="연간 운영실적", page_icon="📊", layout="wide")

from utils.auth import check_password
check_password()

st.title("📊 연간 운영 현황")
st.caption("2012년부터의 공연 운영 데이터를 다양한 관점으로 분석합니다.")
st.divider()

yearly_df = load_yearly_performance()
detail_df = load_detailed_management()

if yearly_df is None or detail_df is None:
    st.error("데이터를 정상적으로 불러오지 못했습니다")
    st.stop()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [1] 연도별 공연 판매 현황
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown('<div style="font-size:2rem;font-weight:700;margin:24px 0 16px 0;">[1] 연도별 공연 판매 현황</div>', unsafe_allow_html=True)

if detail_df is not None and not detail_df.empty:
    _s1_df = detail_df.copy()

    # 제외 조건
    _s1_df = _s1_df[_s1_df['상태'] != '취소공연']
    _s1_df = _s1_df[~_s1_df['사업\n구분'].isin(['교육', '특강', '기타', '연기'])]
    _s1_df = _s1_df[_s1_df['티켓\n구분'] != '무료']
    _s1_df = _s1_df.dropna(subset=['기본\n좌석', '발권\n유료', '년도'])

    # 기본좌석 숫자 변환 + 0 제외
    _s1_df['기본\n좌석'] = pd.to_numeric(_s1_df['기본\n좌석'], errors='coerce')
    _s1_df = _s1_df[_s1_df['기본\n좌석'] > 0]

    # 점유율 계산
    _s1_df['_점유율'] = _s1_df['발권\n유료'] / _s1_df['기본\n좌석'] * 100

    # 연도 int 변환
    _s1_df['_년도'] = _s1_df['년도'].astype(int)

    # 월/일 컬럼 suffix 제거 ('1월'→'1', '26일'→'26')
    _s1_df['월'] = _s1_df['월'].astype(str).str.replace('월', '', regex=False).str.strip()
    _s1_df['일'] = _s1_df['일'].astype(str).str.replace('일', '', regex=False).str.strip()

    # 날짜 조합
    _s1_df['_날짜'] = pd.to_datetime(
        _s1_df['년도'].astype(int).astype(str) + '-' +
        _s1_df['월'].astype(str) + '-' +
        _s1_df['일'].astype(str),
        errors='coerce'
    )
    _s1_df = _s1_df.dropna(subset=['_날짜'])

    # 호버용 날짜 포맷
    _weekday_kr = ['월', '화', '수', '목', '금', '토', '일']
    _s1_df['_날짜포맷'] = _s1_df['_날짜'].apply(
        lambda d: f"'{d.year % 100:02d}.{d.month:02d}.{d.day:02d}({_weekday_kr[d.weekday()]})"
        if pd.notna(d) else ''
    )

    # X축 월 위치
    _s1_df['_월위치'] = _s1_df['_날짜'].dt.month + (_s1_df['_날짜'].dt.day - 1) / 31

    # 연도 선택
    _s1_available_years = sorted(_s1_df['_년도'].unique(), reverse=True)
    _s1_selected_year = st.selectbox("연도 선택", _s1_available_years, index=0, key="_s1_year")
    _s1_year_df = _s1_df[_s1_df['_년도'] == _s1_selected_year]

    if _s1_year_df.empty:
        st.info("해당 연도 데이터가 없습니다.")
    else:
        _s1_fig = px.scatter(
            _s1_year_df,
            x='_월위치',
            y='_점유율',
            custom_data=['공연명', '장르1', '_날짜포맷', '발권\n유료', '_점유율'],
            color_discrete_sequence=['#0FFD02'],
        )
        _s1_fig.update_traces(
            marker=dict(size=10, opacity=0.7, line=dict(width=1, color='#FFFFFF')),
            hovertemplate=(
                '<b>%{customdata[0]}</b><br>'
                '장르: %{customdata[1]}<br>'
                '공연일: %{customdata[2]}<br>'
                '유료판매: %{customdata[3]:,.0f}석<br>'
                '점유율: %{customdata[4]:.1f}%<extra></extra>'
            ),
        )
        _s1_fig.update_layout(
            xaxis=dict(
                title='월',
                tickmode='array',
                tickvals=list(range(1, 13)),
                ticktext=[f'{m}월' for m in range(1, 13)],
                range=[0.5, 12.5],
            ),
            yaxis=dict(
                title='유료점유율(%)',
                range=[0, 110],
            ),
            height=500,
            showlegend=False,
        )
        _s1_fig = apply_common_layout(_s1_fig)
        st.plotly_chart(_s1_fig, use_container_width=True)

        # 요약 지표
        _s1_c1, _s1_c2, _s1_c3 = st.columns(3)
        _s1_c1.metric("총 공연 수", f"{len(_s1_year_df)}건")
        _s1_c2.metric("평균 점유율", f"{_s1_year_df['_점유율'].mean():.1f}%")
        _s1_c3.metric("최고 점유율", f"{_s1_year_df['_점유율'].max():.1f}%")

    st.divider()

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