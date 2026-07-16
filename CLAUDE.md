# CLAUDE.md

Sistema de custos + vendas do **Sabrina Hansen Atelier** (ateliê de roupas). Flask + SQLite, roda local, exposto por Cloudflare Tunnel.

**Idioma:** responder em **português (Brasil)**. Usuário é data scientist aprendendo MLOps.

## Stack
Flask 3 · Flask-SQLAlchemy · SQLite · Alembic/Flask-Migrate · Flask-WTF (CSRF) · Flask-Caching · Flask-Limiter · Gunicorn · Jinja2 + Bootstrap. Sem front-end build (JS/CSS vanilla vendorizados em `app/static`).

## Rodar / testar
```bash
.venv/bin/python run.py              # dev (porta 8000; HTTPS se certs/ existir)
.venv/bin/gunicorn -c gunicorn.conf.py wsgi:app   # produção (127.0.0.1:8000)
.venv/bin/pytest                     # 97 testes (pythonpath=. no pytest.ini)
.venv/bin/ruff check . && .venv/bin/ruff format .
```
Portas: 8000 (5000 é sequestrada pelo AirPlay do macOS → 403).
Reload sem downtime após deploy de código: `kill -HUP $(pgrep -f "gunicorn.*wsgi:app" | head -1)` (HUP no master recarrega os workers). Túnel Cloudflare roda à parte, não reinicia junto.

## URLs (importante)
Dois blueprints:
- `publico` na **raiz**: `/` = vitrine pública (loja), `/health`, `/publico/frete|cupom|pedido`.
- `main` sob **`/console/erp/`**: todo o ERP, login em `/console/erp/login`. Registrado com `url_prefix`, então **rotas antigas na raiz dão 404**.

Guarda de login protege só o blueprint `main`. Templates usam 100% `url_for` — nunca hardcode caminho.

## Convenções
- Rotas em `app/routes/*.py` reexportam helpers via `from .helpers import *` (por isso os ignores F403/F405 no ruff). Blueprints `bp` (main) e `publico_bp` vêm de `app/routes/__init__.py`.
- Dinheiro: `dinheiro()` (Decimal ROUND_HALF_UP); `arredondar_cima(v, base=5)` (teto p/ preço sob-encomenda). Filtro Jinja `| moeda`, `| dt`, `| num`.
- Endpoints públicos POST: `@csrf.exempt`. Cupom pessoal **nunca** aplica na vitrine pública (vaza desconto).
- Fluxo pedido vitrine: cria **Lead** (pendente) + **Venda** status `pre-pedido`. Confirmar lead só cria/vincula Cliente; confirmar pedido baixa estoque e vira `realizado`. `pre-pedido` **fora** de todos os relatórios/receita.

## Armadilhas (JÁ custaram tempo)
- **Antes de migração de schema: PARAR o servidor** — o reloader do Flask quebra a migração no meio.
- **`vendas_legacy`**: `venda_itens` tem FK p/ tabela inexistente. `batch_alter_table` recria a tabela e crasha (`NoSuchTableError`). Em migração, usar **só `op.add_column` direto**, sem FK/batch.
- **macOS + fork (Gunicorn):** HTTP em worker forkado crasha via `_scproxy`. Fix já aplicado: `ProxyHandler({})` em `helpers.py` + `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` no `gunicorn.conf.py`.
- **Ler DB com servidor no ar:** usar `sqlite3` direto (snapshot via `.backup()`), não `create_app` inline — WAL fica stale e há lock.
- **`.env` com chave duplicada:** dotenv usa a **última**; linha de exemplo fraca ofusca a forte e `_checar_segredos` recusa subir (`PRODUCAO=1`).
- Schema é **só Alembic** — não há fallback `db.create_all()`. Sem `migrations/versions` o app não sobe.
- **Cache da vitrine:** `/` tem `@cache.cached(timeout=60)`. Invalidação é **seletiva**: listeners `after_flush`/`after_commit` (em `app/__init__.py`, nível de módulo — `db.session` é global) limpam o cache só quando o commit tocou `Peca`/`EstoquePeca`/`FotoPeca`/`Colecao`/`Parametro`/`Insumo`/`PecaInsumo` (`_MODELOS_VITRINE`). Novo modelo que afete a vitrine → adicionar à tupla. Se criar novo endpoint cacheado, lembrar que a limpeza é `cache.clear()` (tudo).

## Segurança
Nunca commitar `.env`. Produção: `PRODUCAO=1`, `SECRET_KEY`/`APP_SENHA` fortes, `SESSION_COOKIE_SECURE=1`.
