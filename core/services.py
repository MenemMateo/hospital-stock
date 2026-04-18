from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Compra, Inventario, Movimiento, Recuperado, StockMovil, Vencido


def log_movimiento(tipo, medicamento, cantidad, movil=None, descripcion=''):
    return Movimiento.objects.create(
        tipo=tipo,
        medicamento=medicamento,
        cantidad=cantidad,
        movil=movil,
        descripcion=descripcion,
    )


def registrar_compra(
    medicamento,
    cantidad,
    movil=None,
    precio_unitario=None,
    descuento=Decimal('0'),
    contar_como_gasto=True,
    motivo_sin_gasto='',
):
    precio_base = precio_unitario if precio_unitario is not None else medicamento.precio_unitario
    sin_precio_definido = precio_base is None
    precio_final = precio_base if precio_base is not None else Decimal('0')

    return Compra.objects.create(
        medicamento=medicamento,
        cantidad=cantidad,
        precio_unitario=precio_final,
        descuento=descuento or Decimal('0'),
        movil=movil,
        sin_precio_definido=sin_precio_definido,
        contar_como_gasto=contar_como_gasto,
        motivo_sin_gasto=motivo_sin_gasto if not contar_como_gasto else None,
    )


def _tomar_desde_inventario(medicamento, fecha_vencimiento, cantidad):
    inventario = Inventario.objects.filter(
        medicamento=medicamento,
        fecha_vencimiento=fecha_vencimiento,
    ).first()

    if not inventario or inventario.cantidad < cantidad:
        raise ValidationError('No hay suficiente stock en inventario para ese medicamento y fecha de vencimiento.')

    inventario.cantidad -= cantidad
    inventario.full_clean()
    inventario.save()
    return inventario


def _crear_o_actualizar_stock_movil(movil, medicamento, fecha_vencimiento):
    stock, _ = StockMovil.objects.get_or_create(
        movil=movil,
        medicamento=medicamento,
        fecha_vencimiento=fecha_vencimiento,
        defaults={'cantidad': 0},
    )
    return stock


def _registrar_recuperado(medicamento, cantidad, movil, descripcion):
    Recuperado.objects.create(
        medicamento=medicamento,
        cantidad=cantidad,
        movil_origen=movil,
    )
    log_movimiento(
        tipo='recuperado',
        medicamento=medicamento,
        cantidad=cantidad,
        movil=movil,
        descripcion=descripcion,
    )


def _describir_origen(origen, movil, cantidad=None, ajuste=False):
    if origen == 'inventario':
        base = f'Transferencia desde inventario al {movil.nombre}'
    else:
        base = f'Carga externa directa al {movil.nombre}'

    if ajuste and cantidad is not None:
        return f'{base} para completar ajuste de {cantidad} unidades'
    return base


def operar_stock_movil(
    movil,
    medicamento,
    fecha_vencimiento,
    modo,
    cantidad,
    origen='inventario',
    enviar_recuperado=False,
    reemplazar_existente=False,
):
    if cantidad < 0:
        raise ValidationError('La cantidad no puede ser negativa.')

    if modo == 'add' and cantidad <= 0:
        raise ValidationError('La cantidad debe ser mayor que cero para agregar stock.')

    if origen not in {'inventario', 'externo'}:
        raise ValidationError('Seleccione un origen de stock valido.')

    with transaction.atomic():
        stock = _crear_o_actualizar_stock_movil(movil, medicamento, fecha_vencimiento)
        actual = stock.cantidad

        if modo == 'add':
            if origen == 'inventario':
                _tomar_desde_inventario(medicamento, fecha_vencimiento, cantidad)
            else:
                registrar_compra(medicamento=medicamento, cantidad=cantidad, movil=movil)

            stock.cantidad = actual + cantidad
            stock.full_clean()
            stock.save()

            log_movimiento(
                tipo='entrada',
                medicamento=medicamento,
                cantidad=cantidad,
                movil=movil,
                descripcion=_describir_origen(origen, movil),
            )
            return stock

        if modo != 'set':
            raise ValidationError('Operacion de stock no soportada.')

        if actual == cantidad and not reemplazar_existente:
            log_movimiento(
                tipo='ajuste',
                medicamento=medicamento,
                cantidad=0,
                movil=movil,
                descripcion=f'Ajuste de stock en {movil.nombre} sin cambios.',
            )
            return stock

        unidades_a_retirar = actual if reemplazar_existente else max(actual - cantidad, 0)
        unidades_a_ingresar = cantidad if reemplazar_existente else max(cantidad - actual, 0)

        if unidades_a_retirar and enviar_recuperado:
            _registrar_recuperado(
                medicamento=medicamento,
                cantidad=unidades_a_retirar,
                movil=movil,
                descripcion=f'Sobrante enviado a recuperados desde {movil.nombre}',
            )

        if unidades_a_ingresar:
            if origen == 'inventario':
                _tomar_desde_inventario(medicamento, fecha_vencimiento, unidades_a_ingresar)
            else:
                registrar_compra(medicamento=medicamento, cantidad=unidades_a_ingresar, movil=movil)

            log_movimiento(
                tipo='entrada',
                medicamento=medicamento,
                cantidad=unidades_a_ingresar,
                movil=movil,
                descripcion=_describir_origen(origen, movil, cantidad=unidades_a_ingresar, ajuste=True),
            )

        stock.cantidad = cantidad
        stock.full_clean()
        stock.save()

        detalle = f'Ajuste de stock en {movil.nombre}: {actual} -> {cantidad}.'
        if reemplazar_existente and actual:
            detalle += ' Se reemplazo el stock anterior.'
        if unidades_a_retirar:
            if enviar_recuperado:
                detalle += ' Sobrante enviado a recuperados.'
            else:
                detalle += ' Sobrante retirado sin enviar a recuperados.'

        log_movimiento(
            tipo='ajuste',
            medicamento=medicamento,
            cantidad=max(abs(cantidad - actual), unidades_a_retirar, unidades_a_ingresar),
            movil=movil,
            descripcion=detalle,
        )
        return stock


