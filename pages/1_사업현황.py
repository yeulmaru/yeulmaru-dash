import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from zoneinfo import ZoneInfo

from utils.data_loader import load_daily_input, load_sales_trend, get_base_date, load_performance_master, load_round_details, get_data_source, match_performance, match_performance_category, get_target_occupancy
from utils.charts import COLORS, apply_common_layout


def get_contrast_text_color(hex_color):
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.5 else "#FFFFFF"

st.set_page_config(page_title="사업현황", page_icon="📊", layout="wide")

from utils.auth import check_password
check_password()

st.markdown('''
<style>
[data-testid="stDataFrame"] tbody tr:nth-child(even) {
    background-color: rgba(255,255,255,0.06) !important;
}
[data-testid="stDataFrame"] tbody tr:nth-child(odd) {
    background-color: rgba(255,255,255,0.01) !important;
}
</style>
''', unsafe_allow_html=True)

st.title("📊 실시간 판매현황")
st.markdown('<div style="margin-bottom:40px;"></div>', unsafe_allow_html=True)

daily_df = load_daily_input()
trend_df = load_sales_trend()
base_date = get_base_date()

if daily_df is None or trend_df is None:
    st.error("데이터를 정상적으로 불러오지 못했습니다. `data` 폴더에 올바른 엑셀 파일이 위치해 있는지 확인해주세요.")
    st.stop()

# ── 날짜 파싱 ──
weekdays_kr = ['월', '화', '수', '목', '금', '토', '일']

# 오늘 (한국 시간 기준)
now_dt = datetime.now(ZoneInfo("Asia/Seoul"))
today_str = now_dt.strftime('%Y년 %m월 %d일') + f' ({weekdays_kr[now_dt.weekday()]}) {now_dt.strftime("%H:%M")}'

# 갱신일자 (엑셀 B2)
if hasattr(base_date, 'weekday'):
    base_dt = base_date
else:
    base_dt = pd.to_datetime(base_date, errors='coerce')

if pd.notna(base_dt):
    # 시간 정보가 없으면(자정) 기본값 10:00:00 적용
    if base_dt.hour == 0 and base_dt.minute == 0 and base_dt.second == 0:
        base_dt = base_dt.replace(hour=10, minute=0, second=0)
    base_date_str = base_dt.strftime('%Y년 %m월 %d일') + f' ({weekdays_kr[base_dt.weekday()]}) {base_dt.strftime("%H:%M:%S")}'
else:
    base_date_str = str(base_date)
    base_dt = None

dates_differ = base_dt is not None and base_dt.date() != now_dt.date()

# ── 공연별 최신 스냅샷 (날짜별 누적값이므로 최신 행만 사용) ──
if '공연명' not in daily_df.columns:
    st.warning("데이터에 '공연명' 컬럼이 없습니다.")
    st.stop()

# 기준일자 → datetime 변환 (공연별 최신 행 선택용)
daily_df['_date_dt'] = pd.to_datetime(
    daily_df['기준일자'].astype('Int64').astype(str),
    format='%Y%m%d',
    errors='coerce'
)
daily_df['_sort_key'] = range(len(daily_df))

# ── 공연마스터 · 회차상세 로드 ──
master_df = load_performance_master()
rounds_df = load_round_details()

FALLBACK_SEAT = 926  # 공연마스터 매칭 실패 시 기본값
WEEKDAYS_KR = ['월', '화', '수', '목', '금', '토', '일']


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


def _fmt_perf_dates(dates):
    """공연일 목록 → 요일 포함 포맷.
    단일일: "5.7(목)"  연속: "4.16(수)~19(토)"  비연속: "5.14(수)~16(금), 5.23(토)"
    """
    dates = sorted(set(dates))
    if not dates:
        return ''

    # 연속 날짜 그룹으로 묶기
    groups = []
    cur = [dates[0]]
    for d in dates[1:]:
        if (d - cur[-1]).days == 1:
            cur.append(d)
        else:
            groups.append(cur)
            cur = [d]
    groups.append(cur)

    parts = []
    for g in groups:
        first, last = g[0], g[-1]
        fw = WEEKDAYS_KR[first.weekday()]
        if first == last:
            parts.append(f"{first.month}.{first.day}({fw})")
        else:
            lw = WEEKDAYS_KR[last.weekday()]
            if first.month == last.month:
                parts.append(f"{first.month}.{first.day}({fw})~{last.day}({lw})")
            else:
                parts.append(f"{first.month}.{first.day}({fw})~{last.month}.{last.day}({lw})")
    return ', '.join(parts)


