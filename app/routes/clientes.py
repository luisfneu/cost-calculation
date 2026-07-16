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
    Endereco,
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

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email_valido(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))


def _grupos_duplicados():
    """Grupos de possíveis cadastros duplicados: mesmo WhatsApp, CPF ou e-mail."""
    por_chave = {}
    for c in Cliente.query.all():
        chaves = []
        if c.whatsapp_numero:
            chaves.append(("WhatsApp", c.whatsapp_numero))
        cpf = re.sub(r"\D", "", c.cpf or "")
        if cpf:
            chaves.append(("CPF", cpf))
        if c.email:
            chaves.append(("E-mail", Cliente.normalizar_email(c.email)))
        for k in chaves:
            por_chave.setdefault(k, []).append(c)
    grupos, vistos = [], set()
    for (tipo, _valor), lista in por_chave.items():
        if len(lista) < 2:
            continue
        ids = frozenset(c.id for c in lista)   # mesmo par via 2 chaves: mostra 1×
        if ids in vistos:
            continue
        vistos.add(ids)
        grupos.append({"tipo": tipo, "clientes": sorted(lista, key=lambda c: c.id)})
    return grupos


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
    return render_template("clientes.html", clientes=clientes, q=q, pagina=pagina,
                           total_paginas=total_paginas, duplicados=_grupos_duplicados())


@bp.route("/clientes/novo", methods=["GET", "POST"])
@bp.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
def form_cliente(cliente_id=None):
    cliente = Cliente.query.get_or_404(cliente_id) if cliente_id else None

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("O nome do cliente é obrigatório.", "erro")
            return render_template("cliente_form.html", cliente=cliente)
        # E-mail (login da conta na vitrine): opcional, mas válido e único quando informado.
        email = Cliente.normalizar_email(request.form.get("email", ""))
        if email and not _email_valido(email):
            flash("Informe um e-mail válido.", "erro")
            return render_template("cliente_form.html", cliente=cliente)
        if email:
            existente = Cliente.por_email(email)
            if existente and (cliente is None or existente.id != cliente.id):
                flash("Já existe um cliente com esse e-mail.", "erro")
                return render_template("cliente_form.html", cliente=cliente)
        # WhatsApp: quando informado, exige DDD (mesma regra do cadastro do site) e é único.
        telefone = request.form.get("telefone", "").strip()
        if telefone and len(re.sub(r"\D", "", telefone)) < 10:
            flash("Informe um WhatsApp válido com DDD.", "erro")
            return render_template("cliente_form.html", cliente=cliente)
        if telefone:
            por_zap = Cliente.por_whatsapp(telefone)
            if por_zap and (cliente is None or por_zap.id != cliente.id):
                flash(f"Já existe um cliente com esse WhatsApp: {por_zap.nome} (#{por_zap.id}). "
                      "Abra o cadastro dele ou use a mesclagem.", "erro")
                return render_template("cliente_form.html", cliente=cliente)
        cpf = re.sub(r"\D", "", request.form.get("cpf", ""))
        if not cpf_valido(cpf):
            flash("CPF inválido.", "erro")
            return render_template("cliente_form.html", cliente=cliente)
        # CPF único (o login da vitrine aceita CPF — duplicado deixaria o login ambíguo).
        if cpf:
            dono = Cliente.por_cpf(cpf)
            if dono and (cliente is None or dono.id != cliente.id):
                flash(f"CPF já cadastrado para {dono.nome} (#{dono.id}).", "erro")
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
        # Endereço não é editado aqui: é gerenciado na ficha do cliente (múltiplos,
        # com principal), igual ao site. Os campos inline são espelho do principal.
        db.session.commit()
        flash("Cliente salvo com sucesso.", "sucesso")
        return redirect(url_for("main.detalhe_cliente", cliente_id=cliente.id))

    return render_template("cliente_form.html", cliente=cliente)


