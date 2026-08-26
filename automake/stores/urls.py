from django.urls import path
from . import views

urlpatterns = [
    path('list', views.StoreListView.as_view(), name='store-list'),
    path('<int:store_id>/', views.StoreDetailView.as_view(), name='store-detail'),
]
