# Manual de Usuario — BotTrading

Esta guía resume el flujo de uso normal de la plataforma, desde el arranque hasta
la ejecución de un bot en modo paper. La regla de oro del sistema es:
**backtest → paper → real**, en ese orden, sin saltarse etapas.

---

## 1. Qué es BotTrading

BotTrading es una plataforma modular para operar estrategias automatizadas sobre
mercados financieros. La arquitectura está pensada para separar responsabilidades
por servicios: autenticación, riesgo, cartera, ejecución, backtesting, AI y
orquestación. El usuario final normalmente interactúa con el dashboard web y con
la API del gateway, mientras el sistema procesa cada orden a través de los
servicios correspondientes.

---

## 2. Requisitos previos

Antes de usar la plataforma, asegurate de tener:

- Windows 10/11 con PowerShell disponible.
- Python 3.11 o superior.
- Node.js 18+ y npm.
- Docker Desktop opcional, solo si querés correr la pila completa con contenedores.
- Una cuenta de correo para registrarte.

Si vas a usar brokers reales, también necesitás:

- Claves API válidas del broker.
- Permisos de trading adecuados.
- Un capital inicial pequeño para comenzar.

---

## 3. Encender el sistema

### Opción A — Local (Windows, sin Docker)

Desde la raíz del repositorio, ejecutá:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-bottrading.ps1
```

Esto levanta:

- Los servicios backend principales.
- El frontend en el puerto 3000.
- Los logs locales en la carpeta logs/.

Accesos esperados:

- Dashboard: http://localhost:3000
- Gateway/API: http://localhost:8000
- Auth service: http://localhost:8001

Para detener todo:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-bottrading.ps1
```

### Opción B — Docker

Si tenés Docker Desktop instalado, podés usar la pila completa:

```bash
cp infra/docker/.env.example infra/docker/.env
# completar los valores en el archivo .env
docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env up --build
```

En este modo además tendrás acceso a Grafana en:

- http://localhost:3001

> Si el dashboard muestra servicios caídos o el sistema responde con errores,
> lo más común es que alguno de los servicios no haya arrancado correctamente o
> esté corriendo código viejo. En ese caso, repetí el ciclo de stop + start.

---

## 4. Crear tu cuenta

1. Abrí http://localhost:3000.
2. Entrá en Register y completá email y contraseña.
3. El primer usuario con el email configurado en la variable
   `AUTH_BOOTSTRAP_ADMIN_EMAIL` recibe el rol `admin` al registrarse o al iniciar
   sesión, siempre que aún no exista ningún administrador.
4. Si querés, activá MFA con una app como Google Authenticator o Authy.

### Roles disponibles

- `admin`: controla mercados globales, riesgo, modo real y administración.
- `trader`: puede operar y configurar estrategias.
- `viewer`: acceso de solo lectura.
- `auditor`: consulta auditoría y eventos del sistema.

Un administrador asigna roles a los demás usuarios.

---

## 5. Configurar mercados

En la sección Markets, el administrador habilita las clases de activo globales,
como cripto, acciones o forex. Luego cada usuario activa los mercados que desea
usar. Un bot solo podrá operar en mercados habilitados en ambos niveles.

Esto evita que un usuario intente operar activos que no están permitidos por la
configuración del sistema.

---

## 6. Conectar un broker

Antes de operar, necesitás definir un broker.

### Recomendación inicial

Usá siempre el modo Demo primero. El sistema está pensado para validar el flujo
completo sin exponer dinero real.

### Binance

El conector más completo es Binance. Podés generar claves gratuitas en el
Testnet:

- https://testnet.binance.vision

Usá el modo Demo del conector para operar con dinero ficticio en un entorno de
prueba real. La documentación específica del conector está en
`services/broker-connectors/README-binance.md`.

> Las claves API nunca se muestran de vuelta ni aparecen en los logs.

---

## 7. Elegir y probar estrategias

En la sección Strategies podés ver la biblioteca de estrategias disponibles.
Cada estrategia muestra:

