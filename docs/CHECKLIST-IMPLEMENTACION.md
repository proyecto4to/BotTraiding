# Checklist de implementación — BotTrading

Este documento convierte el plan en tareas concretas para seguir paso a paso.

---

## Fase 1 — Hacer que funcione localmente

### Objetivo
Lograr que el proyecto arranque y quede operativo en Windows.

### Tareas
- [ ] Verificar que los servicios Python puedan arrancar uno por uno.
- [ ] Revisar que las rutas de Python y los paths del proyecto sean correctos.
- [ ] Confirmar que las variables de entorno necesarias estén definidas.
- [ ] Ajustar los scripts de inicio y parada.
- [ ] Comprobar que los puertos esperados respondan.
- [ ] Validar que el frontend pueda hablar con el gateway.
- [ ] Confirmar que los health endpoints respondan.

### Criterio de salida
- [ ] El sistema arranca localmente sin intervención manual compleja.

---

## Fase 2 — Validar el flujo completo

### Objetivo
Comprobar que un usuario puede usar el sistema de principio a fin.

### Tareas
- [ ] Crear una cuenta.
- [ ] Iniciar sesión.
- [ ] Configurar mercados.
- [ ] Conectar un broker en modo demo.
- [ ] Ejecutar un backtest.
- [ ] Crear un bot en paper.
- [ ] Revisar órdenes, riesgo y alertas.

### Criterio de salida
- [ ] El flujo completo funciona sin errores visibles.

---

## Fase 3 — Mejorar la experiencia de usuario

### Objetivo
Hacer que la plataforma sea más clara y simple de operar.

### Tareas
- [ ] Revisar el dashboard y detectar puntos confusos.
- [ ] Hacer visibles los estados de los servicios y bots.
- [ ] Simplificar la configuración de estrategias y brokers.
- [ ] Mejorar mensajes de error y validaciones.
- [ ] Reducir pasos innecesarios para tareas comunes.

### Criterio de salida
- [ ] Un usuario nuevo puede completar tareas básicas sin ayuda.

---

## Fase 4 — Implementar autonomía segura

### Objetivo
Que el sistema pueda aprender, recomendar y ejecutar con supervisión.

### Tareas
- [ ] Definir métricas de rendimiento básicas.
- [ ] Crear recomendaciones automáticas simples.
- [ ] Implementar un modo auto-safe.
- [ ] Añadir un botón para activar/desactivar el modo automático.
- [ ] Registrar decisiones automáticas para auditoría.
- [ ] Garantizar que el riesgo siga siendo el guardián final.

### Criterio de salida
- [ ] El sistema puede operar de forma casi autónoma, pero siempre bajo control humano.

---

## Fase 5 — Preparar producción y escalabilidad

### Objetivo
Dejar el proyecto preparado para crecer y operar con más robustez.

### Tareas
- [ ] Revisar seguridad de credenciales y tokens.
- [ ] Mejorar observabilidad y logs.
- [ ] Preparar despliegue y configuración de entorno real.
- [ ] Revisar rate limiting y escalabilidad.

### Criterio de salida
- [ ] El proyecto está mejor preparado para crecer sin perder estabilidad.

---

## Orden recomendado

1. Arranque local.
2. Flujo completo.
3. UX y usabilidad.
4. Autonomía segura.
5. Producción y escalabilidad.

---

## Regla de oro

No pasar a la siguiente fase hasta haber completado la anterior y verificado el resultado.
