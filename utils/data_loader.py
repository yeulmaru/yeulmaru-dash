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


@st.cache_data(ttl=60)
def download_excel_from_sharepoint():
    """SharePoint에서 엑셀 파일 다운로드 → raw bytes 반환 (캐싱 안전)"""
    try:
        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        site_name = st.secrets["azure"]["site_name"]
        file_name = st.secrets["azure"]["file_name"]
        graph_base = "https://graph.microsoft.com/v1.0"

        # 1) SharePoint 사이트 ID 조회
        site_url = f"{graph_base}/sites/gscaltexyeulmaru.sharepoint.com:/sites/{site_name}"
        site_resp = requests.get(site_url, headers=headers)
        site_resp.raise_for_status()
        site_id = site_resp.json()["id"]

        # 2) 사이트의 모든 드라이브 조회 후 각 드라이브에서 파일 검색
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
            st.warning("SharePoint에서 파일을 찾을 수 없습니다.")
            return None

        # 3) 다운로드 URL로 파일 받기
        download_url = target.get("@microsoft.graph.downloadUrl")
        if download_url:
            file_resp = requests.get(download_url)
            file_resp.raise_for_status()
            return file_resp.content  # raw bytes (immutable, 캐싱 안전)

        # downloadUrl 없으면 drive_id + item_id로 다운로드
        item_id = target["id"]
        content_url = f"{graph_base}/drives/{target_drive_id}/items/{item_id}/content"
        file_resp = requests.get(content_url, headers=headers)
        file_resp.raise_for_status()
        return file_resp.content  # raw bytes

    except Exception as e:
        st.warning(f"SharePoint 연결 실패, 로컬 파일로 전환합니다: {e}")
        return None


_data_source = "unknown"  # 디버그용: 마지막 데이터 소스 추적


def get_data_source():
    """현재 데이터 소스 반환 (디버그용)"""
    return _data_source


def get_excel_data():
    """SharePoint 우선, 실패 시 로컬 data/ 폴더에서 읽기 (fallback)"""
    global _data_source
    # SharePoint 시도
    try:
        raw = download_excel_from_sharepoint()
        if raw:
            _data_source = "SharePoint"
            return io.BytesIO(raw)  # 매번 새 BytesIO 생성 → 파일포인터 항상 0
    except:
        pass

    # fallback: 로컬 파일
    data_dir = "data"
    if os.path.exists(data_dir):
        excel_files = glob.glob(os.path.join(data_dir, "*.xlsx"))
        if excel_files:
            _data_source = f"로컬({os.path.basename(excel_files[0])})"
            return excel_files[0]
    _data_source = "없음"
    return None


# ── 하위 호환용 ──

@st.cache_data(ttl=60)
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
        if perf_name_s == master_name or perf_name_s in master_name or master_name in perf_name_s:
            return row
    return None


def match_performance_category(perf_name, master_df):
    """공연명으로 공연마스터에서 사업구분(상업성/공공성) 찾기.

    Returns:
        '상업성' or '공공성' or None
    """
    matched = match_performance(perf_name, master_df)
    if matched is not None and pd.notna(matched.get('사업구분')):
        return str(matched['사업구분']).strip()
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


# ── SharePoint 파일 메타 (drive_id, item_id) 조회 ──

def _get_sharepoint_file_meta():
    """SharePoint 파일의 drive_id, item_id를 반환"""
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    site_name = st.secrets["azure"]["site_name"]
    file_name = st.secrets["azure"]["file_name"]
    graph_base = "https://graph.microsoft.com/v1.0"

    site_url = f"{graph_base}/sites/gscaltexyeulmaru.sharepoint.com:/sites/{site_name}"
    site_resp = requests.get(site_url, headers=headers)
    site_resp.raise_for_status()
    site_id = site_resp.json()["id"]

    drives_url = f"{graph_base}/sites/{site_id}/drives"
    drives_resp = requests.get(drives_url, headers=headers)
    drives_resp.raise_for_status()
    drives = drives_resp.json().get("value", [])

    for drv in drives:
        drive_id = drv["id"]
        search_url = f"{graph_base}/drives/{drive_id}/root/search(q='{file_name}')"
        search_resp = requests.get(search_url, headers=headers)
        if search_resp.status_code != 200:
            continue
        items = search_resp.json().get("value", [])
        for item in items:
            if item.get("name") == file_name:
                return drive_id, item["id"]

    raise FileNotFoundError("SharePoint에서 파일을 찾을 수 없습니다.")


# ── SharePoint 엑셀 쓰기 ──

