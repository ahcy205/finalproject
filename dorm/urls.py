from django.urls import path

from .views import login_api, signup_api, apply_dorm_api

app_name = 'dorm'

urlpatterns = [
    path('login/', login_api, name='login'),
    path('signup/', signup_api, name='signup'),
    path('dorm_apply/', apply_dorm_api, name='dorm_apply'),
]