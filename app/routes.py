"""Rotas da aplicação."""
import csv
import io
import os
import re
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
    url_for,
)
from werkzeug.utils import secure_filename

from .models import (
    TAMANHOS,
    Cliente,
    Despesa,
    EstoquePeca,
    FotoPeca,
    Insumo,
    MovimentoEstoque,
    MovimentoPeca,
    Peca,
    PecaInsumo,
    Venda,
    VendaItem,
    db,
)

bp = Blueprint("main", __name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _to_float(valor, padrao=0.0):
    """Converte string de formulário em float, aceitando vírgula decimal."""
    if valor is None or str(valor).strip() == "":
        return padrao
    try:
        return float(str(valor).replace(".", "").replace(",", ".")) if "," in str(valor) else float(valor)
    except ValueError:
        return padrao


def _to_date(valor):
    """Converte 'YYYY-MM-DD' (input date) em date, ou None."""
    if not valor:
        return None
    try:
        return datetime.strptime(valor.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def _extensao_permitida(nome):
    return "." in nome and nome.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_EXTENSIONS"]


def _salvar_foto(arquivo):
    """Salva o upload com nome único e retorna o nome do arquivo (ou None)."""
    if not arquivo or arquivo.filename == "":
        return None
    if not _extensao_permitida(arquivo.filename):
        flash("Formato de imagem não suportado. Use png, jpg, jpeg, gif ou webp.", "erro")
        return None
    ext = secure_filename(arquivo.filename).rsplit(".", 1)[1].lower()
    nome = f"{uuid.uuid4().hex}.{ext}"
    arquivo.save(os.path.join(current_app.config["UPLOAD_FOLDER"], nome))
    return nome


def _remover_foto(nome):
    if not nome:
        return
    caminho = os.path.join(current_app.config["UPLOAD_FOLDER"], nome)
    if os.path.exists(caminho):
        os.remove(caminho)


def _linha_estoque_peca(peca, tamanho, criar=False):
    """Retorna a linha de estoque da peça no tamanho (cria se pedido)."""
    linha = next((e for e in peca.estoques if e.tamanho == tamanho), None)
    if linha is None and criar:
        linha = EstoquePeca(peca=peca, tamanho=tamanho, quantidade=0.0)
        db.session.add(linha)
    return linha


def _registrar_movimento(insumo, tipo, quantidade, observacao="", custo_unitario=None):
    """Aplica um movimento de estoque e registra no histórico.

    Em entradas com custo informado, recalcula o custo médio ponderado do insumo.
    """
    if tipo == "entrada":
        if custo_unitario and custo_unitario > 0:
            base = insumo.estoque * insumo.custo_unitario + quantidade * custo_unitario
            insumo.custo_unitario = base / (insumo.estoque + quantidade) if (insumo.estoque + quantidade) else custo_unitario
        insumo.estoque += quantidade
    else:  # saida
        insumo.estoque -= quantidade
    db.session.add(MovimentoEstoque(
        insumo=insumo, tipo=tipo, quantidade=quantidade, observacao=observacao,
        custo_unitario=(custo_unitario if custo_unitario else insumo.custo_unitario),
    ))


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@bp.route("/")
def index():
    pecas = Peca.query.order_by(Peca.criado_em.desc()).all()
    insumos = Insumo.query.order_by(Insumo.nome).all()
    alertas = [i for i in insumos if i.ativo and i.estoque_baixo]
    vendas = Venda.query.all()
    totais_venda = {
        "receita": sum(v.receita for v in vendas),
        "lucro": sum(v.lucro for v in vendas),
        "qtd": sum(v.quantidade_total for v in vendas),
        "a_receber": sum(v.receita for v in vendas if not v.pago),
    }
    return render_template(
        "index.html", pecas=pecas, insumos=insumos, alertas=alertas,
        totais_venda=totais_venda, n_clientes=Cliente.query.count(),
    )


@bp.route("/vitrine")
def vitrine():
    """Vitrine para mostrar ao cliente: foto + preço de etiqueta, por coleção."""
    pecas = Peca.query.order_by(Peca.colecao, Peca.nome).all()
    grupos = {}
    for p in pecas:
        grupos.setdefault(p.colecao or "Sem coleção", []).append(p)
    return render_template("vitrine.html", grupos=grupos)


# --------------------------------------------------------------------------- #
# Insumos (estoque)
# --------------------------------------------------------------------------- #
@bp.route("/insumos")
def listar_insumos():
    q = request.args.get("q", "").strip()
    tipo = request.args.get("tipo", "").strip()
    situacao = request.args.get("situacao", "").strip()  # "baixo" | "inativo" | ""
    query = Insumo.query
    if q:
        query = query.filter(Insumo.nome.ilike(f"%{q}%"))
    if tipo in ("materia_prima", "embalagem"):
        query = query.filter_by(tipo=tipo)
    insumos = query.order_by(Insumo.nome).all()
    if situacao == "baixo":
        insumos = [i for i in insumos if i.estoque_baixo]
    elif situacao == "inativo":
        insumos = [i for i in insumos if not i.ativo]
    return render_template("insumos.html", insumos=insumos, q=q, tipo=tipo, situacao=situacao)


@bp.route("/insumos/novo", methods=["GET", "POST"])
@bp.route("/insumos/<int:insumo_id>/editar", methods=["GET", "POST"])
def form_insumo(insumo_id=None):
    insumo = Insumo.query.get_or_404(insumo_id) if insumo_id else None

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("O nome do insumo é obrigatório.", "erro")
            return render_template("insumo_form.html", insumo=insumo)

        if insumo is None:
            insumo = Insumo()
            db.session.add(insumo)

        insumo.nome = nome
        tipo = request.form.get("tipo", "materia_prima")
        insumo.tipo = tipo if tipo in ("materia_prima", "embalagem") else "materia_prima"
        insumo.unidade = request.form.get("unidade", "un").strip() or "un"
        insumo.custo_unitario = _to_float(request.form.get("custo_unitario"))
        insumo.estoque_minimo = _to_float(request.form.get("estoque_minimo"))
        insumo.ativo = request.form.get("ativo") == "on"
        insumo.fornecedor = request.form.get("fornecedor", "").strip()
        # Estoque inicial só é definido na criação; depois é alterado por movimentos.
        if insumo_id is None:
            insumo.estoque = _to_float(request.form.get("estoque"))
            # Registra a compra inicial (aparece como saída de caixa na contabilidade).
            if insumo.estoque > 0:
                db.session.add(MovimentoEstoque(
                    insumo=insumo, tipo="entrada", quantidade=insumo.estoque,
                    custo_unitario=insumo.custo_unitario,
                    observacao="Estoque inicial (cadastro)",
                ))

        # Foto (opcional).
        nova_foto = _salvar_foto(request.files.get("foto"))
        if nova_foto:
            _remover_foto(insumo.foto)
            insumo.foto = nova_foto

        db.session.commit()
        flash("Insumo salvo com sucesso.", "sucesso")
        return redirect(url_for("main.listar_insumos"))

    return render_template("insumo_form.html", insumo=insumo)


@bp.route("/insumos/<int:insumo_id>/excluir", methods=["POST"])
def excluir_insumo(insumo_id):
    insumo = Insumo.query.get_or_404(insumo_id)
    if insumo.usos:
        flash("Não é possível excluir: este insumo é usado em uma ou mais peças.", "erro")
        return redirect(url_for("main.listar_insumos"))
    _remover_foto(insumo.foto)
    db.session.delete(insumo)
    db.session.commit()
    flash("Insumo excluído.", "sucesso")
    return redirect(url_for("main.listar_insumos"))


@bp.route("/insumos/<int:insumo_id>/movimentar", methods=["POST"])
def movimentar_estoque(insumo_id):
    insumo = Insumo.query.get_or_404(insumo_id)
    tipo = request.form.get("tipo")
    quantidade = _to_float(request.form.get("quantidade"))
    observacao = request.form.get("observacao", "").strip()
    custo_compra = _to_float(request.form.get("custo_unitario"))  # opcional (só entrada)

    if tipo not in ("entrada", "saida") or quantidade <= 0:
        flash("Informe um tipo válido e uma quantidade maior que zero.", "erro")
        return redirect(url_for("main.listar_insumos"))

    if tipo == "saida" and quantidade > insumo.estoque:
        flash(f"Estoque insuficiente de '{insumo.nome}' (disponível: {insumo.estoque}).", "erro")
        return redirect(url_for("main.listar_insumos"))

    _registrar_movimento(insumo, tipo, quantidade, observacao, custo_unitario=custo_compra)
    db.session.commit()
    msg = f"Movimento de estoque registrado para '{insumo.nome}'."
    if tipo == "entrada" and custo_compra > 0:
        msg += f" Custo médio atualizado para R$ {insumo.custo_unitario:.2f}."
    flash(msg, "sucesso")
    return redirect(url_for("main.listar_insumos"))


# --------------------------------------------------------------------------- #
# Peças
# --------------------------------------------------------------------------- #
@bp.route("/pecas")
def listar_pecas():
    q = request.args.get("q", "").strip()
    query = Peca.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Peca.nome.ilike(like), Peca.colecao.ilike(like), Peca.tags.ilike(like)))
    pecas = query.order_by(Peca.criado_em.desc()).all()
    return render_template("pecas.html", pecas=pecas, q=q)


