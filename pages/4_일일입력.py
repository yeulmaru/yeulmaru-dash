import streamlit as st
import pandas as pd
from datetime import date, datetime

from utils.data_loader import (
    load_performance_master,
    load_round_details,
    load_sales_trend,
    get_active_performances,
    match_performance_category,
    get_target_occupancy,
    match_performance,
)
from utils.local_excel_writer import save_daily_entry_local as save_daily_entry
from utils.charts import COLORS

st.set_page_config(page_title="일일입력", page_icon="📝", layout="wide")

from utils.auth import check_password
check_password()

# ── 상수 ──
WEEKDAYS_KR = ['월', '화', '수', '목', '금', '토', '일']
ACCENT = COLORS['primary']

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

# 저장 결과 표시 (이전 저장 결과가 있으면)
for sr in st.session_state.save_results:
    if sr['status'] == 'error':
        st.error(f"❌ {sr['perf']}: {sr['message']}")
    else:
        st.success(f"✅ {sr['perf']}: {sr['message']}")
st.session_state.save_results = []

# 미저장 경고 배너
if st.session_state.has_unsaved_changes:
    st.warning("⚠️ 저장되지 않은 변경사항이 있습니다.")

st.markdown("---")
base_date = st.date_input("📅 기준일자", value=date.today())
today = pd.Timestamp(base_date)
date_int = int(base_date.strftime('%Y%m%d'))

# ── 판매중 공연 목록 ──
active_df = get_active_performances(master_df, today=today)

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
        result[name] = {
            '합계좌석': int(r['합계좌석']) if pd.notna(r['합계좌석']) else 0,
            '합계금액': int(r['합계금액']) if pd.notna(r['합계금액']) else 0,
        }
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
        for col in ['유료좌석', '유료금액', '예약좌석', '예약금액', '무료좌석',
                     '합계좌석', '합계금액']:
            if col in r.index and pd.notna(r[col]):
                entry[col] = int(r[col])
        if name not in result:
            result[name] = entry
    return result


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


def _match_prev(perf_name, prev_data):
    perf_s = str(perf_name).strip()
    for key, val in prev_data.items():
        if perf_s == key or perf_s in key or key in perf_s:
            return val
    return None


def _match_today(perf_name, today_data):
    perf_s = str(perf_name).strip()
    for key, val in today_data.items():
        if perf_s == key or perf_s in key or key in perf_s:
            return val
    return None


def _sess_key(perf_id, round_no):
    return f"input_{perf_id}_{round_no}"


# ── 입력 필드 렌더링 ──
def _render_input_row(perf_id, round_no, seat_capacity, cols_spec, prefill=None):
    sk = _sess_key(perf_id, round_no)
    pf = prefill or {}
    def_paid_s = pf.get('유료좌석', 0)
    def_paid_a = pf.get('유료금액', 0)
    def_rsv_s = pf.get('예약좌석', 0)
    def_rsv_a = pf.get('예약금액', 0)
    def_free = pf.get('무료좌석', 0)

    c1, c2, c3, c4, c5 = cols_spec
    with c1:
        paid_s = st.number_input("유료좌석", min_value=0, value=def_paid_s,
                                  step=1, key=f"{sk}_ps", label_visibility="collapsed")
    with c2:
        paid_a = st.number_input("유료금액", min_value=0, value=def_paid_a,
                                  step=1000, key=f"{sk}_pa", label_visibility="collapsed")
    with c3:
        rsv_s = st.number_input("예약좌석", min_value=0, value=def_rsv_s,
                                 step=1, key=f"{sk}_rs", label_visibility="collapsed")
    with c4:
        rsv_a = st.number_input("예약금액", min_value=0, value=def_rsv_a,
                                 step=1000, key=f"{sk}_ra", label_visibility="collapsed")
    with c5:
        free_s = st.number_input("무료좌석", min_value=0, value=def_free,
                                  step=1, key=f"{sk}_fr", label_visibility="collapsed")

    total_seats = paid_s + rsv_s + free_s
    total_amount = paid_a + rsv_a
    occ = min(total_seats / seat_capacity * 100, 100.0) if seat_capacity > 0 else 0.0
    has_input = (paid_s + paid_a + rsv_s + rsv_a + free_s) > 0

    if has_input:
        st.session_state.has_unsaved_changes = True

    return {
        '유료좌석': paid_s, '유료금액': paid_a,
        '예약좌석': rsv_s, '예약금액': rsv_a,
        '무료좌석': free_s,
        '합계좌석': total_seats, '합계금액': total_amount,
        '점유율': occ, 'has_input': has_input,
    }


