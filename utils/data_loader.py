import os
import io
import glob
import pandas as pd
import streamlit as st
import requests


def get_access_token():
    """Azure AD에서 Microsoft Graph API 액세스 토큰 발급"""
    tenant_id = st.secrets["azure"]["tenant_id"]
    client_id = st.secrets["azure"]["client_id"]
    client_secret = st.secrets["azure"]["client_secret"]

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default"
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]


@st.cache_data(ttl=300)
def download_excel_from_sharepoint():
    """SharePoint에서 엑셀 파일 다운로드 → BytesIO 반환"""
    try:
        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        site_name = st.secrets["azure"]["site_name"]
        file_name = st.secrets["azure"]["file_name"]

        # 1) SharePoint 사이트 ID 조회
        site_url = f"https://graph.microsoft.com/v1.0/sites/gscaltexyeulmaru.sharepoint.com:/sites/{site_name}"
        site_resp = requests.get(site_url, headers=headers)
        site_resp.raise_for_status()
        site_id = site_resp.json()["id"]

        # 2) 파일 검색 (드라이브 루트에서)
        file_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{file_name}:/content"
        file_resp = requests.get(file_url, headers=headers)

        # 루트에 없으면 전체 검색
        if file_resp.status_code == 404:
            search_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root/search(q='{file_name}')"
            search_resp = requests.get(search_url, headers=headers)
            search_resp.raise_for_status()
            items = search_resp.json().get("value", [])
            if items:
                download_url = items[0].get("@microsoft.graph.downloadUrl")
                if download_url:
                    file_resp = requests.get(download_url)

        file_resp.raise_for_status()
        return io.BytesIO(file_resp.content)
    except Exception as e:
        st.warning(f"SharePoint 연결 실패, 로컬 파일로 전환합니다: {e}")
        return None


def get_excel_data():
    """SharePoint 우선, 실패 시 로컬 data/ 폴더에서 읽기 (fallback)"""
    # SharePoint 시도
    try:
        excel_bytes = download_excel_from_sharepoint()
        if excel_bytes:
            return excel_bytes
    except:
        pass

    # fallback: 로컬 파일
    data_dir = "data"
    if os.path.exists(data_dir):
        excel_files = glob.glob(os.path.join(data_dir, "*.xlsx"))
        if excel_files:
            return excel_files[0]
    return None


# ── 하위 호환용 ──

@st.cache_data(ttl=300)
def get_data_filepath():
    """하위 호환용 - 로컬 파일 경로 반환"""
    data_dir = "data"
    if not os.path.exists(data_dir):
        return None
    excel_files = glob.glob(os.path.join(data_dir, "*.xlsx"))
    if not excel_files:
        return None
    return excel_files[0]


# ── 데이터 로드 함수들 ──

@st.cache_data(ttl=300)
def get_base_date():
    source = get_excel_data()
    if not source:
        return None
    try:
        df = pd.read_excel(source, sheet_name='일일입력', nrows=2, header=None)
        val = df.iloc[1, 1]
        try:
            return pd.to_datetime(str(int(val)), format='%Y%m%d')
        except:
            return val
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_daily_input():
    source = get_excel_data()
    if not source:
        return None
    try:
        df = pd.read_excel(source, sheet_name='일일입력', skiprows=3)
        if 'No' in df.columns:
            df = df[pd.to_numeric(df['No'], errors='coerce').notnull()].copy()

        # 공연일(시작) 컬럼 자동 감지
        for col in df.columns:
            col_str = str(col)
            if '공연' in col_str and '시작' in col_str:
                df[col] = pd.to_datetime(df[col], errors='coerce')

        return df
    except Exception as e:
        st.error(f"`일일입력` 데이터 로드 오류: {e}")
        return None


@st.cache_data(ttl=300)
def load_sales_trend():
    source = get_excel_data()
    if not source:
        return None
    try:
        df = pd.read_excel(source, sheet_name='판매추이')
        # 기준일자 컬럼 자동 감지
        for col in df.columns:
            col_str = str(col)
            if '기준' in col_str and '일자' in col_str:
                df[col] = pd.to_datetime(df[col].astype(str), format='%Y%m%d', errors='coerce')
        return df
    except Exception as e:
        st.error(f"`판매추이` 데이터 로드 오류: {e}")
        return None


@st.cache_data(ttl=300)
def load_25_performance():
    source = get_excel_data()
    if not source:
        return None
    try:
        df_raw = pd.read_excel(source, sheet_name='25공연', header=None)
        df = df_raw.iloc[5:].copy()

        columns = [
            'A', '카테고리', '공연명', '진행상', '횟수', '예산', '지출', '비고1',
            '판매좌석율', '매출', '비고2', '차액', '판매인원', '총관인원',
            '공연', '수익율', '수익율2'
        ]

        num_cols = min(len(df.columns), len(columns))
        df = df.iloc[:, :num_cols]
        df.columns = columns[:num_cols]

        if '카테고리' in df.columns:
            df['카테고리'] = df['카테고리'].ffill()

        if '공연명' in df.columns:
            df = df.dropna(subset=['공연명'])
            df = df[~df['공연명'].astype(str).str.contains('소계|중계|공연', na=False)]

        numeric_cols = ['횟수', '예산', '지출', '판매좌석율', '매출', '차액', '판매인원', '총관인원', '공연', '수익율']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        return df
    except Exception as e:
        st.error(f"`25공연` 데이터 로드 오류: {e}")
        return None


@st.cache_data(ttl=300)
def load_yearly_performance():
    source = get_excel_data()
    if not source:
        return None
    try:
        df = pd.read_excel(source, sheet_name='운영실적통합', skiprows=3)
        df = df.dropna(subset=['구분', '기간'], how='all').copy()
        return df
    except Exception as e:
        st.error(f"`운영실적통합` 데이터 로드 오류: {e}")
        return None


@st.cache_data(ttl=300)
def load_detailed_management():
    source = get_excel_data()
    if not source:
        return None
    try:
        df = pd.read_excel(source, sheet_name='세부운영관리대장(정리)', skiprows=1)

        # 전체순번 컬럼 자동 감지
        for col in df.columns:
            col_str = str(col)
            if '전체' in col_str and '순번' in col_str:
                df = df[df[col].astype(str) != '중계']
                df = df[df[col].notna()]

        # 연도 컬럼 자동 감지
        for col in df.columns:
            if '연도' in str(col):
                df[col] = df[col].astype(str).str.replace(r'\D', '', regex=True)
                df[col] = pd.to_numeric(df[col], errors='coerce')

        return df
    except Exception as e:
        st.error(f"`세부운영관리대장(정리)` 데이터 로드 오류: {e}")
        return None