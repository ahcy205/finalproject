from django.contrib import admin
from .models import (
    Dorm,
    OutingApply,
    Notice,
    Post,
    Comment,
    UserProfile,
    Inquiry,
    InquiryAnswer,
    Like,
)

admin.site.register(Dorm)
admin.site.register(OutingApply)
admin.site.register(Notice)
admin.site.register(Post)
admin.site.register(Comment)
admin.site.register(UserProfile)
admin.site.register(Inquiry)
admin.site.register(InquiryAnswer)
admin.site.register(Like)