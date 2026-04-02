import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

from utils.data_loader import load_daily_input, load_sales_trend, get_base_date, load_performance_master, load_round_details, get_data_source
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
    st.write("**daily_df 처음 5행:**")
    st.dataframe(daily_df.head(5), use_container_width=True, hide_index=True)
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
    occ_label = '점유율(%)' if is_active else '최종 점유율(%)'
    headers = ['공연일', '공연명', 'D-day', '판매좌석(석)', '전일대비(석)', '오픈석(석)', occ_label, '판매금액(만원)']
    right_align_cols = {3, 4, 5, 6, 7}

    html = '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
    html += '<tr>'
    for i, h in enumerate(headers):
        align = 'right' if i in right_align_cols else 'left'
        html += f'<th style="text-align:{align};padding:8px 12px;border-bottom:2px solid #444;color:#AAA;font-weight:600;">{h}</th>'
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
        html += f'<td style="padding:8px 12px;color:#AAA;">{date_str}</td>'
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
        # 판매좌석 (흰색)
        html += f'<td style="padding:8px 12px;text-align:right;color:#FFFFFF;font-weight:600;">{seats:,}</td>'
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

    # D-day 임박순: 작은 D-day가 위 → Plotly는 아래부터 그리므로 ascending=False
    chart_df = active_df.sort_values('_days', ascending=False).copy()

    # 목표점유율 매칭 (SharePoint 파일에 컬럼이 없을 수 있으므로 코드 레벨 fallback)
    _TARGET_FALLBACK = {
        '브런치콘서트': 60, '실내악 페스티벌': 20, '김영욱': 20,
        '100층짜리': 50, '한국페스티발앙상블': 20, '국립심포니': 20,
    }
    chart_df['목표점유율'] = 80.0
    for idx, row in chart_df.iterrows():
        name = row['공연명']
        matched = _match_master(name, master_df)
        target = None
        # 1차: 공연마스터에서 읽기
        if matched is not None and pd.notna(matched.get('목표점유율')):
            val = float(matched['목표점유율'])
            if val != 80.0:  # 기본값이 아닌 실제 값
                target = val
        # 2차: 기본값(80)이면 코드 레벨 매핑으로 override
        if target is None:
            for key, fallback in _TARGET_FALLBACK.items():
                if key in str(name):
                    target = float(fallback)
                    break
        if target is not None:
            chart_df.at[idx, '목표점유율'] = target

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

    # Y축 라벨: 공연명 + 공연일 (D-day는 별도 annotation)
    y_tick_texts = []
    for name, date_str, color in zip(y_labels, y_dates, label_colors):
        if date_str:
            y_tick_texts.append(
                f'<span style="color:{color}">{name}</span><br>'
                f'<span style="color:#999;font-size:10px">{date_str}</span>'
            )
        else:
            y_tick_texts.append(f'<span style="color:{color}">{name}</span>')

    # D-day 별도 annotation 열 (Y축 왼쪽에 정렬)
    for i, days in enumerate(y_ddays):
        if pd.notna(days):
            dday_str = fmt_dday(days)
            dday_color = _label_color(days)
            fig.add_annotation(
                x=-0.01, y=y_labels[i], xref="paper", yref="y",
                xanchor="right",
                text=f'<b>{dday_str}</b>',
                showarrow=False,
                font=dict(size=12, color=dday_color),
            )

    # 범례 (차트 영역 밖 상단, 가로 배치)
    legend_text = (
        '<span style="color:#AAA">■ 달성률</span>  '
        '<span style="color:#FFFFFF">● 75%↑</span>  '
        '<span style="color:#FFD700">● 50~75%</span>  '
        '<span style="color:#FF8C00">● 25~50%</span>  '
        '<span style="color:#FF4B4B">● ~25%</span>    '
        '<span style="color:#FFD700">┆</span> <span style="color:#AAA">목표</span>  '
        '<span style="color:#FF4B4B">┆</span> <span style="color:#AAA">100%</span>  '
        '<span style="color:#555">─</span> <span style="color:#AAA">D-28</span>'
    )
    fig.add_annotation(
        x=0.5, y=1.15, xref="paper", yref="paper",
        xanchor="center", yanchor="bottom",
        text=legend_text, showarrow=False,
        font=dict(size=10, color="#AAA"),
        bgcolor="rgba(0,0,0,0.5)", bordercolor="#333", borderwidth=1, borderpad=5,
    )

    fig.update_layout(
        xaxis_title="", yaxis_title="",
        height=550,
        margin=dict(t=100, l=60),
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
