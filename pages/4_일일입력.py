import streamlit as st
import pandas as pd
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.data_loader import (
    load_25_performance, load_daily_input,
    check_duplicate_entries, write_daily_entries_to_sharepoint,
)
from utils.charts import COLORS

st.set_page_config(page_title="일일입력", page_icon="📝", layout="wide")

from utils.auth import check_password
check_password()

st.title("📝 일일 판매현황 입력")
st.markdown("---")

# ── 데이터 로드 ──
perf_df = load_25_performance()
daily_df = load_daily_input()

if perf_df is None or perf_df.empty:
    st.error("25공연 시트를 불러올 수 없습니다. 데이터 파일을 확인해주세요.")
    st.stop()

# 공연명 목록
perf_list = perf_df['공연명'].dropna().unique().tolist()

# 일일입력 당일 데이터에서 공연별 오픈석/공연일/회차 매핑 (No < 100인 행 = 당일)
open_seats_map = {}
perf_info_map = {}  # 공연명 → {공연일, 회차/시각}
if daily_df is not None and '공연명' in daily_df.columns:
    daily_df['No_num'] = pd.to_numeric(daily_df['No'], errors='coerce')
    today_data = daily_df[(daily_df['No_num'].notnull()) & (daily_df['No_num'] < 100)]
    for _, row in today_data.iterrows():
        name = str(row['공연명']).strip()
        if '오픈석' in daily_df.columns:
            open_seats_map[name] = int(row['오픈석']) if pd.notna(row['오픈석']) else 0
        info = {}
        if '공연일' in daily_df.columns and pd.notna(row.get('공연일')):
            info['공연일'] = str(row['공연일'])
        if '회차/시각' in daily_df.columns and pd.notna(row.get('회차/시각')):
            info['회차/시각'] = str(row['회차/시각'])
        perf_info_map[name] = info

# ── 세션 상태: 입력된 데이터 목록 ──
if "daily_entries" not in st.session_state:
    st.session_state.daily_entries = []

# ── 입력 폼 ──
st.subheader("📋 판매 데이터 입력")

with st.form("daily_input_form", clear_on_submit=True):
    col_date, col_perf = st.columns([1, 2])
    with col_date:
        base_date = st.date_input("📅 기준일자", value=date.today())
    with col_perf:
        selected_perf = st.selectbox("🎭 공연 선택", perf_list)

    # 오픈석: 일일입력 당일 데이터에서 매칭 시도, 없으면 수동 입력
    matched_open = None
    for key, val in open_seats_map.items():
        if selected_perf in key or key in selected_perf:
            matched_open = val
            break

    st.markdown("##### 좌석·금액 입력")
    col1, col2, col3 = st.columns(3)
    with col1:
        open_seats = st.number_input("🪑 오픈석", min_value=0, value=matched_open or 0, step=1)
        paid_seats = st.number_input("🎫 유료좌석", min_value=0, value=0, step=1)
        paid_amount = st.number_input("💰 유료금액 (원)", min_value=0, value=0, step=10000)
    with col2:
        reserved_seats = st.number_input("📌 예약좌석", min_value=0, value=0, step=1)
        reserved_amount = st.number_input("💰 예약금액 (원)", min_value=0, value=0, step=10000)
    with col3:
        free_seats = st.number_input("🆓 무료좌석", min_value=0, value=0, step=1)

    submitted = st.form_submit_button("➕ 입력 추가", use_container_width=True)

if submitted:
    total_seats = paid_seats + reserved_seats + free_seats
    total_amount = paid_amount + reserved_amount
    occupancy = min(total_seats / open_seats * 100, 100.0) if open_seats > 0 else 0.0

    # 공연일/회차 자동 매칭
    matched_info = {}
    for key, info in perf_info_map.items():
        if selected_perf in key or key in selected_perf:
            matched_info = info
            break

    entry = {
        "기준일자": base_date.strftime("%Y-%m-%d"),
        "공연명": selected_perf,
        "공연일": matched_info.get("공연일", ""),
        "회차/시각": matched_info.get("회차/시각", ""),
        "오픈석": open_seats,
        "유료좌석": paid_seats,
        "유료금액": paid_amount,
        "예약좌석": reserved_seats,
        "예약금액": reserved_amount,
        "무료좌석": free_seats,
        "합계좌석": total_seats,
        "합계금액": total_amount,
        "점유율": round(occupancy, 2),
    }
    st.session_state.daily_entries.append(entry)
    st.success(f"✅ **{selected_perf}** 데이터가 추가되었습니다.")

