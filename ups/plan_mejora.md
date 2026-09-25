Quiero rediseñar completamente la interfaz del dashboard de mi UPS.

La interfaz actual funciona, pero visualmente parece un dashboard genérico de métricas. Quiero convertirla en una interfaz moderna, intuitiva, tecnológica y claramente orientada a monitoreo de infraestructura.

IMPORTANTE:
- No modificar la lógica de backend ni romper las integraciones actuales con NUT/PBS/PVE.
- Mantener todas las métricas y datos que ya existen.
- Mejorar principalmente UX/UI, jerarquía visual, navegación, componentes y visualización de datos.
- Antes de cambiar lógica existente, revisar cómo se obtienen actualmente los datos.
- No inventar métricas que el backend no pueda obtener.
- El diseño debe funcionar perfectamente en desktop, tablet y móvil.
- Mantener una arquitectura de componentes limpia y reutilizable.
- Evitar sobrecargar la pantalla con demasiadas tarjetas.
- La información más importante debe poder entenderse en menos de 2 segundos.

==================================================
1. CONCEPTO GENERAL
==================================================

Quiero que el dashboard tenga el concepto visual de:

"Centro de Energía / Infrastructure Power Center"

No quiero que parezca simplemente una página de estadísticas.

La aplicación debe transmitir:

- estado actual de la UPS
- autonomía
- flujo de energía
- consumo
- salud del sistema
- eventos importantes
- estado de PVE/PBS/NUT
- historial
- capacidad de reacción ante un apagón

La interfaz debe responder inmediatamente:

1. ¿La UPS está bien?
2. ¿Está usando red eléctrica o batería?
3. ¿Cuánta batería queda?
4. ¿Cuánto tiempo tengo?
5. ¿Cuánto estoy consumiendo?
6. ¿Hay algún problema?
7. ¿Qué ocurrió recientemente?
8. ¿PVE/NUT/PBS están funcionando?


==================================================
2. HEADER
==================================================

Rediseñar el header.

Actualmente muestra el nombre de la UPS y poco más.

Quiero algo similar a:

APC BR1500M2-LM
Back-UPS RS 1500M2
American Power Conversion
Firmware 962.f2 .D

A la derecha:

? ONLINE

y debajo o cerca:

USB ? Connected
NUT ? Running
PVE ? Running

También mostrar:

Última actualización
hace 2 s

El estado general debe ser muy visible.

Estados posibles:

ONLINE
ON BATTERY
LOW BATTERY
CRITICAL
OFFLINE
UNKNOWN

No utilizar únicamente texto para representar el estado; usar icono + texto + indicador visual.


==================================================
3. HERO PRINCIPAL
==================================================

La autonomía debe convertirse en el elemento visual principal de toda la aplicación.

Actualmente:

00:50:40

Quiero que sea mucho más protagonista.

Diseñar una sección principal tipo:

--------------------------------------------
 APC BR1500M2-LM                   ? ONLINE

              50:40
       AUTONOMÍA ESTIMADA

        ¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦
              100%

      Batería disponible

--------------------------------------------

El contador debe tener números grandes.

La autonomía debe actualizarse automáticamente.

Mostrar debajo información contextual:

"Basado en consumo actual de 117 W"

Esto ayuda a que el usuario entienda por qué la autonomía cambia.


==================================================
4. BATTERY VISUAL
==================================================

Rediseñar el indicador de batería.

No utilizar solamente una tarjeta con "100%".

Crear un indicador visual grande:

- batería vertical o circular
- porcentaje
- estado
- autonomía

Ejemplo conceptual:

100%
¦¦¦¦¦¦¦¦¦

Estados:

100–50% = normal
49–25% = warning
24–10% = critical
<10% = emergency

No depender exclusivamente del color.
Agregar texto y/o iconos para accesibilidad.


==================================================
5. POWER FLOW
==================================================

Agregar una sección central llamada:

