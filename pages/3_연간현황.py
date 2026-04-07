import streamlit as st
import pandas as pd
import plotly.express as px

from utils.data_loader import load_detailed_management
from utils.charts import COLORS, apply_common_layout

st.set_page_config(page_title="연간 운영실적", page_icon="📊", layout="wide")

from utils.auth import check_password
check_password()

st.title("📊 연간 운영 현황")
st.caption("2012년부터의 공연 운영 데이터를 다양한 관점으로 분석합니다.")
st.divider()

detail_df = load_detailed_management()

if detail_df is None:
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

    # ── 분류(공연구분) 체크박스 (최소 1개 강제) ──
    _s1_sel_final = []
    if _s1_perf_type_col:
        _s1_types = sorted(_s1_year_df[_s1_perf_type_col].dropna().astype(str).str.strip().unique())

        # session_state 초기화 (키가 없을 때만 default 설정)
        for t in _s1_types:
            if f'_s1_cb_{t}' not in st.session_state:
                st.session_state[f'_s1_cb_{t}'] = (t == '기획')

        # 현재 선택 상태 읽기
        _s1_selected = [t for t in _s1_types if st.session_state.get(f'_s1_cb_{t}', False)]
        _s1_only_one = len(_s1_selected) == 1

        # 체크박스 가로 배치 + 컬러 바 인디케이터
        _CB_COLORS = {'기획': '#0FFD02', '대관': '#FFFF00', '기타': '#FF6EC7'}
        _s1_cb_cols = st.columns(len(_s1_types))
        for i, t in enumerate(_s1_types):
            is_checked = st.session_state.get(f'_s1_cb_{t}', False)
            is_disabled = _s1_only_one and is_checked
            with _s1_cb_cols[i]:
                st.checkbox(t, key=f'_s1_cb_{t}', disabled=is_disabled)
                _bar_color = _CB_COLORS.get(t, '#555') if is_checked else '#333'
                st.markdown(
                    f'<div style="height:3px;background:{_bar_color};border-radius:2px;'
                    f'margin-top:-10px;margin-bottom:4px;"></div>',
                    unsafe_allow_html=True,
                )

        # 필터 적용
        _s1_sel_final = [t for t in _s1_types if st.session_state.get(f'_s1_cb_{t}', False)]
        if _s1_sel_final:
            _s1_year_df = _s1_year_df[_s1_year_df[_s1_perf_type_col].astype(str).str.strip().isin(_s1_sel_final)]

    # ── 공연 단위 그룹화 (공연명 기준) ──
    _weekday_kr = ['월', '화', '수', '목', '금', '토', '일']

    if _s1_year_df.empty:
        st.info("해당 연도/분류 데이터가 없습니다.")
    else:
        _s1_genre_col = '장르1' if '장르1' in _s1_year_df.columns else '세부\n장르'
        _s1_type_col = _s1_perf_type_col if _s1_perf_type_col else '공연\n구분'
        _s1_grouped = _s1_year_df.groupby('공연명').agg(
            _평균점유율=('_점유율', 'mean'),
            _종료일=('_날짜', 'max'),
            _시작일=('_날짜', 'min'),
            _유료합계=('발권\n유료', 'sum'),
            _오픈합계=('기본\n좌석', 'sum'),
            _회차수=('공연명', 'count'),
            _장르=(_s1_genre_col, 'first'),
            _공연구분=(_s1_type_col, 'first'),
        ).reset_index()
        _s1_grouped['_공연구분'] = _s1_grouped['_공연구분'].astype(str).str.strip()
        _s1_grouped = _s1_grouped.sort_values('_종료일').reset_index(drop=True)

        # X축: 종료일 기준 월 위치
        _s1_grouped['_월위치'] = _s1_grouped['_종료일'].dt.month + (_s1_grouped['_종료일'].dt.day - 1) / 31

        # 호버용 날짜 포맷 (종료일)
        _s1_grouped['_날짜포맷'] = _s1_grouped['_종료일'].apply(
            lambda d: f"'{d.year % 100:02d}.{d.month:02d}.{d.day:02d}({_weekday_kr[d.weekday()]})"
            if pd.notna(d) else ''
        )

        _GENRE_COLORS = {
            '클래식': '#0FFD02',
            '뮤지컬': '#00BFFF',
            '대중': '#00FFFF',
            '발레/연극': '#FFFF00',
            '어린이·가족': '#FF6EC7',
            '기타': '#B0B0B0',
        }
        _TYPE_COLORS = {
            '기획': '#0FFD02',
            '대관': '#FFFF00',
            '기타': '#FF6EC7',
        }

        _s1_multi = len(_s1_sel_final) > 1
        if _s1_multi:
            _s1_color_col = '_공연구분'
            _s1_color_map = _TYPE_COLORS
        else:
            _s1_color_col = '_장르'
            _s1_color_map = _GENRE_COLORS

        _GENRE_ORDER = ['클래식', '뮤지컬', '어린이·가족', '발레/연극', '대중', '기타']
        _TYPE_ORDER = ['기획', '대관', '기타']
        _s1_cat_orders = {_s1_color_col: _TYPE_ORDER if _s1_multi else _GENRE_ORDER}

        _s1_fig = px.scatter(
            _s1_grouped,
            x='_월위치',
            y='_평균점유율',
            color=_s1_color_col,
            custom_data=['공연명', '_장르', '_날짜포맷', '_유료합계', '_평균점유율'],
            color_discrete_map=_s1_color_map,
            category_orders=_s1_cat_orders,
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
                title='',
                tickmode='array',
                tickvals=list(range(1, 13)),
                ticktext=[f'{m}월' for m in range(1, 13)],
                range=[0.5, 12.5],
            ),
            yaxis=dict(
                title='',
                range=[0, 110],
            ),
            height=500,
            margin=dict(t=40, r=150),
            showlegend=True,
            legend=dict(
                orientation='h',
                yanchor='top',
                y=-0.12,
                xanchor='center',
                x=0.5,
                font=dict(color='#FFFFFF'),
                bgcolor='rgba(0,0,0,0)',
                title_text='',
            ),
            annotations=[
                dict(
                    text='(%)',
                    x=0,
                    y=1.04,
                    xref='paper',
                    yref='paper',
                    showarrow=False,
                    xanchor='left',
                    yanchor='bottom',
                    font=dict(color='#FFFFFF', size=13),
                ),
                dict(
                    text='(%)',
                    x=1.01,
                    y=1.04,
                    xref='paper',
                    yref='paper',
                    showarrow=False,
                    xanchor='left',
                    yanchor='bottom',
                    font=dict(color='#FFFFFF', size=11),
                ),
            ],
        )
        # ── 카테고리별 평균 점선 + 우측 수치 ──
        _avg_annotations = []
        _used_y = []
        for _cat, _color in _s1_color_map.items():
            _cat_df = _s1_grouped[_s1_grouped[_s1_color_col] == _cat]
            if _cat_df.empty:
                continue
            _avg = _cat_df['_평균점유율'].mean()

            _s1_fig.add_shape(
                type='line', x0=0.5, x1=12.5, y0=_avg, y1=_avg,
                line=dict(dash='dash', color=_color, width=1.5),
                opacity=0.5,
            )

            # 겹침 방지: 기존 수치와 Y 간격 < 3이면 오프셋
            _adj_y = _avg
            for _uy in _used_y:
                if abs(_adj_y - _uy) < 3:
                    _adj_y = _uy + 3
            _used_y.append(_adj_y)

            # 숫자 + 카테고리명 (paper x좌표로 margin 영역에 표시)
            _avg_annotations.append(dict(
                x=1.005, y=_adj_y,
                xref='paper', yref='y',
                text=f"{_avg:.0f}",
                showarrow=False,
                xanchor='left', yanchor='middle',
                font=dict(color=_color, size=13),
            ))
            _avg_annotations.append(dict(
                x=1.005, y=_adj_y - 2.8,
                xref='paper', yref='y',
                text=f"({_cat})",
                showarrow=False,
                xanchor='left', yanchor='middle',
                font=dict(color=_color, size=9),
            ))

        # 기존 annotations에 평균 annotations 추가
        _s1_fig.layout.annotations = list(_s1_fig.layout.annotations) + _avg_annotations

        _s1_fig = apply_common_layout(_s1_fig)
        st.plotly_chart(_s1_fig, use_container_width=True)

        # ── 요약 영역: 좌측 지표 + 우측 장르 평균 표 ──
        st.markdown('<div style="margin:24px 0 16px 0;border-top:1px solid #333;"></div>', unsafe_allow_html=True)

        _sum_left, _sum_right = st.columns([1, 2])

        # 좌측: 요약 3개
        with _sum_left:
            _total_cnt = len(_s1_grouped)
            _avg_all = _s1_grouped['_평균점유율'].mean()
            _max_all = _s1_grouped['_평균점유율'].max()
            st.markdown(
                f'<div style="font-size:15px;line-height:2.2;padding:12px 0;">'
                f'<b>총 공연 수</b> &nbsp; <span style="color:#0FFD02;font-weight:700;">{_total_cnt}</span>건<br>'
                f'<b>평균 점유율</b> &nbsp; <span style="color:#0FFD02;font-weight:700;">{_avg_all:.1f}</span>%<br>'
                f'<b>최고 점유율</b> &nbsp; <span style="color:#0FFD02;font-weight:700;">{_max_all:.1f}</span>%'
                f'</div>',
                unsafe_allow_html=True,
            )

        # 우측: 카테고리별 평균 점유율 표
        with _sum_right:
            _order = (_TYPE_ORDER if _s1_multi else _GENRE_ORDER)
            _active_cats = [c for c in _order if c in _s1_grouped[_s1_color_col].values]

            if _active_cats:
                _hdr_cells = '<td style="padding:6px 12px;font-weight:700;color:#AAA;"></td>'
                for _ac in _active_cats:
                    _hc = _s1_color_map.get(_ac, '#FFF')
                    _hdr_cells += f'<td style="padding:6px 12px;text-align:center;font-weight:700;color:{_hc};">{_ac}</td>'

                _data_cells = '<td style="padding:6px 12px;font-weight:600;color:#FFF;">평균 점유율 (%)</td>'
                for _ac in _active_cats:
                    _cat_avg = _s1_grouped[_s1_grouped[_s1_color_col] == _ac]['_평균점유율'].mean()
                    _data_cells += f'<td style="padding:6px 12px;text-align:right;color:#FFF;">{_cat_avg:.1f}</td>'

                st.markdown(
                    f'<div style="padding:12px 0 32px 0;">'
                    f'<table style="width:100%;border-collapse:collapse;font-size:14px;">'
                    f'<tr style="background:rgba(255,255,255,0.05);border-bottom:1px solid #444;">{_hdr_cells}</tr>'
                    f'<tr>{_data_cells}</tr>'
                    f'</table>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # ── 공연 목록 표 (st.dataframe) ──
        _s1_tbl = _s1_grouped.copy()  # already sorted by _종료일

        def _fmt_date_range(row):
            s, e = row['_시작일'], row['_종료일']
            if pd.isna(s) or pd.isna(e):
                return '-'
            _wd = ['월','화','수','목','금','토','일']
            if s == e or row['_회차수'] == 1:
                return f"{e.month:02d}.{e.day:02d}({_wd[e.weekday()]})"
            if s.month == e.month:
                return f"{s.month:02d}.{s.day:02d}({_wd[s.weekday()]})~{e.day:02d}({_wd[e.weekday()]})"
            return f"{s.month:02d}.{s.day:02d}({_wd[s.weekday()]})~{e.month:02d}.{e.day:02d}({_wd[e.weekday()]})"

        _s1_display = pd.DataFrame({
            '공연일': _s1_tbl.apply(_fmt_date_range, axis=1),
            '공연명': _s1_tbl['공연명'],
            '장르': _s1_tbl['_장르'].fillna(''),
            '회차': _s1_tbl['_회차수'].astype(int),
            '판매좌석(석)': _s1_tbl['_유료합계'].fillna(0).astype(int),
            '오픈석(석)': _s1_tbl['_오픈합계'].fillna(0).astype(int),
            '점유율(%)': _s1_tbl['_평균점유율'].round(1),
            '판매금액(만원)': pd.Series([None] * len(_s1_tbl), dtype='Int64'),
        }).reset_index(drop=True)

        _s1_styled = _s1_display.style.set_properties(
            **{'color': '#FFEB3B'}, subset=['판매좌석(석)']
        ).set_properties(
            **{'color': '#0FFD02', 'font-weight': '700'}, subset=['점유율(%)']
        ).set_properties(
            **{'color': '#0FFD02'}, subset=['판매금액(만원)']
        )

        _s1_tbl_height = min(35 * (len(_s1_display) + 1) + 3, 600)
        st.dataframe(
            _s1_styled,
            use_container_width=True,
            hide_index=True,
            height=_s1_tbl_height,
            column_config={
                '공연일': st.column_config.TextColumn('공연일', width='small'),
                '공연명': st.column_config.TextColumn('공연명', width='large'),
                '장르': st.column_config.TextColumn('장르', width='small'),
                '회차': st.column_config.NumberColumn('회차', width='small', format='%d'),
                '판매좌석(석)': st.column_config.NumberColumn('판매좌석(석)', format='%,d'),
                '오픈석(석)': st.column_config.NumberColumn('오픈석(석)', format='%,d'),
                '점유율(%)': st.column_config.NumberColumn('점유율(%)', format='%.1f'),
                '판매금액(만원)': st.column_config.NumberColumn('판매금액(만원)', format='%,d'),
            },
        )

    st.divider()

