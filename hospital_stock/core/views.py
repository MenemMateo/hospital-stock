from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import (
    AgregarMedicamentoAlInventarioForm,
    ConsumoStockForm,
    EditarPrecioForm,
    MedicamentoForm,
    MovilForm,
    StockActionForm,
    TransferirInventarioItemForm,
    UsuarioCreateForm,
)
from .models import Compra, ConfiguracionGastos, Inventario, Medicamento, Movimiento, Movil, Recuperado, StockMovil, Vencido
from .services import (
    agregar_stock_desde_recuperados,
    descartar_stock,
    operar_stock_movil,
    registrar_consumo_stock,
    registrar_ingreso_inventario,
    transferir_stock_a_movil,
)


def group_required(groups):
    def check(user):
        return user.is_superuser or user.groups.filter(name__in=groups).exists()

    return user_passes_test(check, login_url='login')


def no_spectador_post(view_func):
    def wrapper(request, *args, **kwargs):
        if request.method != 'GET' and request.user.groups.filter(name='Espectador').exists():
            raise PermissionDenied('No tiene permiso para modificar datos.')
        return view_func(request, *args, **kwargs)

    return wrapper


def _first_day_of_month(year, month):
    return timezone.make_aware(datetime(year, month, 1))


def _next_month(date_value):
    if date_value.month == 12:
        next_value = datetime(date_value.year + 1, 1, 1)
    else:
        next_value = datetime(date_value.year, date_value.month + 1, 1)
    return timezone.make_aware(next_value)


def _month_window():
    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, _next_month(start)


def _show_missing_price_warning(request, medicamento):
    if medicamento.precio_unitario is None:
        messages.warning(
            request,
            f'El medicamento "{medicamento.nombre}" no tiene precio definido. La operacion se registro igual y quedo marcada sin costo.',
        )


def _stock_action_initial(request, stock=None):
    mode = request.GET.get('mode', 'add')
    initial = {
        'action': 'set' if mode == 'set' else 'add',
        'origen': request.GET.get('origen', 'inventario'),
    }
    if stock is not None:
        initial['cantidad'] = stock.cantidad if initial['action'] == 'set' else 1
    return initial


def _stock_action_template_context(movil, form, stock=None):
    if stock is None:
        titulo = f'Agregar medicamento al {movil.nombre}'
        descripcion = 'Seleccione medicamento, vencimiento, origen y cantidad para cargar stock directamente desde el movil.'
    else:
        titulo = f'Operar stock de {stock.medicamento.nombre}'
        descripcion = 'Puede sumar stock o dejar un valor final para este medicamento dentro del movil.'

    return {
        'titulo': titulo,
        'descripcion': descripcion,
        'movil': movil,
        'stock': stock,
        'form': form,
    }


def _build_inventory_alert_entry(item):
    return {
        'medicamento': item.medicamento.nombre,
        'cantidad': item.cantidad,
        'fecha_vencimiento': item.fecha_vencimiento,
        'ubicacion': 'Inventario',
        'detalle': 'Ver inventario',
        'url': reverse('inventario_list'),
    }


def _build_mobile_alert_entry(item):
    return {
        'medicamento': item.medicamento.nombre,
        'cantidad': item.cantidad,
        'fecha_vencimiento': item.fecha_vencimiento,
        'ubicacion': item.movil.nombre,
        'detalle': f'Ver {item.movil.nombre}',
        'url': reverse('movil_detail', args=[item.movil_id]),
    }


