# Deploy — Sabrina Hansen Atelier (Cloudflare Tunnel)

O app roda na **sua máquina** (via Gunicorn, em `http://127.0.0.1:8000`) e o
**Cloudflare Tunnel** o expõe à internet com **HTTPS**, sem abrir portas no
roteador. Barato (túnel grátis) e os dados ficam com você.

```
Internet ──HTTPS──> Cloudflare ──túnel──> cloudflared ──HTTP──> Gunicorn (127.0.0.1:8000) ──> app
```

### Endereços
- **Raiz `/`** → **vitrine pública** (loja para o cliente). Ex.: `https://www.sabrinahansen.com.br/`
- **`/console/erp/`** → **sistema (ERP)**, protegido por login. Ex.: `.../console/erp/login`
- **`/health`** → checagem de status (para monitor externo).
- APIs públicas da vitrine: `/publico/frete`, `/publico/cupom`, `/publico/pedido`.

---

## 0) Uma vez: preparar o ambiente

```bash
cd /Users/luisneu/gitWorkspace/cost-calculation
python3 -m venv .venv                 # se ainda não existir
.venv/bin/pip install -r requirements.txt

# Configurar segredos:
cp .env.example .env
# edite o .env e defina, no mínimo:
#   SECRET_KEY  -> gere:  python -c "import secrets; print(secrets.token_hex(32))"
#   APP_SENHA   -> uma senha forte
```

Instale o cloudflared (macOS):

```bash
brew install cloudflared
```

---

## 1) TESTE RÁPIDO (URL temporária, sem conta nem domínio)

Ótimo para validar antes de configurar o definitivo.

**Terminal 1 — sobe o app:**
```bash
cd /Users/luisneu/gitWorkspace/cost-calculation
.venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
```

**Terminal 2 — abre o túnel:**
```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

O cloudflared imprime uma URL tipo `https://algo-aleatorio.trycloudflare.com`.
Abra no celular/navegador: é o seu sistema, público e com HTTPS. 🎉

> A URL do teste rápido **muda a cada vez** e o túnel cai quando você fecha o
> terminal. Para algo fixo, use o passo 2.

---

## 2) DEFINITIVO (túnel nomeado + seu domínio)

Precisa de uma conta Cloudflare (grátis) com um domínio adicionado a ela.

```bash
cloudflared tunnel login                       # abre o navegador p/ autorizar
cloudflared tunnel create atelier              # cria o túnel (gera um id + credencial)
cloudflared tunnel route dns atelier vitrine.SEUDOMINIO.com
```

Crie `~/.cloudflared/config.yml`:
```yaml
tunnel: atelier
credentials-file: /Users/luisneu/.cloudflared/<ID-DO-TUNEL>.json
ingress:
  - hostname: vitrine.SEUDOMINIO.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Rode:
```bash
cloudflared tunnel run atelier
```

Acesse `https://vitrine.SEUDOMINIO.com`.

> **Sem domínio próprio?** Use o passo 1 (trycloudflare) ou registre um domínio
> barato (~R$40/ano). O túnel em si é grátis.

---

## 3) Manter rodando sempre (macOS, launchd)

Assim o app e o túnel sobem sozinhos e sobrevivem a logout/reinício.
Crie os LaunchAgents (ajuste os caminhos se necessário):

`~/Library/LaunchAgents/com.atelier.app.plist`
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.atelier.app</string>
  <key>WorkingDirectory</key><string>/Users/luisneu/gitWorkspace/cost-calculation</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/luisneu/gitWorkspace/cost-calculation/.venv/bin/gunicorn</string>
    <string>-c</string><string>gunicorn.conf.py</string><string>wsgi:app</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/atelier-app.log</string>
  <key>StandardErrorPath</key><string>/tmp/atelier-app.log</string>
</dict></plist>
```

`~/Library/LaunchAgents/com.atelier.tunnel.plist`
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.atelier.tunnel</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/cloudflared</string>
    <string>tunnel</string><string>run</string><string>atelier</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/atelier-tunnel.log</string>
  <key>StandardErrorPath</key><string>/tmp/atelier-tunnel.log</string>
</dict></plist>
```

Carregue:
```bash
launchctl load ~/Library/LaunchAgents/com.atelier.app.plist
launchctl load ~/Library/LaunchAgents/com.atelier.tunnel.plist
```
(Para parar: `launchctl unload ...`.)

---

## 4) Backup automático (diário)

O script `backup.py` faz uma cópia **íntegra** do banco (mesmo com o app rodando)
+ zip das fotos, em `./backups/`, mantendo os últimos 14.

Teste manual:
```bash
.venv/bin/python backup.py
```

Agende (todo dia às 2h) via launchd — `~/Library/LaunchAgents/com.atelier.backup.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.atelier.backup</string>
  <key>WorkingDirectory</key><string>/Users/luisneu/gitWorkspace/cost-calculation</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/luisneu/gitWorkspace/cost-calculation/.venv/bin/python</string>
    <string>backup.py</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/tmp/atelier-backup.log</string>
  <key>StandardErrorPath</key><string>/tmp/atelier-backup.log</string>
</dict></plist>
```
```bash
launchctl load ~/Library/LaunchAgents/com.atelier.backup.plist
```

> Dica: copie a pasta `backups/` de vez em quando para um HD externo ou nuvem
> (iCloud/Google Drive) — assim há cópia fora da máquina.

---

## 5) Checklist antes de expor à internet

- [ ] `.env` com **SECRET_KEY forte** e **APP_SENHA forte** (não use os defaults!).
- [ ] Rodou `.venv/bin/pytest` e passou.
- [ ] App sobe com `gunicorn -c gunicorn.conf.py wsgi:app` (HTTP em 127.0.0.1:8000).
- [ ] Túnel funcionando (passo 1 ou 2).
- [ ] Em **Configurações → URL pública da vitrine**, cole a URL pública (para os
      links de WhatsApp de aniversário usarem o endereço certo).
- [ ] Backup testado e agendado.
- [ ] (Opcional) Crie usuários individuais em **Usuários** e evite compartilhar a
      senha-mestre.

---

## Atualizar o sistema (deploy de uma nova versão)

```bash
git pull                                   # se estiver versionando
.venv/bin/pip install -r requirements.txt  # se mudaram dependências
# as migrações de banco rodam sozinhas no boot do app
launchctl kickstart -k gui/$(id -u)/com.atelier.app   # reinicia o app
```
