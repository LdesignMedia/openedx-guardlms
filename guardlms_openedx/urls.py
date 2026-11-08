from django.urls import path
from . import views

app_name = "guardlms"
urlpatterns = [
    path("bootstrap.js", views.bootstrap, name="bootstrap"),
    path("", views.index, name="index"),
    path("connect", views.connect, name="connect"),
    path("callback", views.callback, name="callback"),
    path("disconnect", views.disconnect, name="disconnect"),
    path("push", views.push_now, name="push"),
    path("preferences", views.preferences, name="preferences"),
    path("preview", views.preview, name="preview"),
    path("browser-config", views.browser_config, name="browser-config"),
]