@bp.route("/pecas/nova", methods=["GET", "POST"])
@bp.route("/pecas/<int:peca_id>/editar", methods=["GET", "POST"])
def form_peca(peca_id=None):
    peca = Peca.query.get_or_404(peca_id) if peca_id else None
    insumos = Insumo.query.order_by(Insumo.nome).all()
    is_nova = peca is None

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("O nome da peça é obrigatório.", "erro")
            return render_template("peca_form.html", peca=peca, insumos=insumos)

        # Na criação: lê os insumos selecionados para montar a ficha técnica.
        # (Não dá baixa no estoque — isso só acontece ao Produzir.)
        linhas = []          # [(insumo, qtd_por_peca), ...]
        if is_nova:
            ids = request.form.getlist("insumo_id")
            qtds = request.form.getlist("quantidade_insumo")
            vistos = set()
            for iid, q in zip(ids, qtds):
                if not iid:
                    continue
                qtd = _to_float(q)
                insumo = Insumo.query.get(int(iid))
                if not insumo or qtd <= 0 or insumo.id in vistos:
                    continue
                vistos.add(insumo.id)
                linhas.append((insumo, qtd))

        if peca is None:
            peca = Peca()
            db.session.add(peca)

        peca.nome = nome
        peca.colecao = request.form.get("colecao", "").strip()
        peca.tags = request.form.get("tags", "").strip()
        peca.descricao = request.form.get("descricao", "").strip()
        peca.custo_mao_de_obra = _to_float(request.form.get("custo_mao_de_obra"))
        peca.custos_extras = _to_float(request.form.get("custos_extras"))
        peca.margem_percentual = _to_float(request.form.get("margem_percentual"))
        peca.preco_etiqueta = _to_float(request.form.get("preco_etiqueta"))
        peca.peso_g = _to_float(request.form.get("peso_g"))
        peca.altura_cm = _to_float(request.form.get("altura_cm"))
        peca.largura_cm = _to_float(request.form.get("largura_cm"))
        peca.comprimento_cm = _to_float(request.form.get("comprimento_cm"))

        # Foto principal (opcional).
        nova_foto = _salvar_foto(request.files.get("foto"))
        if nova_foto:
            _remover_foto(peca.foto)
            peca.foto = nova_foto

        # Fotos adicionais (galeria) — aceita múltiplos arquivos.
        for arq in request.files.getlist("fotos"):
            nome_arq = _salvar_foto(arq)
            if nome_arq:
                if not peca.foto:
                    peca.foto = nome_arq  # primeira vira a principal se não houver
                else:
                    db.session.add(FotoPeca(peca=peca, arquivo=nome_arq))

        # Na criação: monta a ficha técnica (quantidade por peça).
        if is_nova and linhas:
            for insumo, qtd in linhas:
                db.session.add(PecaInsumo(peca=peca, insumo=insumo, quantidade=qtd))

        db.session.commit()
        flash("Peça salva. Use 'Produzir' para fabricar e dar entrada no estoque.", "sucesso")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))

    return render_template("peca_form.html", peca=peca, insumos=insumos)


