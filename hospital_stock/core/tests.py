from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .models import Compra, ConfiguracionGastos, Inventario, Medicamento, Movimiento, Movil, Recuperado, StockMovil, Vencido


class StockFlowTests(TestCase):
    def setUp(self):
        self.empleado_group, _ = Group.objects.get_or_create(name='Empleado')
        self.user = User.objects.create_user(username='empleado', password='secret123')
        self.user.groups.add(self.empleado_group)
        self.client.force_login(self.user)

        self.fecha = date.today() + timedelta(days=60)
        self.fecha_vencida = date.today() - timedelta(days=5)
        self.movil = Movil.objects.create(nombre='Movil 1')
        self.medicamento = Medicamento.objects.create(nombre='Paracetamol', precio_unitario=10)
        ConfiguracionGastos.get_configuracion()

    def test_main_dashboard_loads_recent_movements_and_mode_detail(self):
        Inventario.objects.create(medicamento=self.medicamento, cantidad=2, fecha_vencimiento=self.fecha)
        Movimiento.objects.create(tipo='entrada', medicamento=self.medicamento, cantidad=2, descripcion='Carga inicial')

        response = self.client.get(reverse('dashboard'))
        response_detail = self.client.get(f"{reverse('dashboard')}?detail=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response_detail.status_code, 200)
        self.assertContains(response, 'Hospital Stock')
        self.assertContains(response_detail, 'Gasto mensual detallado')

    def test_add_inventory_internal_adjustment_creates_stock_without_purchase(self):
        response = self.client.post(
            reverse('add_inventario'),
            {
                'nuevo_medicamento': 'Ibuprofeno',
                'precio_unitario': '',
                'cantidad': 12,
                'fecha_vencimiento': self.fecha.isoformat(),
                'descuento': '0',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        medicamento = Medicamento.objects.get(nombre='Ibuprofeno')
        inventario = Inventario.objects.get(medicamento=medicamento, fecha_vencimiento=self.fecha)
        self.assertEqual(inventario.cantidad, 12)
        self.assertFalse(Compra.objects.filter(medicamento=medicamento).exists())
        self.assertTrue(Movimiento.objects.filter(medicamento=medicamento, tipo='entrada').exists())

    def test_transfer_inventory_row_to_mobile(self):
        inventario = Inventario.objects.create(medicamento=self.medicamento, cantidad=20, fecha_vencimiento=self.fecha)

        response = self.client.post(
            reverse('transfer_inventory_item', args=[inventario.pk]),
            {
                'movil': self.movil.pk,
                'cantidad': 6,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        inventario.refresh_from_db()
        stock = StockMovil.objects.get(movil=self.movil, medicamento=self.medicamento, fecha_vencimiento=self.fecha)
        self.assertEqual(inventario.cantidad, 14)
        self.assertEqual(stock.cantidad, 6)

    def test_adjust_stock_can_replace_and_send_surplus_to_recuperados(self):
        Inventario.objects.create(medicamento=self.medicamento, cantidad=25, fecha_vencimiento=self.fecha)
        stock = StockMovil.objects.create(movil=self.movil, medicamento=self.medicamento, cantidad=2, fecha_vencimiento=self.fecha)

        response = self.client.post(
            reverse('edit_stock_item', args=[stock.pk]),
            {
                'action': 'set',
                'cantidad': 10,
                'origen': 'inventario',
                'reemplazar_existente': 'on',
                'enviar_recuperado': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        stock.refresh_from_db()
        inventario = Inventario.objects.get(medicamento=self.medicamento, fecha_vencimiento=self.fecha)
        recuperado = Recuperado.objects.get(medicamento=self.medicamento, movil_origen=self.movil)
        self.assertEqual(stock.cantidad, 10)
        self.assertEqual(inventario.cantidad, 15)
        self.assertEqual(recuperado.cantidad, 2)
        self.assertTrue(Movimiento.objects.filter(medicamento=self.medicamento, movil=self.movil, tipo='recuperado').exists())
        self.assertTrue(Movimiento.objects.filter(medicamento=self.medicamento, movil=self.movil, tipo='ajuste').exists())

    def test_register_consumption_creates_consumption_cost(self):
        stock = StockMovil.objects.create(movil=self.movil, medicamento=self.medicamento, cantidad=5, fecha_vencimiento=self.fecha)

        response = self.client.post(
            reverse('registrar_consumo', args=[stock.pk]),
            {
                'cantidad': 3,
                'tipo_consumo': 'uso_normal',
                'observacion': 'Guardia nocturna',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        stock.refresh_from_db()
        compra = Compra.objects.filter(medicamento=self.medicamento, movil=self.movil).latest('fecha')
        self.assertEqual(stock.cantidad, 2)
        self.assertEqual(compra.cantidad, 3)
        self.assertEqual(float(compra.total), 30.0)
        self.assertTrue(Movimiento.objects.filter(medicamento=self.medicamento, movil=self.movil, tipo='consumo').exists())

    def test_register_consumption_rejects_quantity_above_available(self):
        stock = StockMovil.objects.create(movil=self.movil, medicamento=self.medicamento, cantidad=3, fecha_vencimiento=self.fecha)

        response = self.client.post(
            reverse('registrar_consumo', args=[stock.pk]),
            {
                'cantidad': 5,
                'tipo_consumo': 'uso_normal',
                'observacion': 'Consumo invalido',
            },
        )

        self.assertEqual(response.status_code, 200)
        stock.refresh_from_db()
        self.assertEqual(stock.cantidad, 3)
        self.assertContains(response, 'No puede consumir mas de lo disponible en el movil.')

    def test_consumption_devolution_moves_stock_to_recuperados_without_cost(self):
        stock = StockMovil.objects.create(movil=self.movil, medicamento=self.medicamento, cantidad=4, fecha_vencimiento=self.fecha)

        response = self.client.post(
            reverse('registrar_consumo', args=[stock.pk]),
            {
                'cantidad': 2,
                'tipo_consumo': 'devolucion',
                'observacion': 'Vuelve a deposito',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        stock.refresh_from_db()
        recuperado = Recuperado.objects.get(medicamento=self.medicamento, movil_origen=self.movil)
        compra = Compra.objects.filter(medicamento=self.medicamento, movil=self.movil).latest('fecha')
        self.assertEqual(stock.cantidad, 2)
        self.assertEqual(recuperado.cantidad, 2)
        self.assertFalse(compra.contar_como_gasto)

    def test_quick_remove_expired_creates_vencido_record(self):
        stock = StockMovil.objects.create(movil=self.movil, medicamento=self.medicamento, cantidad=3, fecha_vencimiento=self.fecha_vencida)

        response = self.client.post(reverse('descartar_stock_item', args=[stock.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(StockMovil.objects.filter(pk=stock.pk).exists())
        vencido = Vencido.objects.get(medicamento=self.medicamento, movil_origen=self.movil)
        self.assertEqual(vencido.cantidad, 3)
        self.assertTrue(Movimiento.objects.filter(medicamento=self.medicamento, movil=self.movil, tipo='vencido').exists())
