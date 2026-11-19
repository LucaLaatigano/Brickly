"""Casos de uso de importación desde planillas Excel (H9 — ADR-0005).

Permite inspeccionar, validar, mapear columnas, previsualizar con deduplicación
intra-archivo y contra la base SQLite, corregir inline y persistir atómicamente
departamentos, inquilinos y contratos vigentes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Literal

from brickly.aplicacion.informes import (
    ColumnaExcel,
    FilaExcel,
    HojaExportable,
    LibroExportable,
)
from brickly.aplicacion.puertos import (
    FilaCrudaExcel,
    ItemImportacionPersistible,
    ValorCeldaCruda,
)
from brickly.dominio.contrato import Contrato, Inquilino
from brickly.dominio.departamento import (
    Departamento,
    clave_unidad_normalizada,
    desglosar_unidad_compuesta,
    limpiar_espacios,
    nombre_unidad,
)
from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion

if TYPE_CHECKING:
    from brickly.aplicacion.puertos import (
        EscritorExcel,
        LectorExcel,
        Reloj,
        RepositorioDepartamentos,
    )

MAX_FILAS_IMPORTACION = 500

CAMPOS_CANONICOS = (
    "direccion",
    "piso",
    "depto",
    "m2",
    "propietario",
    "nombre_inquilino",
    "telefono_inquilino",
    "email_inquilino",
    "fecha_inicio",
    "fecha_fin",
    "monto_inicial_centavos",
    "dia_vencimiento",
    "dias_gracia",
    "tasa_diaria_bp",
    "ciclo_ipc_meses",
    "redondeo",
)

ETIQUETAS_CAMPOS: dict[str, str] = {
    "direccion": "Dirección / Calle y Nº",
    "piso": "Piso",
    "depto": "Depto / Unidad",
    "m2": "Superficie (m²)",
    "propietario": "Propietario",
    "nombre_inquilino": "Inquilino (nombre)",
    "telefono_inquilino": "Teléfono inquilino",
    "email_inquilino": "Email inquilino",
    "fecha_inicio": "Inicio contrato",
    "fecha_fin": "Fin contrato",
    "monto_inicial_centavos": "Cuota mensual ($)",
    "dia_vencimiento": "Día de vencimiento",
    "dias_gracia": "Días de gracia",
    "tasa_diaria_bp": "Mora diaria (%)",
    "ciclo_ipc_meses": "Ciclo ajuste IPC (meses)",
    "redondeo": "Redondeo de ajuste",
}

SINONIMOS_CAMPOS: dict[str, tuple[str, ...]] = {
    "direccion": (
        "direccion",
        "dirección",
        "calle",
        "domicilio",
        "propiedad",
        "inmueble",
        "ubicacion",
        "ubicación",
        "unidad",
        "departamento",
        "depto.",
    ),
    "piso": ("piso", "nivel", "planta"),
    "depto": ("depto", "dpto", "dto", "uf", "unidad funcional", "puerta", "letra"),
    "m2": ("m2", "metros", "superficie", "sup", "m²", "mts2"),
    "propietario": ("propietario", "dueno", "dueño", "titular", "locador"),
    "nombre_inquilino": (
        "inquilino",
        "locatario",
        "arrendatario",
        "titular contrato",
        "ocupante",
        "nombre inquilino",
    ),
    "telefono_inquilino": (
        "telefono",
        "teléfono",
        "tel",
        "celular",
        "whatsapp",
        "movil",
        "móvil",
        "contacto",
        "tel inquilino",
    ),
    "email_inquilino": ("email", "mail", "correo", "e-mail", "email inquilino"),
    "fecha_inicio": (
        "inicio",
        "fecha inicio",
        "inicio contrato",
        "desde",
        "alta",
        "vigencia desde",
    ),
    "fecha_fin": (
        "fin",
        "fecha fin",
        "fin contrato",
        "vencimiento contrato",
        "hasta",
        "finalizacion",
        "finalización",
    ),
    "monto_inicial_centavos": (
        "cuota",
        "alquiler",
        "monto",
        "valor",
        "canon",
        "importe",
        "precio",
        "cuota vigente",
        "cuota mensual",
        "cuota inicial",
    ),
    "dia_vencimiento": (
        "dia vencimiento",
        "día vencimiento",
        "vence dia",
        "vence día",
        "vencimiento dia",
        "vencimiento día",
        "dia de pago",
        "día de pago",
    ),
    "dias_gracia": (
        "dias gracia",
        "días gracia",
        "gracia",
        "gracia (dias)",
        "gracia (días)",
        "dias de gracia",
        "días de gracia",
        "tolerancia",
    ),
    "tasa_diaria_bp": (
        "mora",
        "tasa mora",
        "interes mora",
        "interés mora",
        "punitorios",
        "recargo",
        "mora diaria (%)",
        "mora mensual",
    ),
    "ciclo_ipc_meses": (
        "ciclo",
        "ciclo ipc",
        "ciclo ipc (meses)",
        "ajuste cada",
        "frecuencia ajuste",
        "meses ajuste",
    ),
    "redondeo": ("redondeo", "tipo redondeo"),
}

EstadoFilaImportacion = Literal[
    "nuevo_con_contrato",
    "nuevo_vacante",
    "nuevo_contrato_vencido",
    "omitido_existente",
    "omitido_contrato_anterior",
    "omitido_manual",
    "error",
]


@dataclass(frozen=True)
class ColumnaDetectada:
    """Información de una columna encontrada en la fila de encabezados."""

    indice: int
    nombre_original: str
    campo_mapeado: str | None
    primer_valor_ejemplo: str | None = None


@dataclass(frozen=True)
class InspeccionArchivoImportacion:
    """Diagnóstico preliminar de un archivo de Excel para el asistente de importación."""

    ruta: str
    hojas: tuple[str, ...]
    hoja_seleccionada: str
    fila_encabezado_detectada: int
    columnas_detectadas: tuple[ColumnaDetectada, ...]


@dataclass(frozen=True)
class EdicionManualFilaImportacion:
    """Sobreescritura de valores o exclusión manual de una fila de importación."""

    numero_fila: int
    valores: dict[str, str | None]
    omitir: bool = False


@dataclass(frozen=True)
class FilaPrevisualizacionImportacion:
    """Fila parseada y diagnosticada lista para presentar en la UI y persistir."""

    numero_fila: int
    unidad_texto: str
    direccion: str
    piso: str | None
    depto: str | None
    m2: int | None
    propietario: str | None
    inquilino_nombre: str | None
    inquilino_telefono: str | None
    inquilino_email: str | None
    fecha_inicio: date | None
    fecha_fin_informativa: date | None
    monto_inicial_centavos: int | None
    dia_vencimiento: int
    dias_gracia: int
    tasa_diaria_bp: int
    ciclo_ipc_meses: int
    redondeo: int
    estado: EstadoFilaImportacion
    errores: tuple[str, ...]
    advertencias: tuple[str, ...]
    defaults_aplicados: tuple[str, ...]
    es_importable: bool
    tiene_celdas_combinadas: bool = False


@dataclass(frozen=True)
class PrevisualizacionImportacion:
    """Resumen y lista completa de filas para la revisión antes de confirmar."""

    total_filas: int
    filas_listas: int
    filas_con_errores: int
    filas_omitidas: int
    filas: tuple[FilaPrevisualizacionImportacion, ...]
    advertencias_generales: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResultadoImportacion:
    """Balance de entidades creadas tras la confirmación atómica."""

    departamentos_creados: int
    contratos_creados: int
    unidades_omitidas: int


# --- Parsers puros en español sin float -------------------------------------


def parsear_monto_importacion(valor: ValorCeldaCruda) -> int | None:
    """Convierte un valor de celda a centavos enteros (> 0) sin usar floats.

    Acepta int, Decimal y str en formato es-AR (ej. '$ 380.000,50' o '380000').
    Rechaza floats, booleanos, monedas extranjeras y formatos ambiguos.
    """
    if valor is None:
        return None
    if isinstance(valor, bool) or isinstance(valor, float):
        raise ErrorDeValidacion("El monto no puede ser float ni booleano.", campo="monto")

    if isinstance(valor, int):
        if valor <= 0:
            raise ErrorDeValidacion("El monto de la cuota debe ser mayor a 0.", campo="monto")
        return valor * 100

    if isinstance(valor, Decimal):
        if valor <= 0:
            raise ErrorDeValidacion("El monto de la cuota debe ser mayor a 0.", campo="monto")
        if valor.as_tuple().exponent < -2:
            raise ErrorDeValidacion("El monto no puede tener más de 2 decimales.", campo="monto")
        return int((valor * 100).to_integral_value())

    if isinstance(valor, str):
        s = limpiar_espacios(valor)
        if not s:
            return None
        s_lower = s.casefold()
        if "usd" in s_lower or "u$s" in s_lower:
            raise ErrorDeValidacion("Solo se admiten montos en pesos argentinos ($).", campo="monto")

        s = s.replace("$", "").strip()

        # Validación de formato ambiguo anglosajón: coma de miles y punto decimal
        if re.search(r",\d{3}\.\d+", s) or re.search(r",\d{3},\d+", s):
            raise ErrorDeValidacion(
                "Formato de monto ambiguo o anglosajón. Usá coma para decimales y punto para miles.",
                campo="monto",
            )
        if s.count(",") > 1:
            raise ErrorDeValidacion("El monto tiene múltiples separadores decimales.", campo="monto")

        if "," in s and "." in s:
            partes = s.split(",")
            parte_entera = partes[0].replace(".", "")
            parte_decimal = partes[1]
            s_norm = f"{parte_entera}.{parte_decimal}"
        elif "," in s:
            s_norm = s.replace(",", ".")
        elif "." in s:
            partes = s.split(".")
            if len(partes) > 2:
                # Ej: 1.200.000 -> miles
                s_norm = "".join(partes)
            else:
                # Si son 3 dígitos después del punto, ej. 380.000 -> miles
                if len(partes[1]) == 3 and len(partes[0]) <= 3:
                    s_norm = "".join(partes)
                else:
                    s_norm = s
        else:
            s_norm = s

        try:
            dec = Decimal(s_norm)
        except InvalidOperation as exc:
            raise ErrorDeValidacion(f"Monto inválido: «{valor}».", campo="monto") from exc

        if dec <= 0:
            raise ErrorDeValidacion("El monto de la cuota debe ser mayor a 0.", campo="monto")
        if dec.as_tuple().exponent < -2:
            raise ErrorDeValidacion("El monto no puede tener más de 2 decimales.", campo="monto")

        return int((dec * 100).to_integral_value())

    raise ErrorDeValidacion(f"Tipo de monto no soportado: {type(valor)}", campo="monto")


def parsear_fecha_importacion(
    valor: ValorCeldaCruda, nombre_campo: str = "fecha"
) -> date | None:
    """Convierte un valor de celda a date con año en 2000..2100.

    Rechaza seriales numéricos de Excel sin formato y años de 2 dígitos.
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        raise ErrorDeValidacion(f"Fecha inválida en {nombre_campo}.", campo=nombre_campo)

    if isinstance(valor, datetime):
        valor = valor.date()

    if isinstance(valor, date):
        if not (2000 <= valor.year <= 2100):
            raise ErrorDeValidacion(
                f"El año de {nombre_campo} debe estar entre 2000 y 2100 ({valor.year}).",
                campo=nombre_campo,
            )
        return valor

    if isinstance(valor, (int, Decimal)):
        raise ErrorDeValidacion(
            f"Fecha en formato numérico ({valor}) no reconocida. Usá formato dd/mm/aaaa.",
            campo=nombre_campo,
        )

    if isinstance(valor, str):
        s = limpiar_espacios(valor)
        if not s:
            return None
        partes = re.split(r"[/.-]", s)
        if len(partes) == 3:
            try:
                if len(partes[0]) == 4:
                    y, m, d = int(partes[0]), int(partes[1]), int(partes[2])
                else:
                    if len(partes[2]) == 2:
                        raise ErrorDeValidacion(
                            "El año debe tener 4 dígitos (ej. 2026).",
                            campo=nombre_campo,
                        )
                    d, m, y = int(partes[0]), int(partes[1]), int(partes[2])
                if not (2000 <= y <= 2100):
                    raise ErrorDeValidacion(
                        f"El año de {nombre_campo} debe estar entre 2000 y 2100 ({y}).",
                        campo=nombre_campo,
                    )
                return date(y, m, d)
            except ValueError as exc:
                raise ErrorDeValidacion(
                    f"Fecha inválida en {nombre_campo}: «{valor}».", campo=nombre_campo
                ) from exc

        raise ErrorDeValidacion(
            f"Formato de fecha no reconocido en {nombre_campo}: «{valor}». Usá dd/mm/aaaa.",
            campo=nombre_campo,
        )

    raise ErrorDeValidacion(f"Tipo de fecha no soportado: {type(valor)}", campo=nombre_campo)