- descripción,
- mercados y timeframes compatibles,
- parámetros editables,
- validaciones de rango.

No conviene activar una estrategia a ciegas. Lo correcto es evaluar primero su
comportamiento con backtesting.

---

## 8. Backtesting — probar antes de arriesgar

En la sección Backtests, elegí:

- estrategia,
- símbolo,
- timeframe,
- rango de fechas,
- capital inicial.

El motor de backtesting simula el comportamiento con fricciones realistas, como:

- spread,
- slippage,
- comisiones,
- gaps,
- liquidez.

### Cómo leer los resultados

| Métrica | Qué mirar |
|---|---|
| Sharpe | Mayor a 1 es aceptable; mayor a 1.5 suele ser bueno. |
| Max Drawdown | ¿La caída sería tolerable con dinero real? |
| Profit Factor | Mayor a 1.3 suele indicar que las ganancias superan las pérdidas. |
| Win Rate + Expectancy | Un win rate bajo puede ser rentable si la expectancy es positiva. |
| Número de trades | Menos de 30 trades da resultados poco confiables. |

Probá la estrategia en distintos regímenes del mercado: tendencia, lateralidad y
crisis. Una estrategia que solo funciona en una condición concreta suele fallar
cuando el mercado cambia.

---

## 9. Configurar el riesgo antes del primer bot

En la sección Risk definí límites por cuenta. Lo mínimo recomendado es:

- riesgo por operación,
- pérdida máxima diaria/semanal/mensual,
- drawdown máximo,
- exposición,
- leverage.

Toda orden pasa por estos controles. Si un parámetro se excede, la orden se
rechaza y queda registrada en el sistema.

### Circuit breakers

El sistema puede detenerse automáticamente con:

- `SOFT_HALT`: no abre nuevas posiciones.
- `HARD_HALT`: recomienda cerrar todo.

Solo un administrador puede resetear estos estados.

---

## 10. Crear tu primer bot en paper

Un bot está compuesto por:

- cuenta,
- broker,
- símbolo o símbolos,
- timeframe,
- estrategia o estrategias,
- intervalo de ejecución.

### Flujo recomendado

1. Creá el bot en modo paper.
2. Ejecutá `run-once` para ver un ciclo completo:
   - lectura de velas,
   - generación de señales,
   - validación de riesgo,
   - ejecución simulada.
3. Si el resultado es correcto, iniciá el bot.

### Comportamiento del bot

- Se ejecuta cada cierto intervalo de tiempo.
- Si falla durante varios ciclos seguidos, se detiene automáticamente.
- Si el sistema se reinicia, los bots no retoman solos; quedan marcados para
  revisión.

---

## 11. Monitorear el sistema

La plataforma ofrece varias vistas para supervisar el rendimiento:

- Dashboard: equity, PnL, drawdown, posiciones abiertas y estado general.
- Executions: historial de órdenes y modo de operación (demo/live).
- Alerts: eventos de riesgo y ejecución.

También podés configurar notificaciones por correo, Telegram o webhook. Un
`HARD_HALT` suele llegar como un evento crítico.

---

## 12. Dejar que el sistema aprenda

La parte de IA y optimización ayuda a mejorar la selección de estrategias:

- El AI Engine clasifica el régimen del mercado y sugiere qué estrategias
  ponderar.
- El Optimizer reevalúa parámetros con validación out-of-sample.
- Los cambios solo se promueven si demuestran mejorar el rendimiento en datos
  no usados durante la optimización.

Estas funciones complementan, pero no reemplazan, el proceso de backtesting y
validación manual.

---

## 13. Pasar a dinero real

El modo live debe considerarse solo cuando el sistema ya ha sido probado con
suficiente profundidad.

### Requisitos mínimos

1. Varias semanas de paper trading con resultados consistentes.
2. Métricas de paper comparables con las del backtest.
3. Límites de riesgo probados y documentados.
4. Claves reales del broker con permisos de trading.

El cambio a live es principalmente de configuración. La lógica es la misma que
en paper; lo que cambia es el destino de las órdenes.

