"""Rotas: sistema."""
import calendar
import csv
import io
import math
import os
import re
import shutil
import sqlite3

# Throttling simples de login (em memória): trava após muitas falhas por IP.
import time as _time  # noqa: E402
import unicodedata
import uuid
from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from sqlalchemy import text
from werkzeug.utils import secure_filename

from .. import APP_VERSION
from ..extensions import limiter
from ..models import (
    TAMANHOS,
    Auditoria,
    Cliente,
    Colecao,
    Cupom,
    Despesa,
    EstoquePeca,
    FotoPeca,
    Insumo,
    Kit,
    KitItem,
    MovimentoEstoque,
    MovimentoPeca,
    OrdemProducao,
    OrdemProducaoItem,
    Pagamento,
    Parametro,
    Parcela,
    Peca,
    PecaInsumo,
    Usuario,
    Vale,
    Venda,
    VendaItem,
    db,
)
from . import bp
from .helpers import *  # noqa: F401,F403

_LOGIN_FALHAS = {}    # ip -> [timestamps de falhas recentes]
_LOGIN_MAX = 5        # falhas permitidas dentro da janela
_LOGIN_JANELA = 300   # segundos (5 min)


def _login_bloqueado(ip):
    agora = _time.time()
    falhas = [t for t in _LOGIN_FALHAS.get(ip, []) if agora - t < _LOGIN_JANELA]
    _LOGIN_FALHAS[ip] = falhas
    return len(falhas) >= _LOGIN_MAX


def _login_falhou(ip):
    _LOGIN_FALHAS.setdefault(ip, []).append(_time.time())


def _login_ok(ip):
    _LOGIN_FALHAS.pop(ip, None)


@bp.route("/health")
@limiter.exempt
def health():
    """Liveness/readiness: 200 se o app e o banco respondem; 503 se o banco falha."""
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        current_app.logger.exception("Health check falhou ao consultar o banco")
        return {"status": "degraded", "banco": "erro", "version": APP_VERSION}, 503
    return {"status": "ok", "banco": "ok", "version": APP_VERSION}, 200


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if _login_bloqueado(ip):
            _log("login_bloqueado", ip)
            flash("Muitas tentativas de login. Aguarde alguns minutos e tente de novo.", "erro")
            return render_template("login.html"), 429

        login_txt = request.form.get("login", "").strip()
        senha = request.form.get("senha", "")
        destino = request.args.get("next") or url_for("main.index")

        # 1) Usuário individual (se informado login e existir usuário ativo).
        if login_txt:
            u = Usuario.query.filter(db.func.lower(Usuario.login) == login_txt.lower()).first()
            if u and u.ativo and u.conferir_senha(senha):
                _login_ok(ip)
                session["logado"] = True
                session["usuario"] = u.nome
                session["admin"] = u.admin
                _log("login", f"usuário {u.login}")
                return redirect(destino)
            _login_falhou(ip)
            flash("Login ou senha inválidos.", "erro")
            return render_template("login.html")

        # 2) Senha-mestre (acesso admin de emergência).
        if senha == current_app.config["APP_SENHA"]:
            _login_ok(ip)
            session["logado"] = True
            session["usuario"] = "Admin"
            session["admin"] = True
            _log("login", "senha-mestre")
            return redirect(destino)

        _login_falhou(ip)
        flash("Login ou senha inválidos.", "erro")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    if session.get("logado"):
        _log("logout")
    session.clear()
    flash("Você saiu do sistema.", "sucesso")
    return redirect(url_for("main.login"))


