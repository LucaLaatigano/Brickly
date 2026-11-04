# ADR-0002: Reglas de negocio confirmadas del MVP (ajuste IPC, redondeo, vencimiento, mora)

- **Status:** aceptada
- **Fecha:** 2026-10-15
- **Aplica a:** `brickly/dominio/`, `brickly/aplicacion/`, `brickly/ui/` (textos y flujos)

## Contexto

El plan del MVP dejó 4 preguntas de negocio abiertas. La spec UX/UI
(`docs/ux/especificacion-ux-ui.md`) avanzó con defaults declarados y el usuario
los confirmó el 2026-10-15. Este ADR los asienta para que dominio, aplicación y
UI no los re-deriven cada uno por su lado.

## Decisión

1. **Impacto del ajuste IPC:** un ajuste confirmado aplica a las cuotas que se
   generen **después** de la confirmación (próximo período). No recalcula
   cuotas ya emitidas ni pagos ya hechos. El historial de ajustes es inmutable.
2. **Redondeo de cuota:** a centavos por defecto; configurable a `$ 100` en
   Configuración. El redondeo es una regla de dominio explícita (ADR-0001 ya lo
   exige), nunca un efecto colateral de floats.
3. **Día de vencimiento:** fijo mes a mes (ej. 10). Si cae fin de semana no se
   corre; no hay corrimiento a día hábil en v1.
4. **Mora:** interés simple diario sobre el saldo impago (cuota − pagado), tras
   los días de gracia. La UI la muestra "a hoy" (vía `Reloj`) y queda congelada
   al momento del pago. No hay interés compuesto.

## Tradeoff aceptado

- Reglas simples y predecibles para un administrador único; menos fidelidad a
  prácticas bancarias (corrimiento a día hábil, interés compuesto).
- El ajuste no retroactivo mantiene el historial contable estable: corregir una
  cuota ya emitida exigiría un flujo de corrección que el MVP no necesita.

## Revisit if

- El usuario pide ajuste retroactivo sobre cuotas ya emitidas → diseñar flujo
  de corrección/nota de crédito antes de tocar la regla.
- Aparecen contratos con reglas propias (interés compuesto, corrimiento a día
  hábil) → modelar por contrato; no cambiar el default.
- El redondeo a `$ 100` genera diferencias que alguien reclama → revisar si el
  redondeo va por cuota o por total.
