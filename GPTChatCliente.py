"""
GPTChatCliente - Cliente del chat multicliente (TCP/IP).

Se conecta al servidor local, envía su nombre cuando el servidor lo solicita
y luego envía los mensajes que el usuario escriba. Los mensajes de todos los
clientes llegan por el mismo socket y se muestran en consola.
"""

import os
import queue
import signal
import socket
import threading

HOST = 'localhost'
PUERTO = 8070
CODIFICACION = 'utf-8'

# El hilo receptor deja aquí las líneas de control (las que no son mensajes de
# chat). El hilo principal las consume para decidir qué preguntar al usuario.
control = queue.Queue()

# Se apaga en cuanto el receptor detecta que el servidor se fue.
conexion_viva = threading.Event()

# Líneas que el servidor usa para dirigir la conversación, no para chatear.
LINEAS_CONTROL = ('SOLICITUD_NOMBRE', 'NOMBRE_ACEPTADO',
                  'NOMBRE_RECHAZADO', 'DESCONEXION')


def mostrar_mensajes(socket_cliente):
    """
    Hilo receptor: lee el socket, imprime el chat y encola las señales de
    control. Nunca llama a input(): solo el hilo principal lee al usuario,
    para que no se pisen entre si.

    Cuando el servidor cierra, este hilo interrumpe al principal para que el
    cliente termine junto con el servidor, aunque el usuario no esté escribiendo.
    """
    buffer = b''
    while True:
        try:
            datos = socket_cliente.recv(4096)
        except OSError:
            terminar_por_desconexion()
            return
        if not datos:          # b'' = el servidor cerró la conexión
            terminar_por_desconexion()
            return

        buffer += datos
        while b'\n' in buffer:
            linea, _, buffer = buffer.partition(b'\n')
            texto = linea.decode(CODIFICACION, errors='replace')
            if texto.startswith(LINEAS_CONTROL):
                control.put(texto)
            else:
                mostrar_linea(texto)


def terminar_por_desconexion():
    """
    El servidor se fue: avisa e interrumpe el input() del hilo principal.

    enviar por el socket no serviría para detectarlo, porque la primera
    escritura tras la muerte del servidor se guarda en el búfer de TCP y
    aparenta éxito. Lo que sí lo detecta al instante es un recv() vacío.
    """
    if not conexion_viva.is_set():
        return                  # ya se avisó, no repetir
    conexion_viva.clear()
    print('\n[*] El servidor cerró la conexión.')
    # Equivale a que el usuario presione Ctrl+C: interrumpe el input().
    # Si el principal no está en un input(), la excepción se atiende igual.
    os.kill(os.getpid(), signal.SIGINT)


def mostrar_linea(linea):
    """Muestra en consola los mensajes de chat y los avisos del servidor."""
    if linea.startswith('MENSAJE:'):
        _, remitente, texto = linea.split(':', 2)
        print(f'\n[{remitente}] {texto}')
    elif linea.startswith('SISTEMA:'):
        print(f'\n--- {linea[len("SISTEMA:"):]} ---')


def identificar(sock):
    """
    Responde a cada solicitud de nombre hasta que el servidor acepte uno.

    El servidor vuelve a preguntar tras cada rechazo, asi que basta con
    atender cada 'SOLICITUD_NOMBRE'. Devuelve el nombre aceptado, o None si
    el servidor cerro la conexion (intentos agotados, por ejemplo).
    """
    while True:
        try:
            linea = control.get(timeout=30)
        except queue.Empty:
            print('\n[*] El servidor no respondió. Cerrando...')
            return None

        if linea.startswith('NOMBRE_ACEPTADO:'):
            nombre = linea[len('NOMBRE_ACEPTADO:'):]
            print(f'*** Bienvenido/a, {nombre} ***')
            print('Escriba su mensaje y presione Enter. "salir" para terminar.\n')
            return nombre

        if linea.startswith('NOMBRE_RECHAZADO:'):
            motivo = linea[len('NOMBRE_RECHAZADO:'):]
            print(f'*** {motivo} ***')
            print('Vuelva a intentarlo con otro nombre.\n')
            continue

        if linea == 'DESCONEXION':
            print('*** El servidor cerró la sesión sin aceptarte ***')
            conexion_viva.clear()
            return None

        if linea == 'SOLICITUD_NOMBRE':
            print('*** Conectado. El servidor solicita un nombre ***')
            nombre = input('Ingrese su nombre: ').strip()
            try:
                sock.sendall((nombre + '\n').encode(CODIFICACION))
            except OSError:
                conexion_viva.clear()
                print('No se pudo enviar el nombre: el servidor se desconectó.')
                return None


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        sock.connect((HOST, PUERTO))
    except ConnectionRefusedError:
        print('No se pudo conectar: el servidor no está en ejecución.')
        sock.close()
        return
    except OSError as error:
        print(f'No se pudo conectar a {HOST}:{PUERTO} ({error}).')
        sock.close()
        return

    conexion_viva.set()

    # Hilo receptor: no bloquea al usuario mientras escribe.
    threading.Thread(target=mostrar_mensajes, args=(sock,), daemon=True).start()

    try:
        nombre = identificar(sock)
        if nombre is None:
            return

        while conexion_viva.is_set():
            mensaje = input('> ')
            if mensaje.strip().lower() == 'salir':
                sock.sendall(b'salir\n')
                break
            sock.sendall((mensaje + '\n').encode(CODIFICACION))
    except (KeyboardInterrupt, EOFError):
        pass
    except OSError:
        # Red de seguridad: escribir puede fallar si el socket ya se cerró.
        conexion_viva.clear()
        print('\n[*] Se perdió la conexión con el servidor.')
    finally:
        conexion_viva.clear()
        sock.close()
        print('* Conexión cerrada')


if __name__ == '__main__':
    main()