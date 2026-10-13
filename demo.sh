#!/usr/bin/env bash
#
# demo.sh - Levanta el servidor y varios clientes a la vez, en una sola terminal.
#
#   ./demo.sh              abre los paneles y deja que escribas a mano
#   ./demo.sh guion        ademas escribe solo los nombres y los mensajes
#   ./demo.sh limpiar      cierra la sesion de la demo
#   ./demo.sh limpiar todo cierra la sesion y libera el puerto 8070
#
# Al terminar de armarse, esta terminal SE CONECTA sola a la sesion de tmux,
# asi que los paneles se ven directamente. Para salir de la demo sin cerrarla:
# Ctrl+B y luego D. Para volver a verla: tmux attach -t chatdemo
#
# Opciones:
#   --sin-conectar   arma los paneles pero no entra a la sesion (util para
#                    cuando la salida no es una terminal, o para grabarla)
#
# Requiere tmux. Sin tmux, ejecuta el script sin argumentos para ver la
# version manual.

set -u

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESION="chatdemo"
PUERTO=8070
SERVIDOR="$RAIZ/GPTChatServer.py"
CLIENTE="$RAIZ/GPTChatCliente.py"
NOMBRES=(Ana Beto Camila)
PY="${PYTHON:-python3}"
LOG_GUION="${TMPDIR:-/tmp}/chatdemo-guion.log"

# ---------------------------------------------------------------- utilidades

pausa() { sleep "${1:-1}"; }

tiene_tmux() { command -v tmux >/dev/null 2>&1; }

puerto_ocupado() {
  # ss no esta en todos los sistemas; si no existe, se asume libre.
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -q ":${PUERTO}\b"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$PUERTO" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

liberar_puerto() {
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PUERTO}/tcp" >/dev/null 2>&1 || true
  fi
  # Por si 'fuser' no alcanza el socket: puede tardar un par de segundos.
  for _ in 1 2 3 4 5 6; do
    puerto_ocupado || return 0
    sleep 0.4
  done
  return 0
}

limpiar() {
  if tiene_tmux && tmux has-session -t "$SESION" 2>/dev/null; then
    tmux kill-session -t "$SESION" 2>/dev/null || true
    echo "Sesion '$SESION' cerrada."
  else
    echo "No hay sesion '$SESION' activa."
  fi
  if [ "${1:-}" = "todo" ]; then
    liberar_puerto
    echo "Puerto $PUERTO liberado."
  fi
}

aviso() { printf '\033[1;33m%s\033[0m\n' "$*"; }
error() { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }
ok()     { printf '\033[1;32m%s\033[0m\n' "$*"; }

esperar_servidor() {
  for _ in $(seq 1 40); do
    puerto_ocupado && return 0
    sleep 0.25
  done
  return 1
}

# --------------------------------------------------------------- modo manual

modo_manual() {
  cat <<EOF

  La demo automatizada necesita tmux y no lo encontremos instalado.

  Se recomienda instalarlo con:

      sudo apt install tmux

  Mientras tanto, la version manual es la misma:

  1. En una terminal, el servidor (dejala corriendo):

      cd "$RAIZ"
      $PY $SERVIDOR

  2. En dos o tres terminales mas, un cliente en cada una:

      cd "$RAIZ"
      $PY $CLIENTE

  En cada cliente escribe un nombre distinto. Luego escribe un mensaje
  en cualquiera de ellos y aparecera en los demas a la vez.

EOF
}

# -------------------------------------------------- el que escribe las teclas
#
# Se ejecuta DESPEGADO de la terminal (setsid) para dos cosas:
#   1. que la demo siga avanzando mientras el usuario mira los paneles,
#   2. que un Ctrl+C del usuario no la interrumpa.
#
# Uso interno: demo.sh guion-interno <modo> <panel...>

