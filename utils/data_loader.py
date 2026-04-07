import io
import os
import pandas as pd
import requests
import streamlit as st

from utils.local_excel_writer import find_local_excel_path


_data_source = "로컬"  # get_excel_data() 호출 시 동적 갱신


def get_data_source():
    """현재 데이터 소스 반환 (디버그용)"""
    return _data_source


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
        "scope": "https://graph.microsoft.com/.default",
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]


def _find_sharepoint_file_ids(force_refresh=False):
    """SharePoint 파일의 site_id/drive_id/item_id/etag를 찾아 session_state에 캐시"""
    if not force_refresh and 'sp_file_ids' in st.session_state:
        return st.session_state['sp_file_ids']

    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    site_name = st.secrets["azure"]["site_name"]
    file_name = st.secrets["azure"]["file_name"]
    graph_base = "https://graph.microsoft.com/v1.0"

    # 1) 사이트 ID
    site_url = f"{graph_base}/sites/gscaltexyeulmaru.sharepoint.com:/sites/{site_name}"
    site_resp = requests.get(site_url, headers=headers)
    site_resp.raise_for_status()
    site_id = site_resp.json()["id"]

    # 2) 드라이브 + 파일 검색
    drives_url = f"{graph_base}/sites/{site_id}/drives"
    drives_resp = requests.get(drives_url, headers=headers)
    drives_resp.raise_for_status()
    drives = drives_resp.json().get("value", [])

    target = None
    target_drive_id = None
    for drv in drives:
        drive_id = drv["id"]
        search_url = f"{graph_base}/drives/{drive_id}/root/search(q='{file_name}')"
        search_resp = requests.get(search_url, headers=headers)
        if search_resp.status_code != 200:
            continue
        items = search_resp.json().get("value", [])
        for item in items:
            if item.get("name") == file_name:
                target = item
                target_drive_id = drive_id
                break
        if target:
            break

    if not target:
        raise FileNotFoundError(f"SharePoint에서 {file_name}을(를) 찾을 수 없습니다")

    result = {
        'site_id': site_id,
        'drive_id': target_drive_id,
        'item_id': target['id'],
        'etag': target.get('eTag', '').strip('"').strip(),
    }
    st.session_state['sp_file_ids'] = result
    return result


@st.cache_data(ttl=60)
def download_excel_from_sharepoint():
    """SharePoint에서 엑셀 파일 다운로드 -> raw bytes 반환"""
    try:
        ids = _find_sharepoint_file_ids()
        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        graph_base = "https://graph.microsoft.com/v1.0"

        content_url = f"{graph_base}/drives/{ids['drive_id']}/items/{ids['item_id']}/content"
        file_resp = requests.get(content_url, headers=headers)
        file_resp.raise_for_status()
        return file_resp.content
    except Exception:
        return None


def upload_excel_to_sharepoint(content_bytes, expected_etag=None):
    """수정된 엑셀 bytes를 SharePoint에 업로드. ETag로 충돌 감지.

    Returns:
        (True, new_etag, None) — 성공
        (False, None, error_message) — 실패
    """
    try:
        token = get_access_token()
        ids = _find_sharepoint_file_ids()

        url = f"https://graph.microsoft.com/v1.0/drives/{ids['drive_id']}/items/{ids['item_id']}/content"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        if expected_etag:
            headers["If-Match"] = f'"{expected_etag}"'

        resp = requests.put(url, headers=headers, data=content_bytes)

        if resp.status_code == 412:
            if 'sp_file_ids' in st.session_state:
                del st.session_state['sp_file_ids']
            return (False, None, "문서가 현재 사용 중에 있습니다. 잠시 후에 시도해주세요.")

        if resp.status_code in (200, 201):
            new_etag = resp.json().get('eTag', '').strip('"').strip()
            if 'sp_file_ids' in st.session_state:
                st.session_state['sp_file_ids']['etag'] = new_etag
            return (True, new_etag, None)

        return (False, None, f"업로드 실패 (HTTP {resp.status_code}): {resp.text[:200]}")

    except Exception as e:
        return (False, None, f"업로드 오류: {str(e)}")


def get_excel_data():
    """운영 엑셀 파일 경로 또는 BytesIO 반환 (로컬 우선, Cloud fallback)"""
    # 1. 로컬 파일 우선 (사무실 PC)
    local_path = find_local_excel_path()
    if local_path:
        return local_path

    # 2. SharePoint download (Cloud 환경)
    raw = download_excel_from_sharepoint()
    if raw:
        return io.BytesIO(raw)

    # 3. 둘 다 실패
    st.error("운영 엑셀 파일을 찾을 수 없습니다.")
    st.stop()


