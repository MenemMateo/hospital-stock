from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, User

from .models import Compra, Inventario, Medicamento, Movil


class TransferStockForm(forms.Form):
    medicamento = forms.ModelChoiceField(queryset=Medicamento.objects.all(), label='Medicamento')
    cantidad = forms.IntegerField(min_value=1, label='Cantidad')
    fecha_vencimiento = forms.DateField(label='Fecha de vencimiento', widget=forms.DateInput(attrs={'type': 'date'}))


class AjustarStockForm(forms.Form):
    medicamento = forms.ModelChoiceField(queryset=Medicamento.objects.all(), label='Medicamento')
    cantidad = forms.IntegerField(min_value=0, label='Cantidad deseada')
    fecha_vencimiento = forms.DateField(label='Fecha de vencimiento', widget=forms.DateInput(attrs={'type': 'date'}))


class MoveStockForm(forms.Form):
    movil = forms.ModelChoiceField(queryset=Movil.objects.all(), label='Movil')
    medicamento = forms.ModelChoiceField(queryset=Medicamento.objects.all(), label='Medicamento')
    cantidad = forms.IntegerField(min_value=1, label='Cantidad')
    fecha_vencimiento = forms.DateField(label='Fecha de vencimiento', widget=forms.DateInput(attrs={'type': 'date'}))


class MovilForm(forms.ModelForm):
    class Meta:
        model = Movil
        fields = ['nombre']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
        }


class MedicamentoForm(forms.ModelForm):
    class Meta:
        model = Medicamento
        fields = ['nombre', 'precio_unitario']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'precio_unitario': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }
        help_texts = {
            'precio_unitario': 'Opcional. Puede dejarse vacio y completarse mas adelante.',
        }

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        queryset = Medicamento.objects.filter(nombre__iexact=nombre)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError('Ya existe un medicamento con ese nombre.')
        return nombre


class InventarioForm(forms.ModelForm):
    fecha_vencimiento = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

    class Meta:
        model = Inventario
        fields = ['medicamento', 'cantidad', 'fecha_vencimiento']


class TransferirStockAlMovilForm(forms.Form):
    """Compatibilidad para el flujo anterior."""

    medicamento = forms.ModelChoiceField(
        queryset=Medicamento.objects.all(),
        label='Medicamento',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_medicamento'}),
    )
    fecha_vencimiento = forms.DateField(
        label='Fecha de vencimiento',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_fecha_vencimiento'}),
        required=True,
    )
    cantidad = forms.IntegerField(
        min_value=1,
        label='Cantidad',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'id': 'id_cantidad'}),
    )


class AjustarStockMovilForm(forms.Form):
    """Compatibilidad para el flujo anterior."""

    medicamento = forms.ModelChoiceField(
        queryset=Medicamento.objects.all(),
        label='Medicamento',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_medicamento'}),
    )
    fecha_vencimiento = forms.DateField(
        label='Fecha de vencimiento',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_fecha_vencimiento'}),
        required=True,
    )
    cantidad = forms.IntegerField(
        min_value=0,
        label='Cantidad deseada',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'id': 'id_cantidad'}),
    )


class UsuarioCreateForm(UserCreationForm):
    ROLE_CHOICES = [
        ('Superuser', 'Superuser'),
        ('Empleado', 'Empleado'),
        ('Espectador', 'Espectador'),
    ]
    role = forms.ChoiceField(choices=ROLE_CHOICES, label='Rol')

    class Meta:
        model = User
        fields = ['username', 'password1', 'password2', 'role']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = False
        user.is_active = True
        role = self.cleaned_data['role']
        if role == 'Superuser':
            user.is_superuser = True
            user.is_staff = True
        else:
            user.is_superuser = False
        if commit:
            user.save()
            Group.objects.get(name=role).user_set.add(user)
        return user