# ── 자동 계산 미리보기 (폼 외부) ──
st.markdown("---")

# ── 입력 내역 표시 ──
if st.session_state.daily_entries:
    st.subheader(f"📊 입력 내역 ({len(st.session_state.daily_entries)}건)")

    display_df = pd.DataFrame(st.session_state.daily_entries)

    # 포맷팅용 복사본
    fmt_df = display_df.copy()
    fmt_df['유료금액'] = fmt_df['유료금액'].apply(lambda x: f"{x:,}")
    fmt_df['예약금액'] = fmt_df['예약금액'].apply(lambda x: f"{x:,}")
    fmt_df['합계금액'] = fmt_df['합계금액'].apply(lambda x: f"{x:,}")
    fmt_df['점유율'] = fmt_df['점유율'].apply(lambda x: f"{x:.1f}%")

    st.dataframe(fmt_df, use_container_width=True, hide_index=True)

    # 합계 요약
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        st.metric("총 합계좌석", f"{display_df['합계좌석'].sum():,}석")
    with col_s2:
        st.metric("총 합계금액", f"{display_df['합계금액'].sum():,}원")
    with col_s3:
        avg_occ = display_df['점유율'].clip(upper=100.0).mean()
        st.metric("평균 점유율", f"{avg_occ:.1f}%")

    # 개별 삭제
    st.markdown("---")
    col_del, col_clear = st.columns(2)
    with col_del:
        if len(st.session_state.daily_entries) > 0:
            del_idx = st.selectbox(
                "삭제할 항목",
                range(len(st.session_state.daily_entries)),
                format_func=lambda i: f"[{i+1}] {st.session_state.daily_entries[i]['공연명']} ({st.session_state.daily_entries[i]['기준일자']})"
            )
            if st.button("🗑️ 선택 항목 삭제"):
                st.session_state.daily_entries.pop(del_idx)
                st.rerun()
    with col_clear:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🗑️ 전체 초기화", type="secondary"):
            st.session_state.daily_entries = []
            st.rerun()

    # 제출 버튼
    st.markdown("---")
    if st.button("📤 SharePoint에 제출", type="primary", use_container_width=True):
        entries = st.session_state.daily_entries

        # 1) 중복 체크
        with st.spinner("🔍 중복 데이터 확인 중..."):
            dup_indices = check_duplicate_entries(entries)

        if dup_indices:
            st.warning("⚠️ 다음 항목이 이미 누적 로그에 존재합니다:")
            for idx in dup_indices:
                e = entries[idx]
                st.markdown(f"  - **{e['공연명']}** ({e['기준일자']})")
            st.info("💡 중복 항목을 삭제한 후 다시 제출하거나, 그대로 제출하려면 아래 버튼을 눌러주세요.")

            if st.button("⚡ 중복 무시하고 강제 제출", key="force_submit"):
                with st.spinner("📤 SharePoint에 저장 중..."):
                    success, msg = write_daily_entries_to_sharepoint(entries)
                if success:
                    st.success(f"✅ {msg}")
                    st.session_state.daily_entries = []
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")
        else:
            # 중복 없음 → 바로 저장
            with st.spinner("📤 SharePoint에 저장 중..."):
                success, msg = write_daily_entries_to_sharepoint(entries)
            if success:
                st.success(f"✅ {msg}")
                for i, entry in enumerate(entries, 1):
                    st.markdown(
                        f"**[{i}] {entry['공연명']}** — "
                        f"좌석 {entry['합계좌석']:,}석, "
                        f"금액 {entry['합계금액']:,}원, "
                        f"점유율 {entry['점유율']:.1f}%"
                    )
                st.session_state.daily_entries = []
                st.rerun()
            else:
                st.error(f"❌ {msg}")
else:
    st.info("💡 위 폼에서 공연 데이터를 입력한 후 **입력 추가** 버튼을 눌러주세요. 여러 공연을 반복 입력할 수 있습니다.")