# 공연별 최신 행 (기준일자 기반, 동일 날짜는 행 인덱스 큰 쪽 선택)
_daily_sorted = daily_df.sort_values(['_date_dt', '_sort_key'], ascending=[True, True])
grouped = _daily_sorted.groupby('공연명', as_index=False).last()

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
        perf_id = matched.get('ID')

        # 공연일: 회차상세에서 날짜 목록 가져와서 요일 포함 포맷
        if rounds_df is not None and perf_id:
            rd = rounds_df[rounds_df['ID'] == perf_id]
            rd_dates = rd['공연일'].dropna().tolist()
            if rd_dates:
                perf_date_map[name] = _fmt_perf_dates(rd_dates)

        # 공연일(날짜): 수식 셀이 nan이면 공연마스터 시작일 사용
        start_dt = pd.to_datetime(matched.get('시작일'), errors='coerce')
        if pd.notna(start_dt):
            grouped.at[idx, '공연일(날짜)'] = start_dt
            # 회차상세에서 못 가져왔으면 시작일/종료일로 fallback
            if name not in perf_date_map:
                end_dt = pd.to_datetime(matched.get('종료일'), errors='coerce')
                sw = WEEKDAYS_KR[start_dt.weekday()]
                if pd.notna(end_dt) and start_dt != end_dt:
                    ew = WEEKDAYS_KR[end_dt.weekday()]
                    perf_date_map[name] = f"{start_dt.month}.{start_dt.day}({sw})~{end_dt.day}({ew})"
                else:
                    perf_date_map[name] = f"{start_dt.month}.{start_dt.day}({sw})"
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
    st.write(f"**데이터 소스:** `{get_data_source()}`")
    st.write(f"**갱신일자 (base_date):** `{repr(base_date)}` (누적기록 max 기준일자)")
    st.write(f"**daily_df:** {daily_df.shape[0]}행 × {daily_df.shape[1]}열")
    st.write(f"**trend_df:** {trend_df.shape[0] if trend_df is not None else 'None'}행")
    if trend_df is not None and '기준일자' in trend_df.columns:
        st.write(f"**trend 날짜 범위:** {trend_df['기준일자'].min()} ~ {trend_df['기준일자'].max()}")
    st.write("**daily_df 마지막 10행 (기준일자 desc):**")
    _dbg = daily_df.sort_values('_date_dt', ascending=False).head(10)
    st.dataframe(_dbg[['기준일자','공연명','합계좌석','합계금액','갱신시각','데이터유형']],
                 use_container_width=True, hide_index=True)
    st.write("**grouped (공연별 최신값):**")
    st.dataframe(grouped[['공연명','기준일자','합계좌석','합계금액']],
                 use_container_width=True, hide_index=True)
    if master_df is not None:
        st.write(f"**공연마스터:** {master_df.shape[0]}행")
        st.dataframe(master_df[['사업명', '시작일', '종료일', '기준석', '총회차']].head(), use_container_width=True, hide_index=True)
    st.write(f"**공연일 포맷:**")
    for k, v in perf_date_map.items():
        st.write(f"  {k[:20]}… → {v}")

# ── 전일대비 계산 (누적기록의 전일대비(석) 컬럼 또는 최신 2일치 비교) ──
daily_diff = {}
if trend_df is not None and not trend_df.empty and '기준일자' in trend_df.columns and '공연명' in trend_df.columns:
    for perf_name, grp in trend_df.groupby('공연명'):
        grp_sorted = grp.dropna(subset=['기준일자']).sort_values('기준일자')
        if grp_sorted.empty:
            continue
        latest = grp_sorted.iloc[-1]
        # 1차: 전일대비(석) 컬럼 직접 사용
        if '전일대비(석)' in grp_sorted.columns and pd.notna(latest.get('전일대비(석)')) and latest['전일대비(석)'] != 0:
            daily_diff[perf_name] = int(latest['전일대비(석)'])
        # 2차: 없으면 최신 2일치 합계좌석 차이
        elif '합계좌석' in grp_sorted.columns and len(grp_sorted) >= 2:
            last_two = grp_sorted.tail(2)
            diff = int(last_two.iloc[1]['합계좌석'] - last_two.iloc[0]['합계좌석'])
            daily_diff[perf_name] = diff

# ── 판매중 / 종료 분리 (공연마스터 티켓오픈일·종료일 기반) ──
today = pd.Timestamp.now().normalize()

# grouped에 티켓오픈일, 종료일 병합
for idx, row in grouped.iterrows():
    matched_m = match_performance(row['공연명'], master_df)
    if matched_m is not None:
        grouped.at[idx, '티켓오픈일'] = pd.to_datetime(matched_m.get('티켓오픈일'), errors='coerce')
        grouped.at[idx, '종료일'] = pd.to_datetime(matched_m.get('종료일'), errors='coerce')
    else:
        grouped.at[idx, '티켓오픈일'] = pd.NaT
        grouped.at[idx, '종료일'] = pd.NaT

grouped['티켓오픈일'] = pd.to_datetime(grouped['티켓오픈일'], errors='coerce')
grouped['종료일'] = pd.to_datetime(grouped['종료일'], errors='coerce')

if '공연일(날짜)' in grouped.columns:
    grouped['공연일(날짜)'] = pd.to_datetime(grouped['공연일(날짜)'], errors='coerce')
grouped['_days'] = (grouped['공연일(날짜)'] - today).dt.days if '공연일(날짜)' in grouped.columns else None

# 판매중: 티켓오픈일 <= today <= 종료일
_has_dates = grouped['티켓오픈일'].notna() & grouped['종료일'].notna()
active_mask = _has_dates & (grouped['티켓오픈일'] <= today) & (today <= grouped['종료일'])
ended_mask = _has_dates & (today > grouped['종료일'])
notyet_mask = _has_dates & (grouped['티켓오픈일'] > today)
# 날짜 정보 없는 행은 기존 로직(공연일 기준) fallback
no_dates_mask = ~_has_dates
if no_dates_mask.any() and '공연일(날짜)' in grouped.columns:
    fallback_active = no_dates_mask & (grouped['_days'] >= 0)
    fallback_ended = no_dates_mask & (grouped['_days'] < 0)
    active_mask = active_mask | fallback_active
    ended_mask = ended_mask | fallback_ended

