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

    # 회차별 점유율
    _s1_df['_점유율'] = _s1_df['발권\n유료'] / _s1_df['기본\n좌석'] * 100

    # 연도 int 변환
    _s1_df['_년도'] = _s1_df['년도'].astype(int)

    # 월/일 suffix 제거
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

    # 공연구분 컬럼
    _s1_perf_type_col = '공연\n구분' if '공연\n구분' in _s1_df.columns else None

    # ── 연도 선택 (기본값: 전년도) ──
    _s1_available_years = sorted(_s1_df['_년도'].unique(), reverse=True)
    from datetime import datetime as _dt
    _s1_default_year = _dt.now().year - 1
    _s1_default_idx = _s1_available_years.index(_s1_default_year) if _s1_default_year in _s1_available_years else 0
    _s1_selected_year = st.selectbox("연도 선택", _s1_available_years, index=_s1_default_idx, key="_s1_year")
    _s1_year_df = _s1_df[_s1_df['_년도'] == _s1_selected_year]

    # ── 분류(공연구분) 라디오 ──
    if _s1_perf_type_col:
        _s1_types = sorted(_s1_year_df[_s1_perf_type_col].dropna().astype(str).str.strip().unique())
        _s1_default_idx = _s1_types.index('기획') if '기획' in _s1_types else 0
        _s1_sel_type = st.radio("공연구분", _s1_types, index=_s1_default_idx, horizontal=True, key="_s1_type")
        _s1_year_df = _s1_year_df[_s1_year_df[_s1_perf_type_col].astype(str).str.strip() == _s1_sel_type]

    # ── 공연 단위 그룹화 (공연명 기준) ──
    _weekday_kr = ['월', '화', '수', '목', '금', '토', '일']

    if _s1_year_df.empty:
        st.info("해당 연도/분류 데이터가 없습니다.")
    else:
        _s1_genre_col = '장르1' if '장르1' in _s1_year_df.columns else '세부\n장르'
        _s1_grouped = _s1_year_df.groupby('공연명').agg(
            _평균점유율=('_점유율', 'mean'),
            _종료일=('_날짜', 'max'),
            _시작일=('_날짜', 'min'),
            _유료합계=('발권\n유료', 'sum'),
            _오픈합계=('기본\n좌석', 'sum'),
            _회차수=('공연명', 'count'),
            _장르=(_s1_genre_col, 'first'),
        ).reset_index()

        # X축: 종료일 기준 월 위치
        _s1_grouped['_월위치'] = _s1_grouped['_종료일'].dt.month + (_s1_grouped['_종료일'].dt.day - 1) / 31

        # 호버용 날짜 포맷 (종료일)
        _s1_grouped['_날짜포맷'] = _s1_grouped['_종료일'].apply(
            lambda d: f"'{d.year % 100:02d}.{d.month:02d}.{d.day:02d}({_weekday_kr[d.weekday()]})"
            if pd.notna(d) else ''
        )

        _s1_fig = px.scatter(
            _s1_grouped,
            x='_월위치',
            y='_평균점유율',
            custom_data=['공연명', '_장르', '_날짜포맷', '_유료합계', '_평균점유율'],
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

        # 요약 지표 (그룹 기준)
        _s1_c1, _s1_c2, _s1_c3 = st.columns(3)
        _s1_c1.metric("총 공연 수", f"{len(_s1_grouped)}건")
        _s1_c2.metric("평균 점유율", f"{_s1_grouped['_평균점유율'].mean():.1f}%")
        _s1_c3.metric("최고 점유율", f"{_s1_grouped['_평균점유율'].max():.1f}%")

        # ── 공연 목록 표 ──
        _s1_tbl = _s1_grouped.sort_values('_종료일').copy()

        def _fmt_date_range(row):
            s, e = row['_시작일'], row['_종료일']
            if pd.isna(s) or pd.isna(e):
                return '-'
            _wd = ['월','화','수','목','금','토','일']
            if s == e or row['_회차수'] == 1:
                return f"{e.month}.{e.day}({_wd[e.weekday()]})"
            if s.month == e.month:
                return f"{s.month}.{s.day}({_wd[s.weekday()]})~{e.day}({_wd[e.weekday()]})"
            return f"{s.month}.{s.day}({_wd[s.weekday()]})~{e.month}.{e.day}({_wd[e.weekday()]})"

        _G = '#0FFD02'
        _Y = '#FFEB3B'
        _W = '#FFFFFF'
        _HDR_BG = 'rgba(255,255,255,0.06)'
        _tbl_rows = []
        for _, r in _s1_tbl.iterrows():
            _date_str = _fmt_date_range(r)
            _paid = int(r['_유료합계']) if pd.notna(r['_유료합계']) else 0
            _open = int(r['_오픈합계']) if pd.notna(r['_오픈합계']) else 0
            _occ = r['_평균점유율']
            _rounds = int(r['_회차수'])
            _tbl_rows.append(
                f'<tr>'
                f'<td style="padding:6px 10px;color:{_W};">{_date_str}</td>'
                f'<td style="padding:6px 10px;color:{_W};">{r["공연명"]}</td>'
                f'<td style="padding:6px 10px;text-align:center;color:{_W};">{_rounds}</td>'
                f'<td style="padding:6px 10px;text-align:right;color:{_Y};">{_paid:,}</td>'
                f'<td style="padding:6px 10px;text-align:right;color:{_W};">{_open:,}</td>'
                f'<td style="padding:6px 10px;text-align:right;color:{_G};font-weight:700;">{_occ:.1f}</td>'
                f'<td style="padding:6px 10px;text-align:right;color:{_G};">-</td>'
                f'</tr>'
            )

        _tbl_html = (
            f'<table style="width:100%;border-collapse:collapse;font-size:15px;margin-top:16px;">'
            f'<tr style="background:{_HDR_BG};border-bottom:1px solid #444;">'
            f'<th style="padding:8px 10px;text-align:left;font-weight:700;">공연일</th>'
            f'<th style="padding:8px 10px;text-align:left;font-weight:700;">공연명</th>'
            f'<th style="padding:8px 10px;text-align:center;font-weight:700;">회차</th>'
            f'<th style="padding:8px 10px;text-align:right;font-weight:700;">판매좌석(석)</th>'
            f'<th style="padding:8px 10px;text-align:right;font-weight:700;">오픈석(석)</th>'
            f'<th style="padding:8px 10px;text-align:right;font-weight:700;">점유율(%)</th>'
            f'<th style="padding:8px 10px;text-align:right;font-weight:700;">판매금액(만원)</th>'
            f'</tr>'
            + ''.join(_tbl_rows)
            + '</table>'
        )
        st.markdown(_tbl_html, unsafe_allow_html=True)

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
