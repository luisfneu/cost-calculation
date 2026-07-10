"""Rotas: clientes."""
import calendar
import csv
import io
import math
import os
import re
import secrets
import string
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
    Lead,
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
    cpf_valido,
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
        query = query.filter(db.or_(Cliente.nome.ilike(like), Cliente.instagram.ilike(like),
                                     Cliente.email.ilike(like)))
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
        # E-mail (login da conta na vitrine): opcional, mas único quando informado.
        email = Cliente.normalizar_email(request.form.get("email", ""))
        if email:
            existente = Cliente.por_email(email)
            if existente and (cliente is None or existente.id != cliente.id):
                flash("Já existe um cliente com esse e-mail.", "erro")
                return render_template("cliente_form.html", cliente=cliente)
        cpf = re.sub(r"\D", "", request.form.get("cpf", ""))
        if not cpf_valido(cpf):
            flash("CPF inválido.", "erro")
            return render_template("cliente_form.html", cliente=cliente)
        if cliente is None:
            cliente = Cliente()
            db.session.add(cliente)
        cliente.nome = nome
        cliente.email = email or None
        cliente.aceita_novidades = request.form.get("aceita_novidades") == "on"
        cliente.instagram = request.form.get("instagram", "").strip()
        cliente.telefone = request.form.get("telefone", "").strip()
        cliente.nascimento = _to_date(request.form.get("nascimento"))
        cliente.genero = request.form.get("genero", "").strip()
        cliente.cpf = cpf
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
    # Possíveis duplicados: mesmo WhatsApp, outro registro (ex.: balcão + vitrine).
    duplicados = []
    if cliente.whatsapp_numero:
        duplicados = [c for c in Cliente.query.all()
                      if c.id != cliente.id and c.whatsapp_numero == cliente.whatsapp_numero]
    return render_template("cliente_detalhe.html", cliente=cliente, vendas=vendas,
                           duplicados=duplicados)


def _mesclar_clientes(principal, duplicado):
    """Une dois cadastros do mesmo cliente: move pedidos/leads/cupons/vales do
    `duplicado` para o `principal`, completa os campos vazios do principal e apaga
    o duplicado. Nunca sobrescreve dado já preenchido no principal."""
    if principal.id == duplicado.id:
        return principal
    # Repontar todas as FKs que apontam para o cliente.
    for Modelo in (Venda, Lead, Cupom, Vale):
        Modelo.query.filter_by(cliente_id=duplicado.id).update(
            {"cliente_id": principal.id}, synchronize_session=False)
    # Completa só o que falta no principal.
    for campo in ("instagram", "telefone", "cep", "logradouro", "numero",
                  "complemento", "bairro", "cidade", "uf", "nascimento",
                  "tamanho_habitual"):
        if not getattr(principal, campo):
            valor = getattr(duplicado, campo)
            if valor:
                setattr(principal, campo, valor)
    # Herda o login (e-mail + senha) se o principal ainda não tem conta.
    if not principal.tem_conta and duplicado.tem_conta:
        principal.email = duplicado.email
        principal.senha_hash = duplicado.senha_hash
        duplicado.email = None  # libera o UNIQUE do e-mail antes de apagar
    principal.aceita_novidades = principal.aceita_novidades or duplicado.aceita_novidades
    db.session.delete(duplicado)
    return principal


@bp.route("/clientes/<int:cliente_id>/mesclar/<int:duplicado_id>", methods=["POST"])
def mesclar_cliente(cliente_id, duplicado_id):
    """Mescla o cadastro `duplicado_id` dentro de `cliente_id` (mantém este)."""
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    principal = Cliente.query.get_or_404(cliente_id)
    duplicado = Cliente.query.get_or_404(duplicado_id)
    if principal.whatsapp_numero != duplicado.whatsapp_numero:
        flash("Só é possível mesclar cadastros com o mesmo WhatsApp.", "erro")
        return redirect(url_for("main.detalhe_cliente", cliente_id=principal.id))
    nome_dup = duplicado.nome
    _mesclar_clientes(principal, duplicado)
    db.session.commit()
    _log("cliente_mesclado", f"#{duplicado_id} ({nome_dup}) → #{principal.id} ({principal.nome})")
    flash(f"Cadastro de {nome_dup} mesclado neste cliente.", "sucesso")
    return redirect(url_for("main.detalhe_cliente", cliente_id=principal.id))