def registrar_ingreso_inventario(
    medicamento,
    cantidad,
    fecha_vencimiento,
    compra_externa=True,
    precio_unitario=None,
    descuento=Decimal('0'),
    contar_como_gasto=True,
    motivo_sin_gasto='',
):
    if cantidad <= 0:
        raise ValidationError('La cantidad debe ser mayor que cero.')

    with transaction.atomic():
        inventario, _ = Inventario.objects.get_or_create(
            medicamento=medicamento,
            fecha_vencimiento=fecha_vencimiento,
            defaults={'cantidad': 0},
        )
        inventario.cantidad += cantidad
        inventario.full_clean()
        inventario.save()

        compra = None
        if compra_externa:
            compra = registrar_compra(
                medicamento=medicamento,
                cantidad=cantidad,
                movil=None,
                precio_unitario=precio_unitario,
                descuento=descuento,
                contar_como_gasto=contar_como_gasto,
                motivo_sin_gasto=motivo_sin_gasto,
            )
            descripcion = f'Compra externa cargada al inventario ({fecha_vencimiento})'
        else:
            descripcion = f'Ajuste interno de inventario ({fecha_vencimiento})'

        log_movimiento(
            tipo='entrada',
            medicamento=medicamento,
            cantidad=cantidad,
            descripcion=descripcion,
        )
        return inventario, compra


def registrar_consumo_stock(stock, cantidad, descripcion=''):
    if cantidad <= 0:
        raise ValidationError('La cantidad consumida debe ser mayor que cero.')

    if cantidad > stock.cantidad:
        raise ValidationError('No puede consumir mas de lo disponible en el movil.')

    with transaction.atomic():
        movil = stock.movil
        medicamento = stock.medicamento
        stock.cantidad -= cantidad

        if stock.cantidad == 0:
            stock.delete()
        else:
            stock.full_clean()
            stock.save()

        log_movimiento(
            tipo='salida',
            medicamento=medicamento,
            cantidad=cantidad,
            movil=movil,
            descripcion=descripcion or f'Consumo registrado en {movil.nombre}',
        )


def transferir_stock_a_movil(movil, medicamento, cantidad, fecha_vencimiento):
    return operar_stock_movil(
        movil=movil,
        medicamento=medicamento,
        fecha_vencimiento=fecha_vencimiento,
        modo='add',
        cantidad=cantidad,
        origen='inventario',
    )


def agregar_stock_movil(stock, cantidad, desde_inventario=True):
    return operar_stock_movil(
        movil=stock.movil,
        medicamento=stock.medicamento,
        fecha_vencimiento=stock.fecha_vencimiento,
        modo='add',
        cantidad=cantidad,
        origen='inventario' if desde_inventario else 'externo',
    )


def ajustar_stock_movimiento(stock, cantidad_deseada, enviar_recuperado=False):
    return operar_stock_movil(
        movil=stock.movil,
        medicamento=stock.medicamento,
        fecha_vencimiento=stock.fecha_vencimiento,
        modo='set',
        cantidad=cantidad_deseada,
        origen='inventario',
        enviar_recuperado=enviar_recuperado,
    )


def ajustar_stock_movil(movil, medicamento, cantidad_deseada, fecha_vencimiento):
    return operar_stock_movil(
        movil=movil,
        medicamento=medicamento,
        fecha_vencimiento=fecha_vencimiento,
        modo='set',
        cantidad=cantidad_deseada,
        origen='inventario',
        enviar_recuperado=True,
    )


def mover_inventario_directo(movil, medicamento, cantidad, fecha_vencimiento):
    return transferir_stock_a_movil(movil, medicamento, cantidad, fecha_vencimiento)


def descartar_stock(stock):
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
            descripcion=f'Stock descartado por vencimiento en {stock.movil.nombre} (vencia el {stock.fecha_vencimiento})',
        )
        stock.delete()


def agregar_stock_desde_recuperados(stock, cantidad, recuperado):
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
