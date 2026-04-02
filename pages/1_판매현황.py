import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.data_loader import load_daily_input, load_sales_trend, get_base_date
from utils.charts import COLORS, apply_common_layout

st.set_page_config(page_title="실시간 판매현황", page_icon="📊", layout="wide")

from utils.auth import check_password
check_password()

st.title("📊 실시간 판매현황")

daily_df = load_daily_input()
trend_df = load_sales_trend()
base_date = get_base_date()

if daily_df is None or trend_df is None:
    st.error("데이터를 정상적으로 불러오지 못했습니다. `data` 폴더에 올바른 엑셀 파일이 위치해 있는지 확인해주세요.")
    st.stop()

# ── 기준일자 파싱 ──
if hasattr(base_date, 'weekday'):
    base_dt = base_date
else:
    base_dt = pd.to_datetime(base_date, errors='coerce')

if pd.notna(base_dt):
    weekdays = ['월', '화', '수', '목', '금', '토', '일']
    wd = weekdays[base_dt.weekday()]
    base_date_str = base_dt.strftime(f'%Y년 %m월 %d일') + f' ({wd})'
else:
    base_date_str = str(base_date)
    base_dt = None

# ── 공연별 최신 스냅샷 (날짜별 누적값이므로 최신 행만 사용) ──
if '공연명' not in daily_df.columns:
    st.warning("데이터에 '공연명' 컬럼이 없습니다.")
    st.stop()

daily_df['_sort_key'] = pd.to_numeric(daily_df['No'], errors='coerce')
grouped = daily_df.sort_values('_sort_key').groupby('공연명').last().reset_index()
# 점유율: 엑셀 원본값 우선 사용, 없으면 합계좌석/오픈석 fallback
if '점유율' in grouped.columns:
    raw = pd.to_numeric(grouped['점유율'], errors='coerce')
    # 소수(0~1 범위)면 ×100, 이미 %면 그대로
    raw = raw.where(raw.isna(), raw.apply(lambda v: v * 100 if pd.notna(v) and v <= 1 else v))
    fallback = (
        grouped['합계좌석'] / grouped['오픈석'].replace(0, float('nan')) * 100
    ).clip(upper=100.0)
    grouped['점유율'] = raw.fillna(fallback).fillna(0)
else:
    grouped['점유율'] = (
        grouped['합계좌석'] / grouped['오픈석'].replace(0, float('nan')) * 100
    ).fillna(0).clip(upper=100.0)

# ── 판매중 / 종료 분리 ──
today = pd.Timestamp.now().normalize()

if '공연일(날짜)' in grouped.columns:
    grouped['공연일(날짜)'] = pd.to_datetime(grouped['공연일(날짜)'], errors='coerce')
    grouped['_days'] = (grouped['공연일(날짜)'] - today).dt.days

    active_df = grouped[grouped['_days'] >= 0].sort_values('공연일(날짜)', ascending=True).copy()
    ended_df = grouped[grouped['_days'] < 0].sort_values('공연일(날짜)', ascending=False).copy()
else:
    active_df = grouped.copy()
    ended_df = pd.DataFrame(columns=grouped.columns)
    active_df['_days'] = None


# ── 헬퍼 함수 ──
def fmt_dday(days):
    if pd.isna(days):
        return ""
    d = int(days)
    if d == 0:
        return "D-Day"
    elif d > 0:
        return f"D-{d}"
    else:
        return f"D+{-d}"


def fmt_occupancy(occ_pct):
    """사전 계산된 점유율(%) 값을 포맷"""
    if pd.isna(occ_pct):
        return "-"
    return f"{occ_pct:.1f}%"


def fmt_money_man(val):
    """원 → 만원 (반올림)"""
    if pd.isna(val) or val == 0:
        return "0"
    return f"{int(round(val / 10000)):,}"


