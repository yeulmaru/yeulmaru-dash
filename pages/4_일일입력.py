import streamlit as st
import pandas as pd
from datetime import date, datetime, timezone, timedelta
import time
import re

from utils.data_loader import (
    load_performance_master,
    load_round_details,
    load_sales_trend,
    get_active_performances,
    match_performance_category,
    get_target_occupancy,
    match_performance,
)
# save_daily_entry: Cloud/로컬 자동 분기 (아래 _IS_CLOUD 이후 설정)
from utils.charts import COLORS

st.set_page_config(page_title="일일입력", page_icon="📝", layout="wide")

from utils.auth import check_password
check_password()

# ── Cloud 환경 감지 ──
import os
_IS_CLOUD = os.path.exists("/mount/src")
# Cloud에서도 일일입력 가능 (SharePoint Graph API 직접 쓰기)
from utils.local_excel_writer import save_daily_entry_local, save_daily_entry_cloud
save_daily_entry = save_daily_entry_cloud if _IS_CLOUD else save_daily_entry_local

# ── 상수 ──
WEEKDAYS_KR = ['월', '화', '수', '목', '금', '토', '일']
ACCENT = COLORS['primary']
LBL_BLUE = '#FFFFFF'
KST = timezone(timedelta(hours=9))

# ── 세션 초기화 ──
if "has_unsaved_changes" not in st.session_state:
    st.session_state.has_unsaved_changes = False
if "save_results" not in st.session_state:
    st.session_state.save_results = []

# ── 데이터 로드 ──
master_df = load_performance_master()
rounds_df = load_round_details()
trend_df = load_sales_trend()

if master_df is None or master_df.empty:
    st.error("공연마스터 데이터를 불러올 수 없습니다. 데이터 파일을 확인해주세요.")
    st.stop()

# ── 페이지 상단 ──
st.title("📝 일일 판매현황 입력")

# 저장 버튼 커스텀 스타일 (검정 배경 + No Mute green)
st.markdown("""
<style>
div.stButton > button[kind="primary"] {
    background-color: #0a0a0a;
    color: #0FFD02;
    border: 1px solid #0FFD02;
    font-weight: 600;
    transition: all 0.2s ease;
}
div.stButton > button[kind="primary"]:hover {
    background-color: #151515;
    box-shadow: 0 0 14px rgba(15, 253, 2, 0.4);
    border-color: #0FFD02;
    color: #0FFD02;
    transform: translateY(-1px);
}
div.stButton > button[kind="primary"]:active {
    background-color: #1a1a1a;
    transform: translateY(0);
    box-shadow: 0 0 8px rgba(15, 253, 2, 0.3);
}
div.stButton > button[kind="primary"]:focus:not(:active) {
    color: #0FFD02;
    border-color: #0FFD02;
}
/* [1] 회차 테이블 텍스트 셀 수직 중앙 정렬 */
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > div {
    display: flex;
    flex-direction: column;
    justify-content: center;
}
/* 헤더 행 음영 배경 (marker div 바로 뒤 st.columns) */
.header-row-bg + div[data-testid="stHorizontalBlock"] {
    background: rgba(255,255,255,0.05) !important;
    border-radius: 4px;
    padding: 2px 0;
}
/* 회차 테이블 행 정렬 */
.round-table-wrap div[data-testid="stHorizontalBlock"] {
    align-items: center !important;
}
/* 방법 A: stNumberInput 빈 label/wrapper 완전 제거 (모든 selector) */
.round-table-wrap div[data-testid="stNumberInput"] label,
.round-table-wrap div[data-testid="stNumberInput"] [data-testid="stWidgetLabel"],
.round-table-wrap div[data-testid="stNumberInput"] > label {
    display: none !important;
    height: 0 !important;
    min-height: 0 !important;
    max-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
}
.round-table-wrap div[data-testid="stNumberInput"] {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    padding-top: 0 !important;
}
/* 방법 B: 텍스트 셀에 padding-top 보정 (~12px, label wrapper 잔여 높이 절반) */
.round-table-wrap div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] .round-text {
    padding-top: 12px;
}
</style>
""", unsafe_allow_html=True)

# (저장 결과는 각 카드 내부에서 표시됨 - 아래 카드 렌더링 참조)

# 미저장 경고 배너 (입력 위젯 값 실시간 스캔)
_any_nonzero = any(
    v != 0 for k, v in st.session_state.items()
    if k.startswith('input_') and isinstance(v, (int, float))
)
if _any_nonzero:
    st.warning("⚠️ 저장되지 않은 변경사항이 있습니다.")

st.markdown("---")
base_date = st.date_input("📅 기준일자", value=date.today())
today = pd.Timestamp(base_date)
date_int = int(base_date.strftime('%Y%m%d'))

# ── 판매중 공연 목록 ──
active_df = get_active_performances(master_df, today=today)

# 시작일 가까운 순 (오름차순) 정렬
if not active_df.empty and '시작일' in active_df.columns:
    active_df = active_df.copy()
    active_df['_start_dt'] = pd.to_datetime(active_df['시작일'], errors='coerce')
    active_df = active_df.sort_values('_start_dt', na_position='last').drop(columns=['_start_dt']).reset_index(drop=True)