def _system_dashboard_context(detail_mode=False):
    today = timezone.now().date()
    warning_date = today + timedelta(days=settings.EXPIRATION_WARNING_DAYS)
    month_start, month_end = _month_window()

    inventario_qs = Inventario.objects.select_related('medicamento').order_by('medicamento__nombre', 'fecha_vencimiento')
    stock_movil_qs = StockMovil.objects.select_related('medicamento', 'movil').order_by('movil__nombre', 'medicamento__nombre', 'fecha_vencimiento')
    movimientos_recientes = Movimiento.objects.select_related('medicamento', 'movil').order_by('-fecha')[:10]

    low_inventory = [
        _build_inventory_alert_entry(item)
        for item in inventario_qs
        if not item.es_vencido and item.cantidad < item.low_stock_threshold
    ]
    low_mobile = [
        _build_mobile_alert_entry(item)
        for item in stock_movil_qs
        if not item.es_vencido and item.cantidad < item.low_stock_threshold
    ]
    expiring_inventory = [
        _build_inventory_alert_entry(item)
        for item in inventario_qs
        if today <= item.fecha_vencimiento <= warning_date
    ]
    expiring_mobile = [
        _build_mobile_alert_entry(item)
        for item in stock_movil_qs
        if today <= item.fecha_vencimiento <= warning_date
    ]
    expired_inventory = [
        _build_inventory_alert_entry(item)
        for item in inventario_qs
        if item.fecha_vencimiento < today
    ]
    expired_mobile = [
        _build_mobile_alert_entry(item)
        for item in stock_movil_qs
        if item.fecha_vencimiento < today
    ]

    low_alerts = low_inventory + low_mobile
    expiring_alerts = expiring_inventory + expiring_mobile
    expired_alerts = expired_inventory + expired_mobile

    config = ConfiguracionGastos.get_configuracion()
    gasto_total_mes = Compra.objects.filter(fecha__gte=month_start, fecha__lt=month_end, contar_como_gasto=True).aggregate(total=Sum('total'))['total'] or 0
    gasto_compras = Compra.objects.filter(
        fecha__gte=month_start,
        fecha__lt=month_end,
        contar_como_gasto=True,
        movil__isnull=True,
    ).aggregate(total=Sum('total'))['total'] or 0
    gasto_consumo = Compra.objects.filter(
        fecha__gte=month_start,
        fecha__lt=month_end,
        contar_como_gasto=True,
        movil__isnull=False,
    ).aggregate(total=Sum('total'))['total'] or 0
    porcentaje_limite = (gasto_total_mes / config.limite_mensual) * 100 if config.limite_mensual else 0

    resumen_moviles = []
    for movil in Movil.objects.all():
        items = [item for item in stock_movil_qs if item.movil_id == movil.id]
        if not items and not detail_mode:
            continue
        resumen_moviles.append(
            {
                'movil': movil,
                'total_items': len(items),
                'total_unidades': sum(item.cantidad for item in items),
                'stock_bajo': sum(1 for item in items if not item.es_vencido and item.cantidad < item.low_stock_threshold),
                'por_vencer': sum(1 for item in items if today <= item.fecha_vencimiento <= warning_date),
                'vencidos': sum(1 for item in items if item.fecha_vencimiento < today),
            }
        )

    resumen_medicamentos = {}
    for item in inventario_qs:
        resumen = resumen_medicamentos.setdefault(
            item.medicamento.nombre,
            {'nombre': item.medicamento.nombre, 'inventario': 0, 'moviles': 0, 'por_vencer': 0, 'vencidos': 0},
        )
        resumen['inventario'] += item.cantidad
        if today <= item.fecha_vencimiento <= warning_date:
            resumen['por_vencer'] += item.cantidad
        if item.fecha_vencimiento < today:
            resumen['vencidos'] += item.cantidad

    for item in stock_movil_qs:
        resumen = resumen_medicamentos.setdefault(
            item.medicamento.nombre,
            {'nombre': item.medicamento.nombre, 'inventario': 0, 'moviles': 0, 'por_vencer': 0, 'vencidos': 0},
        )
        resumen['moviles'] += item.cantidad
        if today <= item.fecha_vencimiento <= warning_date:
            resumen['por_vencer'] += item.cantidad
        if item.fecha_vencimiento < today:
            resumen['vencidos'] += item.cantidad

    return {
        'detail_mode': detail_mode,
        'low_alerts': low_alerts,
        'expiring_alerts': expiring_alerts,
        'expired_alerts': expired_alerts,
        'recent_movements': movimientos_recientes,
        'config_gastos': config,
        'gasto_total_mes': gasto_total_mes,
        'gasto_compras': gasto_compras,
        'gasto_consumo': gasto_consumo,
        'porcentaje_limite': porcentaje_limite,
        'summary_cards': [
            {'label': 'Stock bajo', 'value': len(low_alerts), 'variant': 'warning'},
            {'label': 'Por vencer', 'value': len(expiring_alerts), 'variant': 'warning'},
            {'label': 'Vencidos', 'value': len(expired_alerts), 'variant': 'danger'},
            {'label': 'Gasto del mes', 'value': f'${gasto_total_mes:.2f}', 'variant': 'success'},
        ],
        'resumen_moviles': resumen_moviles,
        'resumen_medicamentos': sorted(resumen_medicamentos.values(), key=lambda item: item['nombre']),
    }