def parsear_tasa_mora_importacion(valor: ValorCeldaCruda) -> int | None:
    """Convierte una tasa de mora diaria a puntos básicos (0..10.000 bp)."""
    if valor is None:
        return None
    if isinstance(valor, bool) or isinstance(valor, float):
        raise ErrorDeValidacion(
            "La tasa de mora no puede ser float ni booleano.", campo="tasa_mora"
        )

    if isinstance(valor, int):
        if not (0 <= valor <= 10_000):
            raise ErrorDeValidacion(
                "La tasa de mora debe estar entre 0 y 10.000 bp.", campo="tasa_mora"
            )
        return valor

    if isinstance(valor, str):
        s = limpiar_espacios(valor).casefold()
        if not s:
            return None
        if s.endswith("bp"):
            try:
                val = int(s[:-2].strip())
            except ValueError as exc:
                raise ErrorDeValidacion(
                    f"Tasa de mora inválida: «{valor}».", campo="tasa_mora"
                ) from exc
            if not (0 <= val <= 10_000):
                raise ErrorDeValidacion(
                    "La tasa de mora debe estar entre 0 y 10.000 bp.", campo="tasa_mora"
                )
            return val
        if s.endswith("%"):
            texto_num = s[:-1].strip().replace(",", ".")
            try:
                dec = Decimal(texto_num)
            except InvalidOperation as exc:
                raise ErrorDeValidacion(
                    f"Tasa de mora inválida: «{valor}».", campo="tasa_mora"
                ) from exc
            bp = int((dec * 100).to_integral_value())
            if not (0 <= bp <= 10_000):
                raise ErrorDeValidacion(
                    "La tasa de mora debe estar entre 0 % y 100 % (10.000 bp).",
                    campo="tasa_mora",
                )
            return bp
        # Número sin sufijo
        texto_num = s.replace(",", ".")
        try:
            dec = Decimal(texto_num)
        except InvalidOperation as exc:
            raise ErrorDeValidacion(
                f"Tasa de mora inválida: «{valor}».", campo="tasa_mora"
            ) from exc
        if "." in texto_num:
            bp = int((dec * 100).to_integral_value())
        else:
            bp = int(dec)
        if not (0 <= bp <= 10_000):
            raise ErrorDeValidacion(
                "La tasa de mora debe estar entre 0 y 10.000 bp.", campo="tasa_mora"
            )
        return bp

    if isinstance(valor, Decimal):
        if valor <= 1:
            bp = int((valor * 10000).to_integral_value())
        else:
            bp = int(valor.to_integral_value())
        if not (0 <= bp <= 10_000):
            raise ErrorDeValidacion(
                "La tasa de mora debe estar entre 0 y 10.000 bp.", campo="tasa_mora"
            )
        return bp

    raise ErrorDeValidacion(f"Tipo de mora no soportado: {type(valor)}", campo="tasa_mora")


