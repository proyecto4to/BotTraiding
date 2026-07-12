# Plan maestro de ejecución — BotTrading

## 1. Análisis del proyecto

El repositorio ya tiene una base sólida y una arquitectura bien definida:

- La arquitectura y la ruta de evolución están documentadas en [docs/ARCHITECTURE.md](ARCHITECTURE.md).
- El estado general del proyecto se describe en [README.md](../README.md).
- El repositorio está organizado como un monorepo modular con servicios Python independientes, un gateway, un frontend Next.js y una app móvil Flutter.
- La documentación indica que el proyecto ya cubre las fases 0–15 y que el flujo señal → riesgo → cartera → ejecución existe en modo paper.

Sin embargo, el punto actual de riesgo no es la arquitectura, sino la ejecución práctica:

- el arranque local en Windows todavía necesita estabilizarse,
- el flujo completo debe validarse de punta a punta,
- y la capa de autonomía debe desarrollarse de forma progresiva y segura.

## 2. Objetivo central

Convertir el proyecto de una base arquitectónica avanzada a un sistema realmente operativo, verificable y escalable, con una evolución clara hacia autonomía segura.

## 3. Plan que voy a seguir

### Fase A — Estabilizar la ejecución local

Objetivo: que el sistema arranque de forma confiable en Windows y pueda usarse sin depender de procesos manuales.

Tareas:

1. Verificar el arranque de cada servicio individualmente.
2. Asegurar variables de entorno y rutas correctas.
3. Dejar los scripts de inicio/paro funcionando de forma determinista.
4. Confirmar que los health endpoints responden correctamente.
5. Validar el flujo auth → gateway → frontend.

Prioridad: máxima.

### Fase B — Validar el flujo real del producto

Objetivo: comprobar que el sistema funciona como producto, no solo como arquitectura.

Tareas:

1. Registro e ingreso de usuarios.
2. Configuración de mercados y brokers.
3. Ejecución de backtesting.
4. Ejecución en paper con riesgo y cartera.
5. Monitoreo de órdenes, eventos y alerts.

Prioridad: máxima.

### Fase C — Pulir la experiencia de usuario

Objetivo: que el sistema sea más claro, usable y accionable para un usuario final.

Tareas:

1. Mejorar dashboard y estados visibles.
2. Hacer más transparente el estado de los servicios.
3. Simplificar la configuración de brokers y estrategias.
4. Mejorar la navegación y los mensajes de error.

Prioridad: alta.

### Fase D — Implementar autonomía segura

Objetivo: que el sistema pueda aprender y recomendar acciones, dejando al usuario solo la decisión de activar o detener el modo.

Tareas:

1. Recolectar métricas de rendimiento.
2. Generar recomendaciones automáticas.
3. Implementar un modo auto-safe con validación de riesgo.
4. Añadir un kill switch para detener la automatización.
5. Registrar auditoría de cada decisión automática.

Prioridad: alta.

### Fase E — Preparar producción y escalabilidad

Objetivo: dejar el sistema listo para crecer sin perder control.

Tareas:

1. Mejorar seguridad de credenciales y tokens.
2. Fortalecer observabilidad.
3. Preparar despliegue y configuración real.
4. Revisar límites de escalabilidad y rate limiting.

Prioridad: media.

## 4. Orden de ejecución

1. Arranque local estable.
2. Flujo end-to-end funcional.
3. UX y usabilidad.
4. Autonomía con seguridad.
5. Producción y escalabilidad.

## 5. Criterio de éxito

Se considera que el proyecto avanza correctamente cuando:

- el sistema arranca de forma confiable,
- el usuario puede completar el ciclo completo de registro, configuración y operación,
- el sistema muestra información útil y clara,
- y la automatización puede activarse o detenerse sin perder control.
