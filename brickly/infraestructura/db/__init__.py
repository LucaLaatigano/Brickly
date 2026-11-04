"""Datos — todo el SQL del proyecto vive acá: conexión, migraciones y repositorios.

La ruta de la base sale de %APPDATA% (carpeta Brickly); se define en
conexion.py. La base vieja de GestionDepartamentos se copia una sola vez en
migracion_datos.py. Migraciones secuenciales con PRAGMA user_version.
"""
