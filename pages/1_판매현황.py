import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

from utils.data_loader import load_daily_input, load_sales_trend, get_base_date, load_performance_master
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

# ── 날짜 파싱 ──
weekdays_kr = ['월', '화', '수', '목', '금', '토', '일']

# 오늘 (시스템)
now_dt = datetime.now()
today_str = now_dt.strftime('%Y년 %m월 %d일') + f' ({weekdays_kr[now_dt.weekday()]})'

# 갱신일자 (엑셀 B2)
if hasattr(base_date, 'weekday'):
    base_dt = base_date
else:
    base_dt = pd.to_datetime(base_date, errors='coerce')

if pd.notna(base_dt):
    base_date_str = base_dt.strftime('%Y년 %m월 %d일') + f' ({weekdays_kr[base_dt.weekday()]})'
else:
    base_date_str = str(base_date)
    base_dt = None

dates_differ = base_dt is not None and base_dt.date() != now_dt.date()

# ── 공연별 최신 스냅샷 (날짜별 누적값이므로 최신 행만 사용) ──
if '공연명' not in daily_df.columns:
    st.warning("데이터에 '공연명' 컬럼이 없습니다.")
    st.stop()

daily_df['_sort_key'] = pd.to_numeric(daily_df['No'], errors='coerce')

# ── 공연마스터 로드 & 매칭 ──
master_df = load_performance_master()

FALLBACK_SEAT = 926  # 공연마스터 매칭 실패 시 기본값

def _match_master(perf_name, master_df):
    """일일입력 공연명 ↔ 공연마스터 사업명 매칭 (contains 양방향)"""
    if master_df is None or master_df.empty:
        return None
    perf_name_s = str(perf_name).strip()
    for _, mr in master_df.iterrows():
        master_name = str(mr['사업명']).strip()
        if perf_name_s == master_name or perf_name_s in master_name or master_name in perf_name_s:
            return mr
    return None

# 당일 데이터(No < 100)
today_rows = daily_df[daily_df['_sort_key'] < 100]

grouped = daily_df.sort_values('_sort_key').groupby('공연명').last().reset_index()

# 공연일(날짜) 컬럼을 datetime으로 통일 (수식 셀이 str/nan 혼재 → dtype 충돌 방지)
if '공연일(날짜)' in grouped.columns:
    grouped['공연일(날짜)'] = pd.to_datetime(grouped['공연일(날짜)'], errors='coerce')

# 공연마스터 기반 오픈석 + 공연일 계산
_debug_match = []
perf_date_map = {}
for idx, row in grouped.iterrows():
    name = row['공연명']
    matched = _match_master(name, master_df)
    if matched is not None:
        base_seat = int(matched['기준석']) if pd.notna(matched['기준석']) and matched['기준석'] > 0 else FALLBACK_SEAT
        rounds = int(matched['총회차']) if pd.notna(matched['총회차']) and matched['총회차'] > 0 else 1
        total_open = int(matched['총오픈석']) if pd.notna(matched['총오픈석']) and matched['총오픈석'] > 0 else base_seat * rounds
        match_status = str(matched['사업명'])

        # 공연일(날짜): 수식 셀이 nan이면 공연마스터 시작일/종료일 사용
        start_dt = pd.to_datetime(matched.get('시작일'), errors='coerce')
        end_dt = pd.to_datetime(matched.get('종료일'), errors='coerce')
        if pd.notna(start_dt):
            grouped.at[idx, '공연일(날짜)'] = start_dt
            if pd.notna(end_dt) and start_dt != end_dt:
                perf_date_map[name] = f"{start_dt.month}.{start_dt.day}~{end_dt.month}.{end_dt.day}"
            else:
                perf_date_map[name] = f"{start_dt.month}.{start_dt.day}"
    else:
        base_seat = FALLBACK_SEAT
        rounds = 1
        total_open = FALLBACK_SEAT
        match_status = '(미매칭)'

    grouped.at[idx, '오픈석'] = base_seat
    grouped.at[idx, '누적오픈석'] = total_open
    grouped.at[idx, '_회차수'] = rounds

    _debug_match.append({
        '공연명': name,
        '매칭': match_status,
        '기준석': base_seat,
        '총회차': rounds,
        '총오픈석': total_open,
        '합계좌석': int(row['합계좌석']) if pd.notna(row['합계좌석']) else 0,
    })

# 점유율: 총오픈석 기준
grouped['점유율'] = (
    grouped['합계좌석'] / grouped['누적오픈석'].replace(0, float('nan')) * 100
).fillna(0).clip(upper=100.0)

