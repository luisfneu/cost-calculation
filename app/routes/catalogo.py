"""Rotas: catalogo."""
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


@bp.route("/vitrine")
def vitrine():
    """Vitrine para mostrar ao cliente: foto + preço de etiqueta, por coleção."""
    pecas = Peca.query.order_by(Peca.colecao, Peca.nome).all()
    grupos = {}
    for p in pecas:
        grupos.setdefault(p.colecao or "Sem coleção", []).append(p)
    return render_template("vitrine.html", grupos=grupos)


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
    elif situacao == "ativo":
        insumos = [i for i in insumos if i.ativo]
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


@bp.route("/pecas")
def listar_pecas():
    q = request.args.get("q", "").strip()
    query = Peca.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Peca.nome.ilike(like), Peca.colecao.ilike(like), Peca.tags.ilike(like)))
    pecas = query.order_by(Peca.criado_em.desc()).all()
    pecas, pagina, total_paginas = _paginar(pecas)
    return render_template("pecas.html", pecas=pecas, q=q, pagina=pagina, total_paginas=total_paginas)


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

        # Atualiza só o que foi enviado — campos ausentes preservam o valor atual
        # (evita zerar dados numa edição parcial).
        def _txt(campo, atual):
            return request.form.get(campo).strip() if campo in request.form else atual

        def _num(campo, atual):
            return _to_float(request.form.get(campo)) if campo in request.form else atual

        peca.nome = nome
        peca.colecao = _txt("colecao", peca.colecao)
        peca.tags = _txt("tags", peca.tags)
        peca.descricao = _txt("descricao", peca.descricao)
        peca.custo_mao_de_obra = _num("custo_mao_de_obra", peca.custo_mao_de_obra)
        peca.custos_extras = _num("custos_extras", peca.custos_extras)
        peca.margem_percentual = _num("margem_percentual", peca.margem_percentual)
        peca.preco_etiqueta = _num("preco_etiqueta", peca.preco_etiqueta)
        peca.preco_promocional = _num("preco_promocional", peca.preco_promocional)
        peca.sku = _txt("sku", peca.sku)
        peca.peso_g = _num("peso_g", peca.peso_g)
        peca.altura_cm = _num("altura_cm", peca.altura_cm)
        peca.largura_cm = _num("largura_cm", peca.largura_cm)
        peca.comprimento_cm = _num("comprimento_cm", peca.comprimento_cm)

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


@bp.route("/ficha/<int:item_id>/quantidade", methods=["POST"])
def atualizar_qtd_ficha(item_id):
    item = PecaInsumo.query.get_or_404(item_id)
    qtd = _to_float(request.form.get("quantidade"))
    if qtd > 0:
        item.quantidade = qtd
        db.session.commit()
        flash("Quantidade atualizada.", "sucesso")
    else:
        flash("Quantidade inválida.", "erro")
    return redirect(url_for("main.detalhe_peca", peca_id=item.peca_id))


@bp.route("/pecas/<int:peca_id>/duplicar", methods=["POST"])
def duplicar_peca(peca_id):
    orig = Peca.query.get_or_404(peca_id)
    nova = Peca(
        nome=f"{orig.nome} (cópia)", colecao=orig.colecao, tags=orig.tags,
        descricao=orig.descricao, foto=_copiar_foto(orig.foto),
        custo_mao_de_obra=orig.custo_mao_de_obra, custos_extras=orig.custos_extras,
        margem_percentual=orig.margem_percentual, preco_etiqueta=orig.preco_etiqueta,
        peso_g=orig.peso_g, altura_cm=orig.altura_cm,
        largura_cm=orig.largura_cm, comprimento_cm=orig.comprimento_cm,
    )
    db.session.add(nova)
    db.session.flush()
    # Copia a ficha técnica (não copia estoque nem fotos extras).
    for it in orig.insumos:
        db.session.add(PecaInsumo(peca=nova, insumo=it.insumo, quantidade=it.quantidade))
    db.session.commit()
    flash("Peça duplicada. Ajuste o nome e os dados.", "sucesso")
    return redirect(url_for("main.form_peca", peca_id=nova.id))


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
    _log("estoque", f"ajuste manual {peca.nome} tam {tamanho} → {nova_qtd:g}")
    flash(f"Estoque do tamanho {tamanho} ajustado para {nova_qtd:g}.", "sucesso")
    return redirect(url_for("main.detalhe_peca", peca_id=peca.id))


@bp.route("/pecas/<int:peca_id>/etiqueta")
def etiqueta_peca(peca_id):
    peca = Peca.query.get_or_404(peca_id)
    # Tamanho pré-selecionado via ?tamanho= (opcional).
    tam_sel = (request.args.get("tamanho") or "").strip().upper()
    if tam_sel not in TAMANHOS:
        tam_sel = ""
    return render_template("etiqueta.html", peca=peca, tamanhos=TAMANHOS, tam_sel=tam_sel)


@bp.route("/publico/vitrine")
def vitrine_publica():
    pecas = Peca.query.order_by(Peca.colecao, Peca.nome).all()
    grupos = {}
    for p in pecas:
        grupos.setdefault(p.colecao or "Sem coleção", []).append(p)
    return render_template("vitrine_publica.html", grupos=grupos)


@bp.route("/kits")
def listar_kits():
    kits = Kit.query.order_by(Kit.ativo.desc(), Kit.nome).all()
    pecas = Peca.query.order_by(Peca.nome).all()
    return render_template("kits.html", kits=kits, pecas=pecas)


@bp.route("/kits/novo", methods=["POST"])
def salvar_kit():
    nome = request.form.get("nome", "").strip()
    if not nome:
        flash("Informe o nome do kit.", "erro")
        return redirect(url_for("main.listar_kits"))
    kit = Kit(nome=nome, preco=_to_float(request.form.get("preco")))
    _salvar_itens_kit(kit)
    if not kit.itens:
        flash("Adicione ao menos uma peça ao kit.", "erro")
        return redirect(url_for("main.listar_kits"))
    db.session.add(kit)
    db.session.commit()
    flash("Kit criado.", "sucesso")
    return redirect(url_for("main.listar_kits"))


@bp.route("/kits/<int:kit_id>/editar", methods=["POST"])
def editar_kit(kit_id):
    kit = Kit.query.get_or_404(kit_id)
    nome = request.form.get("nome", "").strip()
    if nome:
        kit.nome = nome
    kit.preco = _to_float(request.form.get("preco"))
    _salvar_itens_kit(kit)
    db.session.commit()
    flash("Kit atualizado.", "sucesso")
    return redirect(url_for("main.listar_kits"))


@bp.route("/kits/<int:kit_id>/toggle", methods=["POST"])
def toggle_kit(kit_id):
    kit = Kit.query.get_or_404(kit_id)
    kit.ativo = not kit.ativo
    db.session.commit()
    return redirect(url_for("main.listar_kits"))


@bp.route("/kits/<int:kit_id>/excluir", methods=["POST"])
def excluir_kit(kit_id):
    kit = Kit.query.get_or_404(kit_id)
    db.session.delete(kit)
    db.session.commit()
    flash("Kit excluído.", "sucesso")
    return redirect(url_for("main.listar_kits"))
