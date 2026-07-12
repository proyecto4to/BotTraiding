# Tareas técnicas — Implementación del modo autónomo seguro

Esta lista convierte el plan de autonomía en tareas concretas para el desarrollo del proyecto. Está pensada para implementarse por etapas, priorizando primero la observación y las recomendaciones antes de pasar a ejecución automática.

---

## Fase 1 — Observación y métricas base

### Backend
- [ ] Crear modelo o estructura para almacenar métricas de estrategia.
- [ ] Registrar rendimiento por estrategia, símbolo, timeframe y modo.
- [ ] Guardar eventos de riesgo, órdenes y estado de bots.
- [ ] Exponer un endpoint para consultar métricas agregadas.

### Frontend
- [ ] Añadir una vista de métricas en el dashboard.
- [ ] Mostrar win rate, drawdown, profit factor y equity reciente.
- [ ] Mostrar estado de salud del bot y eventos recientes.

### Priorización
- [ ] Esta fase debe quedar lista antes de implementar cualquier recomendación automática.

---

## Fase 2 — Modo recomendador

### Backend
- [ ] Implementar un scorer simple para estrategias.
- [ ] Generar recomendaciones basadas en rendimiento reciente.
- [ ] Definir reglas para recomendar: aumentar/ disminuir riesgo, pausar estrategia, priorizar otra estrategia, o revisar configuración.
- [ ] Crear endpoint para obtener recomendaciones del sistema.

### Frontend
- [ ] Mostrar recomendaciones con nivel de confianza y motivo.
- [ ] Añadir acciones de aceptar/rechazar recomendación.
- [ ] Mostrar historial de recomendaciones aplicadas o ignoradas.

### Seguridad
- [ ] Las recomendaciones no deben modificar nada por sí solas.
- [ ] Deben quedar registradas para auditoría.

---

## Fase 3 — Ejecución segura limitada

### Backend
- [ ] Añadir un modo de ejecución “auto-safe”.
- [ ] Definir límites de riesgo por cuenta o bot.
- [ ] Bloquear cualquier cambio que exceda esos límites.
- [ ] Integrar el Risk Engine como guardián obligatorio.

### Frontend
- [ ] Añadir un switch para activar el modo auto-safe.
- [ ] Mostrar qué cambios están permitidos y cuáles quedaron bloqueados.

### Seguridad
- [ ] Toda acción automática debe pasar por validación de riesgo.
- [ ] Si el riesgo supera el umbral, debe detenerse y reportarse.

---

## Fase 4 — Modo automático con kill switch

### Backend
- [ ] Añadir un estado global: off / recommendations-only / auto-safe / auto-full.
- [ ] Crear un kill switch por bot y por cuenta.
- [ ] Asegurar que cualquier decisión automática pueda detenerse de inmediato.
- [ ] Registrar cada acción automática con timestamp, motivo y resultado.

### Frontend
- [ ] Añadir botón de activación/desactivación del modo automático.
- [ ] Mostrar estado actual y último evento automático.
- [ ] Permitir detener el modo desde la interfaz.

### Seguridad
- [ ] Debe existir siempre una ruta manual para detener la automatización.
- [ ] El sistema debe poder pausar ante condiciones adversas.

---

## Fase 5 — Aprendizaje continuo

### Backend
- [ ] Comparar rendimiento actual con desempeño histórico.
- [ ] Detectar estrategias degradadas o sobreajustadas.
- [ ] Ajustar ponderaciones según contexto de mercado.
- [ ] Reentrenar o reoptimizar parámetros con límites seguros.

### Frontend
- [ ] Mostrar qué aprendió el sistema y qué cambió.
- [ ] Permitir revisar cambios auto-aplicados.

### Seguridad
- [ ] Los cambios de aprendizaje deben estar siempre dentro del marco de riesgo.

---

## Tareas transversales

- [ ] Documentar el flujo del modo automático en el manual de usuario.
- [ ] Añadir tests para métricas, recomendaciones y limitación de riesgo.
- [ ] Preparar logs y auditoría para cada decisión automática.
- [ ] Definir qué usuarios pueden activar el modo automático.
- [ ] Definir qué roles tienen acceso a cambiar la configuración automática.

---

## Orden sugerido de implementación

1. Métricas base.
2. Recomendaciones simples.
3. Auto-safe con validación de riesgo.
4. Kill switch y activación/desactivación.
5. Aprendizaje continuo.

---

## Criterio de éxito

La implementación será exitosa cuando:

- el sistema pueda analizar desempeño reciente,
- pueda proponer acciones útiles,
- aplique cambios dentro de límites seguros,
- y el usuario solo tenga que activar o detener el modo automático.
