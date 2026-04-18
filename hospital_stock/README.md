# Hospital Stock Management System

Un sistema de gestión de inventario para hospitales desarrollado con Django.

## Descripción

Este proyecto es una aplicación web para la gestión de stock de medicamentos y suministros médicos en un hospital. Incluye funcionalidades para:

- Gestión de inventario de medicamentos
- Control de vencimientos
- Transferencias de stock entre ubicaciones
- Dashboard de gastos
- Gestión de usuarios y roles
- Reportes y movimientos de stock

## Instalación

### Prerrequisitos

- Python 3.8 o superior
- Git

### Pasos de instalación

1. **Clona el repositorio:**
   ```bash
   git clone https://github.com/MenemMateo/hospital-stock.git
   cd hospital-stock
   ```

2. **Crea un entorno virtual:**
   ```bash
   python -m venv venv
   ```

3. **Activa el entorno virtual:**
   - En Windows:
     ```bash
     venv\Scripts\activate
     ```
   - En Linux/Mac:
     ```bash
     source venv/bin/activate
     ```

4. **Instala las dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Configura la base de datos:**
   ```bash
   python manage.py migrate
   ```

6. **Crea un superusuario (opcional):**
   ```bash
   python manage.py createsuperuser
   ```

7. **Ejecuta el servidor de desarrollo:**
   ```bash
   python manage.py runserver
   ```

   Accede a la aplicación en `http://127.0.0.1:8000/`

## Uso

### Funcionalidades principales

- **Dashboard:** Vista general del inventario y gastos
- **Inventario:** Gestión de medicamentos y suministros
- **Movimientos:** Registro de entradas y salidas de stock
- **Vencidos:** Control de productos próximos a vencer
- **Gastos:** Seguimiento de gastos del hospital
- **Transferencias:** Movimiento de stock entre ubicaciones

### Acceso administrativo

Para acceder al panel de administración de Django, ve a `http://127.0.0.1:8000/admin/` y usa las credenciales del superusuario creado.

## Estructura del proyecto

```
hospital_stock/
├── config/              # Configuración de Django
├── core/                # Aplicación principal
│   ├── models.py        # Modelos de datos
│   ├── views.py         # Vistas y lógica
│   ├── templates/       # Plantillas HTML
│   ├── static/          # Archivos estáticos
│   └── migrations/      # Migraciones de base de datos
├── db.sqlite3           # Base de datos SQLite
├── manage.py            # Script de gestión de Django
├── requirements.txt     # Dependencias del proyecto
└── README.md            # Este archivo
```

## Tecnologías utilizadas

- **Backend:** Django 6.0.3
- **Base de datos:** SQLite (configurable para PostgreSQL/MySQL)
- **Frontend:** HTML, CSS, JavaScript (con Bootstrap si se incluye)
- **Autenticación:** Sistema de autenticación de Django

## Contribución

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## Configuración de producción

Para desplegar en producción:

1. Configura variables de entorno para `SECRET_KEY`, `DEBUG=False`, etc.
2. Usa un servidor WSGI como Gunicorn
3. Configura un servidor web como Nginx
4. Usa una base de datos más robusta (PostgreSQL recomendado)
5. Configura HTTPS

## Licencia

Este proyecto está bajo la Licencia MIT. Ver el archivo `LICENSE` para más detalles.

## Contacto

Mateo Menem - [Tu email o contacto]

Enlace del proyecto: [https://github.com/MenemMateo/hospital-stock](https://github.com/MenemMateo/hospital-stock)