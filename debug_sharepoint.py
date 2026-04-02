"""
SharePoint Graph API 경로 탐색 스크립트
─────────────────────────────────────
단계별로 API를 호출하여 올바른 파일 경로를 찾습니다.
사용법: python debug_sharepoint.py
"""

import requests
import json
import sys
import os

try:
    import tomllib
except ImportError:
    import tomli as tomllib

# ── .streamlit/secrets.toml에서 설정 로드 ──
SECRETS_PATH = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
with open(SECRETS_PATH, "rb") as f:
    secrets = tomllib.load(f)

azure = secrets["azure"]
TENANT_ID = azure["tenant_id"]
CLIENT_ID = azure["client_id"]
CLIENT_SECRET = azure["client_secret"]
SITE_HOSTNAME = "gscaltexyeulmaru.sharepoint.com"
SITE_PATH = azure.get("site_name", "daxteam")
TARGET_FILE = azure.get("file_name", "yeulmaru_dashboard_db_v1.xlsx")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def get_token(client_secret: str) -> str:
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    resp = requests.post(url, data={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    })
    if resp.status_code != 200:
        print(f"[FAIL] 토큰 발급 실패 ({resp.status_code})")
        print(resp.text)
        sys.exit(1)
    token = resp.json()["access_token"]
    print("[OK] 액세스 토큰 발급 성공")
    return token


