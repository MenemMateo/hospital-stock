from datetime import datetime
import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.conf import settings

from .forms import (AjustarStockForm, InventarioForm, MedicamentoForm, MovilForm, StockActionForm,
                     TransferStockForm, UsuarioCreateForm, EditarPrecioForm, CompraForm, AgregarMedicamentoAlInventarioForm,
                     TransferirStockAlMovilForm, AjustarStockMovilForm)
from .models import Inventario, Medicamento, Movimiento, Movil, Recuperado, StockMovil, Vencido, Compra
from .services import (agregar_stock_movil, agregar_stock_desde_recuperados, ajustar_stock_movil,
                       descartar_stock, transferir_stock_a_movil, ajustar_stock_movimiento)


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


@login_required
@group_required(['Empleado', 'Espectador'])
def dashboard(request):
    from datetime import datetime
    from django.db.models import Sum
    from .models import ConfiguracionGastos

    mobiles = Movil.objects.all()
    estados = []
    for movil in mobiles:
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

    # Calcular gastos del mes actual
    fecha_inicio = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if fecha_inicio.month == 12:
        fecha_fin = datetime(fecha_inicio.year + 1, 1, 1)
    else:
        fecha_fin = datetime(fecha_inicio.year, fecha_inicio.month + 1, 1)

    total_gastado = Compra.objects.filter(fecha__gte=fecha_inicio, fecha__lt=fecha_fin).aggregate(
        total=Sum('total'))['total'] or 0

    # Obtener configuración de la BD
    config = ConfiguracionGastos.get_configuracion()
    limite_mensual = config.limite_mensual
    porcentaje_alerta = config.porcentaje_alerta
    porcentaje_limite = (total_gastado / limite_mensual) * 100 if limite_mensual > 0 else 0

    return render(request, 'core/dashboard.html', {
        'estados': estados,
        'total_gastado': total_gastado,
        'limite_mensual': limite_mensual,
        'porcentaje_alerta': porcentaje_alerta,
        'porcentaje_limite': porcentaje_limite,
    })


@login_required
@group_required(['Empleado', 'Espectador'])
def movil_detail(request, pk):
    movil = get_object_or_404(Movil, pk=pk)
    stock_items = StockMovil.objects.filter(movil=movil)
    return render(request, 'core/movil_detail.html', {'movil': movil, 'stock_items': stock_items})


@login_required
@group_required(['Empleado'])
@no_spectador_post
def edit_stock_item(request, pk):
    stock = get_object_or_404(StockMovil, pk=pk)
    if request.method == 'POST':
        form = StockActionForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data['action']
            cantidad = form.cleaned_data['cantidad']
            if action == 'add':
                origen = form.cleaned_data['origen']
                try:
                    agregar_stock_movil(stock, cantidad, desde_inventario=(origen == 'inventario'))
                    messages.success(request, 'Stock agregado correctamente.')
                    return redirect('movil_detail', pk=stock.movil.pk)
                except Exception as exc:
                    form.add_error(None, str(exc))
            else:
                enviar_recuperado = form.cleaned_data['enviar_recuperado']
                try:
                    ajustar_stock_movimiento(stock, cantidad, enviar_recuperado=enviar_recuperado)
                    messages.success(request, 'Stock ajustado correctamente.')
                    return redirect('movil_detail', pk=stock.movil.pk)
                except Exception as exc:
                    form.add_error(None, str(exc))
    else:
        form = StockActionForm(initial={'action': 'add', 'cantidad': 0, 'origen': 'inventario'})
    return render(request, 'core/stock_edit.html', {'stock': stock, 'form': form})


@login_required
@group_required(['Empleado', 'Espectador'])
def inventario_list(request):
    inventario = Inventario.objects.select_related('medicamento').order_by('fecha_vencimiento')
    medicamentos = Medicamento.objects.all().order_by('nombre')
    medicamentos_sin_precio = medicamentos.filter(precio_unitario__isnull=True)
    return render(request, 'core/inventario.html', {
        'inventario': inventario,
        'medicamentos': medicamentos,
        'medicamentos_sin_precio': medicamentos_sin_precio
    })


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
            messages.success(request, 'Medicamento agregado correctamente.')
            return redirect('inventario_list')
    else:
        form = MedicamentoForm()
    return render(request, 'core/action_form.html', {'form': form, 'titulo': 'Agregar medicamento', 'back_url': 'inventario_list'})


@login_required
@group_required(['Empleado'])
@no_spectador_post
def add_movil(request):
    if request.method == 'POST':
        form = MovilForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Móvil agregado correctamente.')
            return redirect('dashboard')
    else:
        form = MovilForm()
    return render(request, 'core/action_form.html', {'form': form, 'titulo': 'Agregar móvil', 'back_url': 'dashboard'})