guion_interno() {
  local modo="${1:?uso interno: guion-interno <manual|guion> <panel...>}"
  shift
  if [ $# -lt 3 ]; then
    error "guion-interno necesita los 3 paneles de los clientes (llego $#)."
    exit 1
  fi
  local ana="$1" beto="$2" camila="$3"

  # Margen para que los paneles terminen de arrancar.
  pausa 1.5

  # Los nombres se escriben siempre: sin esto los clientes quedan esperando.
  tmux send-keys -t "$ana"    "${NOMBRES[0]}" Enter; pausa 0.9
  tmux send-keys -t "$beto"   "${NOMBRES[1]}" Enter; pausa 0.9
  tmux send-keys -t "$camila" "${NOMBRES[2]}" Enter; pausa 0.9

  # A partir de aqui solo en modo guion.
  [ "$modo" = "guion" ] || return 0

  pausa 1.0
  tmux send-keys -t "$ana"    "Hola a todos, aqui es Ana"  Enter; pausa 1.4
  tmux send-keys -t "$beto"   "Hola Ana, soy Beto"         Enter; pausa 1.4
  tmux send-keys -t "$camila" "Hola! Que tal todo?"        Enter; pausa 1.4
  tmux send-keys -t "$ana"    "Todos bien por aqui"        Enter; pausa 1.6

  # Reintento de nombre: un panel nuevo pide un nombre ya ocupado.
  local extra
  extra="$(tmux split-window -t "$SESION" -d -P -F '#{pane_id}' -h \
    "$PY $CLIENTE; echo; echo '--- cliente terminado ---'; exec bash")"
  tmux select-pane -t "$extra" -T "Duplicado" >/dev/null 2>&1
  tmux select-layout -t "$SESION" tiled >/dev/null 2>&1
  pausa 1.5

  tmux send-keys -t "$extra" "Ana"   Enter    # rechazado: ya existe
  pausa 2.0
  tmux send-keys -t "$extra" "Diego" Enter    # aceptado al segundo intento
  pausa 1.6
  tmux send-keys -t "$extra" "Diego aqui presente, saludos" Enter
  pausa 1.8

  # Salida voluntaria.
  tmux send-keys -t "$ana" "salir" Enter
  pausa 1.5
}

# ------------------------------------------------------------------ la demo

levantar_demo() {
  local modo="${1:-manual}" conectar="${2:-si}"

  # Si ya habia una demo, se cierra antes de abrir otra.
  tmux kill-session -t "$SESION" 2>/dev/null || true
  liberar_puerto

  # Panel 0: el servidor.
  tmux new-session -d -s "$SESION" -x 210 -y 50 "$PY $SERVIDOR"
  local p0
  p0="$(tmux list-panes -t "$SESION" -F '#{pane_id}')"

  if ! esperar_servidor; then
    error "El servidor no levanto en el puerto $PUERTO. Revisa el panel del servidor."
    tmux kill-session -t "$SESION" 2>/dev/null || true
    return 1
  fi

  # Un panel por cliente. Se guardan sus ids para poder escribirles despues.
  local paneles=() i
  for i in "${!NOMBRES[@]}"; do
    # El panel no muere con el cliente: al salir queda el shell, para poder leerlo.
    paneles+=("$(tmux split-window -t "$SESION" -d -P -F '#{pane_id}' -h \
      "$PY $CLIENTE; echo; echo '--- cliente terminado ---'; exec bash")")
    pausa 0.35
  done

  tmux select-layout -t "$SESION" tiled >/dev/null 2>&1

  # Etiquetas en el titulo de cada panel, para saber quien es quien.
  tmux select-pane -t "$p0" -T "SERVIDOR" >/dev/null 2>&1
  for i in "${!NOMBRES[@]}"; do
    tmux select-pane -t "${paneles[$i]}" -T "${NOMBRES[$i]}" >/dev/null 2>&1
  done

  # El que teclea las claves corre aparte, para que la terminal pueda
  # conectarse a la sesion y el usuario vea la demo en vivo.
  setsid nohup bash "$RAIZ/$(basename "${BASH_SOURCE[0]}")" \
    guion-interno "$modo" "${paneles[@]}" \
    > "$LOG_GUION" 2>&1 < /dev/null &
  disown 2>/dev/null || true

  if [ "$conectar" != "si" ]; then
    ok "Paneles listos (1 servidor + ${#NOMBRES[@]} clientes: ${NOMBRES[*]})."
    aviso "Para verlos:  tmux attach -t $SESION"
    aviso "Cerrar la demo:  ./demo.sh limpiar todo"
    return 0
  fi

  # Si la salida no es una terminal no se puede entrar a la demo.
  if [ ! -t 1 ]; then
    ok "Paneles listos. La salida no es una terminal, conectate a mano:"
    echo "    tmux attach -t $SESION"
    return 0
  fi

  ok "Entrando a la demo de ${#NOMBRES[@]} clientes y un servidor..."
  aviso "Para salir de la demo sin cerrarla:  Ctrl+B y luego D"
  pausa 1.5

  tmux attach -t "$SESION" 2>/dev/null || true

  echo
  ok "Saliste de la demo. Los paneles siguen corriendo."
  aviso "Para volver a verlos:   tmux attach -t $SESION"
  aviso "Para cerrar todo:       ./demo.sh limpiar todo"
}

# -------------------------------------------------------------------- inicio

conectar="si"

# Primero se separan las banderas de los subcomandos, para que
# './demo.sh --sin-conectar' se entienda igual que './demo.sh guion --sin-conectar'.
posicionales=()
for arg in "$@"; do
  case "$arg" in
    --sin-conectar) conectar="no" ;;
    *)              posicionales+=("$arg") ;;
  esac
done
set -- ${posicionales[@]+"${posicionales[@]}"}

modo="manual"
extra=""

if [ $# -gt 0 ]; then
  case "$1" in
    guion)          modo="guion" ;;
    limpiar)        modo="limpiar"; extra="${2:-}" ;;
    guion-interno)  modo="guion-interno"; shift ;;
    *)              modo="$1" ;;   # valor invalido: lo reporta el case de abajo
  esac
fi

case "$modo" in
  limpiar)
    case "$extra" in
      todo) limpiar todo ;;
      *)    limpiar ;;
    esac
    exit 0
    ;;
  guion-interno)
    # Uso interno: guion-interno <manual|guion> <panel...>
    guion_interno "$@"
    exit 0
    ;;
  guion|manual)
    tiene_tmux || { modo_manual; exit 0; }
    if [ ! -f "$SERVIDOR" ] || [ ! -f "$CLIENTE" ]; then
      error "No encuentro el servidor o el cliente junto a este script."
      exit 1
    fi
    levantar_demo "$modo" "$conectar"
    ;;
  *)
    echo "Uso: ./demo.sh [guion|limpiar [todo]] [--sin-conectar]" >&2
    exit 2
    ;;
esac