if active_df.empty:
    st.info("현재 판매중인 공연이 없습니다.")
    st.stop()

st.markdown(f"**판매중 공연 {len(active_df)}개**")
st.markdown("")


# ── 전일 데이터 로드 ──
def _load_prev_day_data(trend_df, base_date_ts):
    if trend_df is None or trend_df.empty:
        return {}, None
    tdf = trend_df.copy()
    tdf['기준일자'] = pd.to_datetime(tdf['기준일자'], errors='coerce')
    tdf = tdf.dropna(subset=['기준일자'])
    prev_dates = tdf[tdf['기준일자'] < base_date_ts]['기준일자'].unique()
    if len(prev_dates) == 0:
        return {}, None
    prev_date = max(prev_dates)
    prev_df = tdf[tdf['기준일자'] == prev_date]
    result = {}
    for _, r in prev_df.iterrows():
        name = str(r['공연명']).strip()
        entry = {}
        for col in ['유료좌석', '유료금액', '무료좌석', '합계좌석', '합계금액']:
            if col in r.index and pd.notna(r[col]):
                entry[col] = int(r[col])
        result[name] = entry
    return result, prev_date


def _load_today_data(trend_df, base_date_ts):
    if trend_df is None or trend_df.empty:
        return {}
    tdf = trend_df.copy()
    tdf['기준일자'] = pd.to_datetime(tdf['기준일자'], errors='coerce')
    today_df = tdf[tdf['기준일자'] == base_date_ts]
    result = {}
    for _, r in today_df.iterrows():
        name = str(r['공연명']).strip()
        entry = {}
        for col in ['유료좌석', '유료금액', '무료좌석',
                     '합계좌석', '합계금액']:
            if col in r.index and pd.notna(r[col]):
                entry[col] = int(r[col])
        if name not in result:
            result[name] = entry
    return result


def _load_latest_for_perf(trend_df, perf_name, base_date_ts):
    """해당 공연의 base_date 이하 가장 최근 저장값 반환 (오늘 포함)"""
    if trend_df is None or trend_df.empty:
        return None
    tdf = trend_df.copy()
    tdf['기준일자'] = pd.to_datetime(tdf['기준일자'], errors='coerce')
    tdf = tdf.dropna(subset=['기준일자'])
    tdf = tdf[tdf['기준일자'] <= base_date_ts]
    perf_s = str(perf_name).strip()
    mask = tdf['공연명'].astype(str).apply(
        lambda x: x.strip() == perf_s
    )
    perf_df = tdf[mask]
    if perf_df.empty:
        return None
    latest = perf_df.sort_values('기준일자').iloc[-1]
    def _i(col):
        v = latest.get(col)
        try:
            return int(v) if pd.notna(v) else 0
        except (ValueError, TypeError):
            return 0
    return {
        '유료좌석': _i('유료좌석'),
        '유료금액': _i('유료금액'),
        '무료좌석': _i('무료좌석'),
        '합계좌석': _i('합계좌석'),
        '합계금액': _i('합계금액'),
        '기준일자': latest['기준일자'],
    }


def _load_prev_for_perf(trend_df, perf_name, base_date_ts):
    """해당 공연의 직전 저장값 반환 (현재 바로 이전, 같은 날 포함)"""
    if trend_df is None or trend_df.empty:
        return None
    tdf = trend_df.copy()
    tdf['기준일자'] = pd.to_datetime(tdf['기준일자'], errors='coerce')
    tdf = tdf.dropna(subset=['기준일자'])
    tdf = tdf[tdf['기준일자'] <= base_date_ts]
    perf_s = str(perf_name).strip()
    mask = tdf['공연명'].astype(str).apply(
        lambda x: x.strip() == perf_s
    )
    perf_df = tdf[mask]
    if len(perf_df) < 2:
        return None
    prev_row = perf_df.sort_values('기준일자').iloc[-2]
    def _i(col):
        v = prev_row.get(col)
        try:
            return int(v) if pd.notna(v) else 0
        except (ValueError, TypeError):
            return 0
    return {
        '유료좌석': _i('유료좌석'),
        '유료금액': _i('유료금액'),
        '무료좌석': _i('무료좌석'),
        '합계좌석': _i('합계좌석'),
        '합계금액': _i('합계금액'),
        '기준일자': prev_row['기준일자'],
    }


prev_data, prev_date = _load_prev_day_data(trend_df, today)
today_data = _load_today_data(trend_df, today)


# ── 헬퍼 ──
def _fmt_date_wd(dt):
    if pd.isna(dt):
        return ""
    dt = pd.Timestamp(dt)
    return f"{dt.month}.{dt.day}({WEEKDAYS_KR[dt.weekday()]})"


