# Plan Pront — BotTrading

Este documento reúne el plan de trabajo en formato rápido, claro y accionable para empezar de inmediato.

---

## 1. Meta principal

Llevar el proyecto desde su estado actual a un sistema operativo, verificable y listo para evolucionar hacia autonomía segura.

---

## 2. Prioridad 1 — Hacer que el sistema funcione localmente

### Objetivo
Hacer que el proyecto arranque correctamente en Windows sin depender de procesos manuales complicados.

### Pasos
1. Verificar que todos los servicios puedan arrancar.
2. Revisar variables de entorno como JWT, URLs internas y base de datos.
3. Ajustar los scripts de inicio y parada.
4. Confirmar que los endpoints de salud responden.
5. Validar que el frontend pueda comunicarse con el gateway.

### Resultado esperado
El sistema queda operativo en local y listo para pruebas reales.

---

## 3. Prioridad 2 — Validar el flujo completo del producto

### Objetivo
Comprobar que el usuario puede completar el recorrido real del sistema.

### Pasos
1. Crear cuenta.
2. Iniciar sesión.
3. Configurar mercados.
4. Conectar un broker en modo demo.
5. Ejecutar un backtest.
6. Crear un bot en paper.
7. Revisar órdenes, riesgo y alertas.

### Resultado esperado
El flujo completo funciona de principio a fin.

---

## 4. Prioridad 3 — Mejorar la experiencia de usuario

### Objetivo
Que el sistema sea más claro, simple y fácil de operar.

### Pasos
1. Mejorar el dashboard.
2. Hacer visibles los estados de servicios y bots.
3. Reducir la complejidad de configuración.
4. Mejorar mensajes de error y feedback al usuario.

### Resultado esperado
El usuario entiende qué ocurre y puede operar sin confusión.

---

## 5. Prioridad 4 — Implementar autonomía segura

### Objetivo
Que el sistema pueda aprender, recomendar y ejecutar de forma segura.

### Pasos
1. Recoger métricas de rendimiento.
2. Generar recomendaciones automáticas.
3. Crear un modo auto-safe.
4. Añadir un botón para activar/desactivar el modo.
5. Registrar todo lo que haga el sistema.

### Resultado esperado
El sistema puede trabajar de forma casi autónoma, pero con control humano.

---

## 6. Prioridad 5 — Preparar escalabilidad y producción

### Objetivo
Dejar el proyecto listo para crecer y trabajar en entorno más serio.

### Pasos
1. Mejorar seguridad de tokens y credenciales.
2. Fortalecer observabilidad.
3. Preparar despliegue real.
4. Revisar rate limiting y límites de escalado.

### Resultado esperado
El proyecto está más cerca de producción sin perder estabilidad.

---

## 7. Orden exacto de ejecución

1. Estabilizar arranque local.
2. Validar flujo de usuario.
3. Mejorar experiencia.
4. Añadir recomendaciones y auto-safe.
5. Preparar producción.

---

## 8. Criterio de éxito

El proyecto estará en buen camino cuando:

- arranca correctamente,
- permite registrar y operar de forma real,
- muestra información útil al usuario,
- y permite activar o detener automatización con control.
