import plotly.graph_objects as go

COLORS = {
    'primary': '#0FFD02',      # 네온 그린 (강조)
    'secondary': '#00B2FF',    # 블루
    'danger': '#FF4B4B',       # 빨강 (지출/적자)
    'neutral': '#636EFA',      # 기본
    'bg': '#0E1117',           # 다크 배경
    'card_bg': '#1E1E1E',      # 카드 배경
    'text': '#FAFAFA',         # 텍스트
}

CHART_LAYOUT = dict(
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(color='#FAFAFA', family='Pretendard, sans-serif'),
    margin=dict(l=20, r=20, t=40, b=20),
)

def apply_common_layout(fig):
    """
    Plotly Figure(fig)에 공통 테마(배경 투명, 폰트 색상, 여백 등)를 적용하여 반환합니다.
    """
    fig.update_layout(**CHART_LAYOUT)
    return fig
