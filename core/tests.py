from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .models import Compra, Inventario, Medicamento, Movimiento, Movil, Recuperado, StockMovil


class StockFlowTests(TestCase):
    def setUp(self):
        self.empleado_group, _ = Group.objects.get_or_create(name='Empleado')
        self.user = User.objects.create_user(username='empleado', password='secret123')
        self.user.groups.add(self.empleado_group)
        self.client.force_login(self.user)

        self.fecha = date.today() + timedelta(days=60)
        self.movil = Movil.objects.create(nombre='Movil 1')
        self.medicamento = Medicamento.objects.create(nombre='Paracetamol', precio_unitario=10)

    def test_add_inventory_internal_adjustment_creates_stock_without_purchase(self):
        response = self.client.post(
            reverse('add_inventario'),
            {
                'nuevo_medicamento': 'Ibuprofeno',
                'precio_unitario': '',
                'cantidad': 12,
                'fecha_vencimiento': self.fecha.isoformat(),
                'compra_externa': '',
                'descuento': '0',
                'contar_como_gasto': '',
                'motivo_sin_gasto': '',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        medicamento = Medicamento.objects.get(nombre='Ibuprofeno')
        inventario = Inventario.objects.get(medicamento=medicamento, fecha_vencimiento=self.fecha)
        self.assertEqual(inventario.cantidad, 12)
        self.assertFalse(Compra.objects.filter(medicamento=medicamento).exists())
        self.assertTrue(Movimiento.objects.filter(medicamento=medicamento, tipo='entrada').exists())

    def test_add_stock_to_mobile_from_inventory(self):
        Inventario.objects.create(medicamento=self.medicamento, cantidad=20, fecha_vencimiento=self.fecha)

        response = self.client.post(
            reverse('add_stock_item', args=[self.movil.pk]),
            {
                'medicamento': self.medicamento.pk,
                'fecha_vencimiento': self.fecha.isoformat(),
                'action': 'add',
                'cantidad': 5,
                'origen': 'inventario',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        stock = StockMovil.objects.get(movil=self.movil, medicamento=self.medicamento, fecha_vencimiento=self.fecha)
        inventario = Inventario.objects.get(medicamento=self.medicamento, fecha_vencimiento=self.fecha)
        self.assertEqual(stock.cantidad, 5)
        self.assertEqual(inventario.cantidad, 15)
        self.assertTrue(
            Movimiento.objects.filter(
                medicamento=self.medicamento,
                movil=self.movil,
                descripcion__icontains='Transferencia desde inventario',
            ).exists()
        )

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

    def test_register_consumption_rejects_quantity_above_available(self):
        stock = StockMovil.objects.create(movil=self.movil, medicamento=self.medicamento, cantidad=3, fecha_vencimiento=self.fecha)

        response = self.client.post(
            reverse('registrar_consumo', args=[stock.pk]),
            {
                'cantidad': 5,
                'descripcion': 'Consumo invalido',
            },
        )

        self.assertEqual(response.status_code, 200)
        stock.refresh_from_db()
        self.assertEqual(stock.cantidad, 3)
        self.assertContains(response, 'No puede consumir mas de lo disponible en el movil.')