@bp.route("/pecas/<int:peca_id>")
def detalhe_peca(peca_id):
    peca = Peca.query.get_or_404(peca_id)
    insumos = Insumo.query.order_by(Insumo.nome).all()
    return render_template("peca_detalhe.html", peca=peca, insumos_disponiveis=insumos)


@bp.route("/pecas/<int:peca_id>/excluir", methods=["POST"])
def excluir_peca(peca_id):
    peca = Peca.query.get_or_404(peca_id)
    _remover_foto(peca.foto)
    for f in peca.fotos:
        _remover_foto(f.arquivo)
    db.session.delete(peca)
    db.session.commit()
    flash("Peça excluída.", "sucesso")
    return redirect(url_for("main.listar_pecas"))


@bp.route("/fotos/<int:foto_id>/excluir", methods=["POST"])
def excluir_foto_peca(foto_id):
    foto = FotoPeca.query.get_or_404(foto_id)
    peca_id = foto.peca_id
    _remover_foto(foto.arquivo)
    db.session.delete(foto)
    db.session.commit()
    flash("Foto removida.", "sucesso")
    return redirect(url_for("main.detalhe_peca", peca_id=peca_id))


# ----- Ficha técnica (insumos da peça) -----
@bp.route("/pecas/<int:peca_id>/insumos/adicionar", methods=["POST"])
def adicionar_insumo_peca(peca_id):
    peca = Peca.query.get_or_404(peca_id)
    insumo_id = request.form.get("insumo_id", type=int)
    quantidade = _to_float(request.form.get("quantidade"))
    insumo = Insumo.query.get(insumo_id) if insumo_id else None

    if not insumo or quantidade <= 0:
        flash("Selecione um insumo e informe uma quantidade maior que zero.", "erro")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))

    # Se o insumo já está na ficha, soma a quantidade.
    existente = next((i for i in peca.insumos if i.insumo_id == insumo.id), None)
    if existente:
        existente.quantidade += quantidade
    else:
        db.session.add(PecaInsumo(peca=peca, insumo=insumo, quantidade=quantidade))

    db.session.commit()
    flash(f"'{insumo.nome}' adicionado à ficha técnica.", "sucesso")
    return redirect(url_for("main.detalhe_peca", peca_id=peca.id))


@bp.route("/ficha/<int:item_id>/remover", methods=["POST"])
def remover_insumo_peca(item_id):
    item = PecaInsumo.query.get_or_404(item_id)
    peca_id = item.peca_id
    db.session.delete(item)
    db.session.commit()
    flash("Insumo removido da ficha técnica.", "sucesso")
    return redirect(url_for("main.detalhe_peca", peca_id=peca_id))


@bp.route("/pecas/<int:peca_id>/produzir", methods=["POST"])
def produzir_peca(peca_id):
    """Produz N unidades de um tamanho: baixa os insumos da ficha e dá
    entrada no estoque da peça naquele tamanho (com histórico)."""
    peca = Peca.query.get_or_404(peca_id)
    tamanho = request.form.get("tamanho", "").strip().upper()
    unidades = _to_float(request.form.get("unidades"), padrao=1) or 1

    if tamanho not in TAMANHOS:
        flash("Selecione um tamanho válido (PP, P, M, G ou GG).", "erro")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))
    if unidades <= 0:
        flash("Informe uma quantidade maior que zero.", "erro")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))

    # Verifica estoque de insumos suficiente para a produção.
    faltando = [
        f"{item.insumo.nome} (precisa {item.quantidade * unidades:g}, tem {item.insumo.estoque:g})"
        for item in peca.insumos
        if item.quantidade * unidades > item.insumo.estoque
    ]
    if faltando:
        flash("Estoque de insumos insuficiente para: " + "; ".join(faltando), "erro")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))

    # 1) Baixa os insumos da ficha técnica (com histórico de insumos).
    for item in peca.insumos:
        _registrar_movimento(
            item.insumo,
            "saida",
            item.quantidade * unidades,
            observacao=f"Produção de {unidades:g}x '{peca.nome}' tam {tamanho}",
        )

    # 2) Dá entrada no estoque da peça no tamanho escolhido.
    linha = next((e for e in peca.estoques if e.tamanho == tamanho), None)
    if linha is None:
        linha = EstoquePeca(peca=peca, tamanho=tamanho, quantidade=0.0)
        db.session.add(linha)
    linha.quantidade += unidades

    # 3) Registra o movimento no histórico de peças.
    db.session.add(
        MovimentoPeca(
            peca=peca,
            tamanho=tamanho,
            tipo="producao",
            quantidade=unidades,
            observacao=f"Produção de {unidades:g} un.",
        )
    )

    db.session.commit()
    flash(
        f"Produzidas {unidades:g} un. de '{peca.nome}' tam {tamanho}. "
        f"Estoque da peça e dos insumos atualizados.", "sucesso",
    )
    return redirect(url_for("main.detalhe_peca", peca_id=peca.id))