@login_required
@group_required(['Empleado', 'Espectador'])
def dashboard(request):
    detail_mode = request.GET.get('detail') == '1'
    context = _system_dashboard_context(detail_mode=detail_mode)
    return render(request, 'core/system_dashboard.html', context)


@login_required
@group_required(['Empleado', 'Espectador'])
def moviles_dashboard(request):
    estados = []
    for movil in Movil.objects.all():
        if movil.has_expired_stock:
            nivel = 'danger'
            mensaje = 'Vencido'
        elif movil.has_warning_stock:
            nivel = 'warning'
            mensaje = 'Alerta'
        else:
            nivel = 'success'
            mensaje = 'OK'
        estados.append({'movil': movil, 'nivel': nivel, 'mensaje': mensaje})

    return render(
        request,
        'core/dashboard.html',
        {
            'estados': estados,
        },
    )


@login_required
@group_required(['Empleado', 'Espectador'])
def movil_detail(request, pk):
    movil = get_object_or_404(Movil, pk=pk)
    stock_items = StockMovil.objects.filter(movil=movil).select_related('medicamento').order_by('medicamento__nombre', 'fecha_vencimiento')
    total_unidades = sum(item.cantidad for item in stock_items)
    return render(
        request,
        'core/movil_detail.html',
        {
            'movil': movil,
            'stock_items': stock_items,
            'total_unidades': total_unidades,
        },
    )


@login_required
@group_required(['Empleado'])
@no_spectador_post
def add_stock_item(request, pk):
    movil = get_object_or_404(Movil, pk=pk)
    if request.method == 'POST':
        form = StockActionForm(request.POST)
        if form.is_valid():
            try:
                operar_stock_movil(
                    movil=movil,
                    medicamento=form.cleaned_data['medicamento'],
                    fecha_vencimiento=form.cleaned_data['fecha_vencimiento'],
                    modo=form.cleaned_data['action'],
                    cantidad=form.cleaned_data['cantidad'],
                    origen=form.cleaned_data['origen'],
                    enviar_recuperado=form.cleaned_data['enviar_recuperado'],
                    reemplazar_existente=form.cleaned_data['reemplazar_existente'],
                )
                if form.cleaned_data['origen'] == 'externo':
                    _show_missing_price_warning(request, form.cleaned_data['medicamento'])
                messages.success(request, 'Operacion de stock realizada correctamente.')
                return redirect('movil_detail', pk=movil.pk)
            except Exception as exc:
                form.add_error(None, str(exc))
    else:
        form = StockActionForm(initial=_stock_action_initial(request))

    return render(request, 'core/stock_operation.html', _stock_action_template_context(movil, form))