@bp.route("/clientes/<int:cliente_id>")
def detalhe_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    vendas = sorted(cliente.vendas, key=lambda v: v.criado_em, reverse=True)
    # Possíveis duplicados: mesmo WhatsApp, CPF ou e-mail em outro registro
    # (ex.: balcão + vitrine). São os mesmos critérios aceitos pela mesclagem.
    cpf = re.sub(r"\D", "", cliente.cpf or "")
    email = Cliente.normalizar_email(cliente.email or "")
    duplicados = []
    for c in Cliente.query.all():
        if c.id == cliente.id:
            continue
        if ((cliente.whatsapp_numero and c.whatsapp_numero == cliente.whatsapp_numero)
                or (cpf and re.sub(r"\D", "", c.cpf or "") == cpf)
                or (email and Cliente.normalizar_email(c.email or "") == email)):
            duplicados.append(c)
    favoritos = (Peca.query.filter(Peca.id.in_(cliente.favoritos_ids)).all()
                 if cliente.favoritos_ids else [])
    # Carrinho salvo na conta (itens que a cliente deixou sem fechar pedido).
    import json as _json
    try:
        carrinho_itens = _json.loads(cliente.carrinho_json or "[]")
    except ValueError:
        carrinho_itens = []
    carrinho_total = sum((i.get("preco") or 0) * (i.get("qtd") or 1) for i in carrinho_itens)
    end_editar = request.args.get("end_editar", type=int)
    em_edicao = (Endereco.query.filter_by(id=end_editar, cliente_id=cliente.id).first()
                 if end_editar else None)
    return render_template("cliente_detalhe.html", cliente=cliente, vendas=vendas,
                           duplicados=duplicados, favoritos=favoritos,
                           carrinho_itens=carrinho_itens, carrinho_total=carrinho_total,
                           enderecos=cliente.enderecos, em_edicao=em_edicao)


# --------------------------------------------------------------------------- #
# Endereços do cliente no ERP (mesmo modelo/regra da conta na vitrine)
# --------------------------------------------------------------------------- #
@bp.route("/clientes/<int:cliente_id>/enderecos/salvar", methods=["POST"])
def cliente_endereco_salvar(cliente_id):
    from .conta import _definir_cobranca, _definir_principal, _sincronizar_principal
    cliente = Cliente.query.get_or_404(cliente_id)
    form = request.form
    eid = form.get("id", type=int)
    if eid:
        end = Endereco.query.filter_by(id=eid, cliente_id=cliente.id).first_or_404()
    else:
        end = Endereco(cliente_id=cliente.id)
        db.session.add(end)
    end.apelido = form.get("apelido", "").strip()
    end.destinatario = form.get("destinatario", "").strip() or cliente.nome
    end.cep = form.get("cep", "").strip()
    end.logradouro = form.get("logradouro", "").strip()
    end.numero = form.get("numero", "").strip()
    end.complemento = form.get("complemento", "").strip()
    end.bairro = form.get("bairro", "").strip()
    end.cidade = form.get("cidade", "").strip()
    end.uf = form.get("uf", "").strip().upper()[:2]
    db.session.flush()
    # Primeiro endereço vira principal + cobrança; senão respeita os checkboxes.
    primeiro = Endereco.query.filter_by(cliente_id=cliente.id).count() == 1
    if form.get("principal") == "on" or primeiro:
        _definir_principal(cliente, end)
    if form.get("cobranca") == "on" or primeiro:
        _definir_cobranca(cliente, end)
    _sincronizar_principal(cliente)
    db.session.commit()
    _log("cliente_endereco", f"#{cliente.id}: endereço salvo (#{end.id})")
    flash("Endereço salvo.", "sucesso")
    return redirect(url_for("main.detalhe_cliente", cliente_id=cliente.id))


@bp.route("/clientes/<int:cliente_id>/enderecos/<int:end_id>/principal", methods=["POST"])
def cliente_endereco_principal(cliente_id, end_id):
    from .conta import _definir_principal, _sincronizar_principal
    cliente = Cliente.query.get_or_404(cliente_id)
    end = Endereco.query.filter_by(id=end_id, cliente_id=cliente.id).first_or_404()
    _definir_principal(cliente, end)
    _sincronizar_principal(cliente)
    db.session.commit()
    flash("Endereço principal atualizado.", "sucesso")
    return redirect(url_for("main.detalhe_cliente", cliente_id=cliente.id))