# 디버그에 점유율 추가
for i, row in grouped.iterrows():
    if i < len(_debug_match):
        _debug_match[i]['점유율'] = f"{row['점유율']:.1f}%"

# ── 디버그: 공연마스터 매칭 결과 ──
with st.sidebar.expander("디버그: 공연마스터 매칭"):
    st.dataframe(pd.DataFrame(_debug_match), use_container_width=True, hide_index=True)

# ── 디버그: Raw 데이터 확인 ──
with st.sidebar.expander("디버그: Raw 데이터"):
    st.write(f"**base_date raw:** `{repr(base_date)}`")
    st.write(f"**daily_df:** {daily_df.shape[0]}행 × {daily_df.shape[1]}열")
    st.write(f"**컬럼:** {list(daily_df.columns)}")
    st.write("**daily_df 처음 5행:**")
    st.dataframe(daily_df.head(5), use_container_width=True, hide_index=True)
    if master_df is not None:
        st.write(f"**공연마스터:** {master_df.shape[0]}행")
        st.dataframe(master_df[['사업명', '시작일', '종료일', '기준석', '총회차']].head(), use_container_width=True, hide_index=True)
    else:
        st.write("**공연마스터:** None")
    st.write(f"**grouped 공연일(날짜):**")
    st.dataframe(grouped[['공연명', '공연일(날짜)']].head(), use_container_width=True, hide_index=True)

# ── 전일대비 계산 (판매추이 시트에서 최신 2일치 비교) ──
daily_diff = {}
if trend_df is not None and not trend_df.empty and '기준일자' in trend_df.columns and '공연명' in trend_df.columns and '합계좌석' in trend_df.columns:
    for perf_name, grp in trend_df.groupby('공연명'):
        grp_sorted = grp.dropna(subset=['기준일자', '합계좌석']).sort_values('기준일자')
        if len(grp_sorted) >= 2:
            last_two = grp_sorted.tail(2)
            prev_seats = last_two.iloc[0]['합계좌석']
            curr_seats = last_two.iloc[1]['합계좌석']
            diff = int(curr_seats - prev_seats)
            daily_diff[perf_name] = diff

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
    if pd.isna(occ_pct):
        return "-"
    return f"{occ_pct:.1f}%"


def fmt_money_man(val):
    if pd.isna(val) or val == 0:
        return "0만원"
    return f"{int(round(val / 10000)):,}만원"


def fmt_daily_diff(perf_name):
    diff = daily_diff.get(perf_name)
    if diff is None:
        return "-"
    if diff > 0:
        return f"+{diff}석"
    elif diff < 0:
        return f"{diff}석"
    return "0석"


def _dday_color(days):
    """D-day 값에 따른 색상 반환"""
    if pd.isna(days):
        return "#FFFFFF"
    d = int(days)
    if 0 <= d < 14:
        return "#FF8C00"
    elif 14 <= d < 28:
        return "#FFD700"
    return "#FFFFFF"


ACCENT = "#0FFD02"


def _dday_zone(days):
    """D-day 구간 반환: 0=D-0~13, 1=D-14~27, 2=D-28+, -1=종료/없음"""
    if pd.isna(days):
        return -1
    d = int(days)
    if d < 0:
        return -1
    if d < 14:
        return 0
    if d < 28:
        return 1
    return 2


