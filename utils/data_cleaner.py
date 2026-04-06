"""데이터 정제 함수 (Phase 2)"""
import re

from utils.schema import GENRE_TYPO_FIX, CANCEL_KEYWORDS


def normalize_year(val):
    """'2012년' 등 문자열 → 2012 정수. 변환 불가 시 None."""
    if val is None:
        return None
    s = re.sub(r'\D', '', str(val).split('.')[0])
    if s and 2000 <= int(s) <= 2030:
        return int(s)
    return None


def fix_genre_typo(val):
    """세부장르 오타 교정."""
    if val is None:
        return val
    s = str(val).strip()
    return GENRE_TYPO_FIX.get(s, s)


def is_cancel_row(row):
    """행의 분류 필드에 취소/연기 키워드가 있으면 True."""
    check_fields = ['세부장르', '사업구분', '공연구분', '시간']
    for f in check_fields:
        v = row.get(f)
        if v and any(kw in str(v) for kw in CANCEL_KEYWORDS):
            return True
    return False