POWER FLOW

Debe mostrar visualmente el flujo de energía:

RED ELÉCTRICA
        ?
     128 V
        ?
      UPS
   100% batería
        ?
      117 W
        ?
   INFRAESTRUCTURA

Visualmente quiero que parezca un pequeño diagrama de flujo animado.

Cuando esté ONLINE:

GRID ? UPS ? SERVER

Cuando esté ON BATTERY:

GRID X
   ?
UPS ? SERVER

Cuando esté OFFLINE:

UPS ? SERVER

La dirección del flujo debe ser visual.

Puede utilizar pequeñas partículas/animaciones muy sutiles recorriendo las líneas.

IMPORTANTE:
- Animaciones suaves.
- Nada exagerado.
- No convertir el dashboard en un videojuego.


==================================================
6. RESUMEN DE MÉTRICAS
==================================================

Después del bloque principal, mostrar solamente las métricas más importantes.

No quiero 8–10 tarjetas enormes.

Usar máximo 4:

BATTERY
100%

LOAD
13%

POWER
117 W

INPUT
128 V

Cada tarjeta debe tener:

icono
título
valor grande
unidad
pequeña descripción/contexto
mini tendencia cuando exista histórico

Ejemplo:

POWER
117 W
900 W nominal

LOAD
13%
13% de capacidad


==================================================
7. CONSUMO
==================================================

Crear una sección:

CONSUMPTION

La gráfica de consumo debe ser uno de los elementos importantes del dashboard.

Mostrar:

1h
6h
24h
7d
30d

Mantener las escalas correctas.

Añadir:

Current
Average
Peak

Por ejemplo:

Current: 117 W
Average: 82 W
Peak: 124 W

El usuario debe poder detectar rápidamente si el consumo está aumentando.


==================================================
8. GRÁFICAS
==================================================

Reducir el protagonismo de las gráficas secundarias.

No quiero cuatro gráficas iguales ocupando toda la pantalla.

Diseñar:

GRÁFICA PRINCIPAL
Consumo

y debajo:

Batería
Autonomía
Voltaje

Las secundarias pueden ser más pequeñas.

Usar tooltips modernos.

Cuando el usuario pase el mouse por un punto:

Hora
Consumo
Batería
Voltaje

No mostrar demasiada información simultáneamente si dificulta leerla.


==================================================
9. HEALTH / SYSTEM STATUS
==================================================

Agregar una sección:

SYSTEM STATUS

Mostrar:

? UPS connected
? NUT service running
? PVE reachable
? USB communication OK
? Datastore available

Adaptar esto a los servicios reales disponibles.

Ejemplo:

SYSTEM STATUS

UPS
Online

NUT
Running

PVE
Online

PBS
Online

Storage
Available

No inventar estados.

Si un servicio no puede comprobarse realmente, mostrar:

Not monitored

en lugar de asumir que funciona.


==================================================
10. HEALTH SCORE
==================================================

Crear un indicador visual de estado general.

Por ejemplo:

SYSTEM HEALTH

98%

UPS functioning normally

Pero NO calcular un porcentaje arbitrario sin una lógica clara.

Preferiblemente usar estados:

HEALTHY
WARNING
CRITICAL

El indicador debe basarse en condiciones reales.

Ejemplo:

HEALTHY:
- UPS online
- batería suficiente
- carga normal
- comunicación NUT correcta

WARNING:
- UPS en batería
- batería baja
- carga elevada

CRITICAL:
- runtime muy bajo
- UPS desconectada
- comunicación perdida


==================================================
11. EVENT TIMELINE
==================================================

Agregar una sección:

RECENT ACTIVITY

Ejemplo:

07:31
UPS operating normally

07:14
Input voltage 128 V

06:52
Load increased to 13%

Yesterday
Power outage detected
Duration: 42 sec

Yesterday
Power restored

Mostrar los eventos en formato timeline.

Cada evento debe tener:

timestamp
icono
descripción
valor relacionado cuando aplique

Clasificar los eventos:

INFO
WARNING
CRITICAL


==================================================
12. APAGADO AUTOMÁTICO
==================================================

Quiero una sección dedicada al comportamiento de apagado.

Mostrar solamente si realmente existe esa configuración.

Ejemplo:

AUTOMATIC SHUTDOWN

Enabled

Shutdown after:
10 min on battery

Current state:
Standby

Cuando ocurra un apagón:

POWER OUTAGE

Shutdown sequence starts in:

09:42

PVE
6/6 VMs online

PBS
Online

Cuando el apagado automático esté activo, esa información debe convertirse en una alerta visual mucho más importante.


==================================================
13. MODO EMERGENCIA
==================================================

Cuando la UPS entre en batería, el dashboard debe cambiar ligeramente de estado.

No cambiar completamente el diseño.

Mostrar claramente:

? POWER OUTAGE

UPS is running on battery

Autonomy:
47:32

Current load:
117 W

Estimated shutdown:
10:00

El contador debe ser muy visible.

Cuando la batería esté crítica:

CRITICAL POWER

Battery:
8%

Estimated runtime:
04:12

Shutdown sequence imminent


==================================================
14. INFORMACIÓN TÉCNICA
==================================================

Mover la información secundaria a una sección/página llamada:

DIAGNOSTICS

Aquí colocar:

Model
Manufacturer
Serial
Firmware
USB Vendor ID
USB Product ID
Battery voltage
Nominal voltage
Input voltage
Input sensitivity
Transfer low
Transfer high
UPS nominal power
Real power
Driver
Driver version
NUT status

No mostrar toda esta información en el dashboard principal.


==================================================
15. NAVEGACIÓN
==================================================

Crear navegación clara.

Idealmente:

Dashboard
History
Events
Diagnostics
Settings

No colocar todo en una sola página gigante.

Dashboard:
estado actual

History:
gráficas e históricos

Events:
timeline y cortes eléctricos

Diagnostics:
información técnica

Settings:
configuración disponible


==================================================
16. HISTORIAL DE APAGONES
==================================================

Esta funcionalidad sería especialmente útil.

Crear una sección:

POWER EVENTS

Ejemplo:

POWER OUTAGES

Sep 24
Duration: 42 sec

Sep 18
Duration: 3 min 14 sec

Aug 30
Duration: 1 min 03 sec

Mostrar:

fecha
duración
batería inicial
batería final
consumo promedio

Solo si esos datos pueden obtenerse realmente.


==================================================
17. INFORMACIÓN DE CARGA
==================================================

Actualmente:

13%

Quiero darle más contexto.

Ejemplo:

UPS LOAD

13%

117 W

900 W nominal

Capacity remaining:
783 W

Esto permite entender inmediatamente que 13% no es simplemente un número arbitrario.


==================================================
18. VOLTAJE
==================================================

Mostrar:

INPUT VOLTAGE

128 V

Nominal:
120 V

Range:
78–150 V

Y visualmente indicar si está dentro del rango.

También mostrar:

BATTERY VOLTAGE

27.3 V
Nominal 24 V


==================================================
19. TEMPERATURA
==================================================

No agregar temperatura si la UPS/NUT no proporciona ese dato.

Si en el futuro existe:

UPS TEMPERATURE

mostrarlo como métrica adicional.


==================================================
20. ANIMACIONES
==================================================

Usar microanimaciones.

Por ejemplo:

- actualización suave de valores
- contador de autonomía
- flujo de energía
- cambio de estado
- aparición de eventos
- hover de tarjetas
- transición entre rangos

NO utilizar:

- animaciones constantes innecesarias
- parpadeos
- elementos que distraigan
- efectos exagerados

La aplicación debe sentirse premium, no como una plantilla de dashboard.


==================================================
21. DARK MODE
==================================================