@bp.route("/pecas/<int:peca_id>/preco-etiqueta", methods=["POST"])
def atualizar_preco_etiqueta(peca_id):
    """Atualiza rapidamente o preço de etiqueta (preço comercial) da peça."""
    peca = Peca.query.get_or_404(peca_id)
    peca.preco_etiqueta = _to_float(request.form.get("preco_etiqueta"))
    db.session.commit()
    flash(f"Preço etiqueta atualizado para {peca.preco_etiqueta:.2f}.", "sucesso")
    return redirect(url_for("main.detalhe_peca", peca_id=peca.id))


@bp.route("/pecas/<int:peca_id>/estoque/ajustar", methods=["POST"])
def ajustar_estoque_peca(peca_id):
    """Define manualmente a quantidade em estoque de um tamanho da peça."""
    peca = Peca.query.get_or_404(peca_id)
    tamanho = request.form.get("tamanho", "").strip().upper()
    nova_qtd = _to_float(request.form.get("quantidade"), padrao=-1)

    if tamanho not in TAMANHOS or nova_qtd < 0:
        flash("Selecione um tamanho válido e uma quantidade (0 ou mais).", "erro")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))

    linha = next((e for e in peca.estoques if e.tamanho == tamanho), None)
    anterior = linha.quantidade if linha else 0.0
    if linha is None:
        linha = EstoquePeca(peca=peca, tamanho=tamanho, quantidade=0.0)
        db.session.add(linha)
    linha.quantidade = nova_qtd

    delta = nova_qtd - anterior
    db.session.add(
        MovimentoPeca(
            peca=peca, tamanho=tamanho, tipo="ajuste", quantidade=delta,
            observacao=f"Ajuste manual: {anterior:g} → {nova_qtd:g}",
        )
    )
    db.session.commit()
    flash(f"Estoque do tamanho {tamanho} ajustado para {nova_qtd:g}.", "sucesso")
    return redirect(url_for("main.detalhe_peca", peca_id=peca.id))


@bp.route("/historico")
def historico():
    mov_pecas = MovimentoPeca.query.order_by(MovimentoPeca.criado_em.desc()).limit(300).all()
    mov_insumos = MovimentoEstoque.query.order_by(MovimentoEstoque.criado_em.desc()).limit(300).all()
    return render_template("historico.html", mov_pecas=mov_pecas, mov_insumos=mov_insumos)


# --------------------------------------------------------------------------- #
# Clientes
# --------------------------------------------------------------------------- #
@bp.route("/clientes")
def listar_clientes():
    q = request.args.get("q", "").strip()
    query = Cliente.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Cliente.nome.ilike(like), Cliente.instagram.ilike(like)))
    clientes = query.order_by(Cliente.nome).all()
    return render_template("clientes.html", clientes=clientes, q=q)


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


# --------------------------------------------------------------------------- #
# Vendas
# --------------------------------------------------------------------------- #
def _pecas_com_estoque():
    """Peças que têm ao menos 1 unidade em algum tamanho (para vender)."""
    return [p for p in Peca.query.order_by(Peca.nome).all() if p.estoque_total >= 1]


def _dados_pedido_do_form():
    cid = request.form.get("cliente_id", type=int)
    return {
        "frete": _to_float(request.form.get("frete")),
        "frete_cortesia": request.form.get("frete_cortesia") == "on",
        "marketplace_pct": _to_float(request.form.get("marketplace_pct")),
        "desconto_total": _to_float(request.form.get("desconto_total")),
        "cliente_id": cid if cid else None,
        "forma_pagamento": request.form.get("forma_pagamento", "").strip(),
        "pago": request.form.get("pago") == "on",
        "vencimento": _to_date(request.form.get("vencimento")),
    }


def _itens_do_form():
    """Lê as linhas de item do formulário. Retorna (linhas, erro)."""
    ids = request.form.getlist("peca_id")
    tamanhos = request.form.getlist("tamanho")
    qtds = request.form.getlist("quantidade")
    precos = request.form.getlist("preco_unitario")
    descontos = request.form.getlist("desconto")
    linhas = []
    for i, pid in enumerate(ids):
        if not pid:
            continue
        peca = Peca.query.get(int(pid))
        tam = (tamanhos[i] if i < len(tamanhos) else "").strip().upper()
        qtd = _to_float(qtds[i] if i < len(qtds) else 0)
        preco = _to_float(precos[i] if i < len(precos) else 0)
        desconto = _to_float(descontos[i] if i < len(descontos) else 0)
        if not peca or tam not in TAMANHOS or qtd <= 0:
            continue
        linhas.append({"peca": peca, "tamanho": tam, "quantidade": qtd, "preco": preco, "desconto": desconto})
    if not linhas:
        return [], "Adicione ao menos um item com peça, tamanho e quantidade válidos."
    return linhas, None