def parsear_ciclo_importacion(valor: ValorCeldaCruda) -> int | None:
    """Convierte el ciclo de ajuste IPC a cantidad de meses (entero > 0)."""
    if valor is None:
        return None
    mapa_textos = {
        "mensual": 1,
        "bimestral": 2,
        "trimestral": 3,
        "cuatrimestral": 4,
        "semestral": 6,
        "anual": 12,
    }
    s = limpiar_espacios(str(valor)).casefold()
    if not s:
        return None
    if s in mapa_textos:
        return mapa_textos[s]
    s_limpio = s.replace("meses", "").replace("mes", "").strip()
    if s_limpio in mapa_textos:
        return mapa_textos[s_limpio]
    if isinstance(valor, int):
        if valor <= 0:
            raise ErrorDeValidacion("El ciclo de ajuste debe ser mayor a 0.", campo="ciclo_ipc")
        return valor
    try:
        val = int(s_limpio)
        if val <= 0:
            raise ErrorDeValidacion("El ciclo de ajuste debe ser mayor a 0.", campo="ciclo_ipc")
        return val
    except ValueError as exc:
        raise ErrorDeValidacion(
            f"Ciclo de ajuste inválido: «{valor}». Debe ser un número de meses o Trimestral/Semestral.",
            campo="ciclo_ipc",
        ) from exc


def parsear_redondeo_importacion(valor: ValorCeldaCruda) -> int | None:
    """Convierte el redondeo a 1 (centavos) o 100 ($ 100)."""
    if valor is None:
        return None
    s = limpiar_espacios(str(valor)).casefold()
    if not s:
        return None
    if s in ("1", "centavos", "exacto", "sin redondeo"):
        return 1
    if s in ("100", "$ 100", "$100", "100 pesos", "cien pesos"):
        return 100
    if isinstance(valor, int) and valor in (1, 100):
        return valor
    raise ErrorDeValidacion(
        f"Redondeo inválido: «{valor}». Debe ser 1 (centavos) o 100 ($ 100).",
        campo="redondeo",
    )