class StockActionForm(forms.Form):
    ACTION_CHOICES = [
        ('add', 'Agregar stock'),
        ('set', 'Ajustar stock a valor final'),
    ]
    SOURCE_CHOICES = [
        ('inventario', 'Desde inventario'),
        ('externo', 'Carga externa / compra directa'),
    ]

    medicamento = forms.ModelChoiceField(
        queryset=Medicamento.objects.all(),
        required=False,
        label='Medicamento',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    fecha_vencimiento = forms.DateField(
        required=False,
        label='Fecha de vencimiento',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.RadioSelect,
        initial='add',
        label='Tipo de operacion',
    )
    cantidad = forms.IntegerField(
        min_value=0,
        label='Cantidad',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        help_text='Si ajusta al valor final, indique el stock final deseado.',
    )
    origen = forms.ChoiceField(
        choices=SOURCE_CHOICES,
        required=True,
        initial='inventario',
        label='Origen del stock',
        widget=forms.RadioSelect,
    )
    reemplazar_existente = forms.BooleanField(
        required=False,
        label='Reemplazar el stock actual antes de dejar el valor final',
    )
    enviar_recuperado = forms.BooleanField(
        required=False,
        label='Enviar sobrante a recuperados',
    )

    def __init__(self, *args, stock=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.stock = stock
        if stock is not None:
            self.fields['medicamento'].initial = stock.medicamento
            self.fields['fecha_vencimiento'].initial = stock.fecha_vencimiento
            self.fields['medicamento'].widget = forms.HiddenInput()
            self.fields['fecha_vencimiento'].widget = forms.HiddenInput()

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        cantidad = cleaned_data.get('cantidad')
        medicamento = cleaned_data.get('medicamento') or getattr(self.stock, 'medicamento', None)
        fecha_vencimiento = cleaned_data.get('fecha_vencimiento') or getattr(self.stock, 'fecha_vencimiento', None)
        reemplazar_existente = cleaned_data.get('reemplazar_existente')

        if not medicamento:
            raise forms.ValidationError('Seleccione un medicamento.')

        if not fecha_vencimiento:
            raise forms.ValidationError('Indique la fecha de vencimiento.')

        if cantidad is None:
            raise forms.ValidationError('La cantidad es obligatoria.')

        if action == 'add' and cantidad <= 0:
            raise forms.ValidationError('La cantidad debe ser mayor que cero para agregar stock.')

        if action == 'set' and cantidad < 0:
            raise forms.ValidationError('La cantidad deseada no puede ser negativa.')

        if action != 'set' and reemplazar_existente:
            raise forms.ValidationError('La opcion de reemplazar stock solo aplica al ajuste a valor final.')

        cleaned_data['medicamento'] = medicamento
        cleaned_data['fecha_vencimiento'] = fecha_vencimiento
        return cleaned_data


class AgregarDesdeRecuperadosForm(forms.Form):
    cantidad = forms.IntegerField(min_value=1, label='Cantidad')


class EditarPrecioForm(forms.ModelForm):
    class Meta:
        model = Medicamento
        fields = ['nombre', 'precio_unitario']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'precio_unitario': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['precio_unitario'].required = False
        self.fields['precio_unitario'].help_text = 'Precio unitario en la moneda local. Deje vacio si no aplica.'

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        queryset = Medicamento.objects.filter(nombre__iexact=nombre)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError('Ya existe un medicamento con ese nombre.')
        return nombre


class CompraForm(forms.ModelForm):
    class Meta:
        model = Compra
        fields = ['medicamento', 'cantidad', 'precio_unitario', 'descuento', 'contar_como_gasto', 'motivo_sin_gasto', 'movil']
        widgets = {
            'precio_unitario': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'descuento': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'motivo_sin_gasto': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describe el motivo por el cual no cuenta como gasto'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.medicamento and self.instance.medicamento.precio_unitario:
            self.fields['precio_unitario'].initial = self.instance.medicamento.precio_unitario

    def clean(self):
        cleaned_data = super().clean()
        contar_como_gasto = cleaned_data.get('contar_como_gasto')
        motivo_sin_gasto = cleaned_data.get('motivo_sin_gasto')

        if not contar_como_gasto and not motivo_sin_gasto:
            raise forms.ValidationError('Debe proporcionar un motivo si la compra no cuenta como gasto.')

        return cleaned_data


class AgregarMedicamentoAlInventarioForm(forms.Form):
    """Formulario para agregar stock al inventario desde la app."""

    medicamento = forms.ModelChoiceField(
        queryset=Medicamento.objects.all(),
        required=False,
        label='Medicamento existente',
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='Seleccionar medicamento',
    )
    nuevo_medicamento = forms.CharField(
        required=False,
        label='O crear medicamento nuevo',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Paracetamol 500 mg'}),
        help_text='Complete este campo si el medicamento aun no existe.',
    )
    precio_unitario = forms.DecimalField(
        min_value=0,
        decimal_places=2,
        required=False,
        label='Precio unitario',
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'class': 'form-control'}),
        help_text='Opcional. Si queda vacio se usa el precio del medicamento, si existe.',
    )
    cantidad = forms.IntegerField(min_value=1, label='Cantidad', widget=forms.NumberInput(attrs={'class': 'form-control'}))
    fecha_vencimiento = forms.DateField(label='Fecha de vencimiento', widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    compra_externa = forms.BooleanField(
        initial=True,
        required=False,
        label='Registrar como compra externa',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    descuento = forms.DecimalField(
        min_value=0,
        decimal_places=2,
        initial=0,
        label='Descuento aplicado',
        required=False,
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'class': 'form-control'}),
    )
    contar_como_gasto = forms.BooleanField(
        initial=True,
        required=False,
        label='Contar como gasto',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    motivo_sin_gasto = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Ej: Donacion, ajuste interno, etc.', 'class': 'form-control'}),
        required=False,
        label='Motivo si no cuenta como gasto',
    )

    def clean(self):
        cleaned_data = super().clean()
        medicamento = cleaned_data.get('medicamento')
        nuevo_medicamento = (cleaned_data.get('nuevo_medicamento') or '').strip()
        compra_externa = cleaned_data.get('compra_externa')
        contar_como_gasto = cleaned_data.get('contar_como_gasto')
        motivo_sin_gasto = cleaned_data.get('motivo_sin_gasto')

        if not medicamento and not nuevo_medicamento:
            raise forms.ValidationError('Seleccione un medicamento existente o escriba uno nuevo.')

        if medicamento and nuevo_medicamento:
            raise forms.ValidationError('Use un medicamento existente o cree uno nuevo, pero no ambas opciones a la vez.')

        if nuevo_medicamento and Medicamento.objects.filter(nombre__iexact=nuevo_medicamento).exists():
            raise forms.ValidationError('Ya existe un medicamento con ese nombre.')

        if compra_externa and not contar_como_gasto and not motivo_sin_gasto:
            raise forms.ValidationError('Debe proporcionar un motivo si la compra externa no cuenta como gasto.')

        return cleaned_data


class ConsumoStockForm(forms.Form):
    cantidad = forms.IntegerField(
        min_value=1,
        label='Cantidad consumida',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
    )
    descripcion = forms.CharField(
        required=False,
        label='Descripcion',
        widget=forms.Textarea(
            attrs={
                'rows': 3,
                'class': 'form-control',
                'placeholder': 'Opcional. Ej: Consumo en guardia, reposicion parcial, etc.',
            }
        ),
    )


class ConfiguracionGastosForm(forms.ModelForm):
    """Formulario para editar limites de gastos."""

    class Meta:
        model = None
        fields = ['limite_mensual', 'porcentaje_alerta']
        widgets = {
            'limite_mensual': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'min': '0',
                    'placeholder': 'Ej: 10000',
                }
            ),
            'porcentaje_alerta': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'min': '0',
                    'max': '100',
                    'placeholder': 'Ej: 80',
                }
            ),
        }
        labels = {
            'limite_mensual': 'Limite mensual ($)',
            'porcentaje_alerta': 'Porcentaje para mostrar alerta (%)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import ConfiguracionGastos

        self._meta.model = ConfiguracionGastos
        self._meta.fields = ('limite_mensual', 'porcentaje_alerta')