active_df = grouped[active_mask].sort_values('공연일(날짜)', ascending=True).copy() if '공연일(날짜)' in grouped.columns else grouped[active_mask].copy()
ended_df = grouped[ended_mask].sort_values('공연일(날짜)', ascending=False).copy() if '공연일(날짜)' in grouped.columns else grouped[ended_mask].copy()
notyet_df = grouped[notyet_mask].copy()

if not notyet_df.empty:
    st.sidebar.info(f"미오픈 공연 {len(notyet_df)}건: {', '.join(notyet_df['공연명'].tolist())}")


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
    return f"{occ_pct:.1f}"


def fmt_money_man(val):
    if pd.isna(val) or val == 0:
        return "0"
    return f"{int(round(val / 10000)):,}"


def fmt_daily_diff(perf_name):
    diff = daily_diff.get(perf_name)
    if diff is None:
        return "-"
    if diff > 0:
        return f"+{diff}"
    elif diff < 0:
        return f"{diff}"
    return "0"


def _dday_color(days):
    """D-day 값에 따른 색상 반환"""
    if pd.isna(days):
        return "#FFFFFF"
    d = int(days)
    if d < 0:
        return "#888888"
    if d <= 7:
        return "#FF8C00"
    if d <= 28:
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
    occ_label = '점유율(%)' if is_active else '최종 점유율(%)'
    headers = ['공연일', '공연명', 'D-day', '판매좌석(석)', '전일대비(석)', '오픈석(석)', occ_label, '판매금액(만원)']
    right_align_cols = {3, 4, 5, 6, 7}

    html = '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
    html += '<tr style="background-color:rgba(255,255,255,0.08);">'
    for i, h in enumerate(headers):
        align = 'right' if i in right_align_cols else 'left'
        html += f'<th style="text-align:{align};padding:8px 12px;border-bottom:2px solid #444;color:#AAA;font-weight:bold;">{h}</th>'
    html += '</tr>'

    prev_zone = None
    for _, r in df.iterrows():
        days = r.get('_days')
        dday_col = _dday_color(days)
        seats = int(r['합계좌석']) if pd.notna(r['합계좌석']) else 0
        base_s = int(r['오픈석']) if pd.notna(r.get('오픈석')) else FALLBACK_SEAT
        rounds = int(r['_회차수']) if pd.notna(r.get('_회차수')) else 1
        total_open_seats = base_s * rounds
        open_str = f"{total_open_seats:,}"
        money = r['합계금액'] if pd.notna(r['합계금액']) else 0
        occ = fmt_occupancy(r.get('점유율'))
        diff_str = fmt_daily_diff(r['공연명'])
        money_str = fmt_money_man(money)
        date_str = perf_date_map.get(r['공연명'], '')

        cur_zone = _dday_zone(days) if is_active else -1
        if is_active and prev_zone is not None and cur_zone != prev_zone:
            border_top = 'border-top:2px solid #555;'
        else:
            border_top = ''
        prev_zone = cur_zone

        html += f'<tr style="border-bottom:1px solid #333;{border_top}">'
        # 공연일
        html += f'<td style="padding:8px 12px;color:{dday_col};">{date_str}</td>'
        # 공연명
        html += f'<td style="padding:8px 12px;color:{dday_col};">{r["공연명"]}</td>'
        # D-day
        if is_active:
            html += f'<td style="padding:8px 12px;color:{dday_col};">{fmt_dday(days)}</td>'
        else:
            dt_str = ''
            if '공연일(날짜)' in r.index and pd.notna(r['공연일(날짜)']):
                dt_str = pd.to_datetime(r['공연일(날짜)']).strftime('%Y-%m-%d')
            html += f'<td style="padding:8px 12px;">{dt_str}</td>'
        # 판매좌석 (노랑)
        html += f'<td style="padding:8px 12px;text-align:right;color:#FFD700;font-weight:600;">{seats:,}</td>'
        # 전일대비
        html += f'<td style="padding:8px 12px;text-align:right;color:{ACCENT};font-weight:600;">{diff_str}</td>'
        # 오픈석(누적)
        html += f'<td style="padding:8px 12px;text-align:right;">{open_str}</td>'
        # 점유율
        html += f'<td style="padding:8px 12px;text-align:right;color:{ACCENT};font-weight:600;">{occ}</td>'
        # 합계금액
        html += f'<td style="padding:8px 12px;text-align:right;">{money_str}</td>'
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

# 상업성/공공성 평균 점유율 계산 (공연마스터 기반)
_comm_occ, _pub_occ = [], []
for _, r in active_df.iterrows():
    cat = match_performance_category(r['공연명'], master_df)
    if cat == '상업성':
        _comm_occ.append(r['점유율'])
    elif cat == '공공성':
        _pub_occ.append(r['점유율'])

avg_comm = sum(_comm_occ) / len(_comm_occ) if _comm_occ else 0.0
avg_pub = sum(_pub_occ) / len(_pub_occ) if _pub_occ else 0.0