def es_fila_vacia_o_totales(fila: FilaCrudaExcel) -> bool:
    """Detecta si una fila no tiene datos útiles o corresponde a totales/resumen."""
    if not any(v is not None and str(v).strip() != "" for v in fila.valores):
        return True
    primer_no_vacio = next(
        (
            limpiar_espacios(str(v)).casefold()
            for v in fila.valores
            if v is not None and str(v).strip() != ""
        ),
        "",
    )
    if primer_no_vacio.startswith(("total", "totales", "suma", "promedio", "resumen")):
        return True
    return False


def _tokens_encabezado(texto: str) -> tuple[str, str]:
    """Entrega el token directo y el token sin contenido entre paréntesis."""
    t1 = limpiar_espacios(texto).casefold()
    t2 = limpiar_espacios(re.sub(r"\(.*?\)", "", t1))
    return t1, t2


def detectar_fila_encabezado(filas: tuple[FilaCrudaExcel, ...]) -> int:
    """Busca en las primeras 10 filas la fila con >= 2 coincidencias con encabezados conocidos."""
    mejor_fila = 1
    max_coincidencias = 0

    for fila in filas[:10]:
        coincidencias = 0
        for val in fila.valores:
            if not isinstance(val, str):
                continue
            t1, t2 = _tokens_encabezado(val)
            if not t1:
                continue
            for sinonimos in SINONIMOS_CAMPOS.values():
                if t1 in sinonimos or (t2 and t2 in sinonimos):
                    coincidencias += 1
                    break
        if coincidencias >= 2 and coincidencias > max_coincidencias:
            max_coincidencias = coincidencias
            mejor_fila = fila.numero_fila

    return mejor_fila


def sugerir_mapeo_columnas(
    fila_encabezados: FilaCrudaExcel,
    primera_fila_datos: FilaCrudaExcel | None = None,
) -> list[ColumnaDetectada]:
    """Sugiere el mapeo de columnas del archivo a los 16 campos canónicos de Brickly."""
    columnas_detectadas: list[ColumnaDetectada] = []
    campos_asignados: set[str] = set()

    tokens_encabezados = [
        _tokens_encabezado(str(val))[0] if val is not None else ""
        for val in fila_encabezados.valores
    ]
    tiene_cuota_vigente = any("cuota vigente" in t for t in tokens_encabezados)

    for idx, val in enumerate(fila_encabezados.valores):
        nombre_orig = limpiar_espacios(str(val)) if val is not None else ""
        t1, t2 = _tokens_encabezado(nombre_orig)

        campo_sugerido = None
        if t1 and t1 not in ("estado",):
            if "cuota inicial" in t1 and tiene_cuota_vigente:
                campo_sugerido = None
            else:
                for campo, sinonimos in SINONIMOS_CAMPOS.items():
                    if campo not in campos_asignados and (
                        t1 in sinonimos or (t2 and t2 in sinonimos)
                    ):
                        campo_sugerido = campo
                        campos_asignados.add(campo)
                        break

        ejemplo = None
        if primera_fila_datos is not None and idx < len(primera_fila_datos.valores):
            v_ej = primera_fila_datos.valores[idx]
            if v_ej is not None and str(v_ej).strip() != "":
                ejemplo = str(v_ej)

        columnas_detectadas.append(
            ColumnaDetectada(
                indice=idx,
                nombre_original=nombre_orig or f"Columna {idx + 1}",
                campo_mapeado=campo_sugerido,
                primer_valor_ejemplo=ejemplo,
            )
        )

    # Si no se mapeó dirección pero sí Unidad o Departamento
    if "direccion" not in campos_asignados:
        for idx, col in enumerate(columnas_detectadas):
            if col.campo_mapeado is None:
                tok = col.nombre_original.casefold()
                if tok in ("unidad", "departamento", "propiedad", "inmueble"):
                    columnas_detectadas[idx] = ColumnaDetectada(
                        indice=col.indice,
                        nombre_original=col.nombre_original,
                        campo_mapeado="direccion",
                        primer_valor_ejemplo=col.primer_valor_ejemplo,
                    )
                    campos_asignados.add("direccion")
                    break

    return columnas_detectadas


