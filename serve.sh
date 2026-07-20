#!/usr/bin/env bash
#
# Gerencia o serviço completo do ateliê: Gunicorn (app Flask) + Cloudflare Tunnel.
#
#   ./serve.sh start     # sobe app + tunnel
#   ./serve.sh stop      # pausa app + tunnel
#   ./serve.sh restart   # reinicia app + tunnel
#   ./serve.sh status    # mostra estado + healthcheck
#
# Aliases: up=start, pause=stop, down=stop.
#
set -uo pipefail
cd "$(dirname "$0")"

VENV=".venv/bin"
CONF="gunicorn.conf.py"
APP="wsgi:app"
PATTERN='gunicorn.*wsgi:app'
LOG="instance/logs/deploy_boot.log"
HEALTH="http://127.0.0.1:8000/health"

APP_LABEL="com.costcalc.app"
APP_PLIST="$HOME/Library/LaunchAgents/${APP_LABEL}.plist"

TUNNEL="com.cloudflare.cloudflared"
PLIST="$HOME/Library/LaunchAgents/${TUNNEL}.plist"
TUNNEL_LOG="instance/logs/tunnel.log"
TUNNEL_PATTERN='cloudflared.*tunnel.* run'

# Lê uma chave do .env (sem dar `source` no arquivo). Devolve vazio se não houver.
env_get(){
  [ -f .env ] || return 0
  sed -n "s/^[[:space:]]*\(export[[:space:]]\+\)\?${1}=//p" .env | tail -1 | sed "s/^[\"']//; s/[\"']$//"
}

c_ok(){ printf '  \033[0;32m✓\033[0m %s\n' "$1"; }
c_no(){ printf '  \033[0;31m✗\033[0m %s\n' "$1"; }
c_hd(){ printf '\033[1m%s\033[0m\n' "$1"; }

# ---------- Gunicorn (app) ----------
# Modo launchd: se existir com.costcalc.app.plist, o app sobe/para via launchctl
# (RunAtLoad + KeepAlive = auto-start no login e auto-restart se cair). Senão,
# cai no nohup gerenciado por pgrep.
app_running(){ pgrep -f "$PATTERN" >/dev/null 2>&1; }
app_master(){ pgrep -f "$PATTERN" | head -1; }
app_loaded(){ launchctl list "$APP_LABEL" >/dev/null 2>&1; }

# Espera o healthcheck responder (até ~12s). 0 = ok, 1 = falhou.
_wait_health(){
  for _ in $(seq 1 12); do
    sleep 1
    app_running && curl -fsS -o /dev/null "$HEALTH" 2>/dev/null && return 0
  done
  return 1
}

start_app(){
  mkdir -p instance/logs
  if [ -f "$APP_PLIST" ]; then
    if app_loaded; then launchctl kickstart -k "gui/$(id -u)/${APP_LABEL}" >/dev/null 2>&1
    else launchctl load -w "$APP_PLIST" >/dev/null 2>&1; fi
    if _wait_health; then c_ok "app no ar (launchd, pid $(app_master)) — $HEALTH 200"; return 0; fi
    c_no "app não respondeu — últimas linhas do log:"; tail -n 20 "$LOG" 2>/dev/null; return 1
  fi
  # Fallback: nohup
  if app_running; then c_ok "app já no ar (pid $(app_master))"; return 0; fi
  OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES nohup "$VENV/gunicorn" -c "$CONF" "$APP" >> "$LOG" 2>&1 &
  if _wait_health; then c_ok "app no ar (nohup, pid $(app_master)) — $HEALTH 200"; return 0; fi
  c_no "app não respondeu — últimas linhas do log:"; tail -n 20 "$LOG" 2>/dev/null; return 1
}

stop_app(){
  # Sob launchd com KeepAlive, matar por pkill respawna — precisa descarregar.
  if app_loaded; then
    launchctl unload -w "$APP_PLIST" >/dev/null 2>&1 || launchctl bootout "gui/$(id -u)/${APP_LABEL}" >/dev/null 2>&1
  fi
  if app_running; then
    pkill -TERM -f "$PATTERN" 2>/dev/null
    for _ in $(seq 1 10); do app_running || break; sleep 1; done
    app_running && pkill -KILL -f "$PATTERN" 2>/dev/null
  fi
  sleep 1
  app_running && c_no "não consegui parar o app" || c_ok "app parado"
}