def build_html_table(df, is_active=True):
    """HTML 테이블 생성"""
    if is_active:
        headers = ['공연일', '공연명', 'D-day', '판매좌석', '오픈석(누적)', '점유율(%)', '합계금액', '전일대비']
        right_align_cols = {3, 4, 5, 6, 7}
    else:
        headers = ['공연일', '공연명', 'D-day', '판매좌석', '오픈석(누적)', '최종 점유율(%)', '합계금액', '전일대비']
        right_align_cols = {3, 4, 5, 6, 7}

    html = '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
    # 헤더
    html += '<tr>'
    for i, h in enumerate(headers):
        align = 'right' if i in right_align_cols else 'left'
        html += f'<th style="text-align:{align};padding:8px 12px;border-bottom:2px solid #444;color:#AAA;font-weight:600;">{h}</th>'
    html += '</tr>'

    # 행 — D-day 구간 경계에 구분선 삽입
    prev_zone = None
    for _, r in df.iterrows():
        days = r.get('_days')
        dday_col = _dday_color(days)
        seats = int(r['합계좌석']) if pd.notna(r['합계좌석']) else 0
        base_s = int(r['오픈석']) if pd.notna(r.get('오픈석')) else FALLBACK_SEAT
        rounds = int(r['_회차수']) if pd.notna(r.get('_회차수')) else 1
        # 오픈석(누적) 표시: 1회차 "926석", 2이상 "926×4"
        if rounds > 1:
            open_str = f"{base_s:,}×{rounds}"
        else:
            open_str = f"{base_s:,}석"
        money = r['합계금액'] if pd.notna(r['합계금액']) else 0
        occ = fmt_occupancy(r.get('점유율'))
        diff_str = fmt_daily_diff(r['공연명'])
        money_str = fmt_money_man(money)
        date_str = perf_date_map.get(r['공연명'], '')

        # 구간 경계 구분선 (D-14, D-28 경계)
        cur_zone = _dday_zone(days) if is_active else -1
        if is_active and prev_zone is not None and cur_zone != prev_zone:
            border_top = 'border-top:2px solid #555;'
        else:
            border_top = ''
        prev_zone = cur_zone

        html += f'<tr style="border-bottom:1px solid #333;{border_top}">'
        # 공연일
        html += f'<td style="padding:8px 12px;color:#AAA;">{date_str}</td>'
        # 공연명
        html += f'<td style="padding:8px 12px;color:{dday_col};">{r["공연명"]}</td>'
        # D-day / 공연일(종료)
        if is_active:
            html += f'<td style="padding:8px 12px;color:{dday_col};">{fmt_dday(days)}</td>'
        else:
            dt_str = ''
            if '공연일(날짜)' in r.index and pd.notna(r['공연일(날짜)']):
                dt_str = pd.to_datetime(r['공연일(날짜)']).strftime('%Y-%m-%d')
            html += f'<td style="padding:8px 12px;">{dt_str}</td>'
        # 판매좌석 (강조)
        html += f'<td style="padding:8px 12px;text-align:right;color:{ACCENT};font-weight:600;">{seats:,}석</td>'
        # 오픈석(누적)
        html += f'<td style="padding:8px 12px;text-align:right;">{open_str}</td>'
        # 점유율 (강조)
        html += f'<td style="padding:8px 12px;text-align:right;color:{ACCENT};font-weight:600;">{occ}</td>'
        # 합계금액 (기본)
        html += f'<td style="padding:8px 12px;text-align:right;">{money_str}</td>'
        # 전일대비 (강조)
        html += f'<td style="padding:8px 12px;text-align:right;color:{ACCENT};font-weight:600;">{diff_str}</td>'
        html += '</tr>'

    html += '</table>'
    return html


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 섹션 1: 상단 요약 metric
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
n_active = len(active_df)
if not active_df.empty:
    avg_occ = active_df['점유율'].mean()
    avg_occ = avg_occ if pd.notna(avg_occ) else 0.0
else:
    avg_occ = 0.0

col1, col2, col3 = st.columns(3)
col1.metric("판매중 공연", f"{n_active}개")
col2.markdown(
    f'<div style="font-size:14px;color:#AAA;">평균 점유율</div>'
    f'<div style="font-size:32px;font-weight:700;color:{ACCENT};">{avg_occ:.1f}%</div>',
    unsafe_allow_html=True,
)
renew_color = '#FF8C00' if dates_differ else '#FFFFFF'
col3.markdown(
    f'<div style="font-size:14px;color:#AAA;">오늘</div>'
    f'<div style="font-size:20px;font-weight:600;">{today_str}</div>'
    f'<div style="font-size:14px;color:#AAA;margin-top:4px;">갱신일자</div>'
    f'<div style="font-size:20px;font-weight:600;color:{renew_color};">{base_date_str}</div>',
    unsafe_allow_html=True,
)

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 섹션 2: 판매중 공연 테이블
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.subheader("판매중 공연")

if active_df.empty:
    st.info("현재 판매중인 공연이 없습니다.")
else:
    st.markdown(build_html_table(active_df, is_active=True), unsafe_allow_html=True)

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 섹션 3: 종료 공연 (접힘)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if not ended_df.empty:
    with st.expander(f"종료된 공연 보기 ({len(ended_df)}건)"):
        st.markdown(build_html_table(ended_df, is_active=False), unsafe_allow_html=True)

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
        customdata=chart_df[['합계좌석', '누적오픈석']].values,
        hovertemplate='%{y}<br>점유율: %{x:.1f}%<br>판매좌석: %{customdata[0]:,}<br>누적오픈석: %{customdata[1]:,}<extra></extra>',
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