def _find_last_literal_data_row(base_url, headers, ws_id):
    """누적 로그 영역에서 마지막 리터럴(수식이 아닌) 데이터 행 번호(1-based)를 반환.
    수식 미리보기 행, 안내 텍스트 행은 건너뜀."""
    import re

    # formulas를 포함한 usedRange 조회
    url = f"{base_url}/worksheets/{ws_id}/usedRange"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    addr = data.get("address", "")
    start_row = 1
    if "!" in addr:
        m = re.search(r'(\d+)', addr.split("!")[1])
        if m:
            start_row = int(m.group(1))

    values = data.get("values", [])
    formulas = data.get("formulas", [])

    # 아래에서 위로 탐색: A열이 yyyymmdd이고 수식이 아닌 리터럴 행
    for i in range(len(values) - 1, -1, -1):
        cell_a = values[i][0]
        if cell_a is None or cell_a == "":
            continue

        # 수식 행 건너뛰기
        if formulas and i < len(formulas):
            formula_a = str(formulas[i][0]) if formulas[i][0] else ""
            if formula_a.startswith("="):
                continue

        try:
            val = int(float(cell_a))
            if 20000000 < val < 30000000:  # yyyymmdd 범위
                return start_row + i
        except (ValueError, TypeError):
            continue

    return start_row + len(values) - 1


def check_duplicate_entries(entries):
    """기존 누적 로그에서 동일 기준일자+공연명 중복 확인.
    중복된 entry의 인덱스 리스트를 반환."""
    source = get_excel_data()
    if not source:
        return []

    df = pd.read_excel(source, sheet_name='일일입력', skiprows=3)
    df['No_num'] = pd.to_numeric(df['No'], errors='coerce')
    log_df = df[df['No_num'] > 100].copy()

    duplicates = []
    for idx, entry in enumerate(entries):
        date_val = int(entry['기준일자'].replace('-', ''))
        perf_name = entry['공연명']
        match = log_df[
            (log_df['No_num'] == date_val) &
            (log_df['공연명'].astype(str).str.strip() == perf_name.strip())
        ]
        if not match.empty:
            duplicates.append(idx)

    return duplicates


def write_daily_entries_to_sharepoint(entries):
    """일일입력 시트 누적 로그 영역에 새 행을 추가.
    방식: 마지막 데이터 행 다음에 N행 insert(shift=Down) → 빈 행에 PATCH.
    이렇게 하면 안내 텍스트/수식 행이 아래로 밀리고 데이터가 확실히 저장됨.
    entries: list of dict
    반환: (success: bool, message: str)
    """
    try:
        drive_id, file_item_id = _get_sharepoint_file_meta()
        token = get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        graph_base = "https://graph.microsoft.com/v1.0"
        base_url = f"{graph_base}/drives/{drive_id}/items/{file_item_id}/workbook"

        # 워크시트 ID 조회
        ws_resp = requests.get(f"{base_url}/worksheets", headers=headers)
        ws_resp.raise_for_status()
        ws_id = None
        for ws in ws_resp.json().get("value", []):
            if ws["name"] == "일일입력":
                ws_id = ws["id"]
                break
        if not ws_id:
            return False, "일일입력 워크시트를 찾을 수 없습니다."

        # 마지막 리터럴 데이터 행 찾기 (수식 행 제외)
        last_row = _find_last_literal_data_row(base_url, headers, ws_id)

        # 쓸 데이터 행 구성 (A~Q, 17열)
        rows = []
        for entry in entries:
            date_str = entry['기준일자'].replace('-', '')  # yyyymmdd
            total_seats = entry['합계좌석']
            total_amount = entry['합계금액']
            open_seats = entry['오픈석']
            occupancy = min(total_seats / open_seats, 1.0) if open_seats > 0 else 0
            unit_price = (total_amount / total_seats) if total_seats > 0 else 0

            row = [
                int(date_str),              # A: 기준일자
                entry['공연명'],            # B: 공연명
                entry.get('공연일', ''),     # C: 공연일
                "'" + entry.get('회차/시각', '') if entry.get('회차/시각') else '',  # D: 회차/시각
                open_seats,                 # E: 오픈석
                entry['유료좌석'],          # F: 유료좌석
                entry['유료금액'],          # G: 유료금액
                entry['예약좌석'],          # H: 예약좌석
                entry['예약금액'],          # I: 예약금액
                entry['무료좌석'],          # J: 무료좌석
                total_seats,                # K: 합계좌석
                total_amount,               # L: 합계금액
                round(occupancy, 4),        # M: 점유율
                0,                          # N: 전일대비(석)
                0,                          # O: 전일대비(원)
                round(unit_price),          # P: 객단가
                "",                         # Q: 중복체크
            ]
            rows.append(row)

        n = len(rows)
        insert_start = last_row + 1
        insert_end = insert_start + n - 1
        address = f"A{insert_start}:Q{insert_end}"

        # Step 1: N행 삽입 (기존 행을 아래로 밀기)
        insert_url = f"{base_url}/worksheets/{ws_id}/range(address='{address}')/insert"
        insert_resp = requests.post(insert_url, headers=headers, json={"shift": "Down"})
        if insert_resp.status_code != 200:
            error_detail = insert_resp.json().get("error", {}).get("message", insert_resp.text[:300])
            return False, f"행 삽입 실패 ({insert_resp.status_code}): {error_detail}"

        # Step 2: 삽입된 빈 행에 데이터 쓰기
        patch_url = f"{base_url}/worksheets/{ws_id}/range(address='{address}')"
        patch_resp = requests.patch(patch_url, headers=headers, json={"values": rows})

        if patch_resp.status_code == 200:
            # 쓰인 값 검증
            written = patch_resp.json().get("values", [])
            written_count = sum(1 for r in written if r[0] and r[1])

            # 캐시 초기화
            load_daily_input.clear()
            load_sales_trend.clear()
            get_base_date.clear()
            download_excel_from_sharepoint.clear()
            return True, f"{written_count}건 저장 완료 (행 {insert_start}~{insert_end})"
        else:
            error_detail = patch_resp.json().get("error", {}).get("message", patch_resp.text[:300])
            return False, f"데이터 쓰기 실패 ({patch_resp.status_code}): {error_detail}"

    except FileNotFoundError as e:
        return False, str(e)
    except Exception as e:
        return False, f"SharePoint 쓰기 실패: {e}"




