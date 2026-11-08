from django.urls import include, path
urlpatterns = [path('guardlms/', include('guardlms_openedx.urls'))]