def _fmt_fecha(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


# --- Servicio de Aplicación --------------------------------------------------


class ServicioImportacionDepartamentos:
    """Coordina la inspección, previsualización e importación atómica de unidades."""

    def __init__(
        self,
        repositorio_departamentos: RepositorioDepartamentos,
        lector_excel: LectorExcel,
        reloj: Reloj,
        escritor_excel: EscritorExcel | None = None,
    ) -> None:
        self._repositorio = repositorio_departamentos
        self._lector = lector_excel
        self._reloj = reloj
        self._escritor = escritor_excel

    def inspeccionar_archivo(self, ruta: str) -> InspeccionArchivoImportacion:
        """Diagnostica el archivo, lista sus hojas y sugiere el mapeo de columnas."""
        hojas = self._lector.listar_hojas(ruta)
        if not hojas:
            raise ErrorDeNegocio("El libro de Excel no contiene ninguna hoja.")

        hoja_seleccionada = hojas[0]
        for h in hojas:
            h_lower = h.casefold()
            if "departamento" in h_lower or "contrato" in h_lower:
                hoja_seleccionada = h
                break

        hoja_cruda = self._lector.leer_hoja(ruta, hoja_seleccionada)
        fila_enc = detectar_fila_encabezado(hoja_cruda.filas)

        fila_enc_obj = next(
            (f for f in hoja_cruda.filas if f.numero_fila == fila_enc), None
        )
        if fila_enc_obj is None:
            fila_enc_obj = hoja_cruda.filas[0] if hoja_cruda.filas else FilaCrudaExcel(1, ())

        primera_datos_obj = next(
            (
                f
                for f in hoja_cruda.filas
                if f.numero_fila > fila_enc and not es_fila_vacia_o_totales(f)
            ),
            None,
        )

        cols = sugerir_mapeo_columnas(fila_enc_obj, primera_datos_obj)

        return InspeccionArchivoImportacion(
            ruta=ruta,
            hojas=tuple(hojas),
            hoja_seleccionada=hoja_seleccionada,
            fila_encabezado_detectada=fila_enc,
            columnas_detectadas=tuple(cols),
        )

    def previsualizar(
        self,
        ruta: str,
        nombre_hoja: str,
        fila_encabezado: int,
        mapeo: dict[str, int],
        ediciones: dict[int, EdicionManualFilaImportacion] | None = None,
    ) -> PrevisualizacionImportacion:
        """Procesa, valida, deduplica y devuelve el listado completo de filas analizadas."""
        hoja_cruda = self._lector.leer_hoja(ruta, nombre_hoja)
        hoy = self._reloj.hoy()
        pred = self._repositorio.predeterminados_contrato()

        filas_candidatas = [
            f
            for f in hoja_cruda.filas
            if f.numero_fila > fila_encabezado and not es_fila_vacia_o_totales(f)
        ]

        if len(filas_candidatas) > MAX_FILAS_IMPORTACION:
            raise ErrorDeNegocio(
                f"El archivo supera el límite máximo de {MAX_FILAS_IMPORTACION} filas de datos "
                f"({len(filas_candidatas)} filas encontradas)."
            )

        deptos_existentes = self._repositorio.listar()
        claves_existentes_db = {
            clave_unidad_normalizada(d.direccion, d.piso, d.depto)
            for d in deptos_existentes
        }

        filas_procesadas: list[FilaPrevisualizacionImportacion] = []
        mapa_ediciones = ediciones or {}

        for fila in filas_candidatas:
            edicion = mapa_ediciones.get(fila.numero_fila)

            # Extraemos valores mapeados
            valores_crudos: dict[str, ValorCeldaCruda] = {}
            for campo, col_idx in mapeo.items():
                if 0 <= col_idx < len(fila.valores):
                    valores_crudos[campo] = fila.valores[col_idx]
                else:
                    valores_crudos[campo] = None

            # Aplicamos edición manual de celdas si existe
            if edicion is not None and edicion.valores:
                for campo, val_editado in edicion.valores.items():
                    valores_crudos[campo] = val_editado

            errores_fila: list[str] = []
            advertencias_fila: list[str] = []
            defaults_aplicados: list[str] = []

            # Si el usuario eligió omitir manualmente esta fila
            if edicion is not None and edicion.omitir:
                unidad_txt = str(valores_crudos.get("direccion") or f"Fila {fila.numero_fila}")
                filas_procesadas.append(
                    FilaPrevisualizacionImportacion(
                        numero_fila=fila.numero_fila,
                        unidad_texto=unidad_txt,
                        direccion=str(valores_crudos.get("direccion") or ""),
                        piso=str(valores_crudos.get("piso")) if valores_crudos.get("piso") else None,
                        depto=str(valores_crudos.get("depto")) if valores_crudos.get("depto") else None,
                        m2=None,
                        propietario=None,
                        inquilino_nombre=None,
                        inquilino_telefono=None,
                        inquilino_email=None,
                        fecha_inicio=None,
                        fecha_fin_informativa=None,
                        monto_inicial_centavos=None,
                        dia_vencimiento=pred.dia_vencimiento,
                        dias_gracia=pred.dias_gracia,
                        tasa_diaria_bp=pred.tasa_mora_bp,
                        ciclo_ipc_meses=pred.ciclo_meses,
                        redondeo=pred.redondeo_centavos,
                        estado="omitido_manual",
                        errores=(),
                        advertencias=("Fila desmarcada manualmente.",),
                        defaults_aplicados=(),
                        es_importable=False,
                        tiene_celdas_combinadas=fila.tiene_celdas_combinadas,
                    )
                )
                continue

            # Parseo de dirección y desglose de unidad
            raw_dir = str(valores_crudos.get("direccion") or "")
            raw_piso = (
                str(valores_crudos["piso"])
                if valores_crudos.get("piso") is not None
                else None
            )
            raw_depto = (
                str(valores_crudos["depto"])
                if valores_crudos.get("depto") is not None
                else None
            )

            dir_desglosada, piso_desglosado, depto_desglosado = desglosar_unidad_compuesta(
                raw_dir, raw_piso, raw_depto
            )

            if not dir_desglosada:
                errores_fila.append("La dirección es obligatoria.")

            # m2
            m2_val = None
            if valores_crudos.get("m2") is not None and str(valores_crudos["m2"]).strip() != "":
                try:
                    m2_float = float(str(valores_crudos["m2"]).replace(",", "."))
                    m2_val = int(m2_float)
                    if m2_val <= 0:
                        errores_fila.append("Los m² deben ser un número mayor a 0.")
                except ValueError:
                    errores_fila.append(f"Superficie (m²) inválida: «{valores_crudos['m2']}».")

            # Propietario
            prop_val = (
                limpiar_espacios(str(valores_crudos["propietario"]))
                if valores_crudos.get("propietario") is not None
                else None
            )

            # Inquilino
            inq_nombre = (
                limpiar_espacios(str(valores_crudos["nombre_inquilino"]))
                if valores_crudos.get("nombre_inquilino") is not None
                else None
            )
            inq_tel = (
                limpiar_espacios(str(valores_crudos["telefono_inquilino"]))
                if valores_crudos.get("telefono_inquilino") is not None
                else None
            )
            inq_email = (
                limpiar_espacios(str(valores_crudos["email_inquilino"]))
                if valores_crudos.get("email_inquilino") is not None
                else None
            )

            # Fechas y montos de contrato
            f_inicio = None
            f_fin = None
            monto_centavos = None

            try:
                f_inicio = parsear_fecha_importacion(
                    valores_crudos.get("fecha_inicio"), "inicio de contrato"
                )
            except ErrorDeValidacion as exc:
                errores_fila.append(str(exc))

            try:
                f_fin = parsear_fecha_importacion(
                    valores_crudos.get("fecha_fin"), "fin de contrato"
                )
            except ErrorDeValidacion as exc:
                errores_fila.append(str(exc))

            try:
                monto_centavos = parsear_monto_importacion(
                    valores_crudos.get("monto_inicial_centavos")
                )
            except ErrorDeValidacion as exc:
                errores_fila.append(str(exc))

            # Condiciones de cuota y mora
            dia_venc = pred.dia_vencimiento
            if valores_crudos.get("dia_vencimiento") is not None and str(valores_crudos["dia_vencimiento"]).strip() != "":
                try:
                    dia_venc = int(str(valores_crudos["dia_vencimiento"]).strip())
                    if not (1 <= dia_venc <= 28):
                        errores_fila.append("El día de vencimiento debe estar entre 1 y 28.")
                except ValueError:
                    errores_fila.append("El día de vencimiento debe ser un número entero entre 1 y 28.")
            else:
                defaults_aplicados.append(f"Vencimiento: día {pred.dia_vencimiento}")

            d_gracia = pred.dias_gracia
            if valores_crudos.get("dias_gracia") is not None and str(valores_crudos["dias_gracia"]).strip() != "":
                try:
                    d_gracia = int(str(valores_crudos["dias_gracia"]).strip())
                    if d_gracia < 0:
                        errores_fila.append("Los días de gracia no pueden ser negativos.")
                except ValueError:
                    errores_fila.append("Los días de gracia deben ser un entero mayor o igual a 0.")
            else:
                defaults_aplicados.append(f"Gracia: {pred.dias_gracia} días")

            tasa_mora = pred.tasa_mora_bp
            if valores_crudos.get("tasa_diaria_bp") is not None and str(valores_crudos["tasa_diaria_bp"]).strip() != "":
                try:
                    parsed_mora = parsear_tasa_mora_importacion(valores_crudos["tasa_diaria_bp"])
                    if parsed_mora is not None:
                        tasa_mora = parsed_mora
                except ErrorDeValidacion as exc:
                    errores_fila.append(str(exc))
            else:
                defaults_aplicados.append(f"Mora: {pred.tasa_mora_bp / 100:.2f} % diaria")

            ciclo_ipc = pred.ciclo_meses
            if valores_crudos.get("ciclo_ipc_meses") is not None and str(valores_crudos["ciclo_ipc_meses"]).strip() != "":
                try:
                    parsed_ciclo = parsear_ciclo_importacion(valores_crudos["ciclo_ipc_meses"])
                    if parsed_ciclo is not None:
                        ciclo_ipc = parsed_ciclo
                except ErrorDeValidacion as exc:
                    errores_fila.append(str(exc))
            else:
                defaults_aplicados.append(f"Ciclo IPC: cada {pred.ciclo_meses} meses")

            redondeo_val = pred.redondeo_centavos
            if valores_crudos.get("redondeo") is not None and str(valores_crudos["redondeo"]).strip() != "":
                try:
                    parsed_red = parsear_redondeo_importacion(valores_crudos["redondeo"])
                    if parsed_red is not None:
                        redondeo_val = parsed_red
                except ErrorDeValidacion as exc:
                    errores_fila.append(str(exc))
            else:
                defaults_aplicados.append(
                    f"Redondeo: {'$ 100' if pred.redondeo_centavos == 100 else 'Centavos'}"
                )

            # Clasificación de contrato vs vacante
            hay_contrato = any([
                inq_nombre,
                monto_centavos is not None,
                f_inicio is not None,
                f_fin is not None,
            ])

            estado: EstadoFilaImportacion = "nuevo_vacante"
            f_fin_informativa: date | None = None

            if hay_contrato:
                if not inq_nombre:
                    errores_fila.append("El nombre del inquilino es obligatorio si hay contrato.")
                if f_inicio is None:
                    errores_fila.append("La fecha de inicio de contrato es obligatoria.")
                if monto_centavos is None:
                    errores_fila.append("El monto de la cuota mensual es obligatorio.")

                if f_fin is not None and f_inicio is not None:
                    if f_fin < f_inicio:
                        errores_fila.append("La fecha de fin no puede ser anterior al inicio.")
                    elif f_fin < hoy:
                        estado = "nuevo_contrato_vencido"
                        advertencias_fila.append(
                            f"Contrato vencido el {_fmt_fecha(f_fin)}: se importará solo el departamento (vacante)."
                        )
                    else:
                        estado = "nuevo_con_contrato"
                        f_fin_informativa = f_fin
                else:
                    estado = "nuevo_con_contrato"

            unidad_nom = nombre_unidad(dir_desglosada, piso_desglosado, depto_desglosado)

            # Verificación de duplicado contra base de datos
            clave_norm = clave_unidad_normalizada(
                dir_desglosada, piso_desglosado, depto_desglosado
            )
            if clave_norm in claves_existentes_db:
                estado = "omitido_existente"
                advertencias_fila.append("Ya existe en Brickly; se omite para no duplicar.")

            if errores_fila:
                estado = "error"

            es_imp = estado in ("nuevo_con_contrato", "nuevo_vacante", "nuevo_contrato_vencido") and not errores_fila

            filas_procesadas.append(
                FilaPrevisualizacionImportacion(
                    numero_fila=fila.numero_fila,
                    unidad_texto=unidad_nom,
                    direccion=dir_desglosada,
                    piso=piso_desglosado,
                    depto=depto_desglosado,
                    m2=m2_val,
                    propietario=prop_val,
                    inquilino_nombre=inq_nombre,
                    inquilino_telefono=inq_tel,
                    inquilino_email=inq_email,
                    fecha_inicio=f_inicio,
                    fecha_fin_informativa=f_fin_informativa,
                    monto_inicial_centavos=monto_centavos,
                    dia_vencimiento=dia_venc,
                    dias_gracia=d_gracia,
                    tasa_diaria_bp=tasa_mora,
                    ciclo_ipc_meses=ciclo_ipc,
                    redondeo=redondeo_val,
                    estado=estado,
                    errores=tuple(errores_fila),
                    advertencias=tuple(advertencias_fila),
                    defaults_aplicados=tuple(defaults_aplicados),
                    es_importable=es_imp,
                    tiene_celdas_combinadas=fila.tiene_celdas_combinadas,
                )
            )

        # Deduplicación intra-archivo según ADR-0005 §3
        filas_finales = self._deduplicar_intra_archivo(filas_procesadas, hoy)

        total = len(filas_finales)
        listas = sum(1 for f in filas_finales if f.es_importable and not f.errores)
        con_err = sum(1 for f in filas_finales if f.estado == "error" or f.errores)
        omitidas = sum(1 for f in filas_finales if not f.es_importable and not f.errores)

        return PrevisualizacionImportacion(
            total_filas=total,
            filas_listas=listas,
            filas_con_errores=con_err,
            filas_omitidas=omitidas,
            filas=tuple(filas_finales),
        )

    def _deduplicar_intra_archivo(
        self,
        filas: list[FilaPrevisualizacionImportacion],
        hoy: date,
    ) -> list[FilaPrevisualizacionImportacion]:
        """Resuelve unidades que aparecen más de una vez en el mismo archivo."""
        # Agrupamos por clave canónica solo las que compiten por crearse
        grupos: dict[tuple[str, str, str], list[FilaPrevisualizacionImportacion]] = {}
        for f in filas:
            if f.estado in ("nuevo_con_contrato", "nuevo_vacante", "nuevo_contrato_vencido") and not f.errores:
                clave = clave_unidad_normalizada(f.direccion, f.piso, f.depto)
                grupos.setdefault(clave, []).append(f)

        ganadoras_por_clave: dict[tuple[str, str, str], FilaPrevisualizacionImportacion] = {}
        perdedoras_ids: set[int] = set()

        for clave, grupo in grupos.items():
            if len(grupo) <= 1:
                continue

            # 1. Contratos vigentes a hoy
            vigentes = [
                f
                for f in grupo
                if f.estado == "nuevo_con_contrato"
                and f.fecha_inicio is not None
                and f.fecha_inicio <= hoy
                and (f.fecha_fin_informativa is None or f.fecha_fin_informativa >= hoy)
            ]
            if vigentes:
                # Más reciente por fecha_inicio, y mayor numero_fila ante empate
                ganadora = max(
                    vigentes,
                    key=lambda x: (x.fecha_inicio or date.min, x.numero_fila),
                )
            else:
                # 2. Contratos futuros
                futuros = [
                    f
                    for f in grupo
                    if f.estado == "nuevo_con_contrato"
                    and f.fecha_inicio is not None
                    and f.fecha_inicio > hoy
                ]
                if futuros:
                    ganadora = max(
                        futuros,
                        key=lambda x: (x.fecha_inicio or date.min, x.numero_fila),
                    )
                else:
                    # 3. Solo vacantes o vencidos: la última fila gana
                    ganadora = max(grupo, key=lambda x: x.numero_fila)

            ganadoras_por_clave[clave] = ganadora
            for f in grupo:
                if f.numero_fila != ganadora.numero_fila:
                    perdedoras_ids.add(f.numero_fila)

        # Reconstruimos la lista preservando orden
        resultado: list[FilaPrevisualizacionImportacion] = []
        for f in filas:
            clave = clave_unidad_normalizada(f.direccion, f.piso, f.depto)
            if f.numero_fila in perdedoras_ids:
                ganadora = ganadoras_por_clave[clave]
                resultado.append(
                    FilaPrevisualizacionImportacion(
                        numero_fila=f.numero_fila,
                        unidad_texto=f.unidad_texto,
                        direccion=f.direccion,
                        piso=f.piso,
                        depto=f.depto,
                        m2=f.m2,
                        propietario=f.propietario,
                        inquilino_nombre=f.inquilino_nombre,
                        inquilino_telefono=f.inquilino_telefono,
                        inquilino_email=f.inquilino_email,
                        fecha_inicio=f.fecha_inicio,
                        fecha_fin_informativa=f.fecha_fin_informativa,
                        monto_inicial_centavos=f.monto_inicial_centavos,
                        dia_vencimiento=f.dia_vencimiento,
                        dias_gracia=f.dias_gracia,
                        tasa_diaria_bp=f.tasa_diaria_bp,
                        ciclo_ipc_meses=f.ciclo_ipc_meses,
                        redondeo=f.redondeo,
                        estado="omitido_contrato_anterior",
                        errores=f.errores,
                        advertencias=(
                            *f.advertencias,
                            f"Unidad repetida en fila {ganadora.numero_fila}; se omite este contrato anterior.",
                        ),
                        defaults_aplicados=f.defaults_aplicados,
                        es_importable=False,
                        tiene_celdas_combinadas=f.tiene_celdas_combinadas,
                    )
                )
            elif clave in ganadoras_por_clave and f.numero_fila == ganadoras_por_clave[clave].numero_fila:
                resultado.append(
                    FilaPrevisualizacionImportacion(
                        numero_fila=f.numero_fila,
                        unidad_texto=f.unidad_texto,
                        direccion=f.direccion,
                        piso=f.piso,
                        depto=f.depto,
                        m2=f.m2,
                        propietario=f.propietario,
                        inquilino_nombre=f.inquilino_nombre,
                        inquilino_telefono=f.inquilino_telefono,
                        inquilino_email=f.inquilino_email,
                        fecha_inicio=f.fecha_inicio,
                        fecha_fin_informativa=f.fecha_fin_informativa,
                        monto_inicial_centavos=f.monto_inicial_centavos,
                        dia_vencimiento=f.dia_vencimiento,
                        dias_gracia=f.dias_gracia,
                        tasa_diaria_bp=f.tasa_diaria_bp,
                        ciclo_ipc_meses=f.ciclo_ipc_meses,
                        redondeo=f.redondeo,
                        estado=f.estado,
                        errores=f.errores,
                        advertencias=(
                            *f.advertencias,
                            "Unidad con múltiples filas en el archivo (se importó esta versión).",
                        ),
                        defaults_aplicados=f.defaults_aplicados,
                        es_importable=f.es_importable,
                        tiene_celdas_combinadas=f.tiene_celdas_combinadas,
                    )
                )
            else:
                resultado.append(f)

        return resultado

    def importar(
        self,
        ruta: str,
        nombre_hoja: str,
        fila_encabezado: int,
        mapeo: dict[str, int],
        ediciones: dict[int, EdicionManualFilaImportacion] | None = None,
    ) -> ResultadoImportacion:
        """Confirma e inserta atómicamente las unidades y contratos válidos."""
        preview = self.previsualizar(
            ruta=ruta,
            nombre_hoja=nombre_hoja,
            fila_encabezado=fila_encabezado,
            mapeo=mapeo,
            ediciones=ediciones,
        )

        if preview.filas_con_errores > 0:
            raise ErrorDeNegocio(
                f"No se puede importar: hay {preview.filas_con_errores} fila(s) con errores. "
                "Corregilas o desmarcalas antes de continuar."
            )

        items_persistir: list[ItemImportacionPersistible] = []

        for f in preview.filas:
            if not f.es_importable:
                continue

            depto = Departamento(
                direccion=f.direccion,
                piso=f.piso,
                depto=f.depto,
                m2=f.m2,
                propietario=f.propietario,
            )

            if f.estado == "nuevo_con_contrato":
                if f.inquilino_nombre is None or f.fecha_inicio is None or f.monto_inicial_centavos is None:
                    continue
                inq = Inquilino(
                    nombre=f.inquilino_nombre,
                    telefono=f.inquilino_telefono,
                    email=f.inquilino_email,
                )
                contrato = Contrato(
                    fecha_inicio=f.fecha_inicio,
                    monto_centavos=f.monto_inicial_centavos,
                    dia_vencimiento=f.dia_vencimiento,
                    dias_gracia=f.dias_gracia,
                    tasa_mora_bp=f.tasa_diaria_bp,
                    ciclo_meses=f.ciclo_ipc_meses,
                    redondeo_centavos=f.redondeo,
                    fecha_fin=None,  # Invariante ADR-0005 §1
                )
                items_persistir.append(
                    ItemImportacionPersistible(
                        departamento=depto,
                        inquilino=inq,
                        contrato=contrato,
                    )
                )
            else:
                # nuevo_vacante o nuevo_contrato_vencido
                items_persistir.append(
                    ItemImportacionPersistible(
                        departamento=depto,
                        inquilino=None,
                        contrato=None,
                    )
                )

        if not items_persistir:
            return ResultadoImportacion(
                departamentos_creados=0,
                contratos_creados=0,
                unidades_omitidas=preview.filas_omitidas,
            )

        deptos_creados, contratos_creados = self._repositorio.guardar_lote_importacion(
            items_persistir
        )

        return ResultadoImportacion(
            departamentos_creados=deptos_creados,
            contratos_creados=contratos_creados,
            unidades_omitidas=preview.filas_omitidas,
        )

    def generar_plantilla(self, ruta_destino: str) -> str:
        """Crea una plantilla .xlsx con 16 columnas y 2 ejemplos prácticos."""
        if self._escritor is None:
            raise ErrorDeNegocio("No se ha configurado un escritor de Excel.")

        columnas = (
            ColumnaExcel("Dirección", "texto"),
            ColumnaExcel("Piso", "texto"),
            ColumnaExcel("Depto", "texto"),
            ColumnaExcel("Superficie (m²)", "entero"),
            ColumnaExcel("Propietario", "texto"),
            ColumnaExcel("Inquilino", "texto"),
            ColumnaExcel("Teléfono", "texto"),
            ColumnaExcel("Email", "texto"),
            ColumnaExcel("Inicio contrato", "fecha"),
            ColumnaExcel("Fin contrato", "fecha"),
            ColumnaExcel("Cuota mensual ($)", "moneda"),
            ColumnaExcel("Día vencimiento", "entero"),
            ColumnaExcel("Días gracia", "entero"),
            ColumnaExcel("Mora diaria (%)", "texto"),
            ColumnaExcel("Ciclo IPC (meses)", "entero"),
            ColumnaExcel("Redondeo", "texto"),
        )

        hoy = self._reloj.hoy()
        fecha_fin_ejemplo = date(hoy.year + 2, hoy.month, min(hoy.day, 28))

        filas = (
            FilaExcel(
                valores=(
                    "Av. Rivadavia 3421",
                    "3",
                    "B",
                    48,
                    "Carlos Rodríguez",
                    "Lucía Gómez",
                    "11-4567-8901",
                    "lucia.gomez@email.com",
                    hoy,
                    fecha_fin_ejemplo,
                    380_000_00,  # 380.000 en centavos
                    10,
                    5,
                    "0.15%",
                    3,
                    "Centavos",
                )
            ),
            FilaExcel(
                valores=(
                    "Sarmiento 890",
                    "PB",
                    "A",
                    35,
                    "María Fernández",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            ),
        )

        hoja = HojaExportable(
            nombre="Departamentos y Contratos",
            columnas=columnas,
            filas=filas,
        )

        libro = LibroExportable(
            fecha_generacion=hoy,
            hojas=(hoja,),
        )

        self._escritor.escribir(ruta_destino, libro)
        return ruta_destino
