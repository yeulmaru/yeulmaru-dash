"""장르1 분류 9단계 로직 (Phase 2)"""

KIDS_KW = [
    '어린이', '키즈', 'kids', '아이', '꼬마', '동심',
    '가족극', '가족뮤지컬',
    '두들팝', '알사탕', '캔터빌유령', '핑크퐁', '그래비티 스페이스', '폴리팝', '넘버블록스',
    '아이야한글용사', '하츄핑', '베베핀', '헬로 카봇', '카봇',
]

ADULT_MUSICAL_KW = [
    '지킬앤하이드', '시카고', '맘마미아', '오페라의유령', '레미제라블', '위키드',
    '캣츠', '노트르담드파리', '라이온킹', '렌트', '엘리자벳', '프랑켄슈타인',
    '모차르트', '데스노트', '젠틀맨스가이드', '킹키부츠', '빨래', '팬텀', '스위니토드',
]

CLASSIC_KW = [
    '국제음악제', '오페라', '오케스트라', '음악제', '연주회', '극동방송',
    '리사이틀', '심포니', '음악회', '독주회', '신춘음악회', '송년음악회', '신년음악회',
    '손양원', '여수음악제', '여수예술제', '여순사건', '여수심포니', '여수교원교향악단',
    '퀸텟', '콰르텟', '실내악', '앙상블',
]

OVERRIDES = {
    '아파나도르': '발레/연극',
    '페인터즈': '발레/연극',
}


def classify_genre1(row):
    """공연 행에서 장르1을 분류. row는 dict-like (Series or dict).

    Returns:
        str | None: 장르1 값. 비공연/취소 시 None.
    """
    status = row.get('상태', '정상')
    if status == '취소공연':
        return None

    biz = str(row.get('사업구분', '')).strip()
    if biz != '공연':
        return None

    name = str(row.get('공연명', '')).strip() if row.get('공연명') else ''

    # Step 3: 어린이 화이트리스트
    if any(kw in name for kw in KIDS_KW):
        return '어린이·가족'

    # Step 4: 성인 뮤지컬 블랙리스트
    detail = str(row.get('세부장르', '')).strip() if row.get('세부장르') else ''
    if '뮤지컬' in detail and any(kw in name for kw in ADULT_MUSICAL_KW):
        return '뮤지컬'

    # Step 5: 클래식 키워드
    if any(kw in name for kw in CLASSIC_KW):
        return '클래식'

    # Step 6: 대중 키워드
    if '마술' in name or '콘서트' in name:
        return '대중'

    # Step 7: 기타 키워드
    if 'week' in name.lower() or '위크' in name:
        return '기타'

    # Step 8: 개별 오버라이드
    for kw, genre in OVERRIDES.items():
        if kw in name:
            return genre

    # Step 9: 세부장르 기본 매핑
    d = detail.split('(')[0].strip()
    if d in ('클래식',):
        return '클래식'
    if d in ('뮤지컬',):
        return '뮤지컬'
    if d in ('발레', '연극', '무용'):
        return '발레/연극'
    if d in ('콘서트', '복합', '대중'):
        return '대중'
    return '기타'
