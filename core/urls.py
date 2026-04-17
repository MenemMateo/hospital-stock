from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('movil/<int:pk>/', views.movil_detail, name='movil_detail'),
    path('inventario/', views.inventario_list, name='inventario_list'),
    path('inventario/agregar-medicamento/', views.add_medicamento, name='add_medicamento'),
    path('inventario/agregar-inventario/', views.add_inventario, name='add_inventario'),
    path('usuarios/crear/', views.create_user, name='create_user'),
    path('recuperados/', views.recuperados_list, name='recuperados_list'),
    path('recuperados/<int:pk>/agregar/', views.agregar_desde_recuperados, name='agregar_desde_recuperados'),
    path('vencidos/', views.vencidos_list, name='vencidos_list'),
    path('movimientos/', views.movimientos_list, name='movimientos_list'),
    path('stock/<int:pk>/descartar/', views.descartar_stock_item, name='descartar_stock_item'),
    path('movil/agregar/', views.add_movil, name='add_movil'),
    path('stock/<int:pk>/editar/', views.edit_stock_item, name='edit_stock_item'),
    path('movil/<int:pk>/transferir/', views.transferir_stock, name='transferir_stock'),
    path('movil/<int:pk>/ajustar/', views.ajustar_stock, name='ajustar_stock'),
    path('medicamento/<int:pk>/editar-precio/', views.editar_precio, name='editar_precio'),
    path('gastos/', views.gastos_list, name='gastos_list'),
    path('gastos/actualizar-limites/', views.actualizar_limites_gastos, name='actualizar_limites_gastos'),
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
]