def _agrupar(linhas):
    """Soma as quantidades por (peca_id, tamanho)."""
    agrup = {}
    for l in linhas:
        agrup[(l["peca"].id, l["tamanho"])] = agrup.get((l["peca"].id, l["tamanho"]), 0.0) + l["quantidade"]
    return agrup


def _itens_crus_do_form():
    """Reconstrói os itens digitados (mesmo inválidos) para repovoar o formulário."""
    ids = request.form.getlist("peca_id")
    tamanhos = request.form.getlist("tamanho")
    qtds = request.form.getlist("quantidade")
    precos = request.form.getlist("preco_unitario")
    descontos = request.form.getlist("desconto")
    itens = []
    for i, pid in enumerate(ids):
        peca = Peca.query.get(int(pid)) if pid else None
        itens.append({
            "peca_id": pid or "",
            "nome": peca.nome if peca else "",
            "foto": peca.foto if peca else None,
            "tamanho": tamanhos[i] if i < len(tamanhos) else "",
            "quantidade": qtds[i] if i < len(qtds) else "",
            "preco": precos[i] if i < len(precos) else "",
            "desconto": descontos[i] if i < len(descontos) else "",
            "estoque": peca.estoque_por_tamanho if peca else {},
        })
    return itens


def _render_vendas(prefill_itens=None, prefill_pedido=None):
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()  # "pago" | "pendente" | ""
    vendas = Venda.query.order_by(Venda.criado_em.desc()).all()
    if q:
        ql = q.lower()
        vendas = [v for v in vendas if ql in (v.cliente_nome or "").lower()]
    if status == "pago":
        vendas = [v for v in vendas if v.pago]
    elif status == "pendente":
        vendas = [v for v in vendas if not v.pago]
    totais = {
        "receita": sum(v.receita for v in vendas),
        "custo": sum(v.custo_total for v in vendas),
        "lucro": sum(v.lucro for v in vendas),
        "qtd": sum(v.quantidade_total for v in vendas),
    }
    return render_template(
        "vendas.html", vendas=vendas, pecas=_pecas_com_estoque(), totais=totais,
        clientes=Cliente.query.order_by(Cliente.nome).all(),
        prefill_itens=prefill_itens or [], prefill_pedido=prefill_pedido or {},
        q=q, status=status,
    )


@bp.route("/vendas")
def listar_vendas():
    return _render_vendas()


@bp.route("/vendas/nova", methods=["POST"])
def registrar_venda():
    # Em caso de erro, repovoa o formulário com o que foi digitado.
    def _erro(msg):
        flash(msg, "erro")
        return _render_vendas(_itens_crus_do_form(), request.form)

    linhas, erro = _itens_do_form()
    if erro:
        return _erro(erro)

    # Valida estoque somando por peça/tamanho (caso o mesmo item apareça 2x).
    for (pid, tam), need in _agrupar(linhas).items():
        peca = Peca.query.get(pid)
        linha = _linha_estoque_peca(peca, tam)
        disp = linha.quantidade if linha else 0.0
        if need > disp:
            return _erro(f"Estoque insuficiente de '{peca.nome}' tam {tam} (disponível: {disp:g}).")

    venda = Venda(**_dados_pedido_do_form())
    db.session.add(venda)
    for l in linhas:
        db.session.add(VendaItem(
            venda=venda, peca=l["peca"], tamanho=l["tamanho"],
            quantidade=l["quantidade"], preco_unitario=l["preco"],
            desconto=l["desconto"], custo_unitario=l["peca"].custo_total,
        ))
        linha = _linha_estoque_peca(l["peca"], l["tamanho"], criar=True)
        linha.quantidade -= l["quantidade"]
        db.session.add(MovimentoPeca(
            peca=l["peca"], tamanho=l["tamanho"], tipo="saida", quantidade=l["quantidade"],
            observacao=f"Venda de {l['quantidade']:g} un.",
        ))
    db.session.commit()
    flash(f"Venda registrada com {len(linhas)} item(ns).", "sucesso")
    return redirect(url_for("main.listar_vendas"))


@bp.route("/vendas/<int:venda_id>")
def visualizar_venda(venda_id):
    venda = Venda.query.get_or_404(venda_id)
    return render_template("venda_detalhe.html", venda=venda)


