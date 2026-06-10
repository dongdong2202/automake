from django.urls import path
from .views import SimulatorView

app_name = 'simulator'

urlpatterns = [
    path('', SimulatorView.as_view(), name='index'),
]
