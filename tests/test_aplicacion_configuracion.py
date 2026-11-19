"""ServicioConfiguracion (H4, spec §3.7): defaults, validación y respaldo."""

from datetime import date

import pytest

from brickly.aplicacion.configuracion import (
    REDONDEO_CIEN_PESOS,
    DatosConfiguracion,
    ServicioConfiguracion,
    es_imagen_firma_valida,
)
from brickly.aplicacion.puertos import FirmaAdminGuardada
from brickly.dominio.errores import ErrorDeValidacion


class RelojFijo:
    def __init__(self, fecha: date):
        self.fecha = fecha

    def hoy(self) -> date:
        return self.fecha


class RepoConfigFalso:
    def __init__(self, datos: dict[str, str] | None = None):
        self.datos = dict(datos or {})
        self.firma: FirmaAdminGuardada | None = None

    def cargar(self) -> dict[str, str]:
        return dict(self.datos)

    def actualizar(self, valores: dict[str, str]) -> None:
        self.datos.update(valores)

    def obtener_firma(self) -> FirmaAdminGuardada | None:
        return self.firma

    def guardar_firma(
        self,
        nombre_archivo: str,
        contenido: bytes,
        actualizado_en: str | None = None,
    ) -> None:
        self.firma = FirmaAdminGuardada(
            nombre_archivo=nombre_archivo,
            contenido=bytes(contenido),
            actualizado_en=actualizado_en or "2026-11-10 00:00:00",
        )

    def borrar_firma(self) -> None:
        self.firma = None


def _datos(**cambios) -> DatosConfiguracion:
    base = dict(
        dia_vencimiento=10,
        dias_gracia=5,
        tasa_mora_bp=200,
        redondeo_centavos=1,
        respaldo_recordatorio_dias=14,
    )
    base.update(cambios)
    return DatosConfiguracion(**base)


@pytest.fixture()
def control():
    repo = RepoConfigFalso()
    servicio = ServicioConfiguracion(repo, RelojFijo(date(2026, 10, 16)))
    return repo, servicio


class TestCargar:
    def test_instalacion_vacia_usa_defaults(self, control):
        _repo, servicio = control
        config = servicio.cargar()
        assert (config.dia_vencimiento, config.dias_gracia) == (10, 5)
        assert config.tasa_mora_bp == 200
        assert config.redondeo_centavos == 1
        assert config.respaldo_recordatorio_dias == 14
        assert config.admin_nombre is None
        assert config.ultimo_respaldo is None

    def test_valores_corruptos_caen_a_defaults(self, control):
        repo, servicio = control
        repo.datos = {
            "vencimiento_dia": "abc",
            "mora_bp": "",
            "respaldo_recordatorio_dias": "muchos",
            "ultimo_respaldo": "ayer",
        }
        config = servicio.cargar()
        assert config.dia_vencimiento == 10
        assert config.tasa_mora_bp == 200
        assert config.respaldo_recordatorio_dias == 14
        assert config.ultimo_respaldo is None


class TestGuardar:
    def test_persiste_todas_las_claves(self, control):
        repo, servicio = control
        servicio.guardar(
            _datos(
                dia_vencimiento=5,
                dias_gracia=3,
                tasa_mora_bp=150,
                redondeo_centavos=REDONDEO_CIEN_PESOS,
                respaldo_recordatorio_dias=7,
                admin_nombre="Ada Lovelace",
                admin_telefono="11 5555-4444",
                admin_email="ada@ejemplo.com",
            )
        )
        assert repo.datos == {
            "vencimiento_dia": "5",
            "gracia_dias": "3",
            "mora_bp": "150",
            "redondeo_centavos": "100",
            "respaldo_recordatorio_dias": "7",
            "admin_nombre": "Ada Lovelace",
            "admin_telefono": "11 5555-4444",
            "admin_email": "ada@ejemplo.com",
        }
        assert servicio.cargar().dia_vencimiento == 5

    def test_admin_vacio_se_guarda_como_texto_vacio(self, control):
        repo, servicio = control
        servicio.guardar(_datos())
        assert repo.datos["admin_nombre"] == ""
        assert repo.datos["admin_email"] == ""

    @pytest.mark.parametrize(
        ("cambios", "campo"),
        [
            ({"dia_vencimiento": 0}, "vencimiento_dia"),
            ({"dia_vencimiento": 29}, "vencimiento_dia"),
            ({"dias_gracia": -1}, "gracia_dias"),
            ({"tasa_mora_bp": 10_001}, "mora_bp"),
            ({"redondeo_centavos": 50}, "redondeo_centavos"),
            ({"respaldo_recordatorio_dias": 0}, "respaldo_recordatorio_dias"),
        ],
    )
    def test_invalidos_no_escriben_nada(self, control, cambios, campo):
        repo, servicio = control
        with pytest.raises(ErrorDeValidacion) as capturado:
            servicio.guardar(_datos(**cambios))
        assert capturado.value.campo == campo
        assert repo.datos == {}