def _fmt_perf_date_str(dt):
    """공연일 문자열: '2026. 5. 7(목)' 형식 (엑셀 저장용)"""
    if pd.isna(dt):
        return ""
    dt = pd.Timestamp(dt)
    return f"{dt.year}. {dt.month}. {dt.day}({WEEKDAYS_KR[dt.weekday()]})"


def _dday_text_color(start_dt, today_ts):
    if pd.isna(start_dt):
        return "", "#FFFFFF"
    days = (pd.Timestamp(start_dt) - today_ts).days
    if days == 0:
        return "D-Day", "#FF4B4B"
    elif days > 0:
        text = f"D-{days}"
        color = "#FF4B4B" if days <= 7 else ("#FF8C00" if days <= 14 else "#FFFFFF")
        return text, color
    else:
        return f"D+{-days}", "#888888"


def _badge_html(category):
    if category == '상업성':
        bg, fg = "#FF8C00", "#000000"
    else:
        bg, fg = "#00B2FF", "#000000"
    return (f'<span style="background:{bg};color:{fg};padding:2px 10px;'
            f'border-radius:10px;font-size:12px;font-weight:600;">{category}</span>')


def _dday_badge(start_dt, today_ts):
    """D-day 배지 HTML 반환 (모서리 둥근 네모)"""
    if pd.isna(start_dt):
        return ''
    days = (pd.Timestamp(start_dt) - today_ts).days
    if days < 0:
        text, bg = f"D+{-days}", "#888888"
    elif days == 0:
        text, bg = "D-Day", "#FF8C00"
    elif days <= 7:
        text, bg = f"D-{days}", "#FF8C00"
    elif days <= 28:
        text, bg = f"D-{days}", "#FFD700"
    else:
        text, bg = f"D-{days}", "#FFFFFF"
    return (f'<span style="background:{bg};color:#000000;padding:2px 10px;'
            f'border-radius:10px;font-size:12px;font-weight:600;">{text}</span>')


def _match_prev(perf_name, prev_data):
    perf_s = str(perf_name).strip()
    for key, val in prev_data.items():
        if perf_s == key:
            return val
    return None


def _match_today(perf_name, today_data):
    perf_s = str(perf_name).strip()
    for key, val in today_data.items():
        if perf_s == key:
            return val
    return None


def _sess_key(perf_id, round_no):
    return f"input_{perf_id}_{round_no}"


# ── 입력 필드 렌더링 (예약 필드 제거: 유료/무료만) ──
def _render_input_row(perf_id, round_no, seat_capacity, cols_spec, prefill=None):
    sk = _sess_key(perf_id, round_no)
    pf = prefill or {}
    def_paid_s = pf.get('유료좌석', 0)
    def_paid_a = pf.get('유료금액', 0)
    def_free = pf.get('무료좌석', 0)

    # widget key counter (저장 성공 시 증가 → 위젯 재생성으로 초기화)
    _ckey = f"counter_{perf_id}_{round_no}"
    if _ckey not in st.session_state:
        st.session_state[_ckey] = 0
    _v = st.session_state[_ckey]

    c1, c2, c3 = cols_spec
    with c1:
        paid_s = st.number_input("유료좌석", value=def_paid_s,
                                  step=1, key=f"{sk}_ps_v{_v}", label_visibility="collapsed")
    with c2:
        paid_a = st.number_input("유료금액", value=def_paid_a,
                                  step=1000, key=f"{sk}_pa_v{_v}", label_visibility="collapsed")
    with c3:
        free_s = st.number_input("무료좌석", value=def_free,
                                  step=1, key=f"{sk}_fr_v{_v}", label_visibility="collapsed")

    total_seats = paid_s + free_s
    total_amount = paid_a
    occ = min(total_seats / seat_capacity * 100, 100.0) if seat_capacity > 0 else 0.0
    has_input = any(v != 0 for v in (paid_s, paid_a, free_s))

    return {
        '유료좌석': paid_s, '유료금액': paid_a,
        '무료좌석': free_s,
        '합계좌석': total_seats, '합계금액': total_amount,
        '점유율': occ, 'has_input': has_input,
    }


