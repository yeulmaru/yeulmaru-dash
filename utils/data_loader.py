import os
import glob
import pandas as pd
import streamlit as st

@st.cache_data(ttl=300)
def get_data_filepath():
    data_dir = "data"
    if not os.path.exists(data_dir):
        return None
    excel_files = glob.glob(os.path.join(data_dir, "*.xlsx"))
    if not excel_files:
        return None
    return excel_files[0]

@st.cache_data(ttl=300)
def get_base_date():
    filepath = get_data_filepath()
    if not filepath:
        return None
    try:
        df = pd.read_excel(filepath, sheet_name='일일입력', nrows=2, header=None)
        val = df.iloc[1, 1] # B2 cell
        try:
            return pd.to_datetime(str(int(val)), format='%Y%m%d')
        except:
            return val
    except Exception as e:
        return None

@st.cache_data(ttl=300)
def load_daily_input():
    filepath = get_data_filepath()
    if not filepath:
        return None
    try:
        df = pd.read_excel(filepath, sheet_name='일일입력', skiprows=3)
        # Filter valid data using 'No' column
        if 'No' in df.columns:
            df = df[pd.to_numeric(df['No'], errors='coerce').notnull()].copy()
            
        if '공연일(날짜)' in df.columns:
            df['공연일(날짜)'] = pd.to_datetime(df['공연일(날짜)'], errors='coerce')
            
        return df
    except Exception as e:
        st.error(f"`일일입력` 데이터 로드 오류: {e}")
        return None

@st.cache_data(ttl=300)
def load_sales_trend():
    filepath = get_data_filepath()
    if not filepath:
        return None
    try:
        df = pd.read_excel(filepath, sheet_name='판매추이')
        if '기준일자' in df.columns:
            df['기준일자'] = pd.to_datetime(df['기준일자'].astype(str), format='%Y%m%d', errors='coerce')
        return df
    except Exception as e:
        st.error(f"`판매추이` 데이터 로드 오류: {e}")
        return None

@st.cache_data(ttl=300)
def load_25_performance():
    filepath = get_data_filepath()
    if not filepath:
        return None
    try:
        df_raw = pd.read_excel(filepath, sheet_name='25공연', header=None)
        
        # Start looking from row 6 (index 5)
        df = df_raw.iloc[5:].copy()
        columns = ['A', '카테고리', '공연명', '진행월', '횟수', '예산', '지출', '비율1', '판매수수료', '매출', '비율2', '차액', '판매인원', '초대인원', '계', '수익율1', '수익율2']
        
        num_cols = min(len(df.columns), len(columns))
        df = df.iloc[:, :num_cols]
        df.columns = columns[:num_cols]
        
        if '카테고리' in df.columns:
            df['카테고리'] = df['카테고리'].ffill()
            
        if '공연명' in df.columns:
            df = df.dropna(subset=['공연명'])
            df = df[~df['공연명'].astype(str).str.contains('합계|소계|계', na=False)]
            
        numeric_cols = ['횟수', '예산', '지출', '판매수수료', '매출', '차액', '판매인원', '초대인원', '계', '수익율1']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
        return df
    except Exception as e:
        st.error(f"`25공연` 데이터 로드 오류: {e}")
        return None

@st.cache_data(ttl=300)
def load_yearly_performance():
    filepath = get_data_filepath()
    if not filepath:
        return None
    try:
        df = pd.read_excel(filepath, sheet_name='운영실적통합', skiprows=3)
        df = df.dropna(subset=['구분', '기간'], how='all').copy()
        return df
    except Exception as e:
        st.error(f"`운영실적통합` 데이터 로드 오류: {e}")
        return None

@st.cache_data(ttl=300)
def load_detailed_management():
    filepath = get_data_filepath()
    if not filepath:
        return None
    try:
        df = pd.read_excel(filepath, sheet_name='세부운영관리대장(정리)', skiprows=1)
        if '전체순번' in df.columns:
            df = df[df['전체순번'].astype(str) != '소계']
            df = df[df['전체순번'].notna()]
            
        if '년도' in df.columns:
            df['년도'] = df['년도'].astype(str).str.replace(r'\D', '', regex=True)
            df['년도'] = pd.to_numeric(df['년도'], errors='coerce')
            
        return df
    except Exception as e:
        st.error(f"`세부운영관리대장(정리)` 데이터 로드 오류: {e}")
        return None