class TestRespaldo:
    def test_registrar_y_leer_ultimo(self, control):
        _repo, servicio = control
        assert servicio.ultimo_respaldo() is None
        servicio.registrar_respaldo(date(2026, 10, 16))
        assert servicio.ultimo_respaldo() == date(2026, 10, 16)


class TestFirmaAdmin:
    @pytest.mark.parametrize(
        ("nombre", "formato", "modo"),
        [
            ("  firma.png  ", "PNG", "RGBA"),
            ("firma.jpg", "JPEG", "RGB"),
            ("firma.webp", "WEBP", "RGBA"),
            ("firma.bmp", "BMP", "RGB"),
        ],
    )
    def test_guardar_obtener_y_borrar_firma_imagen(
        self, control, nombre, formato, modo
    ):
        import io
        from PIL import Image

        _repo, servicio = control
        assert servicio.obtener_firma() is None

        buf = io.BytesIO()
        Image.new(modo, (120, 40), (10, 20, 30)).save(buf, format=formato)
        datos = buf.getvalue()

        guardada = servicio.guardar_firma(nombre, datos)
        assert guardada.nombre_archivo == nombre.strip()
        assert guardada.contenido == datos
        assert servicio.obtener_firma() == guardada

        servicio.borrar_firma()
        assert servicio.obtener_firma() is None

    @pytest.mark.parametrize(
        ("nombre", "contenido"),
        [
            ("", b"\x89PNG\r\n\x1a\n1234"),
            ("   ", b"\x89PNG\r\n\x1a\n1234"),
            ("firma.png", b""),
            ("firma.png", b"\x89PNG\r\n\x1a\n"),  # exacto 8 bytes (sin payload)
            ("firma.jpg", b"\xff\xd8\xff"),  # exacto 3 bytes (sin payload)
            ("firma.webp", b"RIFF\x00\x00\x00\x00WEBP"),  # exacto 12 bytes (sin payload)
            ("firma.bmp", b"BM" + b"\x00" * 11),  # 13 bytes (< 14 mínimo BMP)
            ("Photo.pdf", b"%PDF-1.4 contenido pdf"),
            ("firma.png", b"no-es-una-imagen"),
            ("audio.wav", b"RIFF\x24\x00\x00\x00WAVEfmt "),
            ("video.avi", b"RIFF\x24\x00\x00\x00AVI LIST"),
        ],
    )
    def test_rechaza_firma_invalida(self, control, nombre, contenido):
        _repo, servicio = control
        with pytest.raises(ErrorDeValidacion) as exc_info:
            servicio.guardar_firma(nombre, contenido)
        assert exc_info.value.campo == "firma_imagen"
        assert servicio.obtener_firma() is None
        assert es_imagen_firma_valida(contenido) is False or not nombre.strip()

    def test_acepta_bytearray_y_convierte_a_bytes(self, control):
        _repo, servicio = control
        datos = bytearray(b"\x89PNG\r\n\x1a\n1234")
        guardada = servicio.guardar_firma("firma.png", datos)
        assert isinstance(guardada.contenido, bytes)
        assert guardada.contenido == b"\x89PNG\r\n\x1a\n1234"

