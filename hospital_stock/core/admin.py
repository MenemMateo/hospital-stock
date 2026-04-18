from django.contrib import admin
from django.utils.html import format_html

from .models import Inventario, Medicamento, Movimiento, Movil, Recuperado, StockMovil, Vencido, Compra, ConfiguracionGastos


class StockMovilInline(admin.TabularInline):
    model = StockMovil
    extra = 0


@admin.register(Movil)
class MovilAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'stock_items', 'alert_level')
    search_fields = ('nombre',)
    inlines = [StockMovilInline]

    def stock_items(self, obj):
        return obj.stockmovil_set.count()

    def alert_level(self, obj):
        if obj.has_expired_stock:
            return format_html('<span style="color:red;">Vencido</span>')
        if obj.has_warning_stock:
            return format_html('<span style="color:orange;">Alerta</span>')
        return format_html('<span style="color:green;">OK</span>')


@admin.register(Medicamento)
class MedicamentoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'precio_formateado')
    search_fields = ('nombre',)


@admin.register(Inventario)
class InventarioAdmin(admin.ModelAdmin):
    list_display = ('medicamento', 'cantidad', 'fecha_vencimiento', 'status_label')
    list_filter = ('medicamento', 'fecha_vencimiento')
    search_fields = ('medicamento__nombre',)

    def status_label(self, obj):
        if obj.es_vencido:
            return format_html('<span style="color:red;">Vencido</span>')
        if obj.vence_pronto:
            return format_html('<span style="color:orange;">Próximo</span>')
        return format_html('<span style="color:green;">OK</span>')
    status_label.short_description = 'Estado'


@admin.register(StockMovil)
class StockMovilAdmin(admin.ModelAdmin):
    list_display = ('movil', 'medicamento', 'cantidad', 'fecha_vencimiento', 'status_label')
    list_filter = ('movil', 'medicamento', 'fecha_vencimiento')
    search_fields = ('movil__nombre', 'medicamento__nombre')

    def status_label(self, obj):
        if obj.es_vencido:
            return format_html('<span style="color:red;">Vencido</span>')
        if obj.vence_pronto or obj.cantidad < obj.low_stock_threshold:
            return format_html('<span style="color:orange;">Alerta</span>')
        return format_html('<span style="color:green;">OK</span>')
    status_label.short_description = 'Estado'


@admin.register(Recuperado)
class RecuperadoAdmin(admin.ModelAdmin):
    list_display = ('medicamento', 'cantidad', 'movil_origen', 'fecha')
    list_filter = ('medicamento', 'movil_origen')
    search_fields = ('medicamento__nombre', 'movil_origen__nombre')


@admin.register(Vencido)
class VencidoAdmin(admin.ModelAdmin):
    list_display = ('medicamento', 'cantidad', 'fecha_vencimiento', 'movil_origen', 'fecha_descarte')
    list_filter = ('medicamento', 'movil_origen', 'fecha_descarte')
    search_fields = ('medicamento__nombre', 'movil_origen__nombre')


@admin.register(Movimiento)
class MovimientoAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'medicamento', 'cantidad', 'movil', 'fecha', 'descripcion')
    list_filter = ('tipo', 'medicamento', 'movil', 'fecha')
    search_fields = ('medicamento__nombre', 'movil__nombre', 'descripcion')


@admin.register(Compra)
class CompraAdmin(admin.ModelAdmin):
    list_display = ('medicamento', 'cantidad', 'precio_formateado', 'descuento_formateado', 'total_formateado', 'movil', 'fecha', 'contar_como_gasto')
    list_filter = ('medicamento', 'movil', 'fecha', 'sin_precio_definido', 'contar_como_gasto')
    search_fields = ('medicamento__nombre', 'movil__nombre')
    readonly_fields = ('total',)
    fieldsets = (
        ('Medicamento', {
            'fields': ('medicamento', 'cantidad', 'precio_unitario', 'descuento', 'total')
        }),
        ('Ubicación', {
            'fields': ('movil',),
            'description': 'Dejar vacío para indicar que es una compra al inventario'
        }),
        ('Gasto', {
            'fields': ('contar_como_gasto', 'motivo_sin_gasto'),
            'description': 'Si no cuenta como gasto, debe proporcionar un motivo'
        }),
        ('Información', {
            'fields': ('fecha', 'sin_precio_definido'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ConfiguracionGastos)
class ConfiguracionGastosAdmin(admin.ModelAdmin):
    list_display = ('limite_mensual', 'porcentaje_alerta')
    fieldsets = (
        ('Límites de Gastos', {
            'fields': ('limite_mensual', 'porcentaje_alerta')
        }),
    )
    
    def has_add_permission(self, request):
        # Solo permitir un registro
        return not ConfiguracionGastos.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # No permitir eliminar
        return False