> Empezá con el mínimo capital que permita el broker y mantene controles de riesgo
> estrictos.

---

## 14. Problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| Gateway unreachable | Servicios caídos o código viejo | Repetí stop + start |
| Servicios abajo en salud | Algunos servicios no arrancaron | Revisá los logs y repetí el arranque |
| 401 constante | Token vencido o secreto distinto entre servicios | Re-login y verificar `JWT_SECRET` |
| Broker no conecta | Claves inválidas o testnet caído | Regenerá las claves y comprobá la conexión |
| Orden rechazada | Validación de riesgo | Revisá el motivo en Alerts o en los eventos de riesgo |

Logs locales:

- `logs/<servicio>.err.log`

En Docker:

```bash
docker compose logs <servicio>
```

---

## 15. Flujo recomendado para empezar

Si es tu primera vez usando la plataforma, seguí este orden:

1. Arrancar el sistema.
2. Crear cuenta y entrar.
3. Configurar mercados.
4. Conectar un broker en modo demo.
5. Probar estrategias en backtest.
6. Definir límites de riesgo.
7. Crear un bot en paper.
8. Monitorear y ajustar.
9. Solo luego considerar pasar a live.

Este flujo evita errores costosos y ayuda a validar que la plataforma funciona
correctamente antes de operar con capital real.

---

## 16. Sugerencias de mejoras para que aprenda solo

El objetivo ideal es que la plataforma no dependa de que el usuario esté
constantemente ajustando parámetros. La evolución recomendada es pasar de un
sistema guiado a uno con autonomía progresiva.

### 1) Modo aprendizaje automático con supervisión

- El sistema debería aprender de resultados históricos y de desempeño reciente.
- Podría ajustar pesos de estrategias, rangos de riesgo y parámetros de entrada
  de forma automática.
- El usuario solo debería activar o desactivar el modo de aprendizaje, no tener
  que modificar todo manualmente.

### 2) Recomendaciones automáticas en lugar de decisiones manuales

- En vez de pedir al usuario que elija cada ajuste, el sistema debería proponer:
  - qué estrategia priorizar,
  - qué mercado activar,
  - qué límites de riesgo revisar,
  - cuándo pausar o reiniciar un bot.
- El usuario mantendría el control final con un botón de aceptar o rechazar.

### 3) Autonomía segura

Para que sea confiable, la automatización debería trabajar en tres niveles:

- Nivel 1: sugerencias.
- Nivel 2: ejecución limitada con validación de riesgo.
- Nivel 3: ejecución completa, solo si el usuario habilita el modo auto.

Esto evita que el sistema tome decisiones peligrosas sin supervisión.

### 4) Aprendizaje continuo

El sistema debería:

- registrar resultados de cada estrategia,
- comparar rendimiento contra contexto de mercado,
- detectar patrones de caída o sobreajuste,
- proponer mejoras automáticamente.

Con el tiempo, la plataforma podría pasar de “seguir reglas” a “adaptar reglas”.

### 5) Experiencia ideal para el usuario

El flujo deseado sería este:

1. El usuario activa el modo automático.
2. El sistema analiza mercado, riesgo y desempeño.
3. Propone o aplica cambios dentro de límites seguros.
4. El usuario solo decide si lo habilita o lo detiene.

En esa visión, el usuario ya no tendría que hacer todo manualmente; solo
supervisaría y decidiría cuándo encender o apagar la automatización.

---

## 17. Visión futura

La meta final no es que el sistema opere sin control, sino que sea capaz de
aprender y adaptarse dentro de reglas claras de riesgo. El usuario debería
mantener una función simple:

- activar la automatización cuando quiera,
- desactivarla cuando lo considere necesario,
- revisar resultados y conservar el control final.

Ese equilibrio entre autonomía y seguridad es lo que haría a BotTrading más
útil, escalable y fácil de operar a largo plazo.

Para ver el plan concreto de implementación de esta visión, consultá
[docs/PLAN-AUTONOMIA.md](PLAN-AUTONOMIA.md).
