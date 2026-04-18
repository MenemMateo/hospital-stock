from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Movil(models.Model):
    nombre = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    @property
    def stock_items(self):
        return self.stockmovil_set.count()

    @property
    def has_expired_stock(self):
        return self.stockmovil_set.filter(fecha_vencimiento__lt=timezone.now().date()).exists()

    @property
    def has_warning_stock(self):
        threshold = settings.LOW_STOCK_THRESHOLD
        warning_date = timezone.now().date() + timedelta(days=settings.EXPIRATION_WARNING_DAYS)
        return self.stockmovil_set.filter(
            models.Q(cantidad__lt=threshold) |
            models.Q(fecha_vencimiento__lte=warning_date, fecha_vencimiento__gte=timezone.now().date())
        ).exists()


class Medicamento(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text='Precio unitario en la moneda local')

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    @property
    def precio_formateado(self):
        if self.precio_unitario is not None:
            return f'${self.precio_unitario:.2f}'
        return 'Sin precio'


class Inventario(models.Model):
    medicamento = models.ForeignKey(Medicamento, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField(default=0)
    fecha_vencimiento = models.DateField()

    class Meta:
        unique_together = ('medicamento', 'fecha_vencimiento')
        ordering = ['fecha_vencimiento']

    def __str__(self):
        return f'{self.medicamento} - {self.cantidad} unidades ({self.fecha_vencimiento})'

    def clean(self):
        if self.cantidad < 0:
            raise ValidationError('Cantidad no puede ser negativa.')

    @property
    def es_vencido(self):
        return self.fecha_vencimiento < timezone.now().date()

    @property
    def vence_pronto(self):
        return 0 <= (self.fecha_vencimiento - timezone.now().date()).days <= settings.EXPIRATION_WARNING_DAYS

    @property
    def low_stock_threshold(self):
        return settings.LOW_STOCK_THRESHOLD

    @property
    def alert_label(self):
        if self.es_vencido:
            return 'Vencido'
        if self.vence_pronto:
            return 'Próximo'
        if self.cantidad < self.low_stock_threshold:
            return 'Bajo'
        return 'OK'


class StockMovil(models.Model):
    movil = models.ForeignKey(Movil, on_delete=models.CASCADE)
    medicamento = models.ForeignKey(Medicamento, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField(default=0)
    fecha_vencimiento = models.DateField()

    class Meta:
        unique_together = ('movil', 'medicamento', 'fecha_vencimiento')
        ordering = ['movil', 'medicamento', 'fecha_vencimiento']

    def __str__(self):
        return f'{self.movil} - {self.medicamento}: {self.cantidad}'

    def clean(self):
        if self.cantidad < 0:
            raise ValidationError('Cantidad no puede ser negativa.')

    @property
    def es_vencido(self):
        return self.fecha_vencimiento < timezone.now().date()

    @property
    def vence_pronto(self):
        return 0 <= (self.fecha_vencimiento - timezone.now().date()).days <= settings.EXPIRATION_WARNING_DAYS

    @property
    def low_stock_threshold(self):
        return settings.LOW_STOCK_THRESHOLD

    @property
    def alerta(self):
        if self.es_vencido:
            return 'Vencido'
        if self.vence_pronto or self.cantidad < self.low_stock_threshold:
            return 'Alerta'
        return 'OK'


class Recuperado(models.Model):
    medicamento = models.ForeignKey(Medicamento, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField()
    movil_origen = models.ForeignKey(Movil, on_delete=models.SET_NULL, null=True, blank=True)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        origen = self.movil_origen.nombre if self.movil_origen else 'Desconocido'
        return f'{self.cantidad} {self.medicamento} recuperado de {origen} el {self.fecha:%Y-%m-%d}'


class Vencido(models.Model):
    medicamento = models.ForeignKey(Medicamento, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField()
    movil_origen = models.ForeignKey(Movil, on_delete=models.SET_NULL, null=True, blank=True)
    fecha_vencimiento = models.DateField()
    fecha_descarte = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-fecha_descarte']

    def __str__(self):
        origen = self.movil_origen.nombre if self.movil_origen else 'Desconocido'
        return f'{self.cantidad} {self.medicamento} (vencido {self.fecha_vencimiento}) descartado de {origen}'


class Movimiento(models.Model):
    TIPO_CHOICES = [
        ('entrada', 'Entrada'),
        ('salida', 'Salida'),
        ('ajuste', 'Ajuste'),
        ('consumo', 'Consumo'),
        ('recuperado', 'Recuperado'),
        ('vencido', 'Vencido'),
    ]
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    medicamento = models.ForeignKey(Medicamento, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField()
    movil = models.ForeignKey(Movil, on_delete=models.SET_NULL, null=True, blank=True)
    fecha = models.DateTimeField(default=timezone.now)
    descripcion = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        movil_label = self.movil.nombre if self.movil else 'Inventario'
        return f'[{self.fecha:%Y-%m-%d %H:%M}] {self.tipo} {self.cantidad} {self.medicamento} ({movil_label})'


class Compra(models.Model):
    medicamento = models.ForeignKey(Medicamento, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    descuento = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text='Descuento aplicado al total')
    total = models.DecimalField(max_digits=12, decimal_places=2)
    movil = models.ForeignKey(Movil, on_delete=models.SET_NULL, null=True, blank=True)
    fecha = models.DateTimeField(default=timezone.now)
    sin_precio_definido = models.BooleanField(default=False)
    contar_como_gasto = models.BooleanField(default=True, help_text='Marcar para incluir en cálculo de gastos')
    motivo_sin_gasto = models.CharField(max_length=255, blank=True, null=True, help_text='Motivo si no se cuenta como gasto')

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'Compra'
        verbose_name_plural = 'Compras'

    def __str__(self):
        movil_label = self.movil.nombre if self.movil else 'Inventario'
        return f'Compra: {self.cantidad} {self.medicamento} en {movil_label} - ${self.total:.2f}'

    def save(self, *args, **kwargs):
        # Calcular el total automáticamente: (cantidad * precio_unitario) - descuento
        subtotal = self.cantidad * self.precio_unitario
        self.total = subtotal - self.descuento
        super().save(*args, **kwargs)

    @property
    def precio_formateado(self):
        return f'${self.precio_unitario:.2f}'

    @property
    def total_formateado(self):
        return f'${self.total:.2f}'
    
    @property
    def descuento_formateado(self):
        return f'${self.descuento:.2f}'
    
    @property
    def subtotal_formateado(self):
        subtotal = self.cantidad * self.precio_unitario
        return f'${subtotal:.2f}'


class ConfiguracionGastos(models.Model):
    """Configuración de límites y alertas de gastos"""
    limite_mensual = models.DecimalField(max_digits=12, decimal_places=2, default=10000, help_text='Límite máximo de gastos mensuales')
    porcentaje_alerta = models.IntegerField(default=80, help_text='Porcentaje del límite para mostrar alerta (0-100)')
    
    class Meta:
        verbose_name = 'Configuración de Gastos'
        verbose_name_plural = 'Configuración de Gastos'
    
    def __str__(self):
        return f'Límite: ${self.limite_mensual:.2f} - Alerta: {self.porcentaje_alerta}%'
    
    @classmethod
    def get_configuracion(cls):
        """Obtener la única instancia de configuración, crear si no existe"""
        config, created = cls.objects.get_or_create(pk=1)
        return config
    
    def save(self, *args, **kwargs):
        # Asegurar que solo existe un registro
        self.pk = 1
        super().save(*args, **kwargs)
