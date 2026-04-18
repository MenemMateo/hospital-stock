def role_flags(request):
    user = request.user
    if not user.is_authenticated:
        return {}

    groups = set(user.groups.values_list('name', flat=True))
    return {
        'is_superuser': user.is_superuser,
        'is_empleado': user.is_superuser or 'Empleado' in groups,
        'is_espectador': 'Espectador' in groups,
        'can_modify_stock': user.is_superuser or 'Empleado' in groups,
        'can_view': user.is_superuser or 'Empleado' in groups or 'Espectador' in groups,
        'can_create_user': user.is_superuser,
    }