# ── 저장 실행 함수 ──
def _do_save_perf(perf, perf_rounds_info, round_results, prev, current=None):
    """한 공연의 모든 회차를 저장 (current + input 누적). 반환: list of result dicts"""
    perf_name = str(perf['사업명']).strip()
    base_seat = int(perf['기준석']) if pd.notna(perf['기준석']) else 926
    total_rounds = int(perf['총회차']) if pd.notna(perf['총회차']) else 1
    total_open = int(perf['총오픈석']) if pd.notna(perf['총오픈석']) and perf['총오픈석'] > 0 else base_seat * total_rounds

    prev_seats = prev['합계좌석'] if prev else 0
    prev_amount = prev['합계금액'] if prev else 0

    # 현재 저장된 값 (누적 시작점)
    cur = current or {}
    cur_paid_s = int(cur.get('유료좌석', 0) or 0)
    cur_paid_a = int(cur.get('유료금액', 0) or 0)
    cur_free = int(cur.get('무료좌석', 0) or 0)

    results = []

    if total_rounds > 1 and perf_rounds_info:
        # 다회차: 전체 합산 1행으로 저장 (current + input)
        agg_paid_s = cur_paid_s + sum(r['유료좌석'] for r in round_results)
        agg_paid_a = cur_paid_a + sum(r['유료금액'] for r in round_results)
        agg_free = cur_free + sum(r['무료좌석'] for r in round_results)

        # 공연일/시각: 첫 회차 정보
        first_rd = perf_rounds_info[0]
        perf_date_str = first_rd.get('date_str', '')
        round_time = first_rd.get('time', '')

        res = save_daily_entry(
            date_int=date_int,
            perf_name=perf_name,
            perf_date_str=perf_date_str,
            round_time=round_time,
            open_seats=total_open,
            paid_seats=agg_paid_s,
            paid_amount=agg_paid_a,
            free_seats=agg_free,
            prev_seats=prev_seats,
            prev_amount=prev_amount,
        )
        res['perf'] = perf_name
        res['ts'] = time.time()
        results.append(res)
    else:
        # 단일회차 (current + input)
        r = round_results[0]
        ri = perf_rounds_info[0] if perf_rounds_info else {}
        perf_date_str = ri.get('date_str', '')
        round_time = ri.get('time', '')

        res = save_daily_entry(
            date_int=date_int,
            perf_name=perf_name,
            perf_date_str=perf_date_str,
            round_time=round_time,
            open_seats=base_seat,
            paid_seats=cur_paid_s + r['유료좌석'],
            paid_amount=cur_paid_a + r['유료금액'],
            free_seats=cur_free + r['무료좌석'],
            prev_seats=prev_seats,
            prev_amount=prev_amount,
        )
        res['perf'] = perf_name
        res['ts'] = time.time()
        results.append(res)

    return results


# ══════════════════════════════════════════════════
# 카드 렌더링 + 저장 (모든 카드 데이터 수집)
# ══════════════════════════════════════════════════
all_cards = []  # 각 카드 정보 수집 (전체 저장용)

