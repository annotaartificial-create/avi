from django.urls import path
from . import views

app_name = 'engine'

urlpatterns = [
    path('', views.game_view, name='game'),
    path('api/state/', views.api_game_state, name='api_state'),
    path('api/bet/place/', views.api_place_bet, name='api_place_bet'),
    path('api/bet/cashout/', views.api_cashout, name='api_cashout'),
]