@bp.route("/")
def index():
    pecas = Peca.query.order_by(Peca.criado_em.desc()).all()
    insumos = Insumo.query.order_by(Insumo.nome).all()
    alertas = [i for i in insumos if i.ativo and i.estoque_baixo]
    pecas_repor = [p for p in pecas if p.precisa_repor]
    vendas = Venda.query.all()
    totais_venda = {
        "receita": sum(v.receita for v in vendas),
        "lucro": sum(v.lucro for v in vendas),
        "qtd": sum(v.quantidade_total for v in vendas),
        "a_receber": sum(v.receita for v in vendas if not v.pago),
    }
    # Meta do mês.
    mes_atual = date.today().strftime("%Y-%m")
    vendas_mes = [v for v in vendas if _mes_de(v.criado_em) == mes_atual]
    receita_mes = sum(v.receita for v in vendas_mes)
    meta = _to_float(Parametro.obter("meta_mensal", "0"))
    meta_pct = (receita_mes / meta * 100) if meta else 0

    # Série de faturamento dos últimos 30 dias (para o mini-gráfico).
    hoje = date.today()
    dias = [hoje - timedelta(days=i) for i in range(29, -1, -1)]
    receita_por_dia = {d: 0.0 for d in dias}
    for v in vendas:
        d = v.criado_em.date() if v.criado_em else None
        if d in receita_por_dia:
            receita_por_dia[d] += v.receita
    serie_30d = [{"label": d.strftime("%d/%m"), "receita": round(receita_por_dia[d], 2)} for d in dias]

    # Top clientes do mês (por receita).
    por_cliente = {}
    for v in vendas_mes:
        nome = v.cliente.nome if v.cliente else (v.cliente_nome or "Sem cliente")
        por_cliente[nome] = por_cliente.get(nome, 0.0) + v.receita
    top_clientes = sorted(por_cliente.items(), key=lambda x: x[1], reverse=True)[:5]

    ticket_medio = (receita_mes / len(vendas_mes)) if vendas_mes else 0.0

    # Lembretes extras: aniversariantes do mês e parcelas de crediário a receber.
    clientes = Cliente.query.all()
    aniversariantes = sorted(
        [c for c in clientes if c.aniversario_no_mes],
        key=lambda c: c.nascimento.day,
    )
    parcelas_abertas = [p for p in Parcela.query.all() if not p.pago]
    parcelas_vencidas = [p for p in parcelas_abertas if p.vencida]
    lembretes = {
        "aniversariantes": aniversariantes,
        "parcelas_abertas": len(parcelas_abertas),
        "parcelas_vencidas": len(parcelas_vencidas),
        "parcelas_valor_vencido": sum(p.valor for p in parcelas_vencidas),
    }
    colecao_fotos = {c.nome: c.foto for c in Colecao.query.all() if c.foto}
    return render_template(
        "index.html", pecas=pecas, insumos=insumos, alertas=alertas,
        pecas_repor=pecas_repor, lembretes=lembretes,
        totais_venda=totais_venda, n_clientes=len(clientes),
        meta=meta, receita_mes=receita_mes, meta_pct=meta_pct,
        colecao_fotos=colecao_fotos,
        serie_30d=serie_30d, top_clientes=top_clientes, ticket_medio=ticket_medio,
    )


@bp.route("/configuracoes", methods=["GET", "POST"])
def configuracoes():
    if request.method == "POST":
        Parametro.definir("pix_chave", request.form.get("pix_chave", "").strip())
        Parametro.definir("pix_nome", request.form.get("pix_nome", "").strip())
        Parametro.definir("pix_cidade", request.form.get("pix_cidade", "").strip())
        Parametro.definir("meta_mensal", _to_float(request.form.get("meta_mensal")))
        # WhatsApp para pedidos na vitrine pública (só dígitos, com DDI/DDD).
        whats = re.sub(r"\D", "", request.form.get("whatsapp", ""))
        Parametro.definir("whatsapp", whats)
        # URL pública fixa da vitrine (para os links enviados por WhatsApp).
        Parametro.definir("vitrine_url", request.form.get("vitrine_url", "").strip())
        # Fuso horário para exibição das datas/horas.
        Parametro.definir("fuso", request.form.get("fuso", "America/Sao_Paulo").strip())
        db.session.commit()
        flash("Configurações salvas.", "sucesso")
        return redirect(url_for("main.configuracoes"))

    # Prévia do Pix com R$ 1,00 para o usuário conferir.
    previa = _pix_payload(
        Parametro.obter("pix_chave", ""), Parametro.obter("pix_nome", ""),
        Parametro.obter("pix_cidade", ""), valor=1.0, txid="TESTE",
    )
    cfg = {
        "pix_chave": Parametro.obter("pix_chave", ""),
        "pix_nome": Parametro.obter("pix_nome", ""),
        "pix_cidade": Parametro.obter("pix_cidade", ""),
        "meta_mensal": Parametro.obter("meta_mensal", "0"),
        "whatsapp": Parametro.obter("whatsapp", ""),
        "vitrine_url": Parametro.obter("vitrine_url", ""),
        "fuso": Parametro.obter("fuso", "America/Sao_Paulo"),
    }
    fusos = [
        "America/Sao_Paulo", "America/Bahia", "America/Fortaleza", "America/Recife",
        "America/Belem", "America/Manaus", "America/Cuiaba", "America/Campo_Grande",
        "America/Porto_Velho", "America/Rio_Branco", "America/Noronha",
    ]
    return render_template("configuracoes.html", cfg=cfg, pix_previa=previa, fusos=fusos)


