from django.contrib.auth.models import Group
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from .models import Movimiento, Recuperado


@receiver(post_save, sender=Recuperado)
def crear_movimiento_recuperado(sender, instance, created, **kwargs):
    if not created:
        return
    Movimiento.objects.create(
        tipo='recuperado',
        medicamento=instance.medicamento,
        cantidad=instance.cantidad,
        movil=instance.movil_origen,
        descripcion=f'Recuperado del móvil {instance.movil_origen} hacia inventario',
    )


@receiver(post_migrate)
def crear_grupos_predeterminados(sender, **kwargs):
    if sender.name != 'core':
        return
    for nombre in ['Superuser', 'Empleado', 'Espectador']:
        Group.objects.get_or_create(name=nombre)
