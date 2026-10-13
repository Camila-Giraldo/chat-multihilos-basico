# Chat multicliente por TCP/IP

Servidor de chat local que acepta **varios clientes al mismo tiempo**, les exige
un **nombre** antes de dejarlos escribir, y reparte cada mensaje a **todos** los
conectados.

Proyecto de únicamente la biblioteca estándar de Python (sin dependencias).

| Archivo | Descripción |
|---|---|
| `GPTChatServer.py` | Servidor. Escucha en `localhost:8070`. |
| `GPTChatCliente.py` | Cliente. Se conecta, se identifica y chatea. |
| `demo.sh` | Levanta servidor y 3 clientes en paneles (para grabar). |

---

## 1. Requisitos y cómo se cumplen

| # | Requisito | Dónde se resuelve |
|---|---|---|
| 1 | Servidor local, varios clientes a la vez | Un hilo por cliente en `main()` |
| 2 | El servidor pide un nombre antes de enviar | `pedir_nombre()` |
| 3 | Envía los mensajes a todos los clientes | `difundir()` |

---

## 2. La decisión de diseño: dos responsabilidades, dos hilos

El error del código original era un único `accept()` fuera de todo bucle:

```python
conn, addr = sock.accept()   # UN solo cliente, y el hilo principal queda atrapado
```

La solución fue separar dos responsabilidades que no pueden vivir en el mismo hilo:

```
SERVIDOR
│
├─ Hilo principal ──── solo acepta conexiones. Nunca espera datos,
│                     así que queda libre de inmediato para el siguiente.
│
├─ Hilo de Ana  ──┐
├─ Hilo de Beto ──┼── cada uno habla solo con su cliente. Si uno se queda
└─ Hilo de Carla ┘   bloqueado, a los demás les da igual.
```

```python
while True:
    cliente, direccion = servidor.accept()          # no bloquea
    threading.Thread(target=manejar_cliente,        # y sigue libre
                     args=(cliente, direccion),
                     daemon=True).start()
```

---

## 3. Primitivas de concurrencia utilizadas

### 3.1 `threading.Lock` — mutex (exclusión mutua)

El diccionario `clientes` es el estado compartido del chat:

```python
lock_clientes = threading.Lock()
clientes = {}   # {socket: nombre}
```

Se usa con `with`, que libera el candado solo aunque haya error dentro. Ese
fragmento se llama **sección crítica**: código que no puede ser interrumpido
por otro hilo.

**El detalle importante es dónde termina la sección crítica:**

```python
def difundir(mensaje):
    with lock_clientes:
        destinos = list(clientes)      # copia DENTRO del lock  (rápido)
    for cliente in destinos:
        enviar(cliente, mensaje)       # envío FUERA del lock   (lento)
```

Si el `for` estuviera dentro del lock, un cliente nuevo no podría conectarse
mientras el servidor le envía un mensaje a otro. **El candado se toma lo más
breve posible.**

### 3.2 `threading.Thread` — los hilos

- **Servidor:** uno por cliente.
- **Cliente:** uno para recibir. Hace falta porque *escribir* y *recibir* se
  bloquean mutuamente: si el usuario escribe "hola" y el hilo espera la
  respuesta, no puede mostrar el mensaje que otro cliente mandó meanwhile.

`daemon=True` en ambos: sin eso, un hilo vivo impediría que el proceso termine.

### 3.3 `queue.Queue` — un solo hilo lee al usuario

En el cliente, el hilo receptor **nunca** llama a `input()`, porque si lo hiciera
habría dos hilos pidiendo texto al usuario a la vez. En vez de eso encola las
señales de control:

```python
control = queue.Queue()          # el hilo receptor deposita
linea = control.get(timeout=30)  # el hilo principal consume
```

**Regla: un solo hilo lee al usuario; los demás le pasan lo que sea por la cola.**

### 3.4 `threading.Event` — bandera de vida

```python
conexion_viva = threading.Event()
```

Un interruptor compartido que informa si el servidor sigue ahí, y que además
impide que el aviso de desconexión se repita si el hilo recibe varios errores.

---

## 4. Lo que NO se usó, y por qué

| Primitiva | Por qué no hizo falta |
|---|---|
| `Semaphore` | Limita cuántos hilos **actúan a la vez**. Aquí no hay recurso limitado: cada cliente tiene su hilo y el `Lock` ya serializa el acceso a la lista. |
| `Barrier` | Obliga a **N hilos a esperarse mutuamente** en un punto. Aquí los clientes son independientes: a nadie le importa cuándo terminan los demás. |
| `Condition` | Un `Lock` avanzado con "avisar a los que esperan". Nadie espera una condición: los hilos se bloquean en `recv()`, que es la forma correcta de esperar sin quemar CPU. |
| `ThreadPool` | Ideal para muchas tareas cortas. Aquí los hilos viven toda la sesión del cliente, así que un pool de tamaño fijo se quedaría corto. |

