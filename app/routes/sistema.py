"""Rotas: sistema."""
"""Rotas da aplicação."""
import calendar
import csv
import io
import math
import os
import re
import unicodedata
import uuid
from datetime import date, datetime

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
from werkzeug.utils import secure_filename

from ..models import (
    TAMANHOS,
    Auditoria,
    Cliente,
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


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_txt = request.form.get("login", "").strip()
        senha = request.form.get("senha", "")
        destino = request.args.get("next") or url_for("main.index")

        # 1) Usuário individual (se informado login e existir usuário ativo).
        if login_txt:
            u = Usuario.query.filter(db.func.lower(Usuario.login) == login_txt.lower()).first()
            if u and u.ativo and u.conferir_senha(senha):
                session["logado"] = True
                session["usuario"] = u.nome
                session["admin"] = u.admin
                _log("login", f"usuário {u.login}")
                return redirect(destino)
            flash("Login ou senha inválidos.", "erro")
            return render_template("login.html")

        # 2) Senha-mestre (acesso admin de emergência).
        if senha == current_app.config["APP_SENHA"]:
            session["logado"] = True
            session["usuario"] = "Admin"
            session["admin"] = True
            _log("login", "senha-mestre")
            return redirect(destino)

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
    receita_mes = sum(v.receita for v in vendas if _mes_de(v.criado_em) == mes_atual)
    meta = _to_float(Parametro.obter("meta_mensal", "0"))
    meta_pct = (receita_mes / meta * 100) if meta else 0

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
    return render_template(
        "index.html", pecas=pecas, insumos=insumos, alertas=alertas,
        pecas_repor=pecas_repor, lembretes=lembretes,
        totais_venda=totais_venda, n_clientes=len(clientes),
        meta=meta, receita_mes=receita_mes, meta_pct=meta_pct,
    )


@bp.route("/configuracoes", methods=["GET", "POST"])
def configuracoes():
    if request.method == "POST":
        Parametro.definir("pix_chave", request.form.get("pix_chave", "").strip())
        Parametro.definir("pix_nome", request.form.get("pix_nome", "").strip())
        Parametro.definir("pix_cidade", request.form.get("pix_cidade", "").strip())
        Parametro.definir("meta_mensal", _to_float(request.form.get("meta_mensal")))
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
    }
    return render_template("configuracoes.html", cfg=cfg, pix_previa=previa)


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
    registros = Auditoria.query.order_by(Auditoria.criado_em.desc()).limit(500).all()
    return render_template("auditoria.html", registros=registros)


@bp.route("/backup")
def backup():
    caminho = os.path.join(current_app.instance_path, "costcalc.db")
    if not os.path.exists(caminho):
        flash("Banco de dados não encontrado.", "erro")
        return redirect(url_for("main.index"))
    nome = f"costcalc-backup-{date.today().isoformat()}.db"
    return send_file(caminho, as_attachment=True, download_name=nome)
