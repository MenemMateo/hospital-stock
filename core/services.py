from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Inventario, Movimiento, Recuperado, StockMovil, Vencido, Compra


def log_movimiento(tipo, medicamento, cantidad, movil=None, descripcion=''):
    return Movimiento.objects.create(
        tipo=tipo,
        medicamento=medicamento,
        cantidad=cantidad,
        movil=movil,
        descripcion=descripcion,
    )


def transferir_stock_a_movil(movil, medicamento, cantidad, fecha_vencimiento):
    if cantidad <= 0:
        raise ValidationError('Cantidad debe ser mayor que cero.')

    with transaction.atomic():
        inventario = Inventario.objects.filter(
            medicamento=medicamento,
            fecha_vencimiento=fecha_vencimiento,
        ).first()
        if not inventario or inventario.cantidad < cantidad:
            raise ValidationError('No hay suficiente stock en inventario para ese medicamento y fecha.')

        inventario.cantidad -= cantidad
        inventario.full_clean()
        inventario.save()

        stock, _ = StockMovil.objects.get_or_create(
            movil=movil,
            medicamento=medicamento,
            fecha_vencimiento=fecha_vencimiento,
            defaults={'cantidad': 0},
        )
        stock.cantidad += cantidad
        stock.full_clean()
        stock.save()

        log_movimiento(
            tipo='entrada',
            medicamento=medicamento,
            cantidad=cantidad,
            movil=movil,
            descripcion=f'Transferido desde inventario a {movil.nombre}',
        )
        return stock


def agregar_stock_movil(stock, cantidad, desde_inventario=True):
    if cantidad <= 0:
        raise ValidationError('Cantidad debe ser mayor que cero.')

    with transaction.atomic():
        if desde_inventario:
            inventario = Inventario.objects.filter(
                medicamento=stock.medicamento,
                fecha_vencimiento=stock.fecha_vencimiento,
            ).first()
            if not inventario or inventario.cantidad < cantidad:
                raise ValidationError('No hay suficiente stock en inventario para ese medicamento y fecha.')
            inventario.cantidad -= cantidad
            inventario.full_clean()
            inventario.save()
            descripcion = f'Agregado desde inventario a {stock.movil.nombre}'
        else:
            # Crear registro de compra cuando se agrega stock externo
            precio_unitario = stock.medicamento.precio_unitario or 0
            sin_precio = stock.medicamento.precio_unitario is None
            Compra.objects.create(
                medicamento=stock.medicamento,
                cantidad=cantidad,
                precio_unitario=precio_unitario,
                movil=stock.movil,
                sin_precio_definido=sin_precio,
            )
            descripcion = f'Agregado externo a {stock.movil.nombre}'

        stock.cantidad += cantidad
        stock.full_clean()
        stock.save()

        log_movimiento(
            tipo='entrada',
            medicamento=stock.medicamento,
            cantidad=cantidad,
            movil=stock.movil,
            descripcion=descripcion,
        )
        return stock


def ajustar_stock_movimiento(stock, cantidad_deseada, enviar_recuperado=False):
    if cantidad_deseada < 0:
        raise ValidationError('Cantidad deseada no puede ser negativa.')

    with transaction.atomic():
        actual = stock.cantidad

        if actual == cantidad_deseada:
            log_movimiento(
                tipo='ajuste',
                medicamento=stock.medicamento,
                cantidad=0,
                movil=stock.movil,
                descripcion='Ajuste sin cambios',
            )
            return stock

        if actual < cantidad_deseada:
            faltante = cantidad_deseada - actual
            inventarios = Inventario.objects.filter(medicamento=stock.medicamento, cantidad__gt=0).order_by('fecha_vencimiento')
            total_disponible = inventarios.aggregate(total=Sum('cantidad'))['total'] or 0
            if total_disponible < faltante:
                raise ValidationError('No hay suficiente stock en inventario para completar el ajuste.')
            restante = faltante
            for inventario in inventarios:
                if restante == 0:
                    break
                mover = min(inventario.cantidad, restante)
                inventario.cantidad -= mover
                inventario.full_clean()
                inventario.save()
                restante -= mover
            stock.cantidad = cantidad_deseada
            stock.full_clean()
            stock.save()
            log_movimiento(
                tipo='entrada',
                medicamento=stock.medicamento,
                cantidad=faltante,
                movil=stock.movil,
                descripcion=f'Ajuste positivo a {cantidad_deseada} unidades',
            )
            return stock

        exceso = actual - cantidad_deseada
        stock.cantidad = cantidad_deseada
        stock.full_clean()
        stock.save()
        descripcion = f'Ajuste negativo de {exceso} unidades'
        if enviar_recuperado:
            Recuperado.objects.create(
                medicamento=stock.medicamento,
                cantidad=exceso,
                movil_origen=stock.movil,
            )
            descripcion += ' y enviado a recuperados'
        log_movimiento(
            tipo='ajuste',
            medicamento=stock.medicamento,
            cantidad=exceso,
            movil=stock.movil,
            descripcion=descripcion,
        )
        return stock