col1, col2, col3, col4, col5 = st.columns([1.2, 1.5, 1.2, 1.2, 2.5])
col1.metric("판매중 공연", f"{n_active}개")
col2.markdown(
    f'<div style="font-size:14px;color:#AAA;">평균 객석 점유율</div>'
    f'<div style="font-size:32px;font-weight:700;color:{ACCENT};">{avg_occ:.1f}%</div>',
    unsafe_allow_html=True,
)
col3.markdown(
    f'<div style="font-size:14px;color:#AAA;">상업성</div>'
    f'<div style="font-size:28px;font-weight:700;color:#FFD700;">{avg_comm:.1f}%</div>',
    unsafe_allow_html=True,
)
col4.markdown(
    f'<div style="font-size:14px;color:#AAA;">공공성</div>'
    f'<div style="font-size:28px;font-weight:700;color:#FFD700;">{avg_pub:.1f}%</div>',
    unsafe_allow_html=True,
)
renew_color = '#FF8C00' if dates_differ else '#0FFD02'
col5.markdown(
    f'<div style="font-size:14px;color:#AAA;">오늘</div>'
    f'<div style="font-size:20px;font-weight:600;">{today_str}</div>'
    f'<div style="font-size:14px;color:#AAA;margin-top:4px;">갱신 일시</div>'
    f'<div style="font-size:20px;font-weight:600;color:{renew_color};">{base_date_str}</div>',
    unsafe_allow_html=True,
)

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 섹션 2: 판매중 공연 테이블
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.subheader("[1] 공연 현황")

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
    st.subheader("[2] 공연별 점유율 비교")

    # 범례 (HTML, 2그룹 좌우 분리)
    leg_l, leg_r = st.columns(2)
    leg_l.markdown(
        '<div style="font-size:17px;color:#AAA;overflow:visible;margin-bottom:8px;">'
        '<span style="color:#FF4B4B;font-size:21px;">■</span> ~25% &nbsp;&nbsp;'
        '<span style="color:#FF8C00;font-size:21px;">■</span> 25~50% &nbsp;&nbsp;'
        '<span style="color:#FFD700;font-size:21px;">■</span> 50~75% &nbsp;&nbsp;'
        '<span style="color:#FFFFFF;font-size:21px;">■</span> 75%↑'
        '</div>',
        unsafe_allow_html=True,
    )
    leg_r.markdown(
        '<div style="font-size:17px;color:#AAA;text-align:right;overflow:visible;margin-bottom:8px;">'
        '<span style="color:#FFD700;font-size:21px;">┊</span> 공연별 목표 &nbsp;&nbsp;'
        '<span style="color:#FF4B4B;font-size:21px;">┊</span> 100% &nbsp;&nbsp;'
        '<span style="color:#555;font-size:21px;">─</span> D-28'
        '</div>',
        unsafe_allow_html=True,
    )

    # D-day 임박순: 작은 D-day가 위 → Plotly는 아래부터 그리므로 ascending=False
    chart_df = active_df.sort_values('_days', ascending=False).copy()

    # 목표점유율 매칭 (공연마스터 기반, fallback=50)
    chart_df['목표점유율'] = 50.0
    for idx, row in chart_df.iterrows():
        target = get_target_occupancy(row['공연명'], master_df)
        if target is not None and target > 0:
            chart_df.at[idx, '목표점유율'] = float(target)

    chart_df['달성률'] = (chart_df['점유율'] / chart_df['목표점유율'].replace(0, 80) * 100).clip(lower=0)

    # 막대 색상 — 달성률 기준
    def _bar_color(achieve):
        if achieve > 75:
            return '#FFFFFF'
        if achieve > 50:
            return '#FFD700'
        if achieve > 25:
            return '#FF8C00'
        return '#FF4B4B'

    colors = [_bar_color(a) for a in chart_df['달성률']]

    # Y축 라벨 색상 (D-day 기반)
    def _label_color(d):
        if pd.isna(d):
            return '#FFFFFF'
        d = int(d)
        if d <= 7:
            return '#FF8C00'
        if d <= 14:
            return '#FFD700'
        return '#FFFFFF'

    y_labels = chart_df['공연명'].tolist()
    y_dates = [perf_date_map.get(name, '') for name in y_labels]
    y_ddays = chart_df['_days'].tolist()
    label_colors = [_label_color(d) for d in y_ddays]

    # D-28 경계 인덱스
    separator_y = None
    for i in range(len(chart_df) - 1):
        d_cur = chart_df.iloc[i]['_days']
        d_next = chart_df.iloc[i + 1]['_days']
        if pd.notna(d_cur) and pd.notna(d_next) and d_cur > 28 and d_next <= 28:
            separator_y = i + 0.5

    # 막대 텍스트 데이터 준비 (annotation으로 표시)
    bar_text_data = []
    for _, row in chart_df.iterrows():
        occ = row['점유율']
        sold = int(row['합계좌석']) if pd.notna(row['합계좌석']) else 0
        base_s = int(row['오픈석']) if pd.notna(row.get('오픈석')) else FALLBACK_SEAT
        rounds = int(row['_회차수']) if pd.notna(row.get('_회차수')) else 1
        total = base_s * rounds
        bar_text_data.append((occ, sold, total))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=chart_df['점유율'],
        y=y_labels,
        orientation='h',
        width=0.3,
        marker=dict(color=colors),
        text=[''] * len(chart_df),
        showlegend=False,
        cliponaxis=False,
        customdata=list(zip(
            chart_df['_days'].fillna(0).astype(int),
            chart_df['목표점유율'],
            chart_df['달성률'].round(1),
            chart_df['합계좌석'].fillna(0).astype(int),
            chart_df['누적오픈석'].fillna(0).astype(int),
        )),
        hovertemplate=(
            '%{y}<br>'
            'D-%{customdata[0]}<br>'
            '점유율: %{x:.1f}%<br>'
            '목표: %{customdata[1]:.0f}%<br>'
            '달성률: %{customdata[2]:.1f}%<br>'
            '판매: %{customdata[3]:,}석 / 오픈: %{customdata[4]:,}석'
            '<extra></extra>'
        ),
    ))

    # 행별 배경색 홀짝 구분 (짝수 행에 미묘한 밝은 배경)
    for i in range(len(y_labels)):
        if i % 2 == 1:
            fig.add_shape(
                type="rect",
                x0=0, x1=1, xref="paper",
                y0=i - 0.5, y1=i + 0.5, yref="y",
                fillcolor="rgba(255,255,255,0.03)",
                line=dict(width=0),
                layer="below",
            )

    # 막대 바깥 텍스트 (annotation으로 강조색 적용 + thin space 자간)
    G = '#0FFD02'
    S = '\u2009'  # thin space
    for i, (occ, sold, total) in enumerate(bar_text_data):
        html_text = (
            f'<span style="color:{G}">{occ:.1f}</span>%'
            f'{S}({S}<span style="color:{G}">{sold:,}</span>{S}/{S}{total:,}{S})'
        )
        fig.add_annotation(
            x=occ + 1, y=y_labels[i], yref="y",
            text=html_text, showarrow=False,
            xanchor='left', font=dict(size=12, color='#FFFFFF'),
            bgcolor='rgba(14,17,23,0.7)', borderpad=2,
        )

    # 100% 기준선
    fig.add_vline(x=100, line_dash="dash", line_color=COLORS['danger'],
                  annotation_text="100%", annotation_position="top right")

    # 각 공연별 목표점유율 개별 세로선 + annotation (모든 공연에 개별 표시)
    target_values = set()
    for i, (_, row) in enumerate(chart_df.iterrows()):
        target = row['목표점유율']
        target_values.add(int(target))
        fig.add_shape(
            type="line",
            x0=target, x1=target,
            y0=i - 0.25, y1=i + 0.25,
            yref="y",
            line=dict(color="#FFD700", width=2, dash="dot"),
        )
        fig.add_annotation(
            x=target, y=i, yref="y",
            text=f"{target:.0f}%",
            showarrow=False,
            font=dict(color="#FFD700", size=9),
            yshift=16,
            bgcolor='rgba(14,17,23,0.7)', borderpad=1,
        )

    # D-28 구분선 (Y축 라벨부터 차트 끝까지 전체 너비)
    if separator_y is not None:
        fig.add_shape(
            type="line",
            x0=0, x1=1, xref="paper",
            y0=separator_y, y1=separator_y, yref="y",
            line=dict(color="#555", width=2),
        )
        fig.add_annotation(
            x=1.0, xref="paper", xanchor="right",
            y=separator_y, yref="y",
            text="<b>D-28</b>", showarrow=False,
            font=dict(color="#FFFFFF", size=12),
            yshift=12,
        )

    # X축 눈금: 목표값은 노란색, 나머지 흰색
    base_ticks = [0, 20, 40, 60, 80, 100]
    all_ticks = sorted(set(base_ticks) | target_values)
    tick_texts = [
        f'<span style="color:#FFD700;font-weight:bold">{t}</span>' if t in target_values
        else f'{t}'
        for t in all_ticks
    ]

    # Y축 라벨: 3줄 (공연명 / 공연일 / D-day)
    y_tick_texts = []
    for name, date_str, color, days in zip(y_labels, y_dates, label_colors, y_ddays):
        dday_str = fmt_dday(days) if pd.notna(days) else ''
        dday_color = _label_color(days)
        lines = f'<span style="color:{color};font-size:13px;line-height:2;">{name}</span>'
        if date_str:
            lines += f'<br><span style="color:#999;font-size:13px;line-height:2;">{date_str}</span>'
        if dday_str:
            lines += f'<br><span style="color:{dday_color};font-size:13px;font-weight:bold;line-height:2;">{dday_str}</span>'
        y_tick_texts.append(lines)

    fig.update_layout(
        xaxis_title="", yaxis_title="",
        height=600,
        margin=dict(t=60, l=60),
        bargap=0.35,
        showlegend=False,
        xaxis=dict(
            tickvals=all_ticks, ticktext=tick_texts,
            showgrid=True, gridcolor="rgba(255,255,255,0.08)", gridwidth=1,
        ),
        yaxis=dict(ticktext=y_tick_texts, tickvals=y_labels, showgrid=False),
    )
    # X축 라벨을 우측 하단에 배치
    fig.add_annotation(
        x=1.0, y=-0.07, xref="paper", yref="paper",
        xanchor="right", yanchor="top",
        text="점유율 (%)", showarrow=False,
        font=dict(size=11, color="#AAA"),
    )

    fig = apply_common_layout(fig)
    st.plotly_chart(fig, use_container_width=True)