Mantener dark mode como tema principal.

El diseño actual oscuro está bien encaminado, pero mejorar:

- contraste
- jerarquía
- espacios
- tipografía
- separación entre paneles

Usar colores semánticos:

Verde:
normal

Amarillo:
warning

Rojo:
critical

Azul:
información

Cyan:
energía/infraestructura

No convertir todo el dashboard en una explosión de colores.


==================================================
22. LIGHT MODE
==================================================

Mantener soporte para light mode si el proyecto ya lo tiene.

No hacer simplemente una inversión de colores.

El light mode debe tener contraste y jerarquía propios.


==================================================
23. TIPOGRAFÍA
==================================================

Usar una tipografía moderna y tecnológica pero altamente legible.

Los números de:

- autonomía
- batería
- consumo
- voltaje

deben tener jerarquía tipográfica fuerte.

Evitar poner demasiados textos pequeños.


==================================================
24. ICONOGRAFÍA
==================================================

Utilizar una familia de iconos consistente.

Ejemplos:

Battery
Zap
Gauge
Activity
Server
Database
Wifi/USB
Shield
AlertTriangle
Clock
Power

No mezclar estilos diferentes de iconos.


==================================================
25. RESPONSIVE
==================================================

En desktop:

Layout amplio con varias columnas.

En tablet:

Reducir columnas.

En móvil:

Orden prioritario:

1. Estado UPS
2. Autonomía
3. Batería
4. Consumo
5. Voltaje
6. Power Flow
7. Estado sistema
8. Eventos
9. Gráficas

El contador de autonomía debe seguir siendo protagonista en móvil.


==================================================
26. ACCESSIBILITY
==================================================

No depender únicamente del color.

Por ejemplo:

? ONLINE
? WARNING
? CRITICAL

Los elementos interactivos deben tener:

- focus visible
- labels
- aria-label cuando sea necesario
- contraste suficiente


==================================================
27. ACTUALIZACIÓN EN TIEMPO REAL
==================================================

Mantener la actualización automática actual.

Mostrar:

Last updated:
2s ago

Evitar recargar toda la página.

Actualizar únicamente los componentes necesarios.

Cuando haya error:

Connection lost

Last successful update:
12 sec ago

No mostrar valores viejos como si fueran actuales.


==================================================
28. ESTADO DE CONEXIÓN
==================================================

Crear un pequeño indicador persistente:

? NUT Connected

o

? NUT Disconnected

Si NUT deja de responder:

? NUT CONNECTION LOST

y explicar cuándo fue la última lectura válida.


==================================================
29. TOAST / NOTIFICACIONES
==================================================

Implementar notificaciones visuales discretas para eventos importantes.

Ejemplo:

? Power outage detected

UPS switched to battery.

Otro:

? Power restored

UPS returned to online mode.


==================================================
30. ESTADOS VACÍOS / ERRORES
==================================================

Diseñar estados para:

- UPS desconectada
- NUT desconectado
- sin datos históricos
- API caída
- datos incompletos
- error de comunicación
- UPS desconocida

No dejar tarjetas vacías o valores "undefined".


==================================================
31. DISEÑO VISUAL
==================================================

Quiero un diseño:

Modern
Premium
Clean
Technical
Minimal
Infrastructure-focused

Inspiración conceptual:

- monitoring de datacenter
- observabilidad
- sistemas eléctricos
- interfaces de infraestructura
- dashboards de DevOps modernos

NO copiar interfaces de marcas concretas.

Evitar el típico:

+--------+
¦ 100%   ¦
+--------+
+--------+
¦ 13%    ¦
+--------+

Quiero una composición más inteligente y jerárquica.


==================================================
32. PROPUESTA DE DISTRIBUCIÓN
==================================================

La pantalla principal debe tener aproximadamente:

HEADER

?


HERO / UPS STATUS

AUTONOMÍA
ESTADO
BATERÍA


?

POWER FLOW