@bp.route("/clientes/<int:cliente_id>/resetar-senha", methods=["POST"])
def resetar_senha_cliente(cliente_id):
    """Gera uma senha temporária para o cliente (não há e-mail transacional).
    O ateliê envia pelo WhatsApp e o cliente troca em Preferências. Evita ter de
    'reivindicar' (que é o caminho inseguro)."""
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    cliente = Cliente.query.get_or_404(cliente_id)
    alfabeto = string.ascii_lowercase + string.digits
    temp = "sh" + "".join(secrets.choice(alfabeto) for _ in range(6))
    cliente.set_senha(temp)
    db.session.commit()
    _log("cliente_senha_reset", f"#{cliente.id} ({cliente.nome})")
    flash(f"Senha temporária de {cliente.nome}: {temp} — envie pelo WhatsApp e "
          "peça para trocá-la em Preferências.", "sucesso")
    return redirect(url_for("main.detalhe_cliente", cliente_id=cliente.id))


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
    vitrine_url = Parametro.obter("vitrine_url", "") or url_for("publico.vitrine_publica", _external=True)
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


# ----- Leads (pré-cadastros da vitrine pública) -----
@bp.route("/leads")
def listar_leads():
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    status = request.args.get("status", "pendente").strip()
    query = Lead.query
    if status in ("pendente", "confirmado", "descartado"):
        query = query.filter_by(status=status)
    leads = query.order_by(Lead.criado_em.desc()).all()
    contagem = {
        "pendente": Lead.query.filter_by(status="pendente").count(),
        "confirmado": Lead.query.filter_by(status="confirmado").count(),
        "descartado": Lead.query.filter_by(status="descartado").count(),
    }
    return render_template("leads.html", leads=leads, status=status, contagem=contagem)


@bp.route("/leads/<int:lead_id>/confirmar", methods=["POST"])
def confirmar_lead(lead_id):
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    lead = Lead.query.get_or_404(lead_id)
    if lead.status == "confirmado" and lead.cliente_id:
        flash("Este lead já foi confirmado.", "erro")
        return redirect(url_for("main.listar_leads"))

    # Evita duplicar: se já existe cliente com o mesmo WhatsApp, vincula a ele.
    cliente = None
    if lead.whatsapp_numero:
        cliente = next(
            (c for c in Cliente.query.all() if c.whatsapp_numero == lead.whatsapp_numero),
            None,
        )
    if cliente is None:
        cliente = Cliente(
            nome=lead.nome, instagram=lead.instagram, telefone=lead.telefone,
            cep=lead.cep, logradouro=lead.logradouro, numero=lead.numero,
            complemento=lead.complemento, bairro=lead.bairro,
            cidade=lead.cidade, uf=lead.uf,
        )
        db.session.add(cliente)
        db.session.flush()
    else:
        # Cliente já existe (mesmo WhatsApp): completa só os campos vazios com o
        # que o lead trouxe — nunca sobrescreve dados que o ateliê já tinha.
        for campo in ("instagram", "telefone", "cep", "logradouro", "numero",
                      "complemento", "bairro", "cidade", "uf"):
            if not (getattr(cliente, campo) or "").strip():
                valor = (getattr(lead, campo) or "").strip()
                if valor:
                    setattr(cliente, campo, valor)

    # Vincula o cliente ao(s) pré-pedido(s) que este lead gerou (não efetiva a venda;
    # o pedido é confirmado depois na própria tela do pedido).
    vendas_lead = Venda.query.filter_by(lead_id=lead.id).all()
    for v in vendas_lead:
        if not v.cliente_id:
            v.cliente_id = cliente.id
            v.comprador = cliente.nome

    lead.status = "confirmado"
    lead.cliente_id = cliente.id
    lead.confirmado_em = datetime.now()
    db.session.commit()
    _log("lead_confirmado", f"lead #{lead.id} → cliente #{cliente.id} ({cliente.nome})")
    flash(f"Cliente {cliente.nome} confirmado.", "sucesso")
    if vendas_lead:
        flash(f"Abra o pré-pedido #{vendas_lead[0].id} para confirmá-lo.", "sucesso")
        return redirect(url_for("main.visualizar_venda", venda_id=vendas_lead[0].id))
    return redirect(url_for("main.detalhe_cliente", cliente_id=cliente.id))


@bp.route("/leads/<int:lead_id>/descartar", methods=["POST"])
def descartar_lead(lead_id):
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    lead = Lead.query.get_or_404(lead_id)
    lead.status = "descartado"
    db.session.commit()
    _log("lead_descartado", f"lead #{lead.id} ({lead.nome})")
    flash("Lead descartado.", "sucesso")
    return redirect(url_for("main.listar_leads"))


@bp.route("/leads/<int:lead_id>/excluir", methods=["POST"])
def excluir_lead(lead_id):
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    lead = Lead.query.get_or_404(lead_id)
    db.session.delete(lead)
    db.session.commit()
    flash("Lead excluído.", "sucesso")
    return redirect(url_for("main.listar_leads"))