@login_required
@group_required(['Empleado'])
@no_spectador_post
def edit_stock_item(request, pk):
    stock = get_object_or_404(StockMovil.objects.select_related('movil', 'medicamento'), pk=pk)
    if request.method == 'POST':
        form = StockActionForm(request.POST, stock=stock)
        if form.is_valid():
            try:
                operar_stock_movil(
                    movil=stock.movil,
                    medicamento=stock.medicamento,
                    fecha_vencimiento=stock.fecha_vencimiento,
                    modo=form.cleaned_data['action'],
                    cantidad=form.cleaned_data['cantidad'],
                    origen=form.cleaned_data['origen'],
                    enviar_recuperado=form.cleaned_data['enviar_recuperado'],
                    reemplazar_existente=form.cleaned_data['reemplazar_existente'],
                )
                if form.cleaned_data['origen'] == 'externo':
                    _show_missing_price_warning(request, stock.medicamento)
                messages.success(request, 'Operacion de stock realizada correctamente.')
                return redirect('movil_detail', pk=stock.movil.pk)
            except Exception as exc:
                form.add_error(None, str(exc))
    else:
        form = StockActionForm(initial=_stock_action_initial(request, stock=stock), stock=stock)

    return render(request, 'core/stock_operation.html', _stock_action_template_context(stock.movil, form, stock=stock))


@login_required
@group_required(['Empleado'])
@no_spectador_post
def registrar_consumo(request, pk):
    stock = get_object_or_404(StockMovil.objects.select_related('movil', 'medicamento'), pk=pk)
    movil = stock.movil

    if request.method == 'POST':
        form = ConsumoStockForm(request.POST)
        if form.is_valid():
            try:
                registrar_consumo_stock(
                    stock=stock,
                    cantidad=form.cleaned_data['cantidad'],
                    tipo_consumo=form.cleaned_data['tipo_consumo'],
                    observacion=form.cleaned_data['observacion'],
                )
                _show_missing_price_warning(request, stock.medicamento)
                messages.success(request, 'Consumo registrado correctamente.')
                return redirect('movil_detail', pk=movil.pk)
            except Exception as exc:
                form.add_error(None, str(exc))
    else:
        form = ConsumoStockForm()

    return render(
        request,
        'core/registrar_consumo.html',
        {
            'titulo': f'Registrar consumo de {stock.medicamento.nombre}',
            'movil': movil,
            'stock': stock,
            'form': form,
        },
    )


@login_required
@group_required(['Empleado', 'Espectador'])
def inventario_list(request):
    inventario = Inventario.objects.select_related('medicamento').order_by('medicamento__nombre', 'fecha_vencimiento')
    medicamentos = Medicamento.objects.all().order_by('nombre')
    medicamentos_sin_precio = medicamentos.filter(precio_unitario__isnull=True)
    return render(
        request,
        'core/inventario.html',
        {
            'inventario': inventario,
            'medicamentos': medicamentos,
            'medicamentos_sin_precio': medicamentos_sin_precio,
        },
    )


@login_required
@group_required(['Empleado'])
@no_spectador_post
def transfer_inventory_item(request, pk):
    inventario = get_object_or_404(Inventario.objects.select_related('medicamento'), pk=pk)
    if request.method == 'POST':
        form = TransferirInventarioItemForm(request.POST)
        if form.is_valid():
            try:
                transferir_stock_a_movil(
                    movil=form.cleaned_data['movil'],
                    medicamento=inventario.medicamento,
                    cantidad=form.cleaned_data['cantidad'],
                    fecha_vencimiento=inventario.fecha_vencimiento,
                )
                messages.success(request, 'Transferencia realizada correctamente.')
                return redirect('inventario_list')
            except Exception as exc:
                form.add_error(None, str(exc))
    else:
        form = TransferirInventarioItemForm()

    return render(
        request,
        'core/transfer_inventory_item.html',
        {
            'inventario': inventario,
            'form': form,
        },
    )


@login_required
@group_required(['Empleado', 'Espectador'])
def recuperados_list(request):
    recuperados = Recuperado.objects.select_related('medicamento', 'movil_origen').order_by('-fecha')
    return render(request, 'core/recuperados.html', {'recuperados': recuperados})