?

4 MÉTRICAS

BATTERY | LOAD | POWER | INPUT


?

SYSTEM STATUS


?

CONSUMPTION GRAPH


?

EVENTS + SECONDARY GRAPHS


No intentar mostrar todo de una vez.


==================================================
33. DASHBOARD PRINCIPAL PROPUESTO
==================================================

La estructura visual aproximada debería ser:

------------------------------------------------------

APC BR1500M2-LM                         ? ONLINE
Back-UPS RS 1500M2                     Updated 2s ago


------------------------------------------------------

                  50:40

              AUTONOMÍA ESTIMADA

          ¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦
                   100%

           Based on 117 W load


------------------------------------------------------

GRID ---------? UPS ---------? PVE
128 V          100%            117 W


------------------------------------------------------

BATTERY       LOAD          POWER        INPUT
100%          13%           117 W        128 V


------------------------------------------------------

SYSTEM STATUS

UPS       ? Online
NUT       ? Running
PVE       ? Online
PBS       ? Online


------------------------------------------------------

CONSUMPTION

[ gráfico ]

1h   6h   24h   7d   30d


------------------------------------------------------

RECENT ACTIVITY

? 07:31 UPS online
? 07:14 Input voltage 128 V
? Yesterday power restored


------------------------------------------------------


==================================================
34. IMPORTANTE SOBRE LOS DATOS
==================================================

Actualmente la UPS entrega datos como:

battery.charge
battery.runtime
battery.runtime.low
battery.voltage
battery.voltage.nominal
input.voltage
input.voltage.nominal
ups.load
ups.realpower.nominal
ups.status
ups.beeper.status
ups.firmware
ups.serial
ups.model
ups.test.result
driver.name
driver.version
etc.

Utilizar esos datos cuando estén disponibles.

Por ejemplo:

ups.status = OL
=> Online

ups.status = OB
=> On Battery

ups.status = LB
=> Low Battery

Pero implementar correctamente la combinación de flags si NUT devuelve varios estados.

No asumir que solamente habrá un estado.


==================================================
35. REGLAS PARA LA UX
==================================================

La interfaz debe priorizar:

1. Seguridad
2. Estado
3. Autonomía
4. Energía
5. Consumo
6. Eventos
7. Diagnóstico

El usuario no debería tener que interpretar una gráfica para saber si existe un problema.

Si existe un problema importante:

hacerlo visible inmediatamente.

Si todo funciona:

la interfaz debe sentirse tranquila y limpia.


==================================================
36. NO HACER
==================================================

No:

- llenar todo de tarjetas
- usar demasiados colores
- usar gradientes exagerados
- utilizar glassmorphism extremo
- animar todo
- mostrar información técnica innecesaria en la portada
- inventar métricas
- inventar valores
- modificar el backend sin necesidad
- cambiar endpoints sin necesidad
- eliminar funcionalidades existentes
- eliminar histórico existente
- romper NUT/PBS/PVE
- hardcodear valores actuales de la UPS


==================================================
37. OBJETIVO FINAL
==================================================

Quiero que al abrir el dashboard la sensación sea:

"Estoy viendo el estado energético de toda mi infraestructura"

y no:

"Estoy viendo una página con números de una UPS".

La aplicación debe sentirse como una herramienta profesional de infraestructura.

Antes de implementar:
1. Revisar la estructura actual del proyecto.
2. Identificar componentes existentes.
3. Identificar cómo llegan los datos de NUT.
4. Mantener las APIs existentes.
5. Proponer la nueva estructura.
6. Implementar el rediseño por componentes.
7. Verificar responsive.
8. Verificar estados ONLINE / ON BATTERY / WARNING / CRITICAL.
9. Verificar que ningún dato actual deje de mostrarse.
10. Verificar que no se rompa la comunicación con NUT.

Quiero que priorices una excelente jerarquía visual y UX por encima de simplemente agregar elementos.