@bp.route("/usuarios")
def listar_usuarios():
    barrado = _exigir_admin()
    if barrado:
        return barrado
    usuarios = Usuario.query.order_by(Usuario.ativo.desc(), Usuario.nome).all()
    return render_template("usuarios.html", usuarios=usuarios)


@bp.route("/usuarios/novo", methods=["POST"])
def novo_usuario():
    barrado = _exigir_admin()
    if barrado:
        return barrado
    nome = request.form.get("nome", "").strip()
    login_txt = request.form.get("login", "").strip()
    senha = request.form.get("senha", "")
    if not nome or not login_txt or not senha:
        flash("Preencha nome, login e senha.", "erro")
        return redirect(url_for("main.listar_usuarios"))
    if Usuario.query.filter(db.func.lower(Usuario.login) == login_txt.lower()).first():
        flash("Já existe um usuário com esse login.", "erro")
        return redirect(url_for("main.listar_usuarios"))
    u = Usuario(nome=nome, login=login_txt, admin=bool(request.form.get("admin")))
    u.set_senha(senha)
    db.session.add(u)
    db.session.commit()
    flash(f"Usuário {u.login} criado.", "sucesso")
    return redirect(url_for("main.listar_usuarios"))


@bp.route("/usuarios/<int:usuario_id>/senha", methods=["POST"])
def redefinir_senha_usuario(usuario_id):
    barrado = _exigir_admin()
    if barrado:
        return barrado
    u = Usuario.query.get_or_404(usuario_id)
    senha = request.form.get("senha", "")
    if not senha:
        flash("Informe a nova senha.", "erro")
        return redirect(url_for("main.listar_usuarios"))
    u.set_senha(senha)
    db.session.commit()
    flash(f"Senha de {u.login} redefinida.", "sucesso")
    return redirect(url_for("main.listar_usuarios"))


@bp.route("/usuarios/<int:usuario_id>/toggle", methods=["POST"])
def toggle_usuario(usuario_id):
    barrado = _exigir_admin()
    if barrado:
        return barrado
    u = Usuario.query.get_or_404(usuario_id)
    u.ativo = not u.ativo
    db.session.commit()
    return redirect(url_for("main.listar_usuarios"))


@bp.route("/usuarios/<int:usuario_id>/excluir", methods=["POST"])
def excluir_usuario(usuario_id):
    barrado = _exigir_admin()
    if barrado:
        return barrado
    u = Usuario.query.get_or_404(usuario_id)
    db.session.delete(u)
    db.session.commit()
    flash("Usuário excluído.", "sucesso")
    return redirect(url_for("main.listar_usuarios"))


@bp.route("/auditoria")
def auditoria():
    usuario = request.args.get("usuario", "").strip()
    acao = request.args.get("acao", "").strip()
    de = _to_date(request.args.get("de"))
    ate = _to_date(request.args.get("ate"))

    query = Auditoria.query
    if usuario:
        query = query.filter(Auditoria.usuario == usuario)
    if acao:
        query = query.filter(Auditoria.acao == acao)
    if de:
        query = query.filter(db.func.date(Auditoria.criado_em) >= de.isoformat())
    if ate:
        query = query.filter(db.func.date(Auditoria.criado_em) <= ate.isoformat())

    registros = query.order_by(Auditoria.criado_em.desc()).all()
    registros, pagina, total_paginas = _paginar(registros)

    # Opções dos filtros (valores distintos existentes).
    usuarios = [r[0] for r in db.session.query(Auditoria.usuario)
                .filter(Auditoria.usuario != "").distinct().order_by(Auditoria.usuario).all()]
    acoes = [r[0] for r in db.session.query(Auditoria.acao)
             .distinct().order_by(Auditoria.acao).all()]
    return render_template(
        "auditoria.html", registros=registros, pagina=pagina, total_paginas=total_paginas,
        usuarios=usuarios, acoes=acoes,
        f_usuario=usuario, f_acao=acao,
        de=request.args.get("de", ""), ate=request.args.get("ate", ""),
    )


