from django.urls import path
from . import views

urlpatterns = [
    path("", views.mushaf_view, name="mushaf"),
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("progress/", views.progress_view, name="progress"),
    path("api/question/", views.quiz_question, name="quiz_question"),
    path("api/answer/", views.quiz_answer, name="quiz_answer"),
    path("api/reset/", views.reset_progress, name="reset_progress"),
]
