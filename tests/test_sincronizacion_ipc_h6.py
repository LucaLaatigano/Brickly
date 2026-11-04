"""Tests de punta a punta para H6: sincronización de IPC con INDEC (ADR-0003).

Cubre:
- Aplicación (`ServicioSincronizacionIpc`): token, JWT `exp`, previsualización,
  clasificación (`nuevo`, `actualizado`, `sin_cambios`, `manual_protegido`),
  importación idempotente y protección de valores manuales.
- Repositorio (`RepositorioAjustesSQLite`): upsert masivo atómico, rollback si
  hay conflicto manual no autorizado y pasaje de `api` → `manual` al editar.
- Infraestructura HTTP (`ClienteIndecHttp`): parseo Decimal, reintentos ante
  502/503/timeout, errores claros en castellano para 401/403/429/JSON inválido
  y no exposición del token.
- Infraestructura de credenciales (`AlmacenTokenCredencialesWindows`): ciclo
  guardar → leer → borrar sobre un target de prueba.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from decimal import Decimal
import io
import json
import socket
import urllib.error
import urllib.request

import pytest

from brickly.aplicacion.ajustes import ServicioAjustesIpc
from brickly.aplicacion.sincronizacion_ipc import (
    DatoIndiceIpc,
    IpcSincronizado,
    ServicioSincronizacionIpc,
    calcular_serie_desde_indices,
    enmascarar_token,
    extraer_fechas_jwt,
    normalizar_token_ipc,
)
from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from brickly.infraestructura.credenciales import AlmacenTokenCredencialesWindows
from brickly.infraestructura.db.conexion import abrir_conexion
from brickly.infraestructura.db.migrador import migrar
from brickly.infraestructura.db.repositorios.ajustes import RepositorioAjustesSQLite
from brickly.infraestructura.db.repositorios.configuracion import (
    RepositorioConfiguracionSQLite,
)
from brickly.infraestructura.indec import (
    ClienteIndecHttp,
    construir_url_ipc_nacional,
    parsear_respuesta_indec,
)


class RelojFijo:
    def __init__(self, fecha: date = date(2026, 11, 3)):
        self.fecha = fecha

    def hoy(self) -> date:
        return self.fecha


class AlmacenTokenMemoria:
    def __init__(self, token: str | None = None):
        self._token = token

    def obtener_token(self) -> str | None:
        return self._token

    def guardar_token(self, token: str) -> None:
        self._token = token

    def borrar_token(self) -> None:
        self._token = None


class FuenteIpcFalsa:
    def __init__(self, indices: list[DatoIndiceIpc] | None = None):
        self.indices = (
            indices
            if indices is not None
            else [
                DatoIndiceIpc(2026, 6, Decimal("11827.1818")),
                DatoIndiceIpc(2026, 7, Decimal("12077.4292")),  # +212 bp
                DatoIndiceIpc(2026, 8, Decimal("12277.3863")),  # +166 bp
                DatoIndiceIpc(2026, 9, Decimal("12514.1508")),  # +193 bp
            ]
        )
        self.tokens_recibidos: list[str] = []

    def obtener_indices(self, token: str) -> list[DatoIndiceIpc]:
        self.tokens_recibidos.append(token)
        return list(self.indices)


def _armar_jwt_falso(iat: date, exp: date) -> str:
    header = (
        base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}')
        .decode("ascii")
        .rstrip("=")
    )
    ts_iat = int(
        datetime(iat.year, iat.month, iat.day, 12, 0, tzinfo=timezone.utc).timestamp()
    )
    ts_exp = int(
        datetime(exp.year, exp.month, exp.day, 12, 0, tzinfo=timezone.utc).timestamp()
    )
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"sub": "test", "iat": ts_iat, "exp": ts_exp}).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    return f"{header}.{payload}.firma_falsa_1234"


@pytest.fixture()
def entorno(tmp_path):
    con = abrir_conexion(tmp_path / "datos.sqlite3")
    migrar(con)
    reloj = RelojFijo(date(2026, 11, 3))
    repo_ajustes = RepositorioAjustesSQLite(con)
    repo_config = RepositorioConfiguracionSQLite(con)
    token_valido = _armar_jwt_falso(date(2026, 11, 3), date(2027, 5, 2))
    almacen = AlmacenTokenMemoria(token_valido)
    fuente = FuenteIpcFalsa()
    ajustes = ServicioAjustesIpc(repo_ajustes, reloj)
    sinc = ServicioSincronizacionIpc(
        repositorio=repo_ajustes,
        fuente=fuente,
        almacen_token=almacen,
        reloj=reloj,
        configuracion=repo_config,
    )
    yield con, reloj, repo_ajustes, repo_config, almacen, fuente, ajustes, sinc
    con.close()


class TestTokenYJwt:
    def test_normalizar_y_enmascarar_token(self):
        crudo = "  Bearer eyJhbGciOiJIUzI1NiJ9.payload.firma9876  "
        limpio = normalizar_token_ipc(crudo)
        assert limpio == "eyJhbGciOiJIUzI1NiJ9.payload.firma9876"
        assert enmascarar_token(limpio) == "eyJh••••••9876"
        assert "payload" not in enmascarar_token(limpio)

        with pytest.raises(ErrorDeValidacion):
            normalizar_token_ipc("   ")
        with pytest.raises(ErrorDeValidacion):
            normalizar_token_ipc("token con espacios")

    def test_extraer_fechas_jwt_y_estado_vencimiento(self, entorno):
        _, reloj, _, _, almacen, _, _, sinc = entorno
        estado = sinc.estado_token()
        assert estado.configurado is True
        assert estado.vencido is False
        assert estado.habilitado is True
        assert estado.fecha_emision == date(2026, 11, 3)
        assert estado.fecha_vencimiento == date(2027, 5, 2)
        assert estado.dias_restantes == 180

        # Si el reloj avanza más allá del vencimiento (6 meses), queda deshabilitado
        reloj.fecha = date(2027, 5, 10)
        estado_vencido = sinc.estado_token()
        assert estado_vencido.vencido is True
        assert estado_vencido.habilitado is False
        assert "venció el 02/05/2027" in (estado_vencido.motivo_deshabilitado or "")

        with pytest.raises(ErrorDeNegocio, match="venció"):
            sinc.previsualizar()

        # Borrar token deja el estado sin configurar
        sinc.borrar_token()
        estado_vacio = sinc.estado_token()
        assert estado_vacio.configurado is False
        assert estado_vacio.habilitado is False
        assert "Configurá el token" in (estado_vacio.motivo_deshabilitado or "")

    def test_jwt_no_estandar_no_rompe_extraccion(self):
        assert extraer_fechas_jwt("token-opaco-sin-puntos") == (None, None)
        assert extraer_fechas_jwt("a.b.c") == (None, None)


class TestSincronizacionYConflictoManual:
    def test_calculo_serie_saltea_huecos_no_consecutivos(self):
        serie = calcular_serie_desde_indices(
            [
                DatoIndiceIpc(2026, 5, Decimal("10000.0000")),
                # Falta junio 2026: no debe calcular julio contra mayo
                DatoIndiceIpc(2026, 7, Decimal("12077.4292")),
                DatoIndiceIpc(2026, 8, Decimal("12277.3863")),
            ]
        )
        assert [(i.anio, i.mes, i.variacion_bp) for i in serie] == [
            (2026, 8, 166)
        ]

    def test_previsualizar_clasifica_los_cuatro_estados(self, entorno):
        _, _, repo_ajustes, _, _, _, ajustes, sinc = entorno
        # Julio: cargado manualmente con otro valor (250 bp != 212 bp) -> manual_protegido
        ajustes.agregar_ipc(2026, 7, 250)
        # Agosto: cargado previamente por API con otro valor (150 bp != 166 bp) -> actualizado
        repo_ajustes.guardar_ipc_masivo(
            [IpcSincronizado(2026, 8, 150, 12_200_000)]
        )
        # Septiembre: no existe -> nuevo

        preview = sinc.previsualizar()
        por_mes = {item.mes: item for item in preview.items}

        assert por_mes[9].estado == "nuevo"
        assert por_mes[9].seleccionado_por_defecto is True

        assert por_mes[8].estado == "actualizado"
        assert por_mes[8].seleccionado_por_defecto is True
        assert por_mes[8].variacion_actual_bp == 150

        assert por_mes[7].estado == "manual_protegido"
        assert por_mes[7].seleccionado_por_defecto is False
        assert por_mes[7].variacion_actual_bp == 250

    def test_importar_protege_manuales_y_es_idempotente(self, entorno):
        _, _, _, _, _, _, ajustes, sinc = entorno
        ajustes.agregar_ipc(2026, 7, 250)  # manual

        preview = sinc.previsualizar()
        # Importar selección por defecto (agosto y septiembre)
        res1 = sinc.importar(preview.periodos_por_defecto, preview=preview)
        assert res1.nuevos == 2
        assert res1.actualizados == 0
        assert res1.reemplazados_manuales == 0

        # Segunda corrida: agosto y septiembre pasan a 'sin_cambios'
        preview2 = sinc.previsualizar()
        por_mes = {item.mes: item for item in preview2.items}
        assert por_mes[8].estado == "sin_cambios"
        assert por_mes[9].estado == "sin_cambios"
        assert por_mes[7].estado == "manual_protegido"

        # Intentar importar julio (manual) sin confirmación explícita falla sin tocar nada
        with pytest.raises(ErrorDeNegocio, match="manual"):
            sinc.importar([(2026, 7)], reemplazar_manuales=False, preview=preview2)

        filas = {f.mes: f for f in ajustes.listar_ipc()}
        assert filas[7].variacion_bp == 250
        assert filas[7].origen == "manual"

        # Con reemplazar_manuales=True, julio se reemplaza por el oficial (212 bp, origen 'api')
        res2 = sinc.importar([(2026, 7)], reemplazar_manuales=True, preview=preview2)
        assert res2.reemplazados_manuales == 1
        filas_despues = {f.mes: f for f in ajustes.listar_ipc()}
        assert filas_despues[7].variacion_bp == 212
        assert filas_despues[7].origen == "api"
        assert filas_despues[7].indice_milesimos == 12_077_429

        # Y registra la fecha de última sincronización
        assert sinc.estado_token().ultima_sincronizacion == date(2026, 11, 3)

    def test_editar_fila_api_la_convierte_en_manual(self, entorno):
        _, _, _, _, _, _, ajustes, sinc = entorno
        sinc.importar([(2026, 9)])
        (fila_sep,) = [f for f in ajustes.listar_ipc() if f.mes == 9]
        assert fila_sep.origen == "api"
        assert fila_sep.indice_milesimos == 12_514_151

        # Al editarla manualmente, pasa a origen 'manual' y limpia indice_milesimos
        ajustes.editar_ipc(fila_sep.id, 200)
        (fila_editada,) = [f for f in ajustes.listar_ipc() if f.mes == 9]
        assert fila_editada.variacion_bp == 200
        assert fila_editada.origen == "manual"
        assert fila_editada.indice_milesimos is None

    def test_guardar_ipc_masivo_es_todo_o_nada_ante_conflicto(self, entorno):
        _, _, repo_ajustes, _, _, _, ajustes, _ = entorno
        ajustes.agregar_ipc(2026, 7, 250)  # manual protegido

        with pytest.raises(ErrorDeNegocio, match="manual protegido"):
            repo_ajustes.guardar_ipc_masivo(
                [
                    IpcSincronizado(2026, 9, 193, 12_514_151),
                    IpcSincronizado(2026, 7, 212, 12_077_429),
                ],
                reemplazar_manuales=False,
            )
        # Septiembre no debe haber quedado grabado por la mitad
        assert not repo_ajustes.existe_ipc(2026, 9)


class TestClienteIndecHttp:
    def test_construir_url_y_parseo_decimal_exacto(self):
        url = construir_url_ipc_nacional()
        assert url.startswith("https://api.indec.gob.ar/v1/ipc_nacional?")
        assert "tipo_de_indicador=eq.Indice" in url

        muestra = json.dumps(
            [
                {"periodo": "202608", "anio": 2026, "mes": 8, "valor": 12277.3863},
                {"periodo": "202609", "anio": 2026, "mes": 9, "valor": 12514.1508},
            ]
        ).encode("utf-8")
        datos = parsear_respuesta_indec(muestra)
        assert datos == [
            DatoIndiceIpc(2026, 8, Decimal("12277.3863")),
            DatoIndiceIpc(2026, 9, Decimal("12514.1508")),
        ]

    def test_reintenta_502_transitorio_y_luego_tiene_exito(self):
        llamadas = 0
        pausas: list[float] = []

        def transporte_falso(req: urllib.request.Request, timeout: float) -> bytes:
            nonlocal llamadas
            llamadas += 1
            assert req.get_header("Authorization") == "Bearer secreto_super_privado"
            assert "Brickly/" in (req.get_header("User-agent") or "")
            if llamadas == 1:
                raise urllib.error.HTTPError(
                    req.full_url, 502, "Bad Gateway", hdrs=None, fp=io.BytesIO(b"")
                )
            return b'[{"anio": 2026, "mes": 9, "valor": 12514.1508}]'

        cliente = ClienteIndecHttp(
            max_reintentos=2,
            pausa_reintento_segundos=0.1,
            transporte=transporte_falso,
            dormir=pausas.append,
        )
        datos = cliente.obtener_indices("secreto_super_privado")
        assert len(datos) == 1
        assert llamadas == 2
        assert len(pausas) == 1

    @pytest.mark.parametrize(
        ("codigo", "fragmento"),
        [
            (401, "inválido, fue revocado o venció"),
            (403, "inválido, fue revocado o venció"),
            (429, "Demasiadas consultas"),
            (503, "servidor de INDEC no está disponible"),
        ],
    )
    def test_errores_http_en_castellano_y_sin_exponer_token(self, codigo, fragmento):
        token_secreto = "TOKEN_SECRETO_QUE_NO_DEBE_FILTRARSE_12345"
        llamadas = 0

        def transporte_error(req: urllib.request.Request, timeout: float) -> bytes:
            nonlocal llamadas
            llamadas += 1
            raise urllib.error.HTTPError(
                req.full_url, codigo, "Error", hdrs=None, fp=io.BytesIO(b"")
            )

        cliente = ClienteIndecHttp(
            max_reintentos=1,
            transporte=transporte_error,
            dormir=lambda _: None,
        )
        with pytest.raises(ErrorDeNegocio) as info:
            cliente.obtener_indices(token_secreto)

        mensaje = str(info.value)
        assert fragmento in mensaje
        assert token_secreto not in mensaje
        # 401/403/429 no reintentan; 503 sí reintenta
        assert llamadas == (2 if codigo == 503 else 1)

    def test_timeout_y_json_invalido(self):
        def transporte_timeout(req: urllib.request.Request, timeout: float) -> bytes:
            raise socket.timeout("timed out")

        cliente = ClienteIndecHttp(
            max_reintentos=1,
            transporte=transporte_timeout,
            dormir=lambda _: None,
        )
        with pytest.raises(ErrorDeNegocio, match="tiempo de espera"):
            cliente.obtener_indices("token_123")

        for cuerpo_malo in (b"no es json", b"{}", b"[]", b'[{"anio": "mal"}]'):
            with pytest.raises(ErrorDeNegocio):
                parsear_respuesta_indec(cuerpo_malo)


class TestAlmacenCredencialesWindows:
    def test_guardar_leer_y_borrar_credencial_aislada(self):
        almacen = AlmacenTokenCredencialesWindows(
            target_name="Brickly/pytest_indec_token_temp",
            usar_entorno=False,
        )
        try:
            almacen.borrar_token()
            assert almacen.obtener_token() is None

            almacen.guardar_token("jwt_de_prueba_aislado_123")
            assert almacen.obtener_token() == "jwt_de_prueba_aislado_123"

            almacen.borrar_token()
            assert almacen.obtener_token() is None
        finally:
            almacen.borrar_token()