# ── 저장 실행 함수 ──
def _do_save_perf(perf, perf_rounds_info, round_results, prev):
    """한 공연의 모든 회차를 저장. 반환: list of result dicts"""
    perf_name = str(perf['사업명']).strip()
    base_seat = int(perf['기준석']) if pd.notna(perf['기준석']) else 926
    total_rounds = int(perf['총회차']) if pd.notna(perf['총회차']) else 1
    total_open = int(perf['총오픈석']) if pd.notna(perf['총오픈석']) and perf['총오픈석'] > 0 else base_seat * total_rounds

    prev_seats = prev['합계좌석'] if prev else 0
    prev_amount = prev['합계금액'] if prev else 0

    results = []

    if total_rounds > 1 and perf_rounds_info:
        # 다회차: 전체 합산 1행으로 저장
        agg_paid_s = sum(r['유료좌석'] for r in round_results)
        agg_paid_a = sum(r['유료금액'] for r in round_results)
        agg_rsv_s = sum(r['예약좌석'] for r in round_results)
        agg_rsv_a = sum(r['예약금액'] for r in round_results)
        agg_free = sum(r['무료좌석'] for r in round_results)

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
            rsv_seats=agg_rsv_s,
            rsv_amount=agg_rsv_a,
            free_seats=agg_free,
            prev_seats=prev_seats,
            prev_amount=prev_amount,
        )
        res['perf'] = perf_name
        results.append(res)
    else:
        # 단일회차
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
            paid_seats=r['유료좌석'],
            paid_amount=r['유료금액'],
            rsv_seats=r['예약좌석'],
            rsv_amount=r['예약금액'],
            free_seats=r['무료좌석'],
            prev_seats=prev_seats,
            prev_amount=prev_amount,
        )
        res['perf'] = perf_name
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

    # ── 카드 ──
    with st.container(border=True):
        hdr_l, hdr_r = st.columns([6, 1])
        with hdr_l:
            st.markdown(
                f'{_badge_html(category)} &nbsp; '
                f'<span style="font-size:20px;font-weight:700;">{perf_name}</span>',
                unsafe_allow_html=True,
            )
        with hdr_r:
            st.markdown(
                f'<div style="text-align:right;font-size:20px;font-weight:700;'
                f'color:{dday_color};">{dday_text}</div>',
                unsafe_allow_html=True,
            )

        ic = st.columns(4)
        ic[0].markdown(f"**공연일** &nbsp; {date_range}")
        ic[1].markdown(f"**회차** &nbsp; {total_rounds}회")
        ic[2].markdown(f"**오픈석** &nbsp; {total_open:,}석")
        ic[3].markdown(f"**목표** &nbsp; {target_occ}%")

        if prev:
            st.markdown(
                f'<div style="font-size:12px;color:#888;margin:4px 0;">'
                f'전일 참고: 좌석 {prev["합계좌석"]:,}석 / 금액 {prev["합계금액"]:,}원</div>',
                unsafe_allow_html=True,
            )

        st.markdown("")

        # ── 입력 영역 ──
        round_results = []

        if total_rounds > 1 and perf_rounds_info:
            _h = st.columns([0.4, 0.9, 0.6, 0.8, 0.8, 0.8, 0.8, 0.8])
            _h[0].markdown("**#**")
            _h[1].markdown("**공연일/시각**")
            _h[2].markdown("**가용석**")
            _h[3].markdown("**유료좌석**")
            _h[4].markdown("**유료금액**")
            _h[5].markdown("**예약좌석**")
            _h[6].markdown("**예약금액**")
            _h[7].markdown("**무료좌석**")

            for rd_info in perf_rounds_info:
                rn = rd_info['round_no']
                cols = st.columns([0.4, 0.9, 0.6, 0.8, 0.8, 0.8, 0.8, 0.8])
                with cols[0]:
                    st.markdown(f"`{rn}`")
                with cols[1]:
                    st.markdown(f"{rd_info['date']} {rd_info['time']}")
                with cols[2]:
                    st.markdown(f"{rd_info['seat']:,}")

                result = _render_input_row(
                    perf_id, rn, rd_info['seat'],
                    (cols[3], cols[4], cols[5], cols[6], cols[7]),
                )
                round_results.append(result)

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
            if perf_rounds_info:
                ri = perf_rounds_info[0]
                st.markdown(f"**시각** {ri['date']} {ri['time']} &nbsp;&nbsp; **가용석** {ri['seat']:,}석")
            st.markdown("")

            _h = st.columns(5)
            _h[0].markdown("**유료좌석**")
            _h[1].markdown("**유료금액**")
            _h[2].markdown("**예약좌석**")
            _h[3].markdown("**예약금액**")
            _h[4].markdown("**무료좌석**")

            input_cols = st.columns(5)
            result = _render_input_row(
                perf_id, 1, base_seat,
                (input_cols[0], input_cols[1], input_cols[2], input_cols[3], input_cols[4]),
                prefill=today_pf,
            )
            round_results.append(result)

        # ── 미리보기 ──
        total_seats = sum(r['합계좌석'] for r in round_results)
        total_amount = sum(r['합계금액'] for r in round_results)
        occ_pct = min(total_seats / total_open * 100, 100.0) if total_open > 0 else 0.0

        diff_seats_str, diff_amount_str = "", ""
        if prev:
            ds = total_seats - prev['합계좌석']
            da = total_amount - prev['합계금액']
            diff_seats_str = f"+{ds}" if ds > 0 else str(ds) if ds != 0 else "0"
            diff_amount_str = f"+{da:,}" if da > 0 else f"{da:,}" if da != 0 else "0"

        occ_diff = occ_pct - target_occ
        occ_diff_color = ACCENT if occ_diff >= 0 else "#FF4B4B"
        occ_diff_str = f"+{occ_diff:.1f}" if occ_diff >= 0 else f"{occ_diff:.1f}"

        st.markdown("---")
        mc = st.columns(5)
        mc[0].metric("합계좌석", f"{total_seats:,}석",
                     delta=diff_seats_str if diff_seats_str else None)
        mc[1].metric("합계금액", f"{total_amount:,}원",
                     delta=diff_amount_str if diff_amount_str else None)
        mc[2].markdown(
            f'<div style="font-size:14px;color:#AAA;">점유율</div>'
            f'<div style="font-size:28px;font-weight:700;color:{ACCENT};">{occ_pct:.1f}%</div>',
            unsafe_allow_html=True,
        )
        mc[3].markdown(
            f'<div style="font-size:14px;color:#AAA;">목표 대비</div>'
            f'<div style="font-size:24px;font-weight:700;color:{occ_diff_color};">'
            f'{occ_diff_str}%p</div>',
            unsafe_allow_html=True,
        )
        mc[4].markdown(
            f'<div style="font-size:14px;color:#AAA;">목표</div>'
            f'<div style="font-size:24px;font-weight:600;">{target_occ}%</div>',
            unsafe_allow_html=True,
        )

        # ── 카드별 저장 버튼 ──
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
                    save_res = _do_save_perf(perf, perf_rounds_info, round_results, prev)

                for sr in save_res:
                    sr['perf'] = perf_name
                    st.session_state.save_results.append(sr)

                if all(sr['status'] != 'error' for sr in save_res):
                    st.session_state.has_unsaved_changes = False
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.rerun()

        # 카드 데이터 수집 (전체 저장용)
        all_cards.append({
            'perf': perf,
            'perf_rounds_info': perf_rounds_info,
            'round_results': round_results,
            'prev': prev,
            'any_input': any_input,
        })

    st.markdown("")


# ══════════════════════════════════════════════════
# 하단: 전체 저장 버튼
# ══════════════════════════════════════════════════
st.markdown("---")

has_any = any(c['any_input'] for c in all_cards)
input_cards = [c for c in all_cards if c['any_input']]
no_input_cards = [c for c in all_cards if not c['any_input']]

if no_input_cards:
    names = ", ".join(str(c['perf']['사업명']).strip()[:15] for c in no_input_cards)
    st.caption(f"미입력 공연: {names}")

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
                                        c['round_results'], c['prev'])
                    pname = str(c['perf']['사업명']).strip()
                    for r in res:
                        r['perf'] = pname
                    all_results.extend(res)

            st.session_state.save_results = all_results
            if all(r['status'] != 'error' for r in all_results):
                st.session_state.has_unsaved_changes = False
                st.cache_data.clear()
            st.rerun()
else:
    st.markdown(
        '<div style="text-align:center;color:#555;padding:20px;">'
        '입력된 데이터가 없습니다. 위 카드에서 판매 데이터를 입력해주세요.</div>',
        unsafe_allow_html=True,
    )