def ajustar_stock_movil(movil, medicamento, cantidad_deseada, fecha_vencimiento):
    if cantidad_deseada < 0:
        raise ValidationError('Cantidad deseada no puede ser negativa.')

    with transaction.atomic():
        stock, created = StockMovil.objects.get_or_create(
            movil=movil,
            medicamento=medicamento,
            fecha_vencimiento=fecha_vencimiento,
            defaults={'cantidad': 0},
        )
        actual = stock.cantidad

        if actual == cantidad_deseada:
            log_movimiento(
                tipo='ajuste',
                medicamento=medicamento,
                cantidad=0,
                movil=movil,
                descripcion='Ajuste sin cambios',
            )
            return stock

        if actual < cantidad_deseada:
            faltante = cantidad_deseada - actual
            inventarios = Inventario.objects.filter(medicamento=medicamento, cantidad__gt=0).order_by('fecha_vencimiento')
            total_disponible = inventarios.aggregate(total=Sum('cantidad'))['total'] or 0
            if total_disponible < faltante:
                raise ValidationError('No hay suficiente stock en inventario para completar el ajuste.')
            restante = faltante
            for inventario in inventarios:
                if restante == 0:
                    break
                mover = min(inventario.cantidad, restante)
                inventario.cantidad -= mover
                inventario.full_clean()
                inventario.save()
                restante -= mover
            stock.cantidad = cantidad_deseada
            stock.full_clean()
            stock.save()
            log_movimiento(
                tipo='entrada',
                medicamento=medicamento,
                cantidad=faltante,
                movil=movil,
                descripcion=f'Ajuste positivo a {cantidad_deseada} unidades',
            )
            return stock

        exceso = actual - cantidad_deseada
        stock.cantidad = cantidad_deseada
        stock.full_clean()
        stock.save()
        Recuperado.objects.create(
            medicamento=medicamento,
            cantidad=exceso,
            movil_origen=movil,
        )
        log_movimiento(
            tipo='ajuste',
            medicamento=medicamento,
            cantidad=exceso,
            movil=movil,
            descripcion=f'Ajuste negativo de {exceso} unidades',
        )
        return stock


def mover_inventario_directo(movil, medicamento, cantidad, fecha_vencimiento):
    return transferir_stock_a_movil(movil, medicamento, cantidad, fecha_vencimiento)


def descartar_stock(stock):
    """Marca un stock como vencido y descartado, lo elimina del móvil."""
    with transaction.atomic():
        Vencido.objects.create(
            medicamento=stock.medicamento,
            cantidad=stock.cantidad,
            movil_origen=stock.movil,
            fecha_vencimiento=stock.fecha_vencimiento,
        )
        log_movimiento(
            tipo='salida',
            medicamento=stock.medicamento,
            cantidad=stock.cantidad,
            movil=stock.movil,
            descripcion=f'Stock descartado por vencimiento (vencía el {stock.fecha_vencimiento})',
        )
        stock.delete()


def agregar_stock_desde_recuperados(stock, cantidad, recuperado):
    """Agrega cantidad desde un registro de Recuperado al stock del móvil."""
    if cantidad <= 0:
        raise ValidationError('Cantidad debe ser mayor que cero.')
    if recuperado.cantidad < cantidad:
        raise ValidationError(f'No hay suficiente cantidad en recuperados. Disponible: {recuperado.cantidad}')

    with transaction.atomic():
        stock.cantidad += cantidad
        stock.full_clean()
        stock.save()

        recuperado.cantidad -= cantidad
        if recuperado.cantidad <= 0:
            descripcion = f'Recuperado movido completamente a {stock.movil.nombre}'
            recuperado.delete()
        else:
            recuperado.full_clean()
            recuperado.save()
            descripcion = f'{cantidad} unidades del recuperado movidas a {stock.movil.nombre}'

        log_movimiento(
            tipo='entrada',
            medicamento=stock.medicamento,
            cantidad=cantidad,
            movil=stock.movil,
            descripcion=descripcion,
        )
        return stock
