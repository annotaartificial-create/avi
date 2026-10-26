from django.urls import path
from . import views

app_name = 'payment'

urlpatterns = [
    path('deposit/initiate/', views.initiate_deposit_view, name='initiate_deposit'),
    path('deposit/status/<str:reference>/', views.deposit_status_view, name='deposit_status'),
    path('deposit/check-status/<str:reference>/', views.check_deposit_status_view, name='check_deposit_status'),
    path('webhook/<str:provider_name>/', views.payment_webhook_view, name='webhook'),
]