def find_existing_row(base_url, headers, ws_id, date_int, perf_name, round_time):
    """누적기록(row16~)에서 기준일자+공연명+회차시각 매칭 행 탐색.
    Returns: int(1-based row) or None"""
    import re as _re
    url = f"{base_url}/worksheets/{ws_id}/usedRange"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    addr = data.get("address", "")
    start_row = 1
    if "!" in addr:
        m = _re.search(r'(\d+)', addr.split("!")[1])
        if m:
            start_row = int(m.group(1))

    values = data.get("values", [])
    formulas = data.get("formulas", [])

    for i in range(len(values)):
        row_vals = values[i]
        if len(row_vals) < 4:
            continue
        cell_a = row_vals[0]
        cell_b = str(row_vals[1]).strip() if row_vals[1] else ""
        cell_d = str(row_vals[3]).strip().lstrip("'") if row_vals[3] else ""

        # 수식 행 건너뛰기
        if formulas and i < len(formulas):
            fa = str(formulas[i][0]) if formulas[i][0] else ""
            if fa.startswith("="):
                continue

        try:
            val_a = int(float(cell_a))
        except (ValueError, TypeError):
            continue

        if val_a != date_int:
            continue

        # 공연명 매칭 (contains 양방향)
        perf_s = str(perf_name).strip()
        name_match = (cell_b == perf_s or perf_s in cell_b or cell_b in perf_s)
        if not name_match:
            continue

        # 회차시각 매칭 (빈 값이면 무조건 매칭)
        rt = str(round_time).strip().lstrip("'") if round_time else ""
        if rt and cell_d and rt != cell_d:
            continue

        return start_row + i

    return None


