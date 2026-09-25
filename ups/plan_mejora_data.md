Quiero mejorar la estrategia de actualización de datos del dashboard de la UPS para que algunos valores sean realmente "en vivo", pero sin generar consultas excesivas ni sobrecargar NUT, el backend o el navegador.

IMPORTANTE:
- No hacer polling independiente desde cada componente.
- No hacer una petición HTTP cada segundo para cada métrica.
- Una sola lectura de NUT debe alimentar todos los componentes del dashboard.
- Mantener separadas las lecturas en tiempo real, las consultas periódicas y los datos estáticos.
- No modificar la lógica existente de NUT/PVE/PBS si no es necesario.

==================================================
1. ARQUITECTURA RECOMENDADA
==================================================

La arquitectura debe ser:

                    APC UPS
                       ¦
                      USB
                       ¦
                       ?
                      NUT
                       ¦
                lectura cada ~2 s
                       ¦
                       ?
                UPS Collector
                       ¦
                estado en memoria
                       ¦
            +---------------------+
            ¦                     ¦
            ?                     ?
           SSE                  REST API
            ¦                     ¦
            ?                     ?
       Dashboard              Historial
       
El navegador NO debe consultar directamente NUT.

El backend debe consultar NUT y mantener el último estado disponible.

Todos los componentes del dashboard deben consumir el mismo estado centralizado.


==================================================
2. DATOS EN TIEMPO REAL
==================================================

Actualizar aproximadamente cada 2–5 segundos:

- ups.status
- battery.charge
- battery.runtime
- ups.load
- potencia actual en W
- input.voltage
- battery.voltage

Estos datos representan el estado operativo actual de la UPS.

No crear una petición HTTP independiente para cada uno.


==================================================
3. AUTONOMÍA
==================================================

La autonomía debe comportarse de forma especial.

NUT entrega algo como:

battery.runtime = 3040

El backend envía ese valor al frontend.

El frontend debe mostrar:

50:40

y realizar el conteo local:

50:40
50:39
50:38
50:37
...

Cada 2–5 segundos debe recibir una nueva lectura de NUT para sincronizar el contador.

NO hacer una petición HTTP cada segundo solamente para actualizar el contador.

El contador debe corregirse automáticamente cuando llegue una nueva lectura real.


==================================================
4. ESTADO DE LA UPS
==================================================

El cambio de estado debe ser considerado prioritario.

Ejemplos:

OL = Online
OB = On Battery
LB = Low Battery

Pero implementar correctamente múltiples flags de NUT cuando existan.

Cuando exista un cambio:

OL ? OB

el dashboard debe reflejarlo inmediatamente.

Ejemplo:

? POWER OUTAGE

UPS RUNNING ON BATTERY

49:52
AUTONOMY

117 W
CURRENT LOAD


Cuando regrese la energía:

OB ? OL

mostrar:

? POWER RESTORED

UPS RETURNED TO LINE POWER

y registrar el evento.


==================================================
5. SERVER-SENT EVENTS (SSE)
==================================================

Preferir SSE para el dashboard si la arquitectura actual lo permite.

Motivo:

El flujo principal es:

Servidor ? navegador

No se necesita WebSocket para actualizar continuamente las métricas.

Crear un endpoint conceptual:

GET /api/ups/stream

El backend puede enviar eventos como:

event: ups
data: {
   "status": "OL",
   "battery": 100,
   "runtime": 3040,
   "load": 13,
   "power": 117,
   "inputVoltage": 128,
   "batteryVoltage": 27.3,
   "updatedAt": "2026-09-25T07:38:05"
}

El frontend debe mantener una conexión SSE y actualizar el estado global del dashboard.


==================================================
6. ESTADO CENTRAL
==================================================

Crear un único estado de UPS en frontend.

Por ejemplo:

upsState = {
    status,
    battery,
    runtime,
    load,
    power,
    inputVoltage,
    batteryVoltage,
    lastUpdate,
    connected
}

Todos los componentes deben leer desde este estado.

No hacer:

Dashboard ? fetch batería
Dashboard ? fetch voltaje
Dashboard ? fetch consumo
Dashboard ? fetch autonomía

Todo debe provenir de:

UPS STATE


==================================================
7. FRECUENCIA DE ACTUALIZACIÓN
==================================================

Utilizar aproximadamente esta estrategia:

TIEMPO REAL / ~2-5 s:

- estado UPS
- batería
- autonomía
- carga
- potencia
- voltajes

~5–15 s:

- actualización de gráficas
- agregados
- estadísticas temporales

~30–60 s:

- persistencia o consolidación del histórico

SOLO CUANDO OCURRE:

- power outage
- power restored
- low battery
- critical battery
- NUT disconnected
- UPS disconnected
- recuperación de conexión


==================================================
8. DATOS ESTÁTICOS
==================================================

Consultar solamente al cargar la aplicación o cuando sea necesario:

- modelo
- fabricante
- serial
- firmware
- vendor ID
- product ID
- driver
- driver version
- potencia nominal
- configuración de la UPS

No actualizar estos datos constantemente.


==================================================
9. GRÁFICAS
==================================================

Las gráficas no necesitan actualizarse cada segundo.

Usar aproximadamente 5–15 segundos.

La gráfica puede recibir nuevos puntos agrupados o utilizar el estado recibido por SSE.

Evitar renderizar nuevamente toda la gráfica cada vez que cambia una métrica.

Actualizar solamente el punto o conjunto de puntos necesarios.


==================================================
10. INDICADOR LIVE
==================================================

Agregar en la interfaz:

? LIVE

Updated 2s ago

o equivalente.

El indicador LIVE debe reaccionar únicamente cuando llega una lectura real del backend.

