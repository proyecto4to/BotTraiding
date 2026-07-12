# Plan de desarrollo — Modo autónomo seguro

Este documento convierte la visión de “aprendizaje automático con supervisión” en un plan concreto para BotTrading. La idea central es simple: el usuario solo debe poder activar o desactivar el modo automático, mientras el sistema se encarga de analizar, proponer y, en fases posteriores, ejecutar acciones dentro de límites seguros.

---

## 1. Objetivo

Llegar a un estado en el que BotTrading pueda:

- aprender de resultados recientes,
- proponer mejoras de forma automática,
- aplicar cambios seguros dentro de reglas de riesgo,
- y dejar al usuario solo con la decisión de activar o detener el modo.

---

## 2. Visión del producto

El producto debe evolucionar en este orden:

1. El sistema observa y mide.
2. El sistema recomienda acciones.
3. El sistema ejecuta acciones seguras.
4. El usuario solo activa/desactiva el modo.

No se busca una autonomía total desde el inicio. La meta es una autonomía progresiva y segura.

---

## 3. Fases recomendadas

### Fase 1 — Observación y métricas base

Objetivo: que el sistema pueda “entender” qué está pasando.

Tareas:

- registrar rendimiento por estrategia,
- medir drawdown, win rate, expectancy, profit factor,
- capturar eventos de riesgo y ejecución,
- almacenar historial por símbolo, timeframe y modo (paper/live).

Entregable:

- un panel de métricas con contexto suficiente para tomar decisiones.

### Fase 2 — Modo recomendador

Objetivo: que el sistema sugiera acciones antes de ejecutarlas.

Tareas:

- calcular un score por estrategia,
- identificar mercados o configuraciones con mejor rendimiento,
- recomendar cambios de riesgo o de ponderación,
- mostrar recomendaciones en el dashboard con motivo y confianza.

Entregable:

- un modo “Asistente” donde el sistema propone mejoras y el usuario puede aceptar o rechazar.

### Fase 3 — Ejecución segura limitada

Objetivo: que el sistema aplique cambios automáticamente solo cuando estén dentro de límites seguros.

Tareas:

- definir reglas de seguridad por usuario o cuenta,
- limitar cambios a rangos preaprobados,
- bloquear acciones que excedan drawdown/risk thresholds,
- exigir validación del risk engine antes de aplicar cambios.

Entregable:

- un modo “Auto-Safe” que aplica solo acciones de bajo riesgo y siempre bajo supervisión técnica.

### Fase 4 — Modo automático con kill switch

Objetivo: que el usuario solo active o desactive el modo.

Tareas:

- agregar botón de activación/desactivación global,
- crear un kill switch por bot y por cuenta,
- implementar circuit breakers y pausa inmediata,
- definir auditoría completa de decisiones automáticas.

Entregable:

- un modo automático que puede activarse o detenerse en un clic.

### Fase 5 — Aprendizaje continuo

Objetivo: que el sistema mejore con el tiempo.

Tareas:

- comparar rendimiento histórico con condiciones actuales,
- ajustar ponderaciones según contexto de mercado,
- detectar estrategias degradadas,
- proponer reentrenamientos o reoptimización automática.

Entregable:

- un motor de adaptación que aprende de resultados, pero sin romper los límites de riesgo.

---

## 4. Priorización recomendada

### Prioridad 1 — MVP rápido

Implementar primero lo mínimo para que el sistema sea útil y seguro:

- métricas de rendimiento,
- recomendaciones básicas,
- botón de activación/desactivación,
- validación de riesgo obligatoria,
- registro de decisiones automáticas.

### Prioridad 2 — Mejoras de calidad

Luego agregar:

- recomendaciones más sofisticadas,
- selección automática de estrategias,
- reequilibrio de riesgo,
- alertas accionables.

### Prioridad 3 — Autonomía avanzada

Más adelante:

- aprendizaje adaptativo,
- optimización continua,
- ajuste dinámico de parámetros,
- coordinación entre IA, risk y execution.

---

## 5. Cambios de arquitectura esperados

### Servicios que deberían recibir trabajo

- AI Engine: para scoring y recomendaciones.
- Risk Engine: para bloquear decisiones inseguras.
- Trading Engine: para ejecutar decisiones automatizadas con control.
- Gateway: para exponer el estado del modo automático al frontend.
- Frontend: para mostrar recomendaciones, modo activo/desactivado y auditoría.

### Requisitos de seguridad

- toda decisión automática debe pasar por Risk Engine,
- el usuario debe poder detenerla en cualquier momento,
- cada acción automática debe quedar registrada,
- no debe existir una ruta que bypassée los circuit breakers.

---

## 6. Experiencia de usuario esperada

El flujo ideal debería ser este:

1. el usuario activa “Modo automático”,
2. el sistema analiza mercado, riesgo y desempeño,
3. propone o aplica cambios solamente dentro de límites seguros,
4. el usuario puede detenerlo cuando quiera,
5. el sistema deja un historial claro de lo que hizo y por qué.

Eso permite que la plataforma sea útil sin perder control.

---

## 7. Criterios de aceptación

El plan se considera cumplido cuando:

- el sistema puede recomendar acciones de forma clara,
- esas acciones pueden aprobarse o rechazarse por el usuario,
- algunas acciones se aplican automáticamente solo bajo límites seguros,
- el usuario puede activar/desactivar el modo en un clic,
- todo queda auditado y reversible.

---

## 8. Siguiente paso concreto

El siguiente paso práctico debería ser implementar la Fase 2 en una versión inicial:

- score de estrategias,
- recomendaciones visibles en el dashboard,
- botón de “aceptar/rechazar recomendación”,
- y el primer modo de asistencia automática con límites simples.