@login_required
@group_required(['Empleado'])
@no_spectador_post
def add_inventario(request):
    if request.method == 'POST':
        form = AgregarMedicamentoAlInventarioForm(request.POST)
        if form.is_valid():
            medicamento = form.cleaned_data['medicamento']
            cantidad = form.cleaned_data['cantidad']
            fecha_vencimiento = form.cleaned_data['fecha_vencimiento']
            precio_unitario = medicamento.precio_unitario  # Se usa automáticamente del medicamento
            descuento = form.cleaned_data['descuento'] or 0
            contar_como_gasto = form.cleaned_data['contar_como_gasto']
            motivo_sin_gasto = form.cleaned_data['motivo_sin_gasto']
            
            try:
                # Crear o actualizar el Inventario
                inventario, created = Inventario.objects.get_or_create(
                    medicamento=medicamento,
                    fecha_vencimiento=fecha_vencimiento,
                    defaults={'cantidad': 0}
                )
                inventario.cantidad += cantidad
                inventario.save()
                
                # Crear automáticamente un Compra/gasto
                compra = Compra.objects.create(
                    medicamento=medicamento,
                    cantidad=cantidad,
                    precio_unitario=precio_unitario,
                    descuento=descuento,
                    total=(cantidad * precio_unitario) - descuento,
                    movil=None,  # movil=None indica que es una compra al inventario
                    contar_como_gasto=contar_como_gasto,
                    motivo_sin_gasto=motivo_sin_gasto if not contar_como_gasto else None
                )
                
                messages.success(request, f'Medicamento "{medicamento.nombre}" ({cantidad} unidades) agregado al inventario correctamente.')
                return redirect('inventario_list')
            except Exception as e:
                form.add_error(None, f'Error al agregar: {str(e)}')
    else:
        form = AgregarMedicamentoAlInventarioForm()
    return render(request, 'core/agregar_al_inventario.html', {'form': form, 'titulo': 'Agregar medicamento al inventario', 'back_url': 'inventario_list'})


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
    movil = get_object_or_404(Movil, pk=pk)
    if request.method == 'POST':
        form = TransferirStockAlMovilForm(request.POST)
        if form.is_valid():
            try:
                transferir_stock_a_movil(
                    movil=movil,
                    medicamento=form.cleaned_data['medicamento'],
                    cantidad=form.cleaned_data['cantidad'],
                    fecha_vencimiento=form.cleaned_data['fecha_vencimiento'],
                )
                messages.success(request, 'Stock transferido correctamente al móvil.')
                return redirect('movil_detail', pk=movil.pk)
            except Exception as exc:
                form.add_error(None, str(exc))
    else:
        form = TransferirStockAlMovilForm()
    
    # Obtener datos de inventario para pasar al template (JSON-serializable)
    inventario_data = {}
    for inv in Inventario.objects.select_related('medicamento'):
        med_id = inv.medicamento.id
        if med_id not in inventario_data:
            inventario_data[med_id] = {
                'medicamento_nombre': inv.medicamento.nombre,
                'cantidad_total': 0,
                'fechas': []
            }
        inventario_data[med_id]['cantidad_total'] += inv.cantidad
        dias_restantes = (inv.fecha_vencimiento - datetime.now().date()).days
        inventario_data[med_id]['fechas'].append({
            'fecha': str(inv.fecha_vencimiento),  # Convertir a string
            'cantidad': inv.cantidad,
            'dias_restantes': dias_restantes,
        })
    
    # Convertir a JSON string para el template
    inventario_json = json.dumps(inventario_data)
    
    return render(request, 'core/transferir_stock_movil.html', {
        'form': form,
        'titulo': 'Transferir stock al móvil',
        'movil': movil,
        'inventario_data': inventario_json
    })


