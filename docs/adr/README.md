# Decisiones de arquitectura (ADR)

Una línea por decisión, en orden de numeración. Antes de una decisión de
estructura se lee lo ya decidido acá; una decisión aceptada se aplica, no se
re-deriva en silencio. Si cambia, se supersede con un ADR nuevo.

| # | Decisión | Status |
|---|----------|--------|
| [ADR-0001](0001-arquitectura-de-capas.md) | Puertos y adaptadores liviana (4 capas, flechas hacia adentro) | aceptada |
| [ADR-0002](0002-reglas-de-negocio-mvp.md) | Reglas de negocio del MVP: ajuste IPC no retroactivo, redondeo, vencimiento fijo, mora simple | aceptada |
| [ADR-0003](0003-ipc-automatico-indec.md) | Sincronización automática de IPC Nacional desde API INDEC (cálculo desde índice, token en Credential Manager, conflicto manual/API) | aceptada |
| [ADR-0004](0004-constancia-pago-pdf.md) | Constancia de pago mensual en PDF con ReportLab (solo cuotas pagadas, firma visual propietario/admin, no fiscal) | aceptada |