@login_required
@group_required(['Empleado'])
@no_spectador_post
def add_medicamento(request):
    if request.method == 'POST':
        form = MedicamentoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Medicamento guardado correctamente.')
            return redirect('inventario_list')
    else:
        form = MedicamentoForm()
    return render(
        request,
        'core/action_form.html',
        {
            'form': form,
            'titulo': 'Nuevo medicamento',
            'descripcion': 'Cree medicamentos sin depender del admin. El precio es opcional.',
            'back_url': 'inventario_list',
        },
    )


@login_required
@group_required(['Empleado'])
@no_spectador_post
def add_movil(request):
    if request.method == 'POST':
        form = MovilForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Movil agregado correctamente.')
            return redirect('moviles_dashboard')
    else:
        form = MovilForm()
    return render(
        request,
        'core/action_form.html',
        {
            'form': form,
            'titulo': 'Agregar movil',
            'back_url': 'moviles_dashboard',
        },
    )


@login_required
@group_required(['Empleado'])
@no_spectador_post
def add_inventario(request):
    if request.method == 'POST':
        form = AgregarMedicamentoAlInventarioForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    medicamento = form.cleaned_data['medicamento']
                    nuevo_nombre = (form.cleaned_data['nuevo_medicamento'] or '').strip()
                    precio_unitario = form.cleaned_data['precio_unitario']

                    if medicamento is None:
                        medicamento = Medicamento.objects.create(nombre=nuevo_nombre, precio_unitario=precio_unitario)
                    elif precio_unitario is not None and medicamento.precio_unitario is None:
                        medicamento.precio_unitario = precio_unitario
                        medicamento.save(update_fields=['precio_unitario'])

                    registrar_ingreso_inventario(
                        medicamento=medicamento,
                        cantidad=form.cleaned_data['cantidad'],
                        fecha_vencimiento=form.cleaned_data['fecha_vencimiento'],
                        compra_externa=form.cleaned_data['compra_externa'],
                        precio_unitario=precio_unitario,
                        descuento=form.cleaned_data['descuento'] or 0,
                        contar_como_gasto=form.cleaned_data['contar_como_gasto'],
                        motivo_sin_gasto=form.cleaned_data['motivo_sin_gasto'],
                    )

                if form.cleaned_data['compra_externa']:
                    _show_missing_price_warning(request, medicamento)
                messages.success(request, f'Stock de "{medicamento.nombre}" agregado al inventario correctamente.')
                return redirect('inventario_list')
            except Exception as exc:
                form.add_error(None, f'Error al agregar stock: {exc}')
    else:
        form = AgregarMedicamentoAlInventarioForm()

    return render(
        request,
        'core/agregar_al_inventario.html',
        {
            'form': form,
            'titulo': 'Cargar stock al inventario',
            'descripcion': 'Puede elegir un medicamento existente o crear uno nuevo desde esta misma pantalla.',
            'back_url': 'inventario_list',
        },
    )


@login_required
@user_passes_test(lambda u: u.is_superuser, login_url='login')
def create_user(request):
    if request.method == 'POST':
        form = UsuarioCreateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Usuario creado correctamente.')
            return redirect('dashboard')
    else:
        form = UsuarioCreateForm()
    return render(request, 'core/action_form.html', {'form': form, 'titulo': 'Crear usuario', 'back_url': 'dashboard'})


@login_required
@group_required(['Empleado', 'Espectador'])
def movimientos_list(request):
    queryset = Movimiento.objects.select_related('medicamento', 'movil').all()
    medicamento = request.GET.get('medicamento')
    movil = request.GET.get('movil')
    tipo = request.GET.get('tipo')
    if medicamento:
        queryset = queryset.filter(medicamento__nombre__icontains=medicamento)
    if movil:
        queryset = queryset.filter(movil__nombre__icontains=movil)
    if tipo:
        queryset = queryset.filter(tipo__icontains=tipo)
    return render(request, 'core/movimientos.html', {'movimientos': queryset, 'filtros': request.GET})