st.markdown('<hr style="margin:8px 0;border-color:rgba(255,255,255,0.1);">', unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 판매추이 (판매중 공연만)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if not trend_df.empty and '기준일자' in trend_df.columns and '공연명' in trend_df.columns:
    st.markdown('<div style="font-size:2rem;font-weight:700;margin:0 0 24px 0;">[3] 판매추이</div>', unsafe_allow_html=True)

    # ── 반응형 CSS (판매추이 차트) ──
    st.markdown('''<style>
    div[data-testid="stPlotlyChart"] {
        aspect-ratio: 16/9;
        min-height: 350px;
        max-height: 850px;
    }
    div[data-testid="stPlotlyChart"] > div,
    div[data-testid="stPlotlyChart"] iframe {
        height: 100% !important;
        width: 100% !important;
    }

    @media (max-width: 768px) {
        div[data-testid="stHorizontalBlock"] {
            flex-direction: column !important;
        }
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            min-width: 100% !important;
        }
    }
    </style>''', unsafe_allow_html=True)

    # ── 판매중 공연 목록 결정 ──
    # 1차: 공연마스터에 '상태' 컬럼이 있으면 '판매중'인 공연
    # 2차: 판매현황 테이블의 active_df (공연일 >= 오늘) 상위 6개
    _active_perf_names = []
    if master_df is not None and '상태' in master_df.columns:
        selling = master_df[master_df['상태'].astype(str).str.strip() == '판매중']
        for _, mr in selling.iterrows():
            master_name = str(mr['사업명']).strip()
            for tn in trend_df['공연명'].unique():
                tn_s = str(tn).strip()
                if tn_s == master_name or tn_s in master_name or master_name in tn_s:
                    _active_perf_names.append(tn)
                    break

    if not _active_perf_names and not active_df.empty:
        _active_perf_names_set = set()
        for aname in active_df['공연명'].tolist()[:6]:
            for tn in trend_df['공연명'].unique():
                tn_s = str(tn).strip()
                aname_s = str(aname).strip()
                if tn_s == aname_s or tn_s in aname_s or aname_s in tn_s:
                    _active_perf_names_set.add(tn)
                    break
        _active_perf_names = list(_active_perf_names_set)

    # ── X축 기간 범위 결정 ──
    _x_min, _x_max = None, None
    for ap_name in _active_perf_names:
        matched_m = _match_master(ap_name, master_df)
        # 시작: 티켓오픈일 → 해당 공연 trend 최초 기록일
        if matched_m is not None and pd.notna(matched_m.get('티켓오픈일')):
            open_dt = pd.to_datetime(matched_m['티켓오픈일'], errors='coerce')
            if pd.notna(open_dt):
                _x_min = min(_x_min, open_dt) if _x_min else open_dt
        if _x_min is None or (matched_m is not None and pd.isna(matched_m.get('티켓오픈일'))):
            ap_trend = trend_df[trend_df['공연명'] == ap_name]
            if not ap_trend.empty:
                first_dt = pd.to_datetime(ap_trend['기준일자'], errors='coerce').min()
                if pd.notna(first_dt):
                    _x_min = min(_x_min, first_dt) if _x_min else first_dt
        # 끝: 공연마스터 종료일 또는 공연일(날짜)
        if matched_m is not None:
            end_dt = pd.to_datetime(matched_m.get('종료일'), errors='coerce')
            if pd.notna(end_dt):
                _x_max = max(_x_max, end_dt) if _x_max else end_dt

    # fallback: active_df의 최대 공연일(날짜)
    if _x_max is None and not active_df.empty and '공연일(날짜)' in active_df.columns:
        _x_max = active_df['공연일(날짜)'].max()

    # ── 영역2: 공통 컨트롤 ──
    _ctrl1, _ctrl2, _ctrl_spacer = st.columns([2.5, 1.5, 4])
    _LBL = 'font-size:24px;font-weight:bold;color:#0FFD02;margin:0 0 8px 0;'
    with _ctrl1:
        st.markdown(f'<div style="{_LBL}">① 지표 선택</div>', unsafe_allow_html=True)
        trend_metric = st.radio("지표 선택", ['점유율(%)', '합계좌석', '합계금액'], horizontal=True, label_visibility="collapsed")
    with _ctrl2:
        st.markdown(f'<div style="{_LBL}">② 기간 단위</div>', unsafe_allow_html=True)
        trend_resample = st.radio("기간 단위", ['일별', '주별', '월별'], index=1, horizontal=True, label_visibility="collapsed")

    perf_list = trend_df['공연명'].unique().tolist()
    _default_perfs = [p for p in _active_perf_names if p in perf_list] or perf_list

    # ── 공연 카테고리: 공연마스터 사업구분 기반 ──
    def _get_category(perf_name):
        cat = match_performance_category(perf_name, master_df)
        return cat if cat else '공공성'

    _commercial = [p for p in _default_perfs if _get_category(p) == '상업성']
    _public = [p for p in _default_perfs if _get_category(p) == '공공성']

    # ── 통합 공연 리스트 (공연일 오름차순) ──
    _all_perfs = _commercial + _public
    _perf_date_lookup = {}
    if not active_df.empty and '공연일(날짜)' in active_df.columns:
        for _, _r in active_df.iterrows():
            _perf_date_lookup[_r['공연명']] = _r['공연일(날짜)']
    _far_future = pd.Timestamp('2099-12-31')
    _all_perfs.sort(key=lambda p: _perf_date_lookup.get(p, _far_future))

    _LABEL_STYLE = 'font-size:24px;font-weight:bold;color:#0FFD02;margin:0 0 12px 0;'

    # ── 공연별 색상 팔레트 ──
    _VIVID_COLORS = ['#FF6B8A', '#64B5F6', '#00FF00', '#FFFF00', '#FF8000', '#8000FF', '#00FFFF']

    def _build_color_map(perf_names):
        return {name: _VIVID_COLORS[i % len(_VIVID_COLORS)] for i, name in enumerate(perf_names)}

    # ── 통합 색상 맵 (체크리스트 + 차트 공유) ──
    _color_map_all = _build_color_map(_all_perfs)

    # ── 체크리스트 테이블 CSS (외곽선·행/열 구분선) ──
    st.markdown('''<style>
    div[data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] {
        gap: 0 !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] {
        border-bottom: 1px solid #333;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"]:first-of-type {
        border-bottom: 2px solid #555;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"]:last-of-type {
        border-bottom: none;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stColumn"]:not(:last-child) {
        border-right: 1px solid #333;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stColumn"] {
        padding: 2px 4px !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stCheckbox"] {
        display: flex;
        align-items: center;
        justify-content: center;
        padding-top: 6px;
    }
    </style>''', unsafe_allow_html=True)

    # ── 공연 선택 표 (체크박스 + 색상 공연명, 테이블 스타일) ──
    def _render_checklist(container, title, perf_names, editor_key, color_map):
        with container:
            st.markdown(f'<div style="{_LABEL_STYLE}">{title}</div>', unsafe_allow_html=True)
            if not perf_names:
                st.caption("해당 공연 없음")
                return []
            selected = []
            with st.container(border=True):
                # 헤더
                _hdr = st.columns([0.4, 0.8, 2.4], gap="small")
                _hdr[0].markdown('<div style="padding:14px 8px;font-size:12px;color:#FFFFFF;font-weight:bold;text-align:center;">선택</div>', unsafe_allow_html=True)
                _hdr[1].markdown('<div style="padding:14px 8px;font-size:12px;color:#FFFFFF;font-weight:bold;">공연일</div>', unsafe_allow_html=True)
                _hdr[2].markdown('<div style="padding:14px 8px;font-size:12px;color:#FFFFFF;font-weight:bold;">공연명</div>', unsafe_allow_html=True)
                # 데이터 행
                for i, pname in enumerate(perf_names):
                    date_str = perf_date_map.get(pname, '')
                    color = color_map.get(pname, '#FFF')
                    cols = st.columns([0.4, 0.8, 2.4], gap="small")
                    with cols[0]:
                        checked = st.checkbox('', value=True, key=f"{editor_key}_{i}", label_visibility="collapsed")
                    with cols[1]:
                        st.markdown(f'<div style="padding:6px 8px;font-size:14px;color:#CCC;">{date_str}</div>', unsafe_allow_html=True)
                    with cols[2]:
                        st.markdown(f'<div style="padding:6px 8px;font-size:14px;color:{color};font-weight:500;">{pname}</div>', unsafe_allow_html=True)
                    if checked:
                        selected.append(pname)
            return selected

    # ── 통합: 테이블 + 차트 좌우 배치 ──
    _trend_tbl, _trend_chart = st.columns([1, 1])
    selected_perfs = _render_checklist(_trend_tbl, "③ 공연 선택", _all_perfs, "_trend_ed_all", _color_map_all)

    # ── 공통 데이터 준비 ──
    filtered_trend = trend_df[trend_df['공연명'].isin(selected_perfs)].copy()
    filtered_trend['기준일자'] = pd.to_datetime(filtered_trend['기준일자'], errors='coerce')
    filtered_trend = filtered_trend.dropna(subset=['기준일자']).sort_values(by='기준일자')

    if _x_min is not None:
        filtered_trend = filtered_trend[filtered_trend['기준일자'] >= _x_min]
    if _x_max is not None:
        filtered_trend = filtered_trend[filtered_trend['기준일자'] <= _x_max]

    # 점유율 계산
    _open_seat_map = {}
    for pname in selected_perfs:
        matched_m = _match_master(pname, master_df)
        if matched_m is not None:
            _open_seat_map[pname] = int(matched_m['총오픈석']) if pd.notna(matched_m.get('총오픈석')) and matched_m['총오픈석'] > 0 else FALLBACK_SEAT
        else:
            _open_seat_map[pname] = FALLBACK_SEAT

    if '합계좌석' in filtered_trend.columns:
        filtered_trend['_오픈석'] = filtered_trend['공연명'].map(_open_seat_map).fillna(FALLBACK_SEAT)
        filtered_trend['점유율(%)'] = (filtered_trend['합계좌석'] / filtered_trend['_오픈석'] * 100).clip(0, 100)

    _y_col = trend_metric
    _resample_cols = [_y_col]
    if _y_col == '점유율(%)':
        _resample_cols = ['합계좌석', '_오픈석', '점유율(%)']

    # ── Y축 동적 스케일링 함수 ──
    def _snap_ymax_pct(max_val):
        if max_val <= 5: return 8
        if max_val <= 10: return 15
        if max_val <= 20: return 25
        if max_val <= 30: return 35
        if max_val <= 40: return 50
        if max_val <= 50: return 60
        if max_val <= 75: return 85
        return 100

    def _snap_ymax_general(max_val):
        if max_val <= 0:
            return 100
        import math
        ceil = max_val * 1.18
        mag = 10 ** math.floor(math.log10(ceil))
        step = mag / 2
        nice = math.ceil(ceil / step) * step
        return nice

    # ── 리샘플링 ──
    if _y_col in filtered_trend.columns and not filtered_trend.empty:
        if trend_resample == '주별':
            filtered_trend = (
                filtered_trend.groupby([pd.Grouper(key='기준일자', freq='W-MON'), '공연명'])
                [_resample_cols].last().reset_index()
            )
        elif trend_resample == '월별':
            filtered_trend = (
                filtered_trend.groupby([pd.Grouper(key='기준일자', freq='MS'), '공연명'])
                [_resample_cols].last().reset_index()
            )
        filtered_trend = filtered_trend.dropna(subset=[_y_col]).sort_values('기준일자')

    # ── 공연별 티켓오픈일 맵 (정체 감지용, 21일 경과 판정) ──
    _ticket_open_map = {}
    for pname in _default_perfs:
        _m = _match_master(pname, master_df)
        if _m is not None and pd.notna(_m.get('티켓오픈일')):
            _ticket_open_map[pname] = pd.to_datetime(_m['티켓오픈일'], errors='coerce')
        else:
            _p_trend = trend_df[trend_df['공연명'] == pname]
            if not _p_trend.empty:
                _ticket_open_map[pname] = pd.to_datetime(_p_trend['기준일자'], errors='coerce').min()

    # ── 목표 점유율 매핑 (공연마스터 기반) ──
    def _get_target_occ(pname):
        val = get_target_occupancy(pname, master_df)
        return val if val and val > 0 else None

    # ── 영역4: 차트 ──
    def _render_chart(container, title, cat_perfs, color_map):
        cat_selected = [p for p in cat_perfs if p in selected_perfs]
        cat_data = filtered_trend[filtered_trend['공연명'].isin(cat_selected)]
        with container:
            if cat_data.empty or _y_col not in cat_data.columns:
                st.caption("데이터 없음")
                return

            _data_max = cat_data[_y_col].max()
            if _y_col == '점유율(%)':
                _y_upper = _snap_ymax_pct(_data_max)
            else:
                _y_upper = _snap_ymax_general(_data_max)

            # Y축 라벨 텍스트 (가로 annotation용)
            if _y_col == '점유율(%)':
                _yaxis_label = '점유율(%)'
            elif _y_col == '합계금액':
                _yaxis_label = '합계금액(만원)'
            else:
                _yaxis_label = '합계좌석(석)'

            if _y_col == '점유율(%)':
                fig = px.line(cat_data, x='기준일자', y='점유율(%)', color='공연명', markers=True,
                              hover_data={'합계좌석': ':,', '_오픈석': ':,'},
                              color_discrete_map=color_map)
                fig.update_layout(yaxis=dict(range=[0, _y_upper]))
                fig.for_each_trace(lambda t: t.update(
                    hovertemplate='%{x}<br>점유율: %{y:.1f}%<br>판매: %{customdata[0]:,}석 / 오픈: %{customdata[1]:,}석<extra>%{fullData.name}</extra>'
                ))
            else:
                fig = px.line(cat_data, x='기준일자', y=_y_col, color='공연명', markers=True,
                              color_discrete_map=color_map)
                fig.update_layout(yaxis=dict(range=[0, _y_upper]))

            # Y축 최상단 눈금만 강조색
            import numpy as np
            _yticks = list(np.linspace(0, _y_upper, 6))
            _ytick_texts = []
            for v in _yticks:
                txt = f'{v:.0f}' if v == int(v) else f'{v:,.0f}'
                if v == _y_upper:
                    _ytick_texts.append(f'<span style="color:#0FFD02;font-weight:bold">{txt}</span>')
                else:
                    _ytick_texts.append(txt)


            fig.update_layout(
                xaxis_title="", yaxis_title="",
                margin=dict(t=50, b=30, l=50, r=20),
                showlegend=False,
                yaxis=dict(range=[0, _y_upper], tickvals=_yticks, ticktext=_ytick_texts),
            )
            # Y축 라벨: plot area 바깥 상단, Y축 숫자 왼쪽 정렬선 기준
            fig.add_annotation(
                text=_yaxis_label, xref='paper', yref='paper',
                x=-0.02, y=1.08, showarrow=False, xanchor='left', yanchor='bottom',
                font=dict(size=11, color='#AAA'),
            )

            # ── 정체 감지 annotation ──
            _now = pd.Timestamp.now()
            for pname in cat_selected:
                # 21일 미경과 공연은 스킵
                _open_dt = _ticket_open_map.get(pname)
                if _open_dt is None or pd.isna(_open_dt) or (_now - _open_dt).days < 21:
                    continue
                _pdata = cat_data[cat_data['공연명'] == pname].sort_values('기준일자')
                if len(_pdata) < 3:
                    continue
                _vals = _pdata[_y_col].values
                _dates = _pdata['기준일자'].tolist()
                _deltas = np.diff(_vals)
                _avg_delta = np.mean(_deltas)
                if _avg_delta <= 0:
                    continue
                _threshold = _avg_delta * 0.5
                # 정체 segment 추적 후 각 segment 중간 지점에 표시
                segments = []
                in_stag = False
                seg_start = None
                for j, d in enumerate(_deltas):
                    if d <= _threshold:
                        if not in_stag:
                            seg_start = j
                            in_stag = True
                    else:
                        if in_stag:
                            segments.append((seg_start, j - 1))
                            in_stag = False
                if in_stag:
                    segments.append((seg_start, len(_deltas) - 1))
                for seg_s, seg_e in segments:
                    val_s = seg_s + 1
                    val_e = seg_e + 1
                    mid_idx = (val_s + val_e) // 2
                    _line_color = color_map.get(pname, '#FF6666')
                    fig.add_annotation(
                        x=_dates[mid_idx], y=float(_vals[mid_idx]),
                        text="정체", showarrow=False,
                        font=dict(size=9, color=get_contrast_text_color(_line_color)),
                        bgcolor=_line_color, borderpad=2,
                        yshift=10, xanchor='center',
                    )

            fig = apply_common_layout(fig)
            st.plotly_chart(fig, use_container_width=True)

    _render_chart(_trend_chart, "판매추이", _all_perfs, _color_map_all)
