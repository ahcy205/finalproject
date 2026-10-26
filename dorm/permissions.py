from rest_framework.permissions import BasePermission, SAFE_METHODS

class IsAuthorOrAdmin(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_staff or obj.author == request.user

class IsInquiryUserOrAdmin(BasePermission):
    """문의는 작성자 본인과 관리자만 볼 수 있다 (조회 요청도 공개하지 않음)."""
    def has_object_permission(self, request, view, obj):
        user = request.user
        return bool(user and user.is_authenticated) and (user.is_staff or obj.user == user)