def _caminho_banco():
    """Caminho do arquivo SQLite em uso (derivado do engine, não fixo)."""
    caminho = db.engine.url.database
    if caminho and not os.path.isabs(caminho):
        caminho = os.path.join(current_app.root_path, "..", caminho)
    return os.path.abspath(caminho) if caminho else ""


@bp.route("/backup")
def backup():
    caminho = _caminho_banco()
    if not caminho or not os.path.exists(caminho):
        flash("Banco de dados não encontrado.", "erro")
        return redirect(url_for("main.index"))
    # Snapshot íntegro: a API .backup do SQLite inclui dados ainda no WAL
    # (o arquivo .db cru pode estar desatualizado com journal_mode=WAL).
    tmp = os.path.join(os.path.dirname(caminho), f"_backup_tmp_{os.getpid()}.db")
    origem = sqlite3.connect(caminho)
    dest = sqlite3.connect(tmp)
    try:
        with dest:
            origem.backup(dest)
    finally:
        origem.close()
        dest.close()
    nome = f"costcalc-backup-{date.today().isoformat()}.db"
    resp = send_file(tmp, as_attachment=True, download_name=nome)
    resp.call_on_close(lambda: os.path.exists(tmp) and os.remove(tmp))
    return resp


# Tabelas que um backup íntegro do sistema precisa ter (sanidade do arquivo).
_TABELAS_OBRIGATORIAS = {"pecas", "vendas", "clientes", "usuarios", "parametros"}


def _validar_backup_sqlite(caminho):
    """Confere se o arquivo é um banco SQLite íntegro e do sistema.
    Retorna (ok, mensagem_de_erro)."""
    try:
        with open(caminho, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                return False, "o arquivo não é um banco SQLite."
    except OSError:
        return False, "não foi possível ler o arquivo."
    con = None
    try:
        con = sqlite3.connect(caminho)
        r = con.execute("PRAGMA integrity_check").fetchone()
        if not r or r[0] != "ok":
            return False, "o banco está corrompido (integrity_check)."
        tabelas = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if _TABELAS_OBRIGATORIAS - tabelas:
            return False, "a estrutura não parece ser deste sistema."
    except sqlite3.DatabaseError as exc:
        return False, f"erro ao abrir o banco ({exc})."
    finally:
        if con is not None:
            con.close()
    return True, ""


@bp.route("/backup/restaurar", methods=["POST"])
def restaurar_backup():
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio

    # Bancos podem passar dos 8 MB (limite global de upload de imagens);
    # eleva o teto só nesta requisição, antes de tocar em request.files.
    request.max_content_length = 500 * 1024 * 1024

    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo de backup (.db) para restaurar.", "erro")
        return redirect(url_for("main.configuracoes"))

    destino = _caminho_banco()
    if not destino:
        flash("Não foi possível localizar o banco atual.", "erro")
        return redirect(url_for("main.configuracoes"))
    pasta = os.path.dirname(destino)
    os.makedirs(pasta, exist_ok=True)
    tmp = os.path.join(pasta, "_restore_tmp.db")
    arquivo.save(tmp)

    ok, msg = _validar_backup_sqlite(tmp)
    if not ok:
        try:
            os.remove(tmp)
        except OSError:
            pass
        flash(f"Backup não restaurado: {msg}", "erro")
        return redirect(url_for("main.configuracoes"))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # Salvaguarda: guarda o banco atual antes de substituir (permite desfazer).
    if os.path.exists(destino):
        try:
            shutil.copy2(destino, f"{destino}.pre-restore-{stamp}")
        except OSError as exc:
            os.remove(tmp)
            flash(f"Não foi possível salvar o banco atual antes de restaurar ({exc}).", "erro")
            return redirect(url_for("main.configuracoes"))

    # Registra a auditoria ANTES de fechar as conexões (ainda no banco atual).
    _log("restaurar-backup", f"arquivo={secure_filename(arquivo.filename)}")

    # Fecha todas as conexões do pool e remove sidecar do WAL para trocar o arquivo.
    db.session.remove()
    db.engine.dispose()
    for ext in ("-wal", "-shm"):
        lado = destino + ext
        if os.path.exists(lado):
            try:
                os.remove(lado)
            except OSError:
                pass

    os.replace(tmp, destino)  # substituição atômica no mesmo diretório
    flash("Backup restaurado com sucesso. Confira se os dados estão corretos. "
          "Observação: as fotos (uploads) não são alteradas por esta restauração.", "sucesso")
    return redirect(url_for("main.index"))
