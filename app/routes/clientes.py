"""Rotas: clientes."""
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


@bp.route("/clientes")
def listar_clientes():
    q = request.args.get("q", "").strip()
    query = Cliente.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Cliente.nome.ilike(like), Cliente.instagram.ilike(like)))
    clientes = query.order_by(Cliente.nome).all()
    clientes, pagina, total_paginas = _paginar(clientes)
    return render_template("clientes.html", clientes=clientes, q=q, pagina=pagina, total_paginas=total_paginas)


@bp.route("/clientes/novo", methods=["GET", "POST"])
@bp.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
def form_cliente(cliente_id=None):
    cliente = Cliente.query.get_or_404(cliente_id) if cliente_id else None

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("O nome do cliente é obrigatório.", "erro")
            return render_template("cliente_form.html", cliente=cliente)
        if cliente is None:
            cliente = Cliente()
            db.session.add(cliente)
        cliente.nome = nome
        cliente.instagram = request.form.get("instagram", "").strip()
        cliente.telefone = request.form.get("telefone", "").strip()
        cliente.nascimento = _to_date(request.form.get("nascimento"))
        cliente.tamanho_habitual = request.form.get("tamanho_habitual", "").strip().upper()
        cliente.cep = request.form.get("cep", "").strip()
        cliente.logradouro = request.form.get("logradouro", "").strip()
        cliente.numero = request.form.get("numero", "").strip()
        cliente.complemento = request.form.get("complemento", "").strip()
        cliente.bairro = request.form.get("bairro", "").strip()
        cliente.cidade = request.form.get("cidade", "").strip()
        cliente.uf = request.form.get("uf", "").strip().upper()[:2]
        db.session.commit()
        flash("Cliente salvo com sucesso.", "sucesso")
        return redirect(url_for("main.detalhe_cliente", cliente_id=cliente.id))

    return render_template("cliente_form.html", cliente=cliente)


@bp.route("/clientes/<int:cliente_id>")
def detalhe_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    vendas = sorted(cliente.vendas, key=lambda v: v.criado_em, reverse=True)
    return render_template("cliente_detalhe.html", cliente=cliente, vendas=vendas)


@bp.route("/crm")
def crm():
    """Painel de relacionamento: aniversariantes do mês e clientes a reativar."""
    try:
        dias_inativo = max(1, int(request.args.get("dias", 90)))
    except (TypeError, ValueError):
        dias_inativo = 90
    clientes = Cliente.query.order_by(Cliente.nome).all()

    aniversariantes = sorted(
        [c for c in clientes if c.aniversario_no_mes],
        key=lambda c: (c.nascimento.day, c.nome),
    )
    reativar = sorted(
        [c for c in clientes if c.inativo(dias_inativo)],
        key=lambda c: c.dias_desde_ultima_compra, reverse=True,
    )
    sem_compra = [c for c in clientes if not c.vendas]

    # Cupom pessoal ativo de cada aniversariante (para exibir e citar no parabéns).
    ids = [c.id for c in aniversariantes]
    cupons_aniv = {}
    if ids:
        for cup in Cupom.query.filter(Cupom.cliente_id.in_(ids)).all():
            if cup.valido and cup.cliente_id not in cupons_aniv:
                cupons_aniv[cup.cliente_id] = cup

    # Mensagem de parabéns (com quebras de linha) por aniversariante.
    # Usa a URL pública configurada; senão, o endereço local da rede.
    vitrine_url = Parametro.obter("vitrine_url", "") or url_for("main.vitrine_publica", _external=True)
    msgs_parabens = {}
    for c in aniversariantes:
        cup = cupons_aniv.get(c.id)
        linhas = [f"Feliz aniversário, {c.nome}!"]
        if cup:
            linhas.append(
                f"Desejamos tudo de bom. Como presente, você ganhou o cupom {cup.codigo} "
                f"de 5% de desconto (válido só hoje)!"
            )
            linhas.append(
                f"Use nossa vitrine {vitrine_url} e, ao fazer seu pedido pelo WhatsApp, "
                f"informe seu cupom :)"
            )
        else:
            linhas.append("Desejamos tudo de bom.")
            linhas.append(f"Conheça nossa vitrine: {vitrine_url}")
        linhas += ["Com carinho,", "", "Sabrina Hansen Atelier."]
        msgs_parabens[c.id] = "\n".join(linhas)

    return render_template(
        "crm.html", aniversariantes=aniversariantes, reativar=reativar,
        sem_compra=sem_compra, dias_inativo=dias_inativo, hoje=date.today(),
        cupons_aniv=cupons_aniv, msgs_parabens=msgs_parabens,
    )