@login_required
@group_required(['Empleado'])
@no_spectador_post
def transferir_stock(request, pk):
    url = reverse('add_stock_item', kwargs={'pk': pk})
    return redirect(f'{url}?mode=add&origen=inventario')


@login_required
@group_required(['Empleado'])
@no_spectador_post
def ajustar_stock(request, pk):
    url = reverse('add_stock_item', kwargs={'pk': pk})
    return redirect(f'{url}?mode=set&origen=inventario')


@login_required
@group_required(['Empleado', 'Espectador'])
def vencidos_list(request):
    vencidos = Vencido.objects.select_related('medicamento', 'movil_origen').order_by('-fecha_descarte')
    return render(request, 'core/vencidos.html', {'vencidos': vencidos})


@login_required
@group_required(['Empleado'])
@no_spectador_post
def descartar_stock_item(request, pk):
    stock = get_object_or_404(StockMovil.objects.select_related('movil', 'medicamento'), pk=pk)
    if request.method != 'POST':
        return redirect('movil_detail', pk=stock.movil.pk)

    movil_pk = stock.movil.pk
    try:
        descartar_stock(stock)
        messages.success(request, 'Vencido eliminado correctamente.')
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect('movil_detail', pk=movil_pk)


@login_required
@group_required(['Empleado'])
@no_spectador_post
def agregar_desde_recuperados(request, pk):
    recuperado = get_object_or_404(Recuperado, pk=pk)
    if request.method == 'POST':
        movil_id = request.POST.get('movil')
        cantidad_str = request.POST.get('cantidad')
        try:
            cantidad = int(cantidad_str)
            movil = get_object_or_404(Movil, pk=movil_id)
            fecha_base = recuperado.medicamento.inventario_set.order_by('fecha_vencimiento').first()
            stock, _ = StockMovil.objects.get_or_create(
                movil=movil,
                medicamento=recuperado.medicamento,
                fecha_vencimiento=fecha_base.fecha_vencimiento if fecha_base else timezone.now().date(),
                defaults={'cantidad': 0},
            )
            agregar_stock_desde_recuperados(stock, cantidad, recuperado)
            messages.success(request, 'Stock agregado desde recuperados.')
            return redirect('recuperados_list')
        except (ValueError, Exception) as exc:
            messages.error(request, str(exc))
    mobiles = Movil.objects.all()
    return render(request, 'core/agregar_desde_recuperados.html', {'recuperado': recuperado, 'mobiles': mobiles})


@login_required
@group_required(['Empleado'])
@no_spectador_post
def editar_precio(request, pk):
    medicamento = get_object_or_404(Medicamento, pk=pk)
    if request.method == 'POST':
        form = EditarPrecioForm(request.POST, instance=medicamento)
        if form.is_valid():
            form.save()
            messages.success(request, f'Medicamento "{medicamento.nombre}" actualizado correctamente.')
            return redirect('inventario_list')
    else:
        form = EditarPrecioForm(instance=medicamento)
    return render(
        request,
        'core/action_form.html',
        {
            'form': form,
            'titulo': f'Editar medicamento: {medicamento.nombre}',
            'descripcion': 'Puede actualizar nombre y precio sin entrar al admin.',
            'back_url': 'inventario_list',
        },
    )