def get_data_filepath():
    """하위 호환용 - 로컬 파일 경로 반환"""
    return find_local_excel_path()


# ── 데이터 로드 함수들 ──

@st.cache_data(ttl=60)
def load_performance_master():
    """공연마스터 시트를 읽어서 DataFrame 반환"""
    source = get_excel_data()
    if not source:
        return None
    try:
        df = pd.read_excel(source, sheet_name='공연마스터')
        # 총오픈석/가용석이 수식이라 NaN일 수 있으므로 계산으로 보정
        for col in ['기준석', '총회차']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        if '총오픈석' not in df.columns or df['총오픈석'].isna().all():
            df['총오픈석'] = df['기준석'] * df['총회차']
        else:
            df['총오픈석'] = pd.to_numeric(df['총오픈석'], errors='coerce')
            df['총오픈석'] = df['총오픈석'].fillna(df['기준석'] * df['총회차'])
        if '가용석' in df.columns:
            df['가용석'] = pd.to_numeric(df['가용석'], errors='coerce')
            df['가용석'] = df['가용석'].fillna(df['기준석'])
        if '목표점유율' in df.columns:
            df['목표점유율'] = pd.to_numeric(df['목표점유율'], errors='coerce').fillna(80)
        else:
            df['목표점유율'] = 80
        return df
    except Exception as e:
        st.warning(f"`공연마스터` 데이터 로드 오류: {e}")
        return None


def get_active_performances(master_df, today=None):
    """판매중 공연 필터링.
    조건: 상태==판매중 AND 티켓오픈일 <= today <= 종료일 (날짜 없으면 상태만으로 판단).

    Args:
        master_df: load_performance_master() 결과
        today: 기준일 (기본값 오늘)

    Returns:
        판매중 공연만 필터링된 DataFrame
    """
    if master_df is None or master_df.empty:
        return pd.DataFrame()
    if today is None:
        today = pd.Timestamp.now().normalize()
    else:
        today = pd.Timestamp(today)

    df = master_df.copy()

    # 1차: 상태 컬럼 필터
    if '상태' in df.columns:
        df = df[df['상태'].astype(str).str.strip() == '판매중']

    # 2차: 날짜 범위 필터 (컬럼 있을 때만)
    if '종료일' in df.columns:
        end = pd.to_datetime(df['종료일'], errors='coerce')
        df = df[end.isna() | (end >= today)]
    if '티켓오픈일' in df.columns:
        open_dt = pd.to_datetime(df['티켓오픈일'], errors='coerce')
        df = df[open_dt.isna() | (open_dt <= today)]

    return df.reset_index(drop=True)


def match_performance(perf_name, master_df):
    """공연명으로 공연마스터 행 매칭 (contains 양방향).

    Args:
        perf_name: 검색할 공연명 문자열
        master_df: load_performance_master() 결과

    Returns:
        매칭된 Series (행) 또는 None
    """
    if master_df is None or master_df.empty:
        return None
    perf_name_s = str(perf_name).strip()
    for _, row in master_df.iterrows():
        master_name = str(row['사업명']).strip()
        if perf_name_s == master_name:
            return row
    return None


def match_performance_category(perf_name, master_df):
    """공연명으로 공연마스터에서 사업구분(상업성/공공성) 찾기.

    Returns:
        '상업성' or '공공성' or None
    """
    matched = match_performance(perf_name, master_df)
    if matched is not None and pd.notna(matched.get('수익성')):
        return str(matched['수익성']).strip()
    return None


def get_target_occupancy(perf_name, master_df):
    """공연명으로 공연마스터에서 목표점유율 찾기.

    Returns:
        int (예: 20, 50, 60) or None
    """
    matched = match_performance(perf_name, master_df)
    if matched is not None and pd.notna(matched.get('목표점유율')):
        val = int(matched['목표점유율'])
        return val
    return None

@st.cache_data(ttl=60)
def load_round_details():
    """회차상세 시트를 읽어서 DataFrame 반환"""
    source = get_excel_data()
    if not source:
        return None
    try:
        df = pd.read_excel(source, sheet_name='회차상세')
        df['공연일'] = pd.to_datetime(df['공연일'], errors='coerce')
        return df
    except Exception:
        return None