def save_daily_entry(
    date_int, perf_name, perf_date_str, round_time, open_seats,
    paid_seats, paid_amount, rsv_seats, rsv_amount, free_seats,
    prev_seats=0, prev_amount=0,
):
    """일일입력 시트 누적기록에 1행 저장 (UPDATE or INSERT).

    Args:
        date_int: 기준일자 (yyyymmdd int)
        perf_name: 공연명
        perf_date_str: 공연일 문자열 ("2026. 5. 7(목)")
        round_time: 회차/시각 ("19:30")
        open_seats: 오픈석
        paid_seats, paid_amount: 유료좌석, 유료금액
        rsv_seats, rsv_amount: 예약좌석, 예약금액
        free_seats: 무료좌석
        prev_seats, prev_amount: 전일 합계좌석/금액 (전일대비 계산용)

    Returns:
        dict: {status, row, message}
    """
    from datetime import datetime as _dt

    total_seats = paid_seats + rsv_seats + free_seats
    total_amount = paid_amount + rsv_amount
    occupancy = min(total_seats / open_seats, 1.0) if open_seats > 0 else 0
    unit_price = round(total_amount / total_seats) if total_seats > 0 else 0
    diff_seats = total_seats - prev_seats
    diff_amount = total_amount - prev_amount
    now_time = _dt.now().strftime('%H:%M:%S')

    row_data = [
        date_int,                        # A: 기준일자
        perf_name,                       # B: 공연명
        perf_date_str,                   # C: 공연일
        "'" + round_time if round_time else '',  # D: 회차/시각
        open_seats,                      # E: 오픈석
        paid_seats,                      # F: 유료좌석
        paid_amount,                     # G: 유료금액
        rsv_seats,                       # H: 예약좌석
        rsv_amount,                      # I: 예약금액
        free_seats,                      # J: 무료좌석
        total_seats,                     # K: 합계좌석
        total_amount,                    # L: 합계금액
        round(occupancy, 4),             # M: 점유율
        diff_seats,                      # N: 전일대비(석)
        diff_amount,                     # O: 전일대비(원)
        unit_price,                      # P: 객단가
        "",                              # Q: 중복체크
        now_time,                        # R: 갱신시각
    ]

    try:
        drive_id, file_item_id = _get_sharepoint_file_meta()
        token = get_access_token()
        hdrs = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        graph_base = "https://graph.microsoft.com/v1.0"
        base_url = f"{graph_base}/drives/{drive_id}/items/{file_item_id}/workbook"

        # 워크시트 ID
        ws_resp = requests.get(f"{base_url}/worksheets", headers=hdrs)
        ws_resp.raise_for_status()
        ws_id = None
        for ws in ws_resp.json().get("value", []):
            if ws["name"] == "일일입력":
                ws_id = ws["id"]
                break
        if not ws_id:
            return {"status": "error", "row": None, "message": "일일입력 워크시트를 찾을 수 없습니다."}

        # 기존 행 탐색
        existing_row = find_existing_row(base_url, hdrs, ws_id, date_int, perf_name, round_time)

        if existing_row:
            # UPDATE: 기존 행 덮어쓰기
            address = f"A{existing_row}:R{existing_row}"
            patch_url = f"{base_url}/worksheets/{ws_id}/range(address='{address}')"
            resp = requests.patch(patch_url, headers=hdrs, json={"values": [row_data]})
            if resp.status_code == 200:
                _clear_caches()
                return {"status": "updated", "row": existing_row,
                        "message": f"행 {existing_row} 갱신 완료 ({now_time})"}
            else:
                err = resp.json().get("error", {}).get("message", resp.text[:300])
                return {"status": "error", "row": existing_row,
                        "message": f"갱신 실패 ({resp.status_code}): {err}"}
        else:
            # INSERT: 새 행 추가
            last_row = _find_last_literal_data_row(base_url, hdrs, ws_id)
            insert_start = last_row + 1
            address = f"A{insert_start}:R{insert_start}"

            # 행 삽입
            insert_url = f"{base_url}/worksheets/{ws_id}/range(address='{address}')/insert"
            ins_resp = requests.post(insert_url, headers=hdrs, json={"shift": "Down"})
            if ins_resp.status_code != 200:
                err = ins_resp.json().get("error", {}).get("message", ins_resp.text[:300])
                return {"status": "error", "row": None,
                        "message": f"행 삽입 실패 ({ins_resp.status_code}): {err}"}

            # 데이터 쓰기
            patch_url = f"{base_url}/worksheets/{ws_id}/range(address='{address}')"
            resp = requests.patch(patch_url, headers=hdrs, json={"values": [row_data]})
            if resp.status_code == 200:
                _clear_caches()
                return {"status": "inserted", "row": insert_start,
                        "message": f"행 {insert_start} 신규 저장 ({now_time})"}
            else:
                err = resp.json().get("error", {}).get("message", resp.text[:300])
                return {"status": "error", "row": None,
                        "message": f"데이터 쓰기 실패 ({resp.status_code}): {err}"}

    except FileNotFoundError as e:
        return {"status": "error", "row": None, "message": str(e)}
    except Exception as e:
        return {"status": "error", "row": None, "message": f"저장 실패: {e}"}


def _clear_caches():
    """모든 데이터 캐시 초기화"""
    try:
        load_daily_input.clear()
        load_sales_trend.clear()
        get_base_date.clear()
        download_excel_from_sharepoint.clear()
        load_performance_master.clear()
    except Exception:
        pass

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