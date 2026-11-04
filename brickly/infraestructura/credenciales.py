"""Almacén del token de API INDEC en Windows Credential Manager (ADR-0003).

Implementa `AlmacenTokenIpc` usando `Advapi32.dll` (`CredWriteW`, `CredReadW`,
`CredDeleteW`, `CredFree`) vía `ctypes` — sin dependencias externas ni archivos
adicionales en disco. El token nunca toca SQLite, logs ni copias de respaldo.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import sys

from brickly.dominio.errores import ErrorDeNegocio

TARGET_CREDENCIAL_INDEC = "Brickly/indec_api_token"
VARIABLE_ENTORNO_INDEC = "INDEC_TOKEN"

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_PCREDENTIALW = ctypes.POINTER(_CREDENTIALW)


def _cargar_advapi32():
    if sys.platform != "win32":
        return None
    dll = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    dll.CredWriteW.argtypes = [_PCREDENTIALW, wintypes.DWORD]
    dll.CredWriteW.restype = wintypes.BOOL
    dll.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_PCREDENTIALW),
    ]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredDeleteW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    dll.CredDeleteW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    dll.CredFree.restype = None
    return dll


_ADVAPI32 = _cargar_advapi32()


def _leer_entorno_usuario(nombre: str) -> str | None:
    valor = os.environ.get(nombre, "").strip()
    if valor:
        return valor
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Environment"
            ) as clave:
                valor_reg, _ = winreg.QueryValueEx(clave, nombre)
                if isinstance(valor_reg, str) and valor_reg.strip():
                    return valor_reg.strip()
        except OSError:
            return None
    return None


class AlmacenTokenCredencialesWindows:
    """Persistencia del token JWT en el Administrador de credenciales de Windows."""

    def __init__(
        self,
        target_name: str = TARGET_CREDENCIAL_INDEC,
        usar_entorno: bool = True,
    ):
        self._target_name = target_name
        self._usar_entorno = usar_entorno
        self._borrado_explicito = False
        self._memoria_fallback: str | None = None

    def obtener_token(self) -> str | None:
        if _ADVAPI32 is not None:
            puntero = _PCREDENTIALW()
            exito = _ADVAPI32.CredReadW(
                self._target_name,
                _CRED_TYPE_GENERIC,
                0,
                ctypes.byref(puntero),
            )
            if exito:
                try:
                    cred = puntero.contents
                    tamano = int(cred.CredentialBlobSize)
                    if tamano <= 0 or not bool(cred.CredentialBlob):
                        return None
                    crudo = bytes(cred.CredentialBlob[:tamano])
                finally:
                    _ADVAPI32.CredFree(puntero)
                try:
                    texto = crudo.decode("utf-16-le").strip()
                except UnicodeDecodeError:
                    texto = crudo.decode("utf-8", errors="ignore").strip()
                return texto or None
            codigo = ctypes.get_last_error()
            if codigo not in (0, _ERROR_NOT_FOUND):
                raise ErrorDeNegocio(
                    "No se pudo leer el token desde el Administrador de credenciales de Windows."
                )
        elif self._memoria_fallback:
            return self._memoria_fallback

        if self._usar_entorno and not self._borrado_explicito:
            return _leer_entorno_usuario(VARIABLE_ENTORNO_INDEC)
        return None

    def guardar_token(self, token: str) -> None:
        limpio = (token or "").strip()
        if not limpio:
            raise ErrorDeNegocio("El token a guardar no puede estar vacío.")
        self._borrado_explicito = False

        if _ADVAPI32 is None:
            self._memoria_fallback = limpio
            return

        datos = limpio.encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(datos)).from_buffer_copy(datos)
        cred = _CREDENTIALW()
        cred.Flags = 0
        cred.Type = _CRED_TYPE_GENERIC
        cred.TargetName = self._target_name
        cred.Comment = "Token de API INDEC para Brickly"
        cred.CredentialBlobSize = len(datos)
        cred.CredentialBlob = ctypes.cast(
            buffer, ctypes.POINTER(ctypes.c_ubyte)
        )
        cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
        cred.AttributeCount = 0
        cred.Attributes = None
        cred.TargetAlias = None
        cred.UserName = "Brickly"

        if not _ADVAPI32.CredWriteW(ctypes.byref(cred), 0):
            raise ErrorDeNegocio(
                "No se pudo guardar el token en el Administrador de credenciales de Windows."
            )

    def borrar_token(self) -> None:
        self._borrado_explicito = True
        self._memoria_fallback = None
        if _ADVAPI32 is None:
            return
        if not _ADVAPI32.CredDeleteW(
            self._target_name, _CRED_TYPE_GENERIC, 0
        ):
            codigo = ctypes.get_last_error()
            if codigo not in (0, _ERROR_NOT_FOUND):
                raise ErrorDeNegocio(
                    "No se pudo eliminar el token del Administrador de credenciales de Windows."
                )