@bp.route("/vendas/<int:venda_id>/editar", methods=["GET", "POST"])
def editar_venda(venda_id):
    venda = Venda.query.get_or_404(venda_id)

    if request.method == "POST":
        linhas, erro = _itens_do_form()
        if erro:
            flash(erro, "erro")
            return render_template("venda_editar.html", venda=venda, pecas=_pecas_com_estoque(), clientes=Cliente.query.order_by(Cliente.nome).all())

        # Estoque que volta ao devolver os itens atuais da venda.
        retornos = {}
        for it in venda.itens:
            retornos[(it.peca_id, it.tamanho)] = retornos.get((it.peca_id, it.tamanho), 0.0) + it.quantidade
        necessarios = _agrupar(linhas)

        # Valida: precisa <= estoque_atual + o que volta da própria venda.
        for (pid, tam), need in necessarios.items():
            peca = Peca.query.get(pid)
            linha = _linha_estoque_peca(peca, tam)
            disp = (linha.quantidade if linha else 0.0) + retornos.get((pid, tam), 0.0)
            if need > disp:
                flash(f"Estoque insuficiente de '{peca.nome}' tam {tam} (disponível: {disp:g}).", "erro")
                return render_template("venda_editar.html", venda=venda, pecas=_pecas_com_estoque(), clientes=Cliente.query.order_by(Cliente.nome).all())

        # Aplica só a diferença líquida por peça/tamanho.
        for chave in set(retornos) | set(necessarios):
            pid, tam = chave
            net = necessarios.get(chave, 0.0) - retornos.get(chave, 0.0)  # >0 sai mais; <0 volta
            if net == 0:
                continue
            peca = Peca.query.get(pid)
            linha = _linha_estoque_peca(peca, tam, criar=True)
            linha.quantidade -= net
            db.session.add(MovimentoPeca(
                peca=peca, tamanho=tam, tipo="saida" if net > 0 else "estorno",
                quantidade=abs(net), observacao=f"Edição de venda #{venda.id}",
            ))

        # Refaz os itens e atualiza os dados do pedido.
        for it in list(venda.itens):
            db.session.delete(it)
        venda.itens = []
        for l in linhas:
            db.session.add(VendaItem(
                venda=venda, peca=l["peca"], tamanho=l["tamanho"],
                quantidade=l["quantidade"], preco_unitario=l["preco"],
                desconto=l["desconto"], custo_unitario=l["peca"].custo_total,
            ))
        for campo, valor in _dados_pedido_do_form().items():
            setattr(venda, campo, valor)

        db.session.commit()
        flash("Venda atualizada e estoque ajustado.", "sucesso")
        return redirect(url_for("main.listar_vendas"))

    return render_template("venda_editar.html", venda=venda, pecas=_pecas_com_estoque(), clientes=Cliente.query.order_by(Cliente.nome).all())


@bp.route("/vendas/<int:venda_id>/excluir", methods=["POST"])
def excluir_venda(venda_id):
    venda = Venda.query.get_or_404(venda_id)
    # Devolve ao estoque a quantidade de cada item.
    for it in venda.itens:
        linha = _linha_estoque_peca(it.peca, it.tamanho, criar=True)
        linha.quantidade += it.quantidade
        db.session.add(MovimentoPeca(
            peca=it.peca, tamanho=it.tamanho, tipo="estorno", quantidade=it.quantidade,
            observacao=f"Estorno por exclusão de venda #{venda.id}",
        ))
    db.session.delete(venda)
    db.session.commit()
    flash("Venda excluída e estoque devolvido às peças.", "sucesso")
    return redirect(url_for("main.listar_vendas"))


@bp.route("/vendas/<int:venda_id>/pagar", methods=["POST"])
def marcar_pago(venda_id):
    venda = Venda.query.get_or_404(venda_id)
    venda.pago = not venda.pago
    db.session.commit()
    flash(
        f"Venda #{venda.id} marcada como {'paga' if venda.pago else 'pendente'}.", "sucesso"
    )
    return redirect(request.referrer or url_for("main.contabilidade"))


# --------------------------------------------------------------------------- #
# Contabilidade
# --------------------------------------------------------------------------- #
def _mes_de(dt):
    return dt.strftime("%Y-%m") if dt else ""


def _mes_label(chave):
    meses = ["", "jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]
    try:
        ano, mes = chave.split("-")
        return f"{meses[int(mes)]}/{ano}"
    except (ValueError, IndexError):
        return chave


@bp.route("/contabilidade")
def contabilidade():
    mes = request.args.get("mes", "").strip()

    vendas = Venda.query.order_by(Venda.criado_em).all()
    compras = (
        MovimentoEstoque.query.filter_by(tipo="entrada")
        .order_by(MovimentoEstoque.criado_em).all()
    )
    despesas = Despesa.query.order_by(Despesa.criado_em).all()

    def _compra_valor(c):
        return c.valor if c.custo_unitario else c.quantidade * c.insumo.custo_unitario

    # Meses disponíveis (dos dados) para o filtro.
    meses = sorted(
        {_mes_de(v.criado_em) for v in vendas} | {_mes_de(c.criado_em) for c in compras}
        | {_mes_de(d.criado_em) for d in despesas},
        reverse=True,
    )

    def no_mes(dt):
        return (not mes) or _mes_de(dt) == mes

    vendas_f = [v for v in vendas if no_mes(v.criado_em)]
    compras_f = [c for c in compras if no_mes(c.criado_em)]
    despesas_f = [d for d in despesas if no_mes(d.criado_em)]

    # Razão (ledger) unificado: vendas = entrada, compras/despesas = saída.
    ledger = []
    for v in vendas_f:
        itens_txt = ", ".join(f"{i.quantidade:g}x {i.peca.nome} ({i.tamanho})" for i in v.itens)
        ledger.append({
            "data": v.criado_em, "tipo": "entrada", "categoria": "Venda",
            "descricao": f"Pedido #{v.id}" + (f" · {v.cliente_nome}" if v.cliente_nome else ""),
            "detalhe": itens_txt, "valor": v.receita, "pago": v.pago,
        })
    for c in compras_f:
        ledger.append({
            "data": c.criado_em, "tipo": "saida", "categoria": "Compra de insumo",
            "descricao": c.insumo.nome, "detalhe": f"{c.quantidade:g} {c.insumo.unidade} · {c.observacao}",
            "valor": _compra_valor(c), "pago": True,
        })
    for d in despesas_f:
        ledger.append({
            "data": d.criado_em, "tipo": "saida", "categoria": d.categoria or "Despesa",
            "descricao": d.descricao, "detalhe": "", "valor": d.valor, "pago": d.pago,
        })
    ledger.sort(key=lambda x: x["data"], reverse=True)

    recebido = sum(v.receita for v in vendas_f if v.pago)
    a_receber = sum(v.receita for v in vendas_f if not v.pago)
    saidas_insumos = sum(_compra_valor(c) for c in compras_f)
    saidas_despesas = sum(d.valor for d in despesas_f if d.pago)
    saidas_total = saidas_insumos + saidas_despesas
    lucro = sum(v.lucro for v in vendas_f)

    # Recebido por forma de pagamento.
    formas = {}
    for v in vendas_f:
        if v.pago:
            k = v.forma_pagamento or "—"
            formas[k] = formas.get(k, 0.0) + v.receita

    # Contas a receber (vendas pendentes) e a pagar (despesas pendentes) — todas.
    pendentes = sorted(
        [v for v in vendas if not v.pago],
        key=lambda v: (v.vencimento or date.max),
    )
    a_pagar = sorted(
        [d for d in despesas if not d.pago],
        key=lambda d: (d.vencimento or date.max),
    )

    kpis = {
        "recebido": recebido,
        "a_receber": a_receber,
        "saidas": saidas_total,
        "saldo": recebido - saidas_total,
        "lucro": lucro,
        "n_vendas": len(vendas_f),
        "ticket": (sum(v.receita for v in vendas_f) / len(vendas_f)) if vendas_f else 0.0,
        "a_receber_total": sum(v.receita for v in pendentes),
        "a_pagar_total": sum(d.valor for d in a_pagar),
    }

    return render_template(
        "contabilidade.html", ledger=ledger, kpis=kpis, formas=formas,
        pendentes=pendentes, a_pagar=a_pagar, meses=meses, mes_atual=mes, mes_label=_mes_label,
    )


# --------------------------------------------------------------------------- #
# Backup do banco
# --------------------------------------------------------------------------- #
@bp.route("/backup")
def backup():
    caminho = os.path.join(current_app.instance_path, "costcalc.db")
    if not os.path.exists(caminho):
        flash("Banco de dados não encontrado.", "erro")
        return redirect(url_for("main.index"))
    nome = f"costcalc-backup-{date.today().isoformat()}.db"
    return send_file(caminho, as_attachment=True, download_name=nome)


# --------------------------------------------------------------------------- #
# Contas a pagar (Despesas)
# --------------------------------------------------------------------------- #
@bp.route("/despesas")
def listar_despesas():
    despesas = Despesa.query.order_by(Despesa.pago, Despesa.vencimento).all()
    total_pendente = sum(d.valor for d in despesas if not d.pago)
    return render_template("despesas.html", despesas=despesas, total_pendente=total_pendente)


@bp.route("/despesas/nova", methods=["POST"])
@bp.route("/despesas/<int:despesa_id>/editar", methods=["POST"])
def salvar_despesa(despesa_id=None):
    d = Despesa.query.get_or_404(despesa_id) if despesa_id else Despesa()
    descricao = request.form.get("descricao", "").strip()
    if not descricao:
        flash("Informe a descrição da despesa.", "erro")
        return redirect(url_for("main.listar_despesas"))
    if despesa_id is None:
        db.session.add(d)
    d.descricao = descricao
    d.categoria = request.form.get("categoria", "").strip()
    d.valor = _to_float(request.form.get("valor"))
    d.vencimento = _to_date(request.form.get("vencimento"))
    d.pago = request.form.get("pago") == "on"
    db.session.commit()
    flash("Despesa salva.", "sucesso")
    return redirect(url_for("main.listar_despesas"))


@bp.route("/despesas/<int:despesa_id>/pagar", methods=["POST"])
def pagar_despesa(despesa_id):
    d = Despesa.query.get_or_404(despesa_id)
    d.pago = not d.pago
    db.session.commit()
    return redirect(request.referrer or url_for("main.listar_despesas"))


@bp.route("/despesas/<int:despesa_id>/excluir", methods=["POST"])
def excluir_despesa(despesa_id):
    d = Despesa.query.get_or_404(despesa_id)
    db.session.delete(d)
    db.session.commit()
    flash("Despesa excluída.", "sucesso")
    return redirect(url_for("main.listar_despesas"))


# --------------------------------------------------------------------------- #
# Relatório mensal
# --------------------------------------------------------------------------- #
@bp.route("/relatorio")
def relatorio():
    vendas = Venda.query.all()
    # Agrega por mês.
    por_mes = {}
    for v in vendas:
        k = _mes_de(v.criado_em)
        m = por_mes.setdefault(k, {"receita": 0.0, "custo": 0.0, "lucro": 0.0, "qtd": 0.0})
        m["receita"] += v.receita
        m["custo"] += v.custo_total
        m["lucro"] += v.lucro
        m["qtd"] += v.quantidade_total
    meses_ord = sorted(por_mes.keys())
    serie = [{"mes": k, "label": _mes_label(k), **por_mes[k]} for k in meses_ord]

    # Peças mais vendidas (por quantidade).
    ranking = {}
    for v in vendas:
        for it in v.itens:
            r = ranking.setdefault(it.peca.nome, {"qtd": 0.0, "receita": 0.0})
            r["qtd"] += it.quantidade
            r["receita"] += it.subtotal_receita
    mais_vendidas = sorted(ranking.items(), key=lambda x: x[1]["qtd"], reverse=True)[:10]

    # Lucro por coleção.
    por_colecao = {}
    for v in vendas:
        for it in v.itens:
            col = it.peca.colecao or "Sem coleção"
            por_colecao[col] = por_colecao.get(col, 0.0) + it.subtotal_receita
    colecoes = sorted(por_colecao.items(), key=lambda x: x[1], reverse=True)

    return render_template(
        "relatorio.html", serie=serie, mais_vendidas=mais_vendidas, colecoes=colecoes,
    )


# --------------------------------------------------------------------------- #
# Exportações CSV
# --------------------------------------------------------------------------- #
def _csv_response(cabecalho, linhas, nome):
    buf = io.StringIO()
    buf.write("﻿")  # BOM p/ Excel abrir acentos corretamente
    w = csv.writer(buf, delimiter=";")
    w.writerow(cabecalho)
    w.writerows(linhas)
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nome}"},
    )