@bp.route("/clientes/<int:cliente_id>/enderecos/<int:end_id>/cobranca", methods=["POST"])
def cliente_endereco_cobranca(cliente_id, end_id):
    from .conta import _definir_cobranca
    cliente = Cliente.query.get_or_404(cliente_id)
    end = Endereco.query.filter_by(id=end_id, cliente_id=cliente.id).first_or_404()
    _definir_cobranca(cliente, end)
    db.session.commit()
    flash("Endereço de cobrança atualizado.", "sucesso")
    return redirect(url_for("main.detalhe_cliente", cliente_id=cliente.id))


@bp.route("/clientes/<int:cliente_id>/enderecos/<int:end_id>/excluir", methods=["POST"])
def cliente_endereco_excluir(cliente_id, end_id):
    from .conta import _definir_cobranca, _definir_principal, _sincronizar_principal
    cliente = Cliente.query.get_or_404(cliente_id)
    end = Endereco.query.filter_by(id=end_id, cliente_id=cliente.id).first_or_404()
    era_principal, era_cobranca = end.principal, end.cobranca
    db.session.delete(end)
    db.session.flush()
    resto = Endereco.query.filter_by(cliente_id=cliente.id).order_by(Endereco.id).first()
    if resto:
        if era_principal:
            _definir_principal(cliente, resto)
        if era_cobranca:
            _definir_cobranca(cliente, resto)
    _sincronizar_principal(cliente)
    db.session.commit()
    flash("Endereço excluído.", "sucesso")
    return redirect(url_for("main.detalhe_cliente", cliente_id=cliente.id))


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
    # Endereços ("Meus endereços" da vitrine): mover via ORM — sem isso o
    # cascade delete-orphan os apagaria junto com o duplicado. Se o principal
    # já tem endereços, os movidos perdem os papéis principal/cobrança.
    principal_tinha_enderecos = bool(principal.enderecos)
    for e in list(duplicado.enderecos):
        e.cliente = principal
        if principal_tinha_enderecos:
            e.principal = e.cobranca = False
    # Completa só o que falta no principal.
    for campo in ("instagram", "telefone", "cpf", "genero", "cep", "logradouro",
                  "numero", "complemento", "bairro", "cidade", "uf", "nascimento",
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
    # Exige ao menos um identificador forte em comum (WhatsApp, CPF ou e-mail).
    mesmo_zap = bool(principal.whatsapp_numero) and principal.whatsapp_numero == duplicado.whatsapp_numero
    cpf_p = re.sub(r"\D", "", principal.cpf or "")
    cpf_d = re.sub(r"\D", "", duplicado.cpf or "")
    mesmo_cpf = bool(cpf_p) and cpf_p == cpf_d
    mesmo_email = bool(principal.email) and (
        Cliente.normalizar_email(principal.email) == Cliente.normalizar_email(duplicado.email or ""))
    if not (mesmo_zap or mesmo_cpf or mesmo_email):
        flash("Só é possível mesclar cadastros com o mesmo WhatsApp, CPF ou e-mail.", "erro")
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


def _criar_cupom_aniversario(c):
    """Cupom pessoal de 5%, uso único, válido até o dia do aniversário deste ano."""
    hoje = date.today()
    try:
        validade = c.nascimento.replace(year=hoje.year)
    except ValueError:  # 29/02 em ano não bissexto
        validade = date(hoje.year, c.nascimento.month, 28)
    base = "NIVER" + re.sub(r"[^A-Z0-9]", "", c.nome.split()[0].upper())[:8]
    codigo, n = base, 1
    while Cupom.query.filter_by(codigo=codigo).first():
        n += 1
        codigo = f"{base}{n}"
    cupom = Cupom(codigo=codigo, tipo="percentual", valor=5.0, validade=validade,
                  ativo=True, max_usos=1, cliente_id=c.id)
    db.session.add(cupom)
    return cupom


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

    # Cupom automático: aniversariantes DO DIA sem cupom válido ganham o cupom
    # ao abrir o CRM (idempotente — não duplica).
    criados_auto = []
    for c in aniversariantes:
        if not c.aniversario_hoje:
            continue
        tem_valido = any(cp.valido for cp in Cupom.query.filter_by(cliente_id=c.id).all())
        if not tem_valido:
            criados_auto.append((c, _criar_cupom_aniversario(c)))
    if criados_auto:
        db.session.commit()
        for c, cup in criados_auto:
            _log("cupom", f"aniversário (auto) {c.nome}: {cup.codigo}")
        flash(f"{len(criados_auto)} cupom(ns) de aniversário criados automaticamente "
              "para quem faz aniversário hoje.", "sucesso")

    # Carrinhos abandonados: clientes logados que montaram carrinho e não
    # fecharam pedido (o checkout limpa o carrinho salvo).
    import json as _json
    carrinhos = []
    for c in clientes:
        if not c.carrinho_json:
            continue
        try:
            itens = _json.loads(c.carrinho_json)
        except ValueError:
            continue
        if not itens:
            continue
        total = sum((i.get("preco") or 0) * (i.get("qtd") or 1) for i in itens)
        carrinhos.append({"cliente": c, "itens": itens, "total": total, "em": c.carrinho_em})
    carrinhos.sort(key=lambda x: x["em"] or datetime.min, reverse=True)
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
    vitrine_url = Parametro.obter("vitrine_url", "") or url_for("publico.vitrine_v2", _external=True)
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
        cupons_aniv=cupons_aniv, msgs_parabens=msgs_parabens, carrinhos=carrinhos,
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

    cupom = _criar_cupom_aniversario(c)
    db.session.commit()
    _log("cupom", f"aniversário {c.nome}: {cupom.codigo} 5% val {cupom.validade}")
    flash(f"Cupom {cupom.codigo} criado: 5% para {c.nome}, válido até "
          f"{cupom.validade.strftime('%d/%m/%Y')} (uso único).", "sucesso")
    return redirect(url_for("main.crm"))


@bp.route("/clientes/<int:cliente_id>/excluir", methods=["POST"])
def excluir_cliente(cliente_id):
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    cliente = Cliente.query.get_or_404(cliente_id)
    if cliente.vendas:
        flash("Não é possível excluir: o cliente possui vendas registradas.", "erro")
        return redirect(url_for("main.detalhe_cliente", cliente_id=cliente.id))
    db.session.delete(cliente)
    db.session.commit()
    flash("Cliente excluído.", "sucesso")
    return redirect(url_for("main.listar_clientes"))


@bp.route("/clientes/<int:cliente_id>/anonimizar", methods=["POST"])
def anonimizar_cliente(cliente_id):
    """LGPD: remove os dados pessoais mantendo o histórico financeiro.

    Excluir é bloqueado quando há vendas (quebraria receita/relatórios);
    anonimizar zera nome/CPF/contatos/endereços e desativa a conta da vitrine.
    Irreversível."""
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    cliente = Cliente.query.get_or_404(cliente_id)
    nome_antigo = cliente.nome
    cliente.nome = f"Cliente anonimizado #{cliente.id}"
    cliente.email = None
    cliente.senha_hash = ""          # desativa o login da vitrine
    cliente.telefone = ""
    cliente.instagram = ""
    cliente.cpf = ""
    cliente.genero = ""
    cliente.nascimento = None
    cliente.tamanho_habitual = ""
    cliente.aceita_novidades = False
    cliente.favoritos_json = ""
    for campo in ("cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf"):
        setattr(cliente, campo, "")
    for e in list(cliente.enderecos):
        db.session.delete(e)
    # Nome também vive no campo texto das vendas e nos leads vinculados.
    Venda.query.filter_by(cliente_id=cliente.id).update(
        {"comprador": cliente.nome}, synchronize_session=False)
    for lead in Lead.query.filter_by(cliente_id=cliente.id).all():
        lead.nome = cliente.nome
        lead.telefone = lead.email = lead.instagram = ""
        for campo in ("cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf"):
            setattr(lead, campo, "")
    db.session.commit()
    _log("cliente_anonimizado", f"#{cliente.id} ({nome_antigo})")
    flash(f"Dados pessoais de '{nome_antigo}' removidos. Histórico financeiro preservado.", "sucesso")
    return redirect(url_for("main.detalhe_cliente", cliente_id=cliente.id))


@bp.route("/clientes/rapido", methods=["POST"])
def cliente_rapido():
    nome = request.form.get("nome", "").strip()
    if not nome:
        return {"ok": False, "erro": "Nome é obrigatório."}, 400
    # Mesmo WhatsApp já cadastrado? Reusa o cliente em vez de criar duplicado.
    telefone = request.form.get("telefone", "").strip()
    existente = Cliente.por_whatsapp(telefone) if telefone else None
    if existente:
        return {"ok": True, "id": existente.id, "nome": existente.nome,
                "cep": existente.cep, "existente": True}
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

    # Evita duplicar: casa por WhatsApp e, se não achar, pelo e-mail do checkout.
    cliente = None
    if lead.whatsapp_numero:
        cliente = next(
            (c for c in Cliente.query.all() if c.whatsapp_numero == lead.whatsapp_numero),
            None,
        )
    if cliente is None and lead.email:
        cliente = Cliente.por_email(lead.email)
    if cliente is None:
        # E-mail do lead só entra se não pertencer a outro cadastro (UNIQUE).
        email_livre = lead.email and Cliente.por_email(lead.email) is None
        cliente = Cliente(
            nome=lead.nome, instagram=lead.instagram, telefone=lead.telefone,
            email=(lead.email if email_livre else None),
            cep=lead.cep, logradouro=lead.logradouro, numero=lead.numero,
            complemento=lead.complemento, bairro=lead.bairro,
            cidade=lead.cidade, uf=lead.uf,
        )
        db.session.add(cliente)
        db.session.flush()
    else:
        # Cliente já existe (mesmo WhatsApp/e-mail): completa só os campos vazios
        # com o que o lead trouxe — nunca sobrescreve dados que o ateliê já tinha.
        for campo in ("instagram", "telefone", "cep", "logradouro", "numero",
                      "complemento", "bairro", "cidade", "uf"):
            if not (getattr(cliente, campo) or "").strip():
                valor = (getattr(lead, campo) or "").strip()
                if valor:
                    setattr(cliente, campo, valor)
        # E-mail: preenche se o cliente não tem e o do lead está livre.
        if not cliente.email and lead.email and Cliente.por_email(lead.email) is None:
            cliente.email = lead.email

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


def _cancelar_pre_pedidos_do_lead(lead):
    """Apaga os pré-pedidos criados junto com o lead (nunca tocaram estoque nem
    relatórios). Sem isso, descartar/excluir o lead deixaria a Venda órfã na
    lista — e 'Confirmar pedido' seguiria clicável num pedido descartado."""
    vendas = Venda.query.filter_by(lead_id=lead.id, status="pre-pedido").all()
    for v in vendas:
        _liberar_reservas_pre_pedido(v)   # devolve o estoque reservado
        db.session.delete(v)
    return len(vendas)


@bp.route("/leads/<int:lead_id>/descartar", methods=["POST"])
def descartar_lead(lead_id):
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    lead = Lead.query.get_or_404(lead_id)
    lead.status = "descartado"
    n = _cancelar_pre_pedidos_do_lead(lead)
    db.session.commit()
    _log("lead_descartado", f"lead #{lead.id} ({lead.nome}), {n} pré-pedido(s) cancelado(s)")
    flash("Lead descartado." + (f" {n} pré-pedido(s) cancelado(s)." if n else ""), "sucesso")
    return redirect(url_for("main.listar_leads"))


@bp.route("/leads/<int:lead_id>/excluir", methods=["POST"])
def excluir_lead(lead_id):
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    lead = Lead.query.get_or_404(lead_id)
    n = _cancelar_pre_pedidos_do_lead(lead)
    db.session.delete(lead)
    db.session.commit()
    flash("Lead excluído." + (f" {n} pré-pedido(s) cancelado(s)." if n else ""), "sucesso")
    return redirect(url_for("main.listar_leads"))
