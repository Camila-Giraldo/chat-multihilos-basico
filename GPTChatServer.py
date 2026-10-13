"""
GPTChatServer - Servidor de chat local multicliente (TCP/IP).

Requisitos que cumple:
  1. Servidor local (localhost) que acepta varios clientes al mismo tiempo.
  2. Al conectarse, el servidor solicita un nombre antes de habilitar el envío.
  3. Cada mensaje recibido se reenvía (broadcast) a todos los clientes conectados.

Protocolo (mensajes delimitados por '\\n', codificados en UTF-8):
  Servidor -> Cliente: 'SOLICITUD_NOMBRE'            pide el nombre al conectarse
  Servidor -> Cliente: 'NOMBRE_ACEPTADO:<nombre>'    nombre registrado
  Servidor -> Cliente: 'NOMBRE_RECHAZADO:<motivo>'   nombre vacío, repetido,
                                                        o se agotaron los intentos
  Servidor -> Cliente: 'MENSAJE:<remitente>:<texto>' broadcast de un mensaje
  Servidor -> Cliente: 'SISTEMA:<texto>'             avisos (entrada/salida)
  Servidor -> Cliente: 'DESCONEXION'                 cierre ordenado
  Cliente  -> Servidor: '<nombre>' o '<texto del mensaje>'

Tras un rechazo el servidor NO cierra la conexion: vuelve a preguntar, de modo
que el cliente puede corregir su nombre sin volver a conectarse.
"""

import socket
import threading

HOST = 'localhost'
PUERTO = 8070
CODIFICACION = 'utf-8'

# Cuantas veces se pide un nombre antes de descartar al cliente.
MAX_INTENTOS_NOMBRE = 3

# Lista de clientes registrados. Se protege con un lock porque varios hilos
# (uno por cliente) la modifican y la leen al mismo tiempo.
lock_clientes = threading.Lock()
clientes = {}  # {socket: nombre}


def enviar(socket_cliente, mensaje):
    """Envía un mensaje a un cliente, tolerando desconexiones."""
    try:
        socket_cliente.sendall((mensaje + '\n').encode(CODIFICACION))
    except OSError:
        pass


def difundir(mensaje):
    """Envía un mensaje a todos los clientes conectados (broadcast)."""
    with lock_clientes:
        destinos = list(clientes)
    for cliente in destinos:
        enviar(cliente, mensaje)


def registrar(cliente, nombre):
    """Agrega el cliente si el nombre es válido y no está repetido."""
    with lock_clientes:
        if nombre in clientes.values():
            return False
        clientes[cliente] = nombre
    return True


def desregistrar(cliente):
    """Quita el cliente de la lista y devuelve su nombre (o None)."""
    with lock_clientes:
        return clientes.pop(cliente, None)


def cantidad_clientes():
    with lock_clientes:
        return len(clientes)


def pedir_nombre(cliente, archivo):
    """
    Fase de identificacion. Pide el nombre y valida hasta MAX_INTENTOS_NOMBRE.

    Devuelve el nombre aceptado, o None si el cliente se fue o se quedaron
    sin intentos. Un nombre rechazado NO cierra la conexion: se vuelve a
    preguntar para que el cliente pueda corregirlo.
    """
    for intento in range(1, MAX_INTENTOS_NOMBRE + 1):
        # 2. El servidor solicita un nombre antes de permitir enviar mensajes.
        enviar(cliente, 'SOLICITUD_NOMBRE')
        nombre = recibir_linea(archivo)

        if nombre is None:
            print(f'[-] El cliente se desconectó tras {intento - 1} intento(s)')
            return None

        nombre = nombre.strip()

        if not nombre:
            motivo = 'el nombre no puede estar vacío'
        elif not registrar(cliente, nombre):
            motivo = 'ese nombre ya está en uso'
        else:
            return nombre  # nombre valido y registrado

        enviar(cliente, f'NOMBRE_RECHAZADO:{motivo} '
                        f'(intento {intento} de {MAX_INTENTOS_NOMBRE})')

    # Se agotaron los intentos: ahora sí se descarta al cliente.
    enviar(cliente, 'NOMBRE_RECHAZADO:se agotaron los intentos, conexión cerrada')
    return None


def manejar_cliente(cliente, direccion):
    """Atiende a un cliente: pide nombre, valida y reenvía sus mensajes."""
    print(f'[*] Conexión entrante desde {direccion}')
    nombre = None

    # makefile resuelve el problema de que recv() entregue fragmentos:
    # readline() entrega líneas completas aunque lleguen repartidas.
    archivo = cliente.makefile('rb')

    nombre = pedir_nombre(cliente, archivo)

    if nombre is None:
        cliente.close()
        return

    enviar(cliente, f'NOMBRE_ACEPTADO:{nombre}')
    difundir(f'SISTEMA:{nombre} se ha conectado')
    print(f'[+] {nombre} conectado. Clientes activos: {cantidad_clientes()}')

    try:
        while True:
            mensaje = recibir_linea(archivo)
            if mensaje is None:          # el cliente cerró la conexión
                break
            mensaje = mensaje.strip()
            if not mensaje:
                continue
            if mensaje.lower() == 'salir':
                break

            # 3. El mensaje se envía a TODOS los clientes (incluido el emisor).
            difundir(f'MENSAJE:{nombre}:{mensaje}')
    finally:
        archivo.close()
        desregistrar(cliente)
        cliente.close()
        difundir(f'SISTEMA:{nombre} se ha desconectado')
        print(f'[-] {nombre} desconectado. '
              f'Clientes activos: {cantidad_clientes()}')


def recibir_linea(archivo):
    """Lee una línea completa del archivo del socket. None si se cerró."""
    try:
        linea = archivo.readline()
    except OSError:
        return None
    if not linea:                       # b'' = el cliente cerró la conexión
        return None
    return linea.decode(CODIFICACION, errors='replace').rstrip('\n')


def main():
    # 1. Servidor local que escucha a todos los clientes a la vez.
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind((HOST, PUERTO))
    servidor.listen()

    print(f'[*] Servidor escuchando en {HOST}:{PUERTO}')
    print('[!] Ctrl+C para detener el servidor')

    try:
        while True:
            cliente, direccion = servidor.accept()
            # Un hilo por cliente: el servidor atiende a varios simultáneamente.
            hilo = threading.Thread(target=manejar_cliente,
                                    args=(cliente, direccion), daemon=True)
            hilo.start()
    except KeyboardInterrupt:
        print('\n[*] Deteniendo el servidor...')
    finally:
        for cliente in list(clientes):
            enviar(cliente, 'DESCONEXION')
            cliente.close()
        servidor.close()
        print('[*] Servidor cerrado')


if __name__ == '__main__':
    main()