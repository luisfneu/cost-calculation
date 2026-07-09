# TOOLS.md — Ferramentas e serviços do sistema

Catálogo de tudo que faz o **Sabrina Hansen Atelier** rodar: infraestrutura,
serviços externos, bibliotecas e ferramentas de desenvolvimento. Serve para saber
o que precisa de conta, onde cada chave mora e quanto custa.

> Convenção: **chaves e segredos ficam no `.env`** (nunca no git). Veja `.env.example`.

---

## 1. Domínio e DNS

| Ferramenta | Para quê | Onde/como | Custo |
|---|---|---|---|
| **GoDaddy** | Compra/registro do domínio `sabrinahansen.com.br` | painel GoDaddy | ~R$40–60/ano |
| **Cloudflare** | DNS + CDN + porta de entrada do túnel | conta Cloudflare (domínio adicionado a ela) | grátis |

> Setup típico: o domínio é **comprado na GoDaddy**, mas os **nameservers apontam
> para a Cloudflare** — quem gerencia DNS (e o túnel) é a Cloudflare.

---

## 2. Publicação / rede (deixar acessível na internet com HTTPS)

| Ferramenta | Para quê | Onde/como | Custo |
|---|---|---|---|
| **Cloudflare Tunnel** (`cloudflared`) | Expõe `http://127.0.0.1:8000` na internet com HTTPS, sem abrir portas do roteador | binário `cloudflared` + túnel nomeado `atelier` | grátis |
| **Homebrew** | Instala o `cloudflared` no macOS (`brew install cloudflared`) | terminal | grátis |

Detalhes de configuração: veja **DEPLOY.md**.

---

## 3. Servidor de aplicação (runtime)

| Ferramenta | Para quê | Onde/como | Custo |
|---|---|---|---|
| **Python 3.12+** | Linguagem (roda em 3.14 na máquina) | `.venv/` | grátis |
| **Gunicorn** | Servidor WSGI de produção (1 worker `gthread`, 4 threads) | `gunicorn.conf.py` · `wsgi:app` | grátis |
| **macOS launchd** | (Opcional) sobe app + túnel no boot e mantém rodando | `~/Library/LaunchAgents/*.plist` | grátis |

Máquina de produção = **o notebook da Sabrina**. Não há servidor na nuvem.

---

## 4. Banco de dados

| Ferramenta | Para quê | Onde/como | Custo |
|---|---|---|---|
| **SQLite** | Banco (arquivo único) | `instance/costcalc.db` | grátis |
| **Alembic / Flask-Migrate** | Migrações de schema (rodam sozinhas no boot) | `migrations/` | grátis |

> O schema é definido **só pelo Alembic** — sem `db.create_all()`.

---

## 5. Framework e bibliotecas Python (`requirements.txt`)

| Lib | Para quê |
|---|---|
| **Flask** | Framework web |
| **Flask-SQLAlchemy** | ORM (modelos → SQLite) |
| **Flask-WTF** | Proteção CSRF nos formulários |
| **Flask-Migrate** | Ponte Flask ↔ Alembic |
| **Flask-Caching** | Cache da vitrine pública (em memória) |
| **Flask-Limiter** | Rate-limit dos endpoints públicos |
| **python-dotenv** | Lê o `.env` |
| **Pillow** | Redimensiona/otimiza as fotos das peças |
| **itsdangerous** | Tokens assinados (link de reset de senha) — vem com o Flask |
| **Werkzeug** (`ProxyFix`) | Enxerga IP/HTTPS reais atrás do túnel — vem com o Flask |

Instalar: `.venv/bin/pip install -r requirements.txt`.

---

## 6. Serviços externos / APIs

| Serviço | Para quê | Chave no `.env` | Conta / custo |
|---|---|---|---|
| **Resend** | E-mail transacional (reset de senha do cliente) | `RESEND_API_KEY`, `MAIL_FROM` | conta Resend + domínio verificado (DNS na Cloudflare) · grátis até 3.000/mês |
| **Melhor Envio** | Cálculo de frete real (Correios/transportadoras) | `MELHOR_ENVIO_TOKEN`, `CEP_ORIGEM` | conta Melhor Envio · grátis (cálculo) |
| **ViaCEP** | Autopreenche endereço a partir do CEP | — (público, sem chave) | grátis |
| **PIX** | "Copia e cola" + QR do total do pedido | configurado em **Configurações** (chave/nome/cidade) | grátis — gerado **localmente**, sem provedor |
| **WhatsApp** | Links `wa.me` para conversar/confirmar pedido | — | grátis — **manual** (API oficial NÃO usada) |
| **Instagram** | Links para o perfil do cliente/ateliê | — | grátis |

> **Não usados (ainda):** provedor de pagamento PIX automático (precisa webhook) e
> WhatsApp Cloud API (precisa número dedicado + verificação Meta).

---

## 7. Frontend (tudo **vendorizado** em `app/static/` — sem CDN)

Servido pela própria aplicação (funciona offline e não depende de terceiros).

| Item | Para quê |
|---|---|
| **Bootstrap 5** + **Bootstrap Icons** | Layout, componentes e ícones |
| **Chart.js** | Gráficos dos relatórios |
| **html5-qrcode** | Ler QR pela câmera (baixa da peça na venda) |
| **qrcode.min.js** | Gerar o QR na etiqueta |
| **Fontes Jost + Cormorant Garamond** | Identidade visual (self-hosted, `fontes.css`) |
| Scripts próprios | `cep-autofill`, `mascaras`, `pix`, `fotos-uploader`, `tags-input`, `foto-clipboard` |

---

## 8. Desenvolvimento, qualidade e CI

| Ferramenta | Para quê | Onde/como | Custo |
|---|---|---|---|
| **pytest** | Testes automatizados | `tests/` · `.venv/bin/pytest` | grátis |
| **ruff** | Linter + formatador | `pyproject.toml` · `requirements-dev.txt` | grátis |
| **GitHub Actions** | CI (roda ruff + pytest a cada push) | `.github/workflows/ci.yml` | grátis (repo) |
| **Git / GitHub** | Versionamento do código | repositório | grátis |

---

## 9. Backup

| Ferramenta | Para quê | Onde/como | Custo |
|---|---|---|---|
| **`backup.py`** | Cópia íntegra do SQLite (`.backup()`) + zip das fotos | pasta `backups/` (mantém 14) | grátis |
| **launchd** (agendado) | Backup diário automático | `com.atelier.backup.plist` | grátis |

> **Pendente recomendado:** cópia **fora da máquina** (rclone → nuvem / HD externo).

---

## Resumo: contas que precisam existir

- **GoDaddy** — domínio (renovação anual).
- **Cloudflare** — DNS + túnel (grátis).
- **Melhor Envio** — token de frete (grátis).
- **Resend** — envio de e-mail (grátis no volume do ateliê; exige verificar o domínio).
- **GitHub** — código + CI (grátis).

Todos os segredos correspondentes ficam no **`.env`** (veja `.env.example`).
