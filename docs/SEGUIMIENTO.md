# Seguimiento de implementación — BotTrading

Este documento sirve como hoja de seguimiento para avanzar de forma ordenada y sin perder contexto.

---

## Estado actual del proyecto

- La arquitectura base ya existe.
- El proyecto tiene documentación amplia y una estructura modular.
- El siguiente foco debe ser hacer que el sistema sea operativo, verificable y fácil de usar.

---

## Prioridad actual

1. Estabilizar el arranque local.
2. Validar el flujo completo del producto.
3. Mejorar la experiencia de usuario.
4. Implementar automatización segura.
5. Preparar escalabilidad.

---

## Seguimiento semanal

### Semana 1 — Estabilidad
- [ ] Verificar arranque de servicios.
- [ ] Corregir errores de entorno.
- [ ] Ajustar scripts de inicio y parada.
- [ ] Comprobar health endpoints.

### Semana 2 — Flujo de usuario
- [ ] Probar registro e inicio de sesión.
- [ ] Configurar mercados.
- [ ] Probar broker demo.
- [ ] Ejecutar backtest.
- [ ] Crear y lanzar un bot en paper.

### Semana 3 — UX
- [ ] Mejorar dashboard.
- [ ] Simplificar tareas repetitivas.
- [ ] Mejorar mensajes y validaciones.
- [ ] Hacer más claros los estados del sistema.

### Semana 4 — Autonomía
- [ ] Implementar métricas base.
- [ ] Crear recomendaciones simples.
- [ ] Añadir modo auto-safe.
- [ ] Implementar kill switch.

### Semana 5 — Producción
- [ ] Revisar seguridad.
- [ ] Mejorar logs y observabilidad.
- [ ] Preparar despliegue.
- [ ] Revisar escalabilidad.

---

## Reglas de seguimiento

- No avanzar a una nueva etapa sin cerrar la anterior.
- Cada cambio debe quedar documentado.
- Cada mejora debe tener un criterio visible de éxito.
- Si aparece un problema nuevo, registrarlo antes de seguir.

---

## Criterio de avance

Se considera avance real cuando:

- el sistema arranca sin problemas,
- se puede usar de forma completa,
- y la automatización puede activarse o detenerse con control.
