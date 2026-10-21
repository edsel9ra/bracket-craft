"""Credenciales por defecto de los servicios locales de desarrollo.

Los valores se conservan para no invalidar un almacenamiento local ya
inicializado. Solo valen en desarrollo: ``Settings`` los rechaza cuando
``APP_ENV`` no es de desarrollo, y la documentación de entorno (``.env.example``
y Compose) los etiqueta como solo desarrollo.
"""

DEVELOPMENT_STORAGE_ACCESS_KEY = "minioadmin"
DEVELOPMENT_STORAGE_SECRET_KEY = "minioadmin"