> **Frase clave para la defensa oral:**
> *"Usé un mutex porque hay datos compartidos entre hilos; no usé barreras porque
> los clientes no necesitan sincronizarse entre sí, solo con la lista del servidor."*

---

## 5. Protocolo

Líneas terminadas en `\n`, codificadas en UTF-8. El `\n` no es decorativo: es el
delimitador que permite leer mensajes completos.

### Servidor → Cliente

| Mensaje | Significado |
|---|---|
| `SOLICITUD_NOMBRE` | Pide el nombre (se repite tras cada rechazo) |
| `NOMBRE_ACEPTADO:<nombre>` | Nombre registrado |
| `NOMBRE_RECHAZADO:<motivo>` | Vacío, repetido, o intentos agotados |
| `MENSAJE:<remitente>:<texto>` | Mensaje de chat (broadcast) |
| `SISTEMA:<texto>` | Avisos de entrada y salida |
| `DESCONEXION` | El servidor cierra la sesión |

### Cliente → Servidor

| Mensaje | Significado |
|---|---|
| `<nombre>` | Respuesta a `SOLICITUD_NOMBRE` |
| `<texto>` | Mensaje de chat |
| `salir` | Desconexión voluntaria |

---

## 6. Cómo ejecutar

**Terminal 1 — el servidor**

```bash
python3 GPTChatServer.py
```

```
[*] Servidor escuchando en localhost:8070
[!] Ctrl+C para detener el servidor
```

**Terminal 2, 3, 4… — un cliente cada una**

```bash
python3 GPTChatCliente.py
```

```
*** Conectado. El servidor solicita un nombre ***
Ingrese su nombre: Ana
*** Bienvenido/a, Ana ***
Escriba su mensaje y presione Enter. "salir" para terminar.

> hola a todos
```

En las otras terminales aparece:

```
[Ana] hola a todos
```

Escribir `salir` desconecta al cliente; `Ctrl+C` detiene el servidor.

---

## 6 bis. Demo automática (`demo.sh`)

Para grabar el video sin abrir cuatro ventanas a mano, el script levanta el
servidor y tres clientes en paneles de `tmux`, dentro de la misma terminal.
**Al terminar de armarse, la terminal se conecta sola a la demo.**

```bash
./demo.sh              # abre los paneles y tú escribes a mano
./demo.sh guion        # además escribe solo los nombres y los mensajes
./demo.sh limpiar      # cierra la sesión de la demo
./demo.sh limpiar todo # cierra la sesión y libera el puerto 8070
```

**Modo `guion`:** el script teclea solo la demo completa, en este orden:

1. Los nombres: `Ana`, `Beto`, `Camila`.
2. Mensajes de cada uno, que se ven aparecer en los otros paneles.
3. **El reintento de nombre**: un cuarto panel intenta conectarse con `Ana`
   (ya ocupada), ve el rechazo, y entra al segundo intento como `Diego`.
4. `Ana` escribe `salir` y se desconecta sola.

Dura unos 32 segundos. El guion corre **despegado de la terminal**, así que no
se interrumpe con `Ctrl+C` y tú solo narras mirando los paneles.

### Atajos dentro de la demo

| Atajo | Qué hace |
|---|---|
| `Ctrl+B`, suelta, `D` | Salir de la demo **sin cerrarla** (los paneles siguen) |
| `Ctrl+B`, suelta, flechas | Moverte entre paneles |
| `Ctrl+B`, suelta, `K` | Matar el panel del foco |

Para volver a verla después: `tmux attach -t chatdemo`

### Si no tienes tmux

`./demo.sh` lo detecta y explica cómo hacerlo a mano. También puedes añadir
`--sin-conectar`, que arma los paneles pero **no** entra a la sesión (útil si la
salida no es una terminal, o si prefieres conectarte con `tmux attach` por tu
cuenta).

---

## 7. Detalles técnicos que se deben explicar

### 7.1 Enviar no confirma nada (el bug más importante)

> La primera escritura después de que el otro extremo muera se guarda en el
> búfer local de TCP y **aparenta éxito**. Solo leer revela la muerte, y leer
> devuelve `b''` (cero bytes, no `None`).

Medido: tras matar el servidor, el **primer** `sendall` pasaba limpio y el
**segundo** fallaba con `BrokenPipeError`. Por eso el cliente se enteraba con
dos mensajes de retraso.

La corrección: el hilo receptor, que sí detecta el cierre de inmediato,
interrumpe al hilo principal:

```python
os.kill(os.getpid(), signal.SIGINT)   # equivale a un Ctrl+C automático
```

**La misma verdad aplica en el servidor:** la limpieza va en `finally`, nunca
condicional. Si alguien se desconecta de golpe, nunca llegará un error de
escritura, así que hay que quitarlo de la lista de forma *inevitable*.

### 7.2 `recv()` no entrega un mensaje