Puede utilizar una microanimación muy sutil cuando llega una nueva lectura.

No mantener una animación constante.


==================================================
11. CONEXIÓN PERDIDA
==================================================

Si SSE o NUT dejan de responder:

mostrar claramente:

? NUT CONNECTION LOST

Last successful update:
12 sec ago

No presentar datos antiguos como si fueran actuales.

Agregar un campo:

connected: false

al estado global.


==================================================
12. RECONEXIÓN
==================================================

El frontend debe intentar reconectar SSE automáticamente.

Usar backoff progresivo razonable.

Ejemplo conceptual:

2 s
5 s
10 s
30 s

Cuando se recupere la conexión:

? NUT CONNECTION RESTORED

y actualizar inmediatamente los valores actuales.


==================================================
13. EVENTOS
==================================================

No generar eventos continuamente.

Generar eventos solamente cuando exista una transición real.

Ejemplos:

OL ? OB
OB ? OL
OB ? LB
LB ? CRITICAL
CONNECTED ? DISCONNECTED
DISCONNECTED ? CONNECTED

Ejemplo:

21:54:13
? Power outage detected

21:56:27
? Power restored

Guardar timestamp y duración cuando sea posible.


==================================================
14. CÁLCULO DE INCIDENTES
==================================================

Cuando ocurra:

OL ? OB

crear un incidente:

Power outage started

Guardar:

startedAt

Cuando vuelva:

OB ? OL

calcular:

endedAt
duration

Ejemplo:

POWER OUTAGE

Duration:
2m 14s

Battery at start:
100%

Battery at end:
94%

Average load:
117 W

Solo utilizar datos realmente disponibles.


==================================================
15. EVITAR POLLING EXCESIVO
==================================================

NO implementar algo como:

setInterval(() => {
    fetch('/api/ups')
}, 1000)

en varios componentes.

Tampoco:

fetch batería
fetch autonomía
fetch consumo
fetch voltaje
fetch estado

cada uno con su propio timer.

Debe existir una única fuente de actualización.


==================================================
16. POSIBLE ESTRUCTURA DE BACKEND
==================================================

Crear un servicio dedicado, por ejemplo:

UPSService
UPSMonitor
UPSCollector

Responsabilidades:

1. Consultar NUT.
2. Parsear las variables.
3. Mantener el estado actual.
4. Detectar cambios.
5. Crear eventos.
6. Emitir actualizaciones al frontend.
7. Guardar histórico si corresponde.

El controlador HTTP no debería ejecutar toda la lógica de NUT cada vez que llega una petición.


==================================================
17. CACHE / ESTADO
==================================================

Mantener el último estado de la UPS en memoria cuando sea suficiente.

No consultar NUT nuevamente para cada usuario conectado si todos pueden recibir el mismo estado.

Ejemplo:

NUT
 ?
Collector
 ?
Current UPS State
 ?
SSE
 ?
Usuarios


==================================================
18. MULTIUSUARIO
==================================================

La arquitectura debe soportar varios navegadores conectados.

Ejemplo:

NUT
  ?
Collector único
  ?
Estado global
  ?
SSE
 +-- navegador 1
 +-- navegador 2
 +-- navegador 3

No crear una consulta independiente a NUT por cada usuario.


==================================================
19. DASHBOARD
==================================================

Los elementos que deben actualizarse visualmente en tiempo real son:

- Estado ONLINE / ON BATTERY / CRITICAL
- porcentaje de batería
- autonomía
- carga
- consumo W
- voltaje de entrada
- voltaje de batería
- indicador LIVE
- última actualización

El resto puede actualizarse con menor frecuencia.


==================================================
20. VISUALIZACIÓN DE TIEMPO REAL
==================================================

Agregar microanimaciones:

Cuando cambia batería:

100% ? 99%

hacer una transición suave.

Cuando cambia carga:

13% ? 14%

animar ligeramente el valor.

Cuando llega una lectura:

? LIVE

hacer un pequeño pulse.

Cuando cambia OL ? OB:

mostrar transición de estado.

Las animaciones deben ser rápidas y discretas.


==================================================
21. POWER FLOW
==================================================

El componente Power Flow debe reaccionar en tiempo real.

ONLINE:

GRID ? UPS ? PVE

ON BATTERY:

GRID X
UPS ? PVE

OFFLINE/CRITICAL:

UPS ? PVE
? CRITICAL

El flujo energético debe cambiar sin recargar la página.


==================================================
22. OBJETIVO
==================================================

El resultado final debe sentirse como un sistema de monitoreo real.

Debe ser evidente:

? ONLINE
Updated 2s ago

50:38
Autonomía

100%
Battery

117 W
Power

128 V
Input

La interfaz debe cambiar inmediatamente cuando ocurra un corte eléctrico.

No esperar 30–60 segundos para mostrar un evento importante.

==================================================
23. REQUISITO FINAL DE IMPLEMENTACIÓN
==================================================

Antes de implementar:

1. Revisar la arquitectura actual.
2. Identificar cómo se consulta NUT.
3. Determinar dónde se puede mantener el estado actual.
4. Verificar si SSE ya está disponible.
5. Reutilizar endpoints existentes cuando sea posible.
6. Evitar romper compatibilidad con el dashboard actual.
7. Implementar primero el estado central.
8. Implementar el stream SSE.
9. Conectar los componentes.
10. Después optimizar gráficas y animaciones.

No crear complejidad innecesaria si el proyecto actual ya tiene una solución adecuada.

PRIORIDAD:

1. Exactitud de los datos
2. Detección rápida de cambios
3. Bajo consumo de recursos
4. UX
5. Animaciones