@bp.route("/vendas/exportar.csv")
def exportar_vendas_csv():
    linhas = []
    for v in Venda.query.order_by(Venda.criado_em).all():
        itens = "; ".join(f"{i.quantidade:g}x {i.peca.nome} ({i.tamanho})" for i in v.itens)
        linhas.append([
            v.id, v.criado_em.strftime("%d/%m/%Y %H:%M"), v.cliente_nome, itens,
            f"{v.receita:.2f}", f"{v.frete:.2f}", f"{v.comissao_marketplace:.2f}",
            f"{v.custo_total:.2f}", f"{v.lucro:.2f}",
            "sim" if v.pago else "não", v.forma_pagamento or "",
        ])
    return _csv_response(
        ["Pedido", "Data", "Cliente", "Itens", "Valor total", "Frete", "Comissão",
         "Custo total", "Lucro", "Pago", "Pagamento"],
        linhas, "vendas.csv",
    )


@bp.route("/contabilidade/receber.csv")
def exportar_receber_csv():
    linhas = [
        [v.id, v.cliente_nome, v.criado_em.strftime("%d/%m/%Y"),
         v.vencimento.strftime("%d/%m/%Y") if v.vencimento else "", f"{v.receita:.2f}",
         "vencida" if v.vencida else "a vencer"]
        for v in Venda.query.filter_by(pago=False).all()
    ]
    return _csv_response(
        ["Pedido", "Cliente", "Data", "Vencimento", "Valor", "Situação"],
        linhas, "contas-a-receber.csv",
    )


# --------------------------------------------------------------------------- #
# Etiqueta com QR code
# --------------------------------------------------------------------------- #
@bp.route("/pecas/<int:peca_id>/etiqueta")
def etiqueta_peca(peca_id):
    peca = Peca.query.get_or_404(peca_id)
    url_peca = url_for("main.detalhe_peca", peca_id=peca.id, _external=True)
    return render_template("etiqueta.html", peca=peca, url_peca=url_peca)


# --------------------------------------------------------------------------- #
# Cadastro rápido de cliente (JSON, usado no modal da venda)
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Vitrine pública (sem menu, para compartilhar com o cliente)
# --------------------------------------------------------------------------- #
@bp.route("/publico/vitrine")
def vitrine_publica():
    pecas = Peca.query.order_by(Peca.colecao, Peca.nome).all()
    grupos = {}
    for p in pecas:
        grupos.setdefault(p.colecao or "Sem coleção", []).append(p)
    return render_template("vitrine_publica.html", grupos=grupos)


# --------------------------------------------------------------------------- #
# Frete (Melhor Envio) — requer token configurado em MELHOR_ENVIO_TOKEN
# --------------------------------------------------------------------------- #
@bp.route("/frete/calcular", methods=["POST"])
def calcular_frete():
    import json
    import urllib.request

    token = os.environ.get("MELHOR_ENVIO_TOKEN", "").strip()
    cep_origem = os.environ.get("CEP_ORIGEM", "").strip()
    if not token or not cep_origem:
        return {"ok": False, "erro": "Frete não configurado. Defina MELHOR_ENVIO_TOKEN e CEP_ORIGEM."}, 400

    cep_destino = re.sub(r"\D", "", request.form.get("cep", ""))
    if len(cep_destino) != 8:
        return {"ok": False, "erro": "CEP de destino inválido."}, 400

    payload = {
        "from": {"postal_code": re.sub(r"\D", "", cep_origem)},
        "to": {"postal_code": cep_destino},
        "package": {
            "weight": _to_float(request.form.get("peso")) / 1000 or 0.3,   # kg
            "height": _to_float(request.form.get("altura")) or 5,
            "width": _to_float(request.form.get("largura")) or 20,
            "length": _to_float(request.form.get("comprimento")) or 30,
        },
    }
    req = urllib.request.Request(
        "https://melhorenvio.com.br/api/v2/me/shipment/calculate",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "Authorization": f"Bearer {token}", "User-Agent": "cost-calculation",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            dados = json.loads(resp.read())
        opcoes = [
            {"nome": o.get("name"), "preco": o.get("price"), "prazo": o.get("delivery_time")}
            for o in dados if not o.get("error") and o.get("price")
        ]

        def _preco(o):
            try:
                return float(o["preco"])
            except (TypeError, ValueError):
                return float("inf")

        # Remove repetições pelo nome do serviço (mantém a mais barata de cada).
        unicas = {}
        for o in opcoes:
            if o["nome"] not in unicas or _preco(o) < _preco(unicas[o["nome"]]):
                unicas[o["nome"]] = o
        lista = list(unicas.values())

        # Seleciona: a mais rápida + as 3 mais baratas (sem repetir), no máx. 4.
        selecionadas = []
        if lista:
            rapida = min(lista, key=lambda o: ((o.get("prazo") or 999), _preco(o)))
            rapida["rapido"] = True
            selecionadas.append(rapida)
            for o in sorted(lista, key=_preco):
                if len(selecionadas) >= 4:
                    break
                if o is not rapida:
                    selecionadas.append(o)
        return {"ok": True, "opcoes": selecionadas}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": f"Falha ao consultar frete: {e}"}, 502