def build_display_df(df, is_active=True):
    """표시용 DataFrame 생성"""
    rows = []
    for _, r in df.iterrows():
        seats = int(r['합계좌석']) if pd.notna(r['합계좌석']) else 0
        open_s = int(r['오픈석']) if pd.notna(r['오픈석']) else 0
        money = r['합계금액'] if pd.notna(r['합계금액']) else 0

        row = {'공연명': r['공연명']}
        if is_active:
            row['D-day'] = fmt_dday(r.get('_days'))
        else:
            if '공연일(날짜)' in r.index and pd.notna(r['공연일(날짜)']):
                row['공연일'] = pd.to_datetime(r['공연일(날짜)']).strftime('%Y-%m-%d')
            else:
                row['공연일'] = ''

        row['판매좌석'] = f"{seats:,}"
        row['오픈석'] = f"{open_s:,}"

        col_name = '점유율(%)' if is_active else '최종 점유율(%)'
        row[col_name] = fmt_occupancy(r.get('점유율'))
        row['합계금액(만원)'] = fmt_money_man(money)
        rows.append(row)

    return pd.DataFrame(rows)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 섹션 1: 상단 요약 metric
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
n_active = len(active_df)
if not active_df.empty:
    avg_occ = active_df.loc[active_df['오픈석'] > 0, '점유율'].mean()
    avg_occ = avg_occ if pd.notna(avg_occ) else 0.0
else:
    avg_occ = 0.0

col1, col2, col3 = st.columns(3)
col1.metric("판매중 공연", f"{n_active}개")
col2.metric("평균 점유율", f"{avg_occ:.1f}%")
col3.metric("오늘 기준일자", base_date_str)

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 섹션 2: 판매중 공연 테이블
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.subheader("판매중 공연")

if active_df.empty:
    st.info("현재 판매중인 공연이 없습니다.")
else:
    disp = build_display_df(active_df, is_active=True)
    right_cols = ['판매좌석', '오픈석', '점유율(%)', '합계금액(만원)']
    col_config = {
        c: st.column_config.TextColumn(c, width="small") for c in right_cols
    }
    st.dataframe(
        disp,
        use_container_width=True,
        hide_index=True,
        column_config=col_config,
    )

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 섹션 3: 종료 공연 (접힘)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if not ended_df.empty:
    with st.expander(f"종료된 공연 보기 ({len(ended_df)}건)"):
        disp_ended = build_display_df(ended_df, is_active=False)
        right_cols_ended = ['판매좌석', '오픈석', '최종 점유율(%)', '합계금액(만원)']
        col_config_ended = {
            c: st.column_config.TextColumn(c, width="small") for c in right_cols_ended
        }
        st.dataframe(
            disp_ended,
            use_container_width=True,
            hide_index=True,
            column_config=col_config_ended,
        )

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 섹션 4: 공연별 점유율 비교 차트 (판매중만)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if not active_df.empty:
    st.subheader("📊 공연별 점유율 비교")
    chart_df = active_df.sort_values('점유율', ascending=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=chart_df['점유율'],
        y=chart_df['공연명'],
        orientation='h',
        marker_color=COLORS['primary'],
        text=[f"{v:.1f}%" for v in chart_df['점유율']],
        textposition='auto',
    ))
    fig.add_vline(
        x=100, line_dash="dash", line_color=COLORS['danger'],
        annotation_text="100%", annotation_position="top right",
    )
    fig.update_layout(xaxis_title="점유율 (%)", yaxis_title="")
    fig = apply_common_layout(fig)
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 판매추이 (기존 유지)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if not trend_df.empty and '기준일자' in trend_df.columns and '공연명' in trend_df.columns:
    st.subheader("📈 판매추이")

    trend_metric = st.radio("지표 선택", ['합계좌석', '합계금액'], horizontal=True)

    perf_list = trend_df['공연명'].unique().tolist()
    selected_perfs = st.multiselect("공연 선택", perf_list, default=perf_list)

    filtered_trend = trend_df[trend_df['공연명'].isin(selected_perfs)].copy()
    filtered_trend = filtered_trend.sort_values(by='기준일자')

    if trend_metric in filtered_trend.columns:
        fig2 = px.line(filtered_trend, x='기준일자', y=trend_metric, color='공연명', markers=True)
        fig2.update_layout(xaxis_title="기준일자", yaxis_title=trend_metric)
        fig2 = apply_common_layout(fig2)
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.warning(f"데이터에 `{trend_metric}` 컬럼이 없습니다.")