@bp.route("/crm/cupom-aniversario/<int:cliente_id>", methods=["POST"])
def cupom_aniversario(cliente_id):
    """Cria um cupom pessoal de 5%, uso único, válido até o dia do aniversário."""
    c = Cliente.query.get_or_404(cliente_id)
    if not c.nascimento:
        flash("Cliente sem data de nascimento cadastrada.", "erro")
        return redirect(url_for("main.crm"))

    # Já existe cupom válido para este cliente? Não duplica.
    existente = next((cp for cp in Cupom.query.filter_by(cliente_id=c.id).all() if cp.valido), None)
    if existente:
        flash(f"{c.nome} já tem um cupom ativo: {existente.codigo}.", "erro")
        return redirect(url_for("main.crm"))

    hoje = date.today()
    try:
        validade = c.nascimento.replace(year=hoje.year)
    except ValueError:  # 29/02 em ano não bissexto
        validade = date(hoje.year, c.nascimento.month, 28)

    # Código único e legível a partir do primeiro nome.
    base = "NIVER" + re.sub(r"[^A-Z0-9]", "", c.nome.split()[0].upper())[:8]
    codigo, n = base, 1
    while Cupom.query.filter_by(codigo=codigo).first():
        n += 1
        codigo = f"{base}{n}"

    db.session.add(Cupom(
        codigo=codigo, tipo="percentual", valor=5.0, validade=validade,
        ativo=True, max_usos=1, cliente_id=c.id,
    ))
    db.session.commit()
    _log("cupom", f"aniversário {c.nome}: {codigo} 5% val {validade}")
    flash(f"Cupom {codigo} criado: 5% para {c.nome}, válido até {validade.strftime('%d/%m/%Y')} (uso único).", "sucesso")
    return redirect(url_for("main.crm"))


@bp.route("/clientes/<int:cliente_id>/excluir", methods=["POST"])
def excluir_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    if cliente.vendas:
        flash("Não é possível excluir: o cliente possui vendas registradas.", "erro")
        return redirect(url_for("main.detalhe_cliente", cliente_id=cliente.id))
    db.session.delete(cliente)
    db.session.commit()
    flash("Cliente excluído.", "sucesso")
    return redirect(url_for("main.listar_clientes"))


@bp.route("/clientes/rapido", methods=["POST"])
def cliente_rapido():
    nome = request.form.get("nome", "").strip()
    if not nome:
        return {"ok": False, "erro": "Nome é obrigatório."}, 400
    c = Cliente(
        nome=nome,
        instagram=request.form.get("instagram", "").strip(),
        telefone=request.form.get("telefone", "").strip(),
        cep=request.form.get("cep", "").strip(),
        logradouro=request.form.get("logradouro", "").strip(),
        numero=request.form.get("numero", "").strip(),
        complemento=request.form.get("complemento", "").strip(),
        bairro=request.form.get("bairro", "").strip(),
        cidade=request.form.get("cidade", "").strip(),
        uf=request.form.get("uf", "").strip().upper()[:2],
    )
    db.session.add(c)
    db.session.commit()
    return {"ok": True, "id": c.id, "nome": c.nome, "cep": c.cep}