for card_idx, (_, perf) in enumerate(active_df.iterrows()):
    perf_id = perf['ID']
    perf_name = str(perf['사업명']).strip()
    category = match_performance_category(perf_name, master_df) or '공공성'
    target_occ = get_target_occupancy(perf_name, master_df)
    if not target_occ or target_occ <= 0:
        target_occ = 50
    total_rounds = int(perf['총회차']) if pd.notna(perf['총회차']) else 1
    base_seat = int(perf['기준석']) if pd.notna(perf['기준석']) else 926
    total_open = int(perf['총오픈석']) if pd.notna(perf['총오픈석']) and perf['총오픈석'] > 0 else base_seat * total_rounds
    start_dt = pd.to_datetime(perf.get('시작일'), errors='coerce')
    end_dt = pd.to_datetime(perf.get('종료일'), errors='coerce')
    dday_text, dday_color = _dday_text_color(start_dt, today)

    s_str = _fmt_date_wd(start_dt)
    e_str = _fmt_date_wd(end_dt)
    date_range = f"{s_str} ~ {e_str}" if s_str and e_str and s_str != e_str else (s_str or "-")

    # 회차상세
    perf_rounds_info = []
    if rounds_df is not None and not rounds_df.empty:
        rd = rounds_df[rounds_df['ID'] == perf_id].sort_values(['공연일', '회차'])
        for _, rr in rd.iterrows():
            perf_rounds_info.append({
                'round_no': int(rr['회차']),
                'date': _fmt_date_wd(rr['공연일']),
                'date_str': _fmt_perf_date_str(rr['공연일']),
                'time': str(rr['시작시간']).strip() if pd.notna(rr['시작시간']) else "",
                'seat': int(rr['가용석']) if pd.notna(rr['가용석']) else base_seat,
            })

    prev = _match_prev(perf_name, prev_data)
    today_pf = _match_today(perf_name, today_data)
    # 해당 공연의 최근 저장값 (오늘 포함, 없으면 None)
    latest_saved = _load_latest_for_perf(trend_df, perf_name, today)
    # 직전 저장값 (현재 바로 이전)
    prev_entry = _load_prev_for_perf(trend_df, perf_name, today)

    # ── 카드 ──
    with st.container(border=True):
        st.markdown(
            f'{_dday_badge(start_dt, today)} &nbsp; '
            f'<span style="font-size:20px;font-weight:700;color:{ACCENT};">{perf_name}</span>'
            f'<div style="margin-bottom:16px;"></div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div style="margin-top:20px;"></div>', unsafe_allow_html=True)

        # ── 헤더 메타정보 (1번 구분선 위) ──
        _hdr_cur = latest_saved or {}
        _hdr_seats = int(_hdr_cur.get('합계좌석', 0) or 0)
        _hdr_occ_pct = (_hdr_seats / total_open * 100) if total_open > 0 else 0.0
        _hdr_occ_i = round(_hdr_occ_pct)
        _hdr_tgt_i = round(target_occ)
        _hdr_tgt_seats = round(total_open * target_occ / 100)
        _hdr_diff_seats = _hdr_seats - _hdr_tgt_seats
        _hdr_diff_pct = _hdr_occ_i - _hdr_tgt_i
        _hdr_avail = sum(r['seat'] for r in perf_rounds_info) if perf_rounds_info else base_seat
        _hdr_avail_pct = round(_hdr_avail / total_open * 100) if total_open > 0 else 0
        def _fs(n):
            return f"{n:,}" if n >= 1000 else str(n)
        _G = "#0FFD02"
        _Y = "#FFD700"

        if total_rounds <= 1 and perf_rounds_info:
            _ri0 = perf_rounds_info[0]
            _hdr_date = f'{_ri0["date"]} {_ri0["time"]}'
        else:
            _hdr_date = date_range

        ic = st.columns([1.5, 2.5], gap="small")

        # 좌측: 공연 일시 + 회차
        ic[0].markdown(
            f'<div style="font-size:21px;">공연 일시 : <span style="color:{_G};font-weight:700;">{_hdr_date}</span></div>'
            f'<div style="font-size:17px;color:#AAA;margin-top:4px;">(총 <span style="color:{_G};font-weight:700;">{total_rounds}</span>회차)</div>',
            unsafe_allow_html=True,
        )

        # 우측: 미니 표 (전치: 2행×5열)
        _TD = 'padding:3px 12px;text-align:center;'
        _TDR = 'padding:3px 12px;text-align:right;'
        _TDH = f'padding:3px 12px;text-align:center;color:{LBL_BLUE};font-weight:700;font-size:15px;'
        _DIM = '#999999'
        def _sign(n):
            return f"+{n:,}" if n > 0 else (f"{n:,}" if n < 0 else "0")
        _diff_s_color = '#FFFFFF' if _hdr_diff_seats >= 0 else _DIM
        _diff_p_color = '#FFFFFF' if _hdr_diff_pct >= 0 else _DIM
        _tbl = (
            f'<table style="font-size:17px;border-collapse:collapse;width:100%;">'
            f'<tr style="border-bottom:1px solid #333;background:rgba(255,255,255,0.05);">'
            f'<td style="{_TD}"></td>'
            f'<td style="{_TDH}">현재</td>'
            f'<td style="{_TDH}">목표</td>'
            f'<td style="{_TDH}">가용</td>'
            f'<td style="{_TDH}">목표대비</td>'
            f'</tr>'
            f'<tr>'
            f'<td style="{_TD}color:{LBL_BLUE};font-weight:700;">객석 (수)</td>'
            f'<td style="{_TDR}"><span style="color:{_G};font-weight:700;">{_fs(_hdr_seats)}</span></td>'
            f'<td style="{_TDR}"><span style="color:{_Y};font-weight:700;">{_fs(_hdr_tgt_seats)}</span></td>'
            f'<td style="{_TDR}">{_fs(_hdr_avail)}</td>'
            f'<td style="{_TDR}"><span style="color:{_diff_s_color};font-weight:700;">{_sign(_hdr_diff_seats)}</span></td>'
            f'</tr>'
            f'<tr>'
            f'<td style="{_TD}color:{LBL_BLUE};font-weight:700;">점유율 (%)</td>'
            f'<td style="{_TDR}"><span style="color:{_G};font-weight:700;">{_hdr_occ_i}</span></td>'
            f'<td style="{_TDR}"><span style="color:{_Y};font-weight:700;">{_hdr_tgt_i}</span></td>'
            f'<td style="{_TDR}">{_hdr_avail_pct}</td>'
            f'<td style="{_TDR}"><span style="color:{_diff_p_color};font-weight:700;">{_sign(_hdr_diff_pct)}</span></td>'
            f'</tr>'
            f'</table>'
        )
        ic[1].markdown(_tbl, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown('<div style="margin-bottom:8px;"></div>', unsafe_allow_html=True)

        # ── 입력 영역 ──
        round_results = []

        if total_rounds > 1 and perf_rounds_info:
            st.markdown('<div class="round-table-wrap">', unsafe_allow_html=True)
            st.markdown('<div class="header-row-bg"></div>', unsafe_allow_html=True)
            _h = st.columns([0.4, 0.9, 0.6, 0.8, 0.8, 0.8])
            _h[0].markdown(f'<div style="font-size:21px;font-weight:700;text-align:center;color:{LBL_BLUE};">#</div>', unsafe_allow_html=True)
            _h[1].markdown(f'<div style="font-size:21px;font-weight:700;text-align:center;color:{LBL_BLUE};">공연일/시각</div>', unsafe_allow_html=True)
            _h[2].markdown(f'<div style="font-size:21px;font-weight:700;text-align:center;color:{LBL_BLUE};">판매석</div>', unsafe_allow_html=True)
            _h[3].markdown(f'<div style="font-size:14px;font-weight:700;text-align:center;color:{LBL_BLUE};margin-bottom:8px;">유료좌석</div>', unsafe_allow_html=True)
            _h[4].markdown(f'<div style="font-size:14px;font-weight:700;text-align:center;color:{LBL_BLUE};margin-bottom:8px;">유료금액</div>', unsafe_allow_html=True)
            _h[5].markdown(f'<div style="font-size:14px;font-weight:700;text-align:center;color:{LBL_BLUE};margin-bottom:8px;">무료좌석</div>', unsafe_allow_html=True)

            for rd_info in perf_rounds_info:
                rn = rd_info['round_no']
                cols = st.columns([0.4, 0.9, 0.6, 0.8, 0.8, 0.8])
                with cols[0]:
                    st.markdown(f'<div class="round-text" style="font-size:21px;text-align:center;">{rn}</div>', unsafe_allow_html=True)
                with cols[1]:
                    st.markdown(f'<div class="round-text" style="font-size:21px;text-align:center;">{rd_info["date"]} {rd_info["time"]}</div>', unsafe_allow_html=True)
                with cols[2]:
                    _rd_sold = round(_hdr_seats / total_rounds) if total_rounds > 0 else 0
                    st.markdown(f'<div class="round-text" style="font-size:21px;text-align:center;color:{ACCENT};font-weight:700;">{_rd_sold:,}</div>', unsafe_allow_html=True)

                result = _render_input_row(
                    perf_id, rn, rd_info['seat'],
                    (cols[3], cols[4], cols[5]),
                )
                round_results.append(result)

            st.markdown('</div>', unsafe_allow_html=True)  # close .round-table-wrap

            missing = [perf_rounds_info[i]['round_no']
                       for i, r in enumerate(round_results) if not r['has_input']]
            if missing and any(r['has_input'] for r in round_results):
                miss_str = ", ".join(str(m) for m in missing)
                st.markdown(
                    f'<div style="color:#FF4B4B;font-size:13px;font-weight:600;">'
                    f'🔴 {miss_str}회차 미입력</div>',
                    unsafe_allow_html=True,
                )
        else:
            _h = st.columns(3)
            _h[0].markdown(f'<div style="font-size:14px;font-weight:700;text-align:center;color:{LBL_BLUE};margin-bottom:8px;">유료좌석</div>', unsafe_allow_html=True)
            _h[1].markdown(f'<div style="font-size:14px;font-weight:700;text-align:center;color:{LBL_BLUE};margin-bottom:8px;">유료금액</div>', unsafe_allow_html=True)
            _h[2].markdown(f'<div style="font-size:14px;font-weight:700;text-align:center;color:{LBL_BLUE};margin-bottom:8px;">무료좌석</div>', unsafe_allow_html=True)

            input_cols = st.columns(3)
            result = _render_input_row(
                perf_id, 1, base_seat,
                (input_cols[0], input_cols[1], input_cols[2]),
            )
            round_results.append(result)

        # ── 지표 4개 (현재 누적값 + 입력 시 누적 시뮬레이션) ──
        # 현재 저장된 값 = 해당 공연의 가장 최근 저장값 (오늘 포함)
        current = latest_saved or {}
        cur_paid = int(current.get('유료좌석', 0) or 0)
        cur_free = int(current.get('무료좌석', 0) or 0)
        cur_seats = int(current.get('합계좌석', 0) or 0)
        cur_amount = int(current.get('합계금액', 0) or 0)
        cur_occ = (cur_seats / total_open * 100) if total_open > 0 else 0.0
        cur_vs_tgt = cur_occ - target_occ

        # 입력 값 (추가분)
        has_input_data = any(r['has_input'] for r in round_results)
        in_paid = sum(r['유료좌석'] for r in round_results)
        in_free = sum(r['무료좌석'] for r in round_results)
        in_seats = sum(r['합계좌석'] for r in round_results)
        in_amount = sum(r['합계금액'] for r in round_results)

        # ── 비교 표 (최신 저장 1건 / 저장 후 과거+현재) ──
        _last_cur_key = f"last_cur_{perf_id}"
        _has_prev_save = _last_cur_key in st.session_state

        _CELL = 'padding:7px 0;text-align:right;'
        _HDR = f'{_CELL}font-size:21px;font-weight:700;color:{LBL_BLUE};'
        _LBL = 'padding:7px 0;font-size:21px;font-weight:600;'

        def _row_style(color):
            return f'{_CELL}font-size:21px;font-weight:700;color:{color};'

        st.markdown('<div style="margin-top:20px;"></div>', unsafe_allow_html=True)
        st.markdown("---")
        _COL_RATIO = [0.4, 1, 1.2, 1.2, 0.8, 1, 0.4]

        # 헤더
        st.markdown('<div class="header-row-bg"></div>', unsafe_allow_html=True)
        _hc = st.columns(_COL_RATIO)
        _hc[1].markdown("")
        _hc[2].markdown(f'<div style="{_HDR}">누적</div>', unsafe_allow_html=True)
        _hc[3].markdown(f'<div style="{_HDR}">판매금액</div>', unsafe_allow_html=True)
        _hc[4].markdown(f'<div style="{_HDR}">점유율</div>', unsafe_allow_html=True)
        _hc[5].markdown(f'<div style="{_HDR}">목표대비</div>', unsafe_allow_html=True)

        def _render_data_row(cols, color, seats, amount, occ, vs_tgt):
            _s = _row_style(color)
            _sign = "+" if vs_tgt >= 0 else ""
            cols[2].markdown(f'<div style="{_s}">{seats:,}석</div>', unsafe_allow_html=True)
            cols[3].markdown(f'<div style="{_s}">{amount/10000:,.1f}만원</div>', unsafe_allow_html=True)
            cols[4].markdown(f'<div style="{_s}">{occ:.1f}%</div>', unsafe_allow_html=True)
            cols[5].markdown(f'<div style="{_s}">{_sign}{vs_tgt:.1f}%p</div>', unsafe_allow_html=True)

        if _has_prev_save:
            # 상태 B: 이번 세션에서 저장 후 → 과거 행 + 현재 행
            _p = st.session_state[_last_cur_key]
            _p_label = st.session_state.get(_last_cur_key + "_label", "직전")
            _p_seats = int(_p.get('합계좌석', 0))
            _p_amount = int(_p.get('합계금액', 0))
            _p_occ = (_p_seats / total_open * 100) if total_open > 0 else 0.0
            _p_vs_tgt = _p_occ - target_occ

            # 과거 행 (항상 #999)
            _r1 = st.columns(_COL_RATIO)
            _r1[1].markdown(f'<div style="{_LBL}color:#999;">{_p_label}</div>', unsafe_allow_html=True)
            _render_data_row(_r1, '#999', _p_seats, _p_amount, _p_occ, _p_vs_tgt)

            # 현재 행: 변경 후 행 뜨면 #999, 아니면 ACCENT
            _save_hhmm = st.session_state.get(_last_cur_key + "_save_hhmm", "")
            _cur_label = f"현재 {_save_hhmm}" if _save_hhmm else "현재"
            _base_color = '#999' if has_input_data else ACCENT
            _r2 = st.columns(_COL_RATIO)
            _r2[1].markdown(f'<div style="{_LBL}color:{_base_color};">{_cur_label}</div>', unsafe_allow_html=True)
            _render_data_row(_r2, _base_color, cur_seats, cur_amount, cur_occ, cur_vs_tgt)
        else:
            # 상태 A: 저장 전 → 최신 저장 1건만 표시
            _cur_date_label = _fmt_date_wd(current.get('기준일자')) if current.get('기준일자') else "현재"
            _base_color = '#999' if has_input_data else '#FFFFFF'
            _r1 = st.columns(_COL_RATIO)
            _r1[1].markdown(f'<div style="{_LBL}color:{_base_color};">{_cur_date_label}</div>', unsafe_allow_html=True)
            if cur_seats > 0 or cur_amount > 0:
                _render_data_row(_r1, _base_color, cur_seats, cur_amount, cur_occ, cur_vs_tgt)
            else:
                _dim = _row_style('#999')
                for _cc in _r1[2:6]:
                    _cc.markdown(f'<div style="{_dim}">—</div>', unsafe_allow_html=True)

        # 변경 미리보기 행 (입력값이 있을 때만)
        if has_input_data:
            _new_seats = cur_seats + in_seats
            _new_amount = cur_amount + in_amount
            _new_occ = (_new_seats / total_open * 100) if total_open > 0 else 0.0
            _new_vs_tgt = _new_occ - target_occ
            _rp = st.columns(_COL_RATIO)
            _rp[1].markdown(f'<div style="{_LBL}color:{ACCENT};">변경 후</div>', unsafe_allow_html=True)
            _render_data_row(_rp, ACCENT, _new_seats, _new_amount, _new_occ, _new_vs_tgt)

        st.markdown('<div style="margin-bottom:20px;"></div>', unsafe_allow_html=True)

        # ── 카드별 저장 버튼 ──
        # 호환성 alias (혹시 다른 코드에서 쓸 경우)
        total_seats = in_seats
        total_amount = in_amount
        any_input = any(r['has_input'] for r in round_results)
        btn_label = f"💾 이 공연 저장"

        if any_input:
            if st.button(btn_label, key=f"save_{perf_id}", type="primary", use_container_width=True):
                # 다회차 미입력 검증
                if total_rounds > 1 and perf_rounds_info:
                    missing_rn = [perf_rounds_info[i]['round_no']
                                  for i, r in enumerate(round_results) if not r['has_input']]
                    if missing_rn:
                        miss_str = ", ".join(str(m) for m in missing_rn)
                        st.error(f"❌ {miss_str}회차 미입력. 모든 회차를 입력해주세요.")
                        st.stop()

                with st.spinner(f"📤 {perf_name} 저장 중..."):
                    save_res = _do_save_perf(perf, perf_rounds_info, round_results, prev, current)

                for sr in save_res:
                    sr['perf'] = perf_name
                    st.session_state.save_results.append(sr)

                if all(sr['status'] != 'error' for sr in save_res):
                    # 직전 값 session_state에 저장 (현재 cur → 직전으로)
                    _last_cur_key = f"last_cur_{perf_id}"
                    st.session_state[_last_cur_key] = {
                        '합계좌석': cur_seats,
                        '합계금액': cur_amount,
                        '기준일자': current.get('기준일자'),
                    }
                    _save_time = datetime.now(KST).strftime('%H:%M')
                    st.session_state[_last_cur_key + "_label"] = f"{_fmt_date_wd(today)} {_save_time}"
                    st.session_state[_last_cur_key + "_save_hhmm"] = _save_time
                    # 이 카드의 입력 필드 초기화 (counter 증가 → 위젯 재생성)
                    for _rn in range(1, total_rounds + 1):
                        _ckey = f"counter_{perf_id}_{_rn}"
                        if _ckey in st.session_state:
                            st.session_state[_ckey] += 1
                    st.session_state.has_unsaved_changes = False
                    st.cache_data.clear()
                    st.rerun()
                else:
                    for sr in save_res:
                        if sr.get('is_conflict'):
                            st.error("문서가 현재 사용 중에 있습니다. 잠시 후에 시도해주세요.")
                            break
                    st.rerun()

        # ── 카드 저장 결과 표시 (자기 카드만, 5초 이내) ──
        _now = time.time()
        for sr in st.session_state.save_results:
            if sr.get('perf') == perf_name and (_now - sr.get('ts', 0)) < 5:
                if sr['status'] == 'error':
                    st.error(f"❌ {sr['message']}")
                else:
                    _m = re.search(r'\((\d{2}:\d{2}:\d{2})\)', sr.get('message', ''))
                    _ts = _m.group(1) if _m else ''
                    st.success(f"✅ {perf_name} 공연 실시간 정보 갱신 완료 ({_ts})")

        # 카드 데이터 수집 (전체 저장용)
        all_cards.append({
            'perf': perf,
            'perf_rounds_info': perf_rounds_info,
            'round_results': round_results,
            'prev': prev,
            'current': current,
            'any_input': any_input,
        })

    st.markdown("")


# ══════════════════════════════════════════════════
# 하단: 전체 저장 버튼
# ══════════════════════════════════════════════════
st.markdown("---")

has_any = any(c['any_input'] for c in all_cards)
input_cards = [c for c in all_cards if c['any_input']]
if has_any:
    if st.button("📤 모두 저장", type="primary", use_container_width=True, key="save_all"):
        # 다회차 미입력 검증
        errors = []
        for c in input_cards:
            pname = str(c['perf']['사업명']).strip()
            tr = int(c['perf']['총회차']) if pd.notna(c['perf']['총회차']) else 1
            if tr > 1 and c['perf_rounds_info']:
                miss = [c['perf_rounds_info'][i]['round_no']
                        for i, r in enumerate(c['round_results']) if not r['has_input']]
                if miss:
                    errors.append(f"{pname}: {', '.join(str(m) for m in miss)}회차 미입력")

        if errors:
            for e in errors:
                st.error(f"❌ {e}")
        else:
            all_results = []
            with st.spinner(f"📤 {len(input_cards)}개 공연 저장 중..."):
                for c in input_cards:
                    res = _do_save_perf(c['perf'], c['perf_rounds_info'],
                                        c['round_results'], c['prev'], c.get('current'))
                    pname = str(c['perf']['사업명']).strip()
                    for r in res:
                        r['perf'] = pname
                    all_results.extend(res)

            st.session_state.save_results = all_results
            if all(r['status'] != 'error' for r in all_results):
                # 직전 값 session_state에 저장 + 입력 필드 초기화
                _save_time = datetime.now(KST).strftime('%H:%M')
                for _c in input_cards:
                    _pid = _c['perf']['ID']
                    _cur = _c.get('current') or {}
                    _last_cur_key = f"last_cur_{_pid}"
                    st.session_state[_last_cur_key] = {
                        '합계좌석': int(_cur.get('합계좌석', 0) or 0),
                        '합계금액': int(_cur.get('합계금액', 0) or 0),
                        '기준일자': _cur.get('기준일자'),
                    }
                    st.session_state[_last_cur_key + "_label"] = f"{_fmt_date_wd(today)} {_save_time}"
                    st.session_state[_last_cur_key + "_save_hhmm"] = _save_time
                    _tr = int(_c['perf']['총회차']) if pd.notna(_c['perf']['총회차']) else 1
                    for _rn in range(1, _tr + 1):
                        _ckey = f"counter_{_pid}_{_rn}"
                        if _ckey in st.session_state:
                            st.session_state[_ckey] += 1
                st.session_state.has_unsaved_changes = False
                st.cache_data.clear()
            else:
                for r in all_results:
                    if r.get('is_conflict'):
                        st.error("문서가 현재 사용 중에 있습니다. 잠시 후에 시도해주세요.")
                        break
            st.rerun()
# 5초 이상 지난 저장 결과는 제거 (메모리 정리)
_now = time.time()
st.session_state.save_results = [
    sr for sr in st.session_state.save_results
    if (_now - sr.get('ts', 0)) < 5
]