`recv(4096)` no significa "recibe un mensaje", significa "lo que haya
disponible ahora". Un mensaje largo puede llegar partido, o dos pueden llegar
pegados.

El servidor lo resuelve con `makefile` + `readline()`:

```python
archivo = cliente.makefile('rb')
linea = archivo.readline()      # siempre una línea completa
```

### 7.3 `split(':', 2)` — máximo dos cortes

```python
_, remitente, texto = linea.split(':', 2)
```

Con un `split(':')` normal, un mensaje como `"Ana: ¿qué hora es?"` se rompería
en muchos pedazos. Limitando los cortes, todo lo que sigue al segundo `:` se
conserva intacto.

### 7.4 `SO_REUSEADDR`

Permite reabrir el puerto 8070 de inmediato al reiniciar el servidor, sin
esperar a que expire el `TIME_WAIT`.

### 7.5 El nombre se reintenta, no se corta

Tras un rechazo el servidor **no** cierra la conexión: vuelve a preguntar
(`MAX_INTENTOS_NOMBRE = 3`). Así el cliente puede corregir su nombre sin
reconectarse. El `close()` quedó fuera del bucle de intentos.

---

## 8. Flujo completo de un mensaje

```
Servidor                          Ana (cliente)
  |                                  |
  |<--------- TCP accept() ----------|   hilo nuevo para Ana
  |--- SOLICITUD_NOMBRE ----------->|   "Ingrese su nombre:"
  |<-------- "Ana\n" --------------|
  |--- NOMBRE_ACEPTADO:Ana ------->|   "Bienvenido/a, Ana"
  |--- SISTEMA:Ana se ha conectado -> Beto ve: "--- Ana se ha conectado ---"
  |                                  |
  |<-------- "hola\n" -------------|   Ana escribe
  |                                  |
  +---> Beto:   MENSAJE:Ana:hola    |
  +---> Carla:  MENSAJE:Ana:hola    |
  +---> Ana:    MENSAJE:Ana:hola    |   (eco: también lo ve el emisor)
```

Todo lo que hizo el hilo de Ana queda registrado en la terminal del servidor:

```
[+] Ana conectado. Clientes activos: 1
[-] Ana desconectado. Clientes activos: 0
```

---

## 9. Casos límite verificados

| Escenario | Resultado |
|---|---|
| Nombre válido | Aceptado, entra al chat |
| Nombre duplicado | Rechaza y **vuelve a preguntar** (hasta 3 intentos) |
| Nombre vacío o con espacios | Rechazado, repregunta |
| 3 rechazos | `"se agotaron los intentos"` y cierra |
| Cierra sin escribir nombre | `"se desconectó tras 0 intento(s)"` |
| Un cliente escribe `salir` | Los demás **siguen** con normalidad |
| Servidor muere (`Ctrl+C`) | Los clientes **cierran solos**, código de salida 0 |

---

## 10. Para la defensa oral

**Orden sugerido:**

1. Los tres requisitos y qué falla en el original (el `accept()` único).
2. El diagrama de dos tipos de hilos — la parte central.
3. El `Lock` y por qué la copia va dentro y el envío fuera.
4. Por qué un solo hilo lee al usuario (la `Queue`).
5. Demo en vivo: 3 clientes, reintento de nombre, broadcast simultáneo, y
   cliente cerrándose solo al detener el servidor.
6. Cierre con el detalle de TCP: por qué la detección va por `recv()`.

**Preguntas con respuesta preparada:**

- *¿Por qué no usaste barreras?* → Los clientes no necesitan sincronizarse entre sí.
- *¿Qué pasa si un cliente se cae?* → El `finally` lo quita siempre de la lista.
- *¿Por qué `finally` y no un `if`?* → Porque nunca llegará un error de escritura;
  la limpieza debe ser inevitable.
- *¿Y si mandan el mismo nombre dos personas?* → Se rechaza al segundo; sin eso
  nadie sabría quién escribió qué.

**Si preguntan por la escala:**

> En este caso es aceptable porque el trabajo por cliente es poco (esperar y
> reenviar) y el límite lo pone la memoria, no la CPU. En un servidor real con
> miles de conexiones se usaría `asyncio` o un pool de hilos, porque un hilo por
> conexión sí escala mal.

---

## 11. Cuántos hilos hay

| Dónde | Hilos | Total con 4 clientes |
|---|---|---|
| Servidor, principal | 1 | 1 |
| Servidor, uno por cliente | 1 por cliente | 4 |
| Clientes, principal (tú) | 1 por cliente | 4 |
| Clientes, receptor del socket | 1 por cliente | 4 |
| **Total** | | **13** |

El hilo principal del servidor **nunca** lee del socket de un cliente: solo
acepta conexiones. Todo lo que llega a un cliente lo atiende su hilo hijo.
Esa separación es la que permite la concurrencia.

Para comprobarlo en caliente:

```bash
ls /proc/<PID_DEL_SERVIDOR>/task
```