@login_required
@group_required(['Empleado', 'Espectador'])
def gastos_list(request):
    tipo = request.GET.get('tipo', 'consumo')
    mes = request.GET.get('mes')
    anio = request.GET.get('anio') or request.GET.get('año')

    if mes and anio:
        try:
            fecha_inicio = _first_day_of_month(int(anio), int(mes))
            fecha_fin = _next_month(fecha_inicio)
        except ValueError:
            fecha_inicio = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            fecha_fin = _next_month(fecha_inicio)
    else:
        fecha_inicio = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fecha_fin = _next_month(fecha_inicio)

    config = ConfiguracionGastos.get_configuracion()
    context = {
        'mes_actual': fecha_inicio,
        'limite_mensual': config.limite_mensual,
        'porcentaje_alerta': config.porcentaje_alerta,
        'mes': fecha_inicio.month,
        'anio': fecha_inicio.year,
        'año': fecha_inicio.year,
        'meses': [
            ('01', 'Enero'),
            ('02', 'Febrero'),
            ('03', 'Marzo'),
            ('04', 'Abril'),
            ('05', 'Mayo'),
            ('06', 'Junio'),
            ('07', 'Julio'),
            ('08', 'Agosto'),
            ('09', 'Septiembre'),
            ('10', 'Octubre'),
            ('11', 'Noviembre'),
            ('12', 'Diciembre'),
        ],
        'tipo': tipo,
    }

    if tipo == 'compras':
        compras = Compra.objects.filter(
            fecha__gte=fecha_inicio,
            fecha__lt=fecha_fin,
            movil__isnull=True,
            contar_como_gasto=True,
        ).order_by('-fecha')
        total_gastado = compras.aggregate(total=Sum('total'))['total'] or 0
        porcentaje_limite = (total_gastado / config.limite_mensual) * 100 if config.limite_mensual else 0
        medicamentos_sin_precio = Medicamento.objects.filter(precio_unitario__isnull=True)
        medicamentos_summary = compras.values('medicamento__nombre').annotate(
            total_cantidad=Sum('cantidad'),
            total_gastado=Sum('total'),
            precio_promedio=Sum('total') / Sum('cantidad'),
        ).order_by('-total_gastado')

        context.update(
            {
                'compras': compras,
                'total_gastado': total_gastado,
                'porcentaje_limite': porcentaje_limite,
                'medicamentos_sin_precio': medicamentos_sin_precio,
                'medicamentos_summary': medicamentos_summary,
            }
        )
    else:
        compras_consumo = Compra.objects.filter(
            fecha__gte=fecha_inicio,
            fecha__lt=fecha_fin,
            movil__isnull=False,
        ).order_by('-fecha')
        compras_consumo_gasto = compras_consumo.filter(contar_como_gasto=True)
        total_consumo = compras_consumo_gasto.aggregate(total=Sum('total'))['total'] or 0
        porcentaje_limite = (total_consumo / config.limite_mensual) * 100 if config.limite_mensual else 0

        resumen_moviles = []
        for movil in Movil.objects.all():
            compras_movil = compras_consumo.filter(movil=movil)
            if compras_movil.exists():
                compras_movil_gasto = compras_movil.filter(contar_como_gasto=True)
                total_movil = compras_movil_gasto.aggregate(total=Sum('total'))['total'] or 0
                cantidad_consumida = compras_movil.aggregate(cantidad=Sum('cantidad'))['cantidad'] or 0
                medicamentos_detalle = compras_movil.values('medicamento__nombre').annotate(
                    total_cantidad=Sum('cantidad'),
                    total_gastado=Sum('total'),
                ).order_by('-total_cantidad')

                resumen_moviles.append(
                    {
                        'movil': movil,
                        'total_gastado': total_movil,
                        'cantidad_consumida': cantidad_consumida,
                        'compras': compras_movil,
                        'medicamentos_detalle': medicamentos_detalle,
                    }
                )

        context.update(
            {
                'compras_consumo': compras_consumo,
                'total_consumo': total_consumo,
                'porcentaje_limite': porcentaje_limite,
                'resumen_moviles': resumen_moviles,
            }
        )

    return render(request, 'core/gastos.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser, login_url='login')
def actualizar_limites_gastos(request):
    if request.method == 'POST':
        config = ConfiguracionGastos.get_configuracion()
        limite_mensual = request.POST.get('limite_mensual')
        porcentaje_alerta = request.POST.get('porcentaje_alerta')
        if limite_mensual:
            config.limite_mensual = limite_mensual
        if porcentaje_alerta:
            config.porcentaje_alerta = porcentaje_alerta
        config.save()
    return redirect('gastos_list')