def api_get(url: str, headers: dict, label: str):
    """GET 요청 + 결과 출력 헬퍼"""
    print(f"\n{'='*60}")
    print(f"[STEP] {label}")
    print(f"  GET {url}")
    resp = requests.get(url, headers=headers)
    print(f"  Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"  Error: {resp.text[:500]}")
        return None
    data = resp.json()
    return data


def main():
    token = get_token(CLIENT_SECRET)
    headers = {"Authorization": f"Bearer {token}"}

    # ── Step 1: 사이트 ID 조회 ──
    # 방법 A: /sites/{hostname}:/sites/{path}
    site_data = api_get(
        f"{GRAPH_BASE}/sites/{SITE_HOSTNAME}:/sites/{SITE_PATH}",
        headers,
        f"사이트 조회: /sites/{SITE_HOSTNAME}:/sites/{SITE_PATH}"
    )

    if not site_data:
        # 방법 B: hostname만으로 루트 사이트 조회
        print("\n[INFO] 사이트 경로 실패 → 루트 사이트 시도")
        site_data = api_get(
            f"{GRAPH_BASE}/sites/{SITE_HOSTNAME}",
            headers,
            "루트 사이트 조회"
        )

    if not site_data:
        # 방법 C: 사이트 검색
        print("\n[INFO] 루트도 실패 → 사이트 검색 시도")
        search_data = api_get(
            f"{GRAPH_BASE}/sites?search={SITE_PATH}",
            headers,
            f"사이트 검색: ?search={SITE_PATH}"
        )
        if search_data and search_data.get("value"):
            print("\n  [결과] 검색된 사이트 목록:")
            for s in search_data["value"]:
                print(f"    - id: {s['id']}")
                print(f"      name: {s.get('name', 'N/A')}")
                print(f"      webUrl: {s.get('webUrl', 'N/A')}")
            site_data = search_data["value"][0]
        else:
            print("\n[FAIL] 사이트를 찾을 수 없습니다. SITE_PATH를 확인하세요.")
            sys.exit(1)

    site_id = site_data["id"]
    print(f"\n  [결과] site_id = {site_id}")
    print(f"         displayName = {site_data.get('displayName', 'N/A')}")
    print(f"         webUrl = {site_data.get('webUrl', 'N/A')}")

    # ── Step 2: 드라이브(문서 라이브러리) 목록 조회 ──
    drives_data = api_get(
        f"{GRAPH_BASE}/sites/{site_id}/drives",
        headers,
        "드라이브(문서 라이브러리) 목록 조회"
    )

    if not drives_data or not drives_data.get("value"):
        print("[FAIL] 드라이브 목록을 가져올 수 없습니다.")
        sys.exit(1)

    drives = drives_data["value"]
    print(f"\n  [결과] 드라이브 {len(drives)}개 발견:")
    for d in drives:
        print(f"    - id: {d['id']}")
        print(f"      name: {d.get('name', 'N/A')}")
        print(f"      webUrl: {d.get('webUrl', 'N/A')}")

    # ── Step 3: 각 드라이브에서 파일 검색 ──
    found_items = []

    for d in drives:
        drive_id = d["id"]
        drive_name = d.get("name", "N/A")

        # 3-a: search API
        search_data = api_get(
            f"{GRAPH_BASE}/drives/{drive_id}/root/search(q='{TARGET_FILE}')",
            headers,
            f"드라이브 '{drive_name}' 에서 '{TARGET_FILE}' 검색"
        )
        if search_data and search_data.get("value"):
            for item in search_data["value"]:
                print(f"    [HIT] {item.get('name')} | id={item['id']}")
                print(f"           webUrl: {item.get('webUrl', 'N/A')}")
                parent = item.get("parentReference", {})
                print(f"           path: {parent.get('path', 'N/A')}")
                found_items.append({
                    "drive_id": drive_id,
                    "drive_name": drive_name,
                    "item_id": item["id"],
                    "name": item.get("name"),
                    "webUrl": item.get("webUrl"),
                    "downloadUrl": item.get("@microsoft.graph.downloadUrl"),
                    "path": parent.get("path"),
                })

    if not found_items:
        # 3-b: 루트 children 탐색 (파일명에 한글이 있으면 search가 안 될 수 있음)
        print("\n[INFO] search로 못 찾음 → 각 드라이브 루트 파일 목록 확인")
        for d in drives:
            drive_id = d["id"]
            drive_name = d.get("name", "N/A")
            children = api_get(
                f"{GRAPH_BASE}/drives/{drive_id}/root/children",
                headers,
                f"드라이브 '{drive_name}' 루트 파일 목록"
            )
            if children and children.get("value"):
                print(f"    루트 항목 {len(children['value'])}개:")
                for item in children["value"]:
                    kind = "📁" if item.get("folder") else "📄"
                    print(f"      {kind} {item.get('name')} | id={item['id']}")
                    if item.get("name") == TARGET_FILE:
                        found_items.append({
                            "drive_id": drive_id,
                            "drive_name": drive_name,
                            "item_id": item["id"],
                            "name": item.get("name"),
                            "downloadUrl": item.get("@microsoft.graph.downloadUrl"),
                        })

    # ── Step 4: 결과 요약 ──
    print(f"\n{'='*60}")
    print("[SUMMARY]")
    if found_items:
        print(f"  파일 {len(found_items)}개 발견!\n")
        for i, f in enumerate(found_items, 1):
            print(f"  [{i}] {f['name']}")
            print(f"      drive: {f['drive_name']} ({f['drive_id']})")
            print(f"      item_id: {f['item_id']}")
            print(f"      path: {f.get('path', 'N/A')}")
            if f.get("downloadUrl"):
                print(f"      downloadUrl: 있음 (바로 다운로드 가능)")

        # 다운로드 테스트
        best = found_items[0]
        print(f"\n  다운로드 테스트: drives/{best['drive_id']}/items/{best['item_id']}/content")
        dl_resp = requests.get(
            f"{GRAPH_BASE}/drives/{best['drive_id']}/items/{best['item_id']}/content",
            headers=headers,
            allow_redirects=False,
        )
        print(f"  Status: {dl_resp.status_code}")
        if dl_resp.status_code in (200, 302):
            print("  [OK] 다운로드 가능 확인!")
        else:
            print(f"  [WARN] {dl_resp.text[:300]}")

        # 코드에 적용할 값 출력
        print(f"\n{'='*60}")
        print("[ACTION] data_loader.py에 적용할 값:")
        print(f'  SITE_ID  = "{site_id}"')
        print(f'  DRIVE_ID = "{best["drive_id"]}"')
        print(f'  ITEM_ID  = "{best["item_id"]}"')
        print(f"  다운로드 URL: {GRAPH_BASE}/drives/{best['drive_id']}/items/{best['item_id']}/content")
    else:
        print("  파일을 찾지 못했습니다.")
        print("  확인사항:")
        print(f"    1. 파일명이 정확한지: '{TARGET_FILE}'")
        print(f"    2. 사이트 경로가 맞는지: /sites/{SITE_PATH}")
        print("    3. 앱 권한에 Sites.Read.All이 있는지")
        print("    4. 파일이 하위 폴더에 있다면 children을 재귀 탐색 필요")


if __name__ == "__main__":
    main()