# ---------- Cloudflare Tunnel ----------
# Modo TOKEN: se CLOUDFLARE_TUNNEL_TOKEN estiver no .env, roda o cloudflared
# direto com o token (gerenciado por este script). Senão, cai no launchd.
tunnel_loaded(){ launchctl list "$TUNNEL" >/dev/null 2>&1; }
tunnel_proc_running(){ pgrep -f "$TUNNEL_PATTERN" >/dev/null 2>&1; }

start_tunnel(){
  local token; token="$(env_get CLOUDFLARE_TUNNEL_TOKEN)"

  if [ -n "$token" ]; then
    # Evita conflito: se o serviço do launchd também estiver rodando, para ele.
    tunnel_loaded && launchctl unload -w "$PLIST" >/dev/null 2>&1
    if tunnel_proc_running; then c_ok "tunnel já no ar (token)"; return 0; fi
    if ! command -v cloudflared >/dev/null 2>&1; then c_no "cloudflared não encontrado no PATH"; return 1; fi
    mkdir -p instance/logs
    nohup cloudflared tunnel --no-autoupdate run --token "$token" >> "$TUNNEL_LOG" 2>&1 &
    for _ in $(seq 1 8); do sleep 1; tunnel_proc_running && { c_ok "tunnel no ar (token) — log em $TUNNEL_LOG"; return 0; }; done
    c_no "tunnel não subiu — ver $TUNNEL_LOG"; tail -n 15 "$TUNNEL_LOG" 2>/dev/null; return 1
  fi

  # Fallback: launchd
  if [ ! -f "$PLIST" ]; then c_no "sem CLOUDFLARE_TUNNEL_TOKEN no .env e plist não encontrado: $PLIST"; return 1; fi
  if tunnel_loaded; then
    launchctl kickstart -k "gui/$(id -u)/${TUNNEL}" >/dev/null 2>&1
    c_ok "tunnel ativo (launchd, reiniciado)"
  else
    launchctl load -w "$PLIST" >/dev/null 2>&1 && c_ok "tunnel carregado (launchd)" || { c_no "falha ao carregar o tunnel"; return 1; }
  fi
}

stop_tunnel(){
  local parou=0
  if tunnel_proc_running; then pkill -TERM -f "$TUNNEL_PATTERN" 2>/dev/null; sleep 1; tunnel_proc_running && pkill -KILL -f "$TUNNEL_PATTERN" 2>/dev/null; c_ok "tunnel (token) parado"; parou=1; fi
  if tunnel_loaded; then
    launchctl unload -w "$PLIST" >/dev/null 2>&1 || launchctl bootout "gui/$(id -u)/${TUNNEL}" >/dev/null 2>&1
    c_ok "tunnel (launchd) parado"; parou=1
  fi
  [ "$parou" -eq 0 ] && c_ok "tunnel já parado"
}

# ---------- Status ----------
status(){
  c_hd "App (Gunicorn)"
  app_loaded && c_ok "gerenciado pelo launchd ($APP_LABEL — auto-start/restart)" || c_no "fora do launchd (nohup/manual)"
  if app_running; then
    c_ok "rodando — pids: $(pgrep -f "$PATTERN" | tr '\n' ' ')"
    if curl -fsS -o /dev/null -w '' "$HEALTH" 2>/dev/null; then c_ok "healthcheck local 200 ($HEALTH)"; else c_no "healthcheck local sem resposta"; fi
  else
    c_no "parado"
  fi
  c_hd "Cloudflare Tunnel"
  if [ -n "$(env_get CLOUDFLARE_TUNNEL_TOKEN)" ]; then
    if tunnel_proc_running; then c_ok "rodando (token) — pids: $(pgrep -f "$TUNNEL_PATTERN" | tr '\n' ' ')"; else c_no "parado (modo token)"; fi
  elif tunnel_loaded; then c_ok "carregado no launchd ($TUNNEL)"
  else c_no "não carregado"; fi
}

# ---------- Dispatch ----------
case "${1:-}" in
  start|up)
    c_hd "Subindo serviço"; start_app && start_tunnel ;;
  stop|pause|down)
    c_hd "Pausando serviço"; stop_tunnel; stop_app ;;
  restart|reload)
    c_hd "Reiniciando serviço"; stop_tunnel; stop_app; echo; start_app && start_tunnel ;;
  status|"")
    status ;;
  *)
    echo "uso: $0 {start|stop|restart|status}  (aliases: up, pause, down)"; exit 2 ;;
esac