@st.cache_data(ttl=60)
def get_base_date():
    """누적기록(행16~)의 최신 기준일자를 갱신일자로 반환."""
    source = get_excel_data()
    if not source:
        return None
    try:
        df = pd.read_excel(source, sheet_name='일일입력', skiprows=15,
                           usecols=[0], names=['기준일자'])
        vals = pd.to_numeric(df['기준일자'], errors='coerce')
        date_vals = vals[(vals > 20000000) & (vals < 30000000)]
        if not date_vals.empty:
            return pd.to_datetime(str(int(date_vals.max())), format='%Y%m%d')
        return None
    except Exception:
        return None


@st.cache_data(ttl=60)
def load_daily_input():
    source = get_excel_data()
    if not source:
        return None
    try:
        df = pd.read_excel(source, sheet_name='일일입력', skiprows=15)
        df = df.loc[:, ~df.columns.str.startswith('Unnamed')]
        df = df.dropna(subset=['기준일자', '공연명']).copy()
        df['기준일자'] = pd.to_numeric(df['기준일자'], errors='coerce')
        df = df[df['기준일자'].between(20000000, 30000000)]
        df['_sort_key'] = range(len(df))
        return df
    except Exception as e:
        st.error(f"`일일입력` 데이터 로드 오류: {e}")
        return None


@st.cache_data(ttl=60)
def load_sales_trend():
    """일일입력 시트의 누적기록(행16~)에서 판매추이 데이터를 읽는다.
    (판매추이 시트는 수식 참조라 openpyxl로 값을 읽을 수 없음)"""
    source = get_excel_data()
    if not source:
        return None
    try:
        df = pd.read_excel(source, sheet_name='일일입력', skiprows=15)
        # 불필요 컬럼 제거
        df = df.loc[:, ~df.columns.str.startswith('Unnamed')]
        # 기준일자·공연명이 비어있는 행 제거
        df = df.dropna(subset=['기준일자', '공연명']).copy()
        # 기준일자 → datetime
        df['기준일자'] = pd.to_datetime(
            df['기준일자'].astype(str).str.replace(r'\.0$', '', regex=True),
            format='%Y%m%d', errors='coerce',
        )
        df = df.dropna(subset=['기준일자'])
        # 숫자 컬럼 변환
        for col in ['합계좌석', '합계금액', '점유율', '전일대비(석)', '전일대비(원)', '객단가']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return df
    except Exception as e:
        st.error(f"판매추이(일일입력 누적) 데이터 로드 오류: {e}")
        return None


@st.cache_data(ttl=60)
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


@st.cache_data(ttl=60)
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


@st.cache_data(ttl=60)
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

@st.cache_data(ttl=60)
def load_combined_performance():
    """일일입력 누적기록 + 세부운영관리대장 UNION.

    두 소스를 공통 컬럼으로 통일해 하나의 DataFrame으로 반환.
    일일입력 데이터는 데이터유형='일일입력', 과거 데이터는 '종료시최종'.
    """
    # 1. 일일입력 누적기록
    daily = load_daily_input()
    if daily is not None:
        daily = daily.copy()
        if '데이터유형' not in daily.columns:
            daily['데이터유형'] = '일일입력'
    else:
        daily = pd.DataFrame()

    # 2. 세부운영관리대장
    detail = load_detailed_management()
    if detail is not None:
        detail = detail.copy()
        # 컬럼 매핑: 세부운영관리대장 → 공통 스키마
        col_map = {}
        for col in detail.columns:
            cs = str(col).replace('\n', '')
            if '공연' in cs and '명' in cs:
                col_map[col] = '공연명'
            elif '세부' in cs and '장르' in cs:
                col_map[col] = '세부장르'
            elif '사업' in cs and '구분' in cs:
                col_map[col] = '사업구분'
            elif '공연' in cs and '구분' in cs:
                col_map[col] = '공연구분'
        detail = detail.rename(columns=col_map)
        detail['데이터유형'] = '종료시최종'
    else:
        detail = pd.DataFrame()

    # 3. UNION (공통 컬럼만)
    common_cols = ['공연명', '데이터유형']
    for c in ['세부장르', '사업구분', '공연구분', '장르1', '상태']:
        if c in daily.columns or (not detail.empty and c in detail.columns):
            common_cols.append(c)

    frames = []
    for df in [daily, detail]:
        if not df.empty:
            available = [c for c in common_cols if c in df.columns]
            frames.append(df[available])

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        return combined
    return pd.DataFrame()
