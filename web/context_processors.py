"""모든 화면에서 쓰는 값 (settings.TEMPLATES의 context_processors에 등록)."""

# 상단 메뉴에서 강조할 묶음. 화면 이름(url name) → 묶음
NAV_SECTIONS = {
    'home': 'home',
    'outside': 'life', 'check_in': 'life', 'apply_success': 'life', 'menu': 'life', 'bus': 'life', 'acc': 'life',
    'guide': 'guide', 'info': 'guide', 'rules': 'guide', 'chatbot': 'guide',
    'community': 'community', 'notice': 'community', 'notice_detail': 'community', 'notice_create': 'community',
    'notice_update': 'community', 'notice_delete': 'community', 'community_home': 'community',
    'community_detail': 'community', 'community_create': 'community', 'community_update': 'community',
    'community_delete': 'community',
    'mypage': 'mypage', 'inquiry_detail': 'mypage',
    'dorminfo': 'staff', 'outside_manage': 'staff', 'outing_info': 'staff', 'reward_penalty': 'staff',
}


def nav(request):
    match = getattr(request, 'resolver_match', None)
    name = match.url_name if match else None
    return {'nav_section': NAV_SECTIONS.get(name, '')}