@login_required
@group_required(['Empleado'])
@no_spectador_post
def ajustar_stock(request, pk):
    movil = get_object_or_404(Movil, pk=pk)
    if request.method == 'POST':
        form = AjustarStockMovilForm(request.POST)
        if form.is_valid():
            try:
                ajustar_stock_movil(
                    movil=movil,
                    medicamento=form.cleaned_data['medicamento'],
                    cantidad_deseada=form.cleaned_data['cantidad'],
                    fecha_vencimiento=form.cleaned_data['fecha_vencimiento'],
                )
                messages.success(request, 'Stock ajustado correctamente en el móvil.')
                return redirect('movil_detail', pk=movil.pk)
            except Exception as exc:
                form.add_error(None, str(exc))
    else:
        form = AjustarStockMovilForm()
    
    # Obtener datos de inventario para pasar al template (JSON-serializable)
    inventario_data = {}
    for inv in Inventario.objects.select_related('medicamento'):
        med_id = inv.medicamento.id
        if med_id not in inventario_data:
            inventario_data[med_id] = {
                'medicamento_nombre': inv.medicamento.nombre,
                'cantidad_total': 0,
                'fechas': []
            }
        inventario_data[med_id]['cantidad_total'] += inv.cantidad
        dias_restantes = (inv.fecha_vencimiento - datetime.now().date()).days
        inventario_data[med_id]['fechas'].append({
            'fecha': str(inv.fecha_vencimiento),  # Convertir a string
            'cantidad': inv.cantidad,
            'dias_restantes': dias_restantes,
        })
    
    # Convertir a JSON string para el template
    inventario_json = json.dumps(inventario_data)
    
    return render(request, 'core/ajustar_stock_movil.html', {
        'form': form,
        'titulo': 'Ajustar stock del móvil',
        'movil': movil,
        'inventario_data': inventario_json
    })


@login_required
@group_required(['Empleado', 'Espectador'])
def vencidos_list(request):
    vencidos = Vencido.objects.select_related('medicamento', 'movil_origen').order_by('-fecha_descarte')
    return render(request, 'core/vencidos.html', {'vencidos': vencidos})


@login_required
@group_required(['Empleado'])
@no_spectador_post
def descartar_stock_item(request, pk):
    stock = get_object_or_404(StockMovil, pk=pk)
    if request.method == 'POST':
        try:
            descartar_stock(stock)
            messages.success(request, 'Stock descartado correctamente.')
            return redirect('movil_detail', pk=stock.movil.pk)
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect('movil_detail', pk=stock.movil.pk)
    return render(request, 'core/confirm_discard.html', {'stock': stock})


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
            stock, _ = StockMovil.objects.get_or_create(
                movil=movil,
                medicamento=recuperado.medicamento,
                fecha_vencimiento=recuperado.medicamento.inventario_set.first().fecha_vencimiento 
                if recuperado.medicamento.inventario_set.exists() else timezone.now().date(),
                defaults={'cantidad': 0},
            )
            agregar_stock_desde_recuperados(stock, cantidad, recuperado)
            messages.success(request, 'Stock agregado desde recuperados.')
            return redirect('recuperados_list')
        except (ValueError, Exception) as exc:
            messages.error(request, str(exc))
    mobiles = Movil.objects.all()
    return render(request, 'core/agregar_desde_recuperados.html', {
        'recuperado': recuperado,
        'mobiles': mobiles,
    })


@login_required
@group_required(['Empleado'])
@no_spectador_post
def editar_precio(request, pk):
    medicamento = get_object_or_404(Medicamento, pk=pk)
    if request.method == 'POST':
        form = EditarPrecioForm(request.POST, instance=medicamento)
        if form.is_valid():
            form.save()
            messages.success(request, f'Precio de {medicamento.nombre} actualizado correctamente.')
            return redirect('inventario_list')
    else:
        form = EditarPrecioForm(instance=medicamento)
    return render(request, 'core/action_form.html', {
        'form': form,
        'titulo': f'Editar precio de {medicamento.nombre}',
        'back_url': 'inventario_list'
    })


