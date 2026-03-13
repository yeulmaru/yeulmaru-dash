import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.data_loader import load_daily_input, load_sales_trend, get_base_date
from utils.charts import COLORS, apply_common_layout

st.set_page_config(page_title="실시간 판매현황", page_icon="📊", layout="wide")

st.title("📊 실시간 판매현황")

daily_df = load_daily_input()
trend_df = load_sales_trend()
base_date = get_base_date()

if daily_df is None or trend_df is None:
    st.error("데이터를 정상적으로 불러오지 못했습니다. `data` 폴더에 올바른 엑셀 파일이 위치해 있는지 확인해주세요.")
    st.stop()

if hasattr(base_date, 'weekday'):
    weekdays = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
    wd = weekdays[base_date.weekday()]
    base_date_str = base_date.strftime(f'%Y년 %m월 %d일 {wd}')
else:
    try:
        dt = pd.to_datetime(base_date)
        weekdays = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
        wd = weekdays[dt.weekday()]
        base_date_str = dt.strftime(f'%Y년 %m월 %d일 {wd}')
    except Exception:
        base_date_str = str(base_date)

st.markdown(f"**기준일자**: {base_date_str}")
st.markdown("---")

total_seats = daily_df['합계좌석'].sum() if '합계좌석' in daily_df.columns else 0
total_rev = daily_df['합계금액'].sum() if '합계금액' in daily_df.columns else 0

col1, col2 = st.columns(2)
with col1:
    st.metric("전체 판매좌석 합계", f"{int(total_seats):,}" if not pd.isna(total_seats) else "0")
with col2:
    st.metric("전체 판매금액 합계", f"{int(total_rev):,}원" if not pd.isna(total_rev) else "0원")

st.markdown("### 공연별 요약")

if '공연명' in daily_df.columns:
    agg_dict = {
        '합계좌석': 'sum',
        '합계금액': 'sum',
        '오픈석': 'sum'
    }
    if '공연일(날짜)' in daily_df.columns:
        agg_dict['공연일(날짜)'] = 'min'
        
    daily_grouped = daily_df.groupby('공연명').agg(agg_dict).reset_index()
    daily_grouped['점유율'] = (daily_grouped['합계좌석'] / daily_grouped['오픈석'].replace(0, float('nan')) * 100).fillna(0)

    if '공연일(날짜)' in daily_grouped.columns:
        base_dt = pd.to_datetime(base_date, errors='coerce')
        if pd.notna(base_dt):
            daily_grouped['days_diff'] = (daily_grouped['공연일(날짜)'] - base_dt).dt.days
        else:
            daily_grouped['days_diff'] = 0
            
        def format_dday(d):
            if pd.isna(d): return ""
            if d == 0: return "D-Day"
            elif d > 0: return f"D-{int(d)}"
            else: return f"D+{int(-d)}"
            
        daily_grouped['D-day'] = daily_grouped['days_diff'].apply(format_dday)
        
        active_df = daily_grouped[daily_grouped['days_diff'] >= 0].copy()
        ended_df = daily_grouped[daily_grouped['days_diff'] < 0].copy()
        
        active_df = active_df.sort_values('공연일(날짜)', ascending=True)
        ended_df = ended_df.sort_values('공연일(날짜)', ascending=False)
    else:
        active_df = daily_grouped.copy()
        ended_df = pd.DataFrame(columns=daily_grouped.columns)
        active_df['D-day'] = ""

    # 1. 판매중 공연 (카드 형태)
    prev_seats = {}
    if not trend_df.empty and '기준일자' in trend_df.columns and '공연명' in trend_df.columns and '합계좌석' in trend_df.columns:
        try:
            temp_trend = trend_df.copy()
            temp_trend['기준일자'] = pd.to_datetime(temp_trend['기준일자'])
            base_dt_val = pd.to_datetime(base_date)
            past_trend = temp_trend[temp_trend['기준일자'] < base_dt_val].sort_values('기준일자')
            latest_past = past_trend.groupby('공연명').last().reset_index()
            prev_seats = dict(zip(latest_past['공연명'], latest_past['합계좌석']))
        except Exception:
            pass

    if not active_df.empty:
        n_active = len(active_df)
        for i, (idx, row) in enumerate(active_df.iterrows()):
            perf_name = row['공연명']
            seats = int(row['합계좌석']) if pd.notna(row['합계좌석']) else 0
            open_s = int(row['오픈석']) if pd.notna(row['오픈석']) else 0
            money = int(row['합계금액']) if pd.notna(row['합계금액']) else 0
            
            if open_s == 0:
                occupancy = "-"
            else:
                occupancy = f"{(seats / open_s * 100):.1f}"
                
            with st.container():
                st.markdown(f"**▶ {perf_name}**")
                content = f"누적좌석: {seats:,}석({occupancy}%)  \n"
                content += f"누적금액: {money:,}원"
                if perf_name in prev_seats:
                    diff = seats - int(prev_seats[perf_name])
                    if diff > 0:
                        content += f"  \n전일대비: :green[+{diff:,}석]"
                    elif diff < 0:
                        content += f"  \n전일대비: :red[{diff:,}석]"
                    else:
                        content += f"  \n전일대비: :gray[+0석]"
                st.markdown(content)
            
            if i < n_active - 1:
                st.divider()
    else:
        st.info("현재 판매중인 공연이 없습니다.")

    st.markdown("<br>", unsafe_allow_html=True)

    # 2. 종료 공연 (카드 형태)
    if not ended_df.empty:
        with st.expander("종료된 공연 보기"):
            n_ended = len(ended_df)
            for i, (idx, row) in enumerate(ended_df.iterrows()):
                perf_name = row['공연명']
                seats = int(row['합계좌석']) if pd.notna(row['합계좌석']) else 0
                open_s = int(row['오픈석']) if pd.notna(row['오픈석']) else 0
                money = int(row['합계금액']) if pd.notna(row['합계금액']) else 0
                
                if open_s == 0:
                    occupancy = "-"
                else:
                    occupancy = f"{(seats / open_s * 100):.1f}"
                    
                with st.container():
                    st.markdown(f"**▶ {perf_name}**")
                    content = f"누적좌석: {seats:,}석({occupancy}%)  \n"
                    content += f"누적금액: {money:,}원"
                    st.markdown(content)
                
                if i < n_ended - 1:
                    st.divider()

    # 이후 '공연별 점유율 비교' 차트 등을 위해 daily_grouped 를 판매중 공연 데이터로 교체
    daily_grouped = active_df.copy()

st.markdown("---")

if '공연명' in daily_df.columns:
    st.subheader("📊 공연별 점유율 비교")
    daily_grouped = daily_grouped.sort_values(by='점유율', ascending=True)
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=daily_grouped['점유율'],
        y=daily_grouped['공연명'],
        orientation='h',
        marker_color=COLORS['primary'],
        text=[f"{val:.1f}%" for val in daily_grouped['점유율']],
        textposition='auto'
    ))
    
    fig.add_vline(x=100, line_dash="dash", line_color=COLORS['danger'], annotation_text="100%", annotation_position="top right")
    fig.update_layout(xaxis_title="점유율 (%)", yaxis_title="")
    fig = apply_common_layout(fig)
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

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