@login_required
@group_required(['Empleado', 'Espectador'])
def gastos_list(request):
    from datetime import datetime
    from django.db.models import Sum, F

    # Obtener tipo de vista
    tipo = request.GET.get('tipo', 'consumo')  # Por defecto mostrar consumo

    # Obtener mes y año del request, por defecto mes actual
    mes = request.GET.get('mes')
    año = request.GET.get('año')

    if mes and año:
        try:
            fecha_inicio = datetime(int(año), int(mes), 1)
            if int(mes) == 12:
                fecha_fin = datetime(int(año) + 1, 1, 1)
            else:
                fecha_fin = datetime(int(año), int(mes) + 1, 1)
        except ValueError:
            fecha_inicio = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            fecha_fin = datetime.now().replace(day=1, month=fecha_inicio.month + 1 if fecha_inicio.month < 12 else 1,
                                             year=fecha_inicio.year if fecha_inicio.month < 12 else fecha_inicio.year + 1,
                                             hour=0, minute=0, second=0, microsecond=0)
    else:
        fecha_inicio = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if fecha_inicio.month == 12:
            fecha_fin = datetime(fecha_inicio.year + 1, 1, 1)
        else:
            fecha_fin = datetime(fecha_inicio.year, fecha_inicio.month + 1, 1)

    # Obtener configuración de límites desde la base de datos
    from .models import ConfiguracionGastos
    config = ConfiguracionGastos.get_configuracion()
    LIMITE_MENSUAL = config.limite_mensual
    PORCENTAJE_ALERTA = config.porcentaje_alerta

    # Lista de meses para el selector
    meses = [
        ('01', 'Enero'), ('02', 'Febrero'), ('03', 'Marzo'), ('04', 'Abril'),
        ('05', 'Mayo'), ('06', 'Junio'), ('07', 'Julio'), ('08', 'Agosto'),
        ('09', 'Septiembre'), ('10', 'Octubre'), ('11', 'Noviembre'), ('12', 'Diciembre')
    ]

    context = {
        'mes_actual': fecha_inicio,
        'limite_mensual': LIMITE_MENSUAL,
        'porcentaje_alerta': PORCENTAJE_ALERTA,
        'mes': fecha_inicio.month,
        'año': fecha_inicio.year,
        'meses': meses,
        'tipo': tipo,
    }

    if tipo == 'compras':
        # Vista de Compras: remedios comprados
        compras = Compra.objects.filter(
            fecha__gte=fecha_inicio,
            fecha__lt=fecha_fin,
            movil__isnull=True,  # Solo compras al inventario
            contar_como_gasto=True
        ).order_by('-fecha')

        # Calcular total gastado en compras
        total_gastado = compras.aggregate(total=Sum('total'))['total'] or 0
        porcentaje_limite = (total_gastado / LIMITE_MENSUAL) * 100 if LIMITE_MENSUAL > 0 else 0

        # Medicamentos sin precio
        medicamentos_sin_precio = Medicamento.objects.filter(precio_unitario__isnull=True)

        # Resumen por medicamento en compras
        medicamentos_summary = compras.values('medicamento__nombre').annotate(
            total_cantidad=Sum('cantidad'),
            total_gastado=Sum('total'),
            precio_promedio=Sum('total') / Sum('cantidad')
        ).order_by('-total_gastado')

        context.update({
            'compras': compras,
            'total_gastado': total_gastado,
            'porcentaje_limite': porcentaje_limite,
            'medicamentos_sin_precio': medicamentos_sin_precio,
            'medicamentos_summary': medicamentos_summary,
        })

    else:  # tipo == 'consumo'
        # Vista de Consumo: lo usado en móviles
        compras_consumo = Compra.objects.filter(
            fecha__gte=fecha_inicio,
            fecha__lt=fecha_fin,
            movil__isnull=False,  # Solo lo que fue a móviles
            contar_como_gasto=True
        ).order_by('-fecha')

        total_consumo = compras_consumo.aggregate(total=Sum('total'))['total'] or 0
        porcentaje_limite = (total_consumo / LIMITE_MENSUAL) * 100 if LIMITE_MENSUAL > 0 else 0

        # Resumen por móvil
        resumen_moviles = []
        for movil in Movil.objects.all():
            compras_movil = compras_consumo.filter(movil=movil)
            if compras_movil.exists():  # Solo mostrar móviles con consumo
                total_movil = compras_movil.aggregate(total=Sum('total'))['total'] or 0
                cantidad_consumida = compras_movil.aggregate(cantidad=Sum('cantidad'))['cantidad'] or 0

                # Detalle de medicamentos por móvil
                medicamentos_detalle = compras_movil.values('medicamento__nombre').annotate(
                    total_cantidad=Sum('cantidad'),
                    total_gastado=Sum('total'),
                    precio_promedio=Sum('total') / Sum('cantidad')
                ).order_by('-total_cantidad')

                resumen_moviles.append({
                    'movil': movil,
                    'total_gastado': total_movil,
                    'cantidad_consumida': cantidad_consumida,
                    'compras': compras_movil,
                    'medicamentos_detalle': medicamentos_detalle,
                })

        context.update({
            'compras_consumo': compras_consumo,
            'total_consumo': total_consumo,
            'porcentaje_limite': porcentaje_limite,
            'resumen_moviles': resumen_moviles,
        })

    return render(request, 'core/gastos.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser, login_url='login')
def actualizar_limites_gastos(request):
    """Vista para actualizar los límites de gastos"""
    from .models import ConfiguracionGastos
    
    if request.method == 'POST':
        config = ConfiguracionGastos.get_configuracion()
        
        # Obtener datos del formulario
        limite_mensual = request.POST.get('limite_mensual')
        porcentaje_alerta = request.POST.get('porcentaje_alerta')
        
        if limite_mensual:
            config.limite_mensual = limite_mensual
        if porcentaje_alerta:
            config.porcentaje_alerta = porcentaje_alerta
        
        config.save()
    
    return redirect('gastos_list')
