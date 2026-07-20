"""Rotas: catalogo."""
import calendar
import csv
import io
import json
import math
import os
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from .. import csrf
from ..extensions import cache, limiter
from ..models import (
    MEDIDAS_CAMPOS,
    MEDIDAS_FEMININAS,
    MEDIDAS_TAMANHOS,
    TAMANHOS,
    Auditoria,
    Campanha,
    CampanhaPeca,
    Cliente,
    Colecao,
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
    NewsletterEnvio,
    NewsletterInscrito,
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
    dinheiro,
)
from . import bp, publico_bp
from .helpers import *  # noqa: F401,F403


@bp.route("/vitrine")
def vitrine():
    """Vitrine para mostrar ao cliente: foto + preço de etiqueta, por coleção."""
    pecas = Peca.query.order_by(Peca.colecao, Peca.nome).all()
    grupos = {}
    for p in pecas:
        grupos.setdefault(p.colecao or "Sem coleção", []).append(p)
    # Foto principal de cada coleção cadastrada (para compor o carrossel das peças).
    colecao_fotos = {c.nome: c.foto for c in Colecao.query.all() if c.foto}
    return render_template("vitrine.html", grupos=grupos, colecao_fotos=colecao_fotos)


@bp.route("/insumos")
def listar_insumos():
    insumos, filtro = _insumos_filtrados()
    insumos, pagina, total_paginas = _paginar(insumos)
    return render_template("insumos.html", insumos=insumos, pagina=pagina,
                           total_paginas=total_paginas, **filtro)


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
        tipo = request.form.get("tipo", "aviamento")
        insumo.tipo = tipo if tipo in ("tecido", "aviamento", "embalagem") else "aviamento"
        # Composição e largura só fazem sentido para tecido.
        if insumo.tipo == "tecido":
            insumo.composicao = request.form.get("composicao", "").strip()
            insumo.largura_cm = _to_float(request.form.get("largura"))
        else:
            insumo.composicao = ""
            insumo.largura_cm = 0.0
        insumo.unidade = request.form.get("unidade", "un").strip() or "un"
        insumo.custo_unitario = dinheiro(_to_float(request.form.get("custo_unitario")))
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
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
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


@bp.route("/insumos/<int:insumo_id>/movimentos")
def movimentos_insumo(insumo_id):
    """Fragmento HTML (para modal) com a movimentação do insumo, paginada em 15."""
    insumo = Insumo.query.get_or_404(insumo_id)
    movs = (
        MovimentoEstoque.query.filter_by(insumo_id=insumo_id)
        .order_by(MovimentoEstoque.criado_em.desc()).all()
    )
    movs, pagina, total_paginas = _paginar(movs, por_pagina=15)
    return render_template(
        "_movimentos_insumo.html", insumo=insumo, movs=movs,
        pagina=pagina, total_paginas=total_paginas,
    )


@bp.route("/pecas")
def listar_pecas():
    q = request.args.get("q", "").strip()
    tipo = request.args.get("tipo", "").strip()
    vitrine = request.args.get("vitrine", "").strip()  # "", "sim" (públicas), "nao" (ocultas)
    query = Peca.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Peca.nome.ilike(like), Peca.colecao.ilike(like), Peca.tags.ilike(like)))
    if tipo:
        query = query.filter(Peca.tipo == tipo)
    if vitrine == "sim":
        query = query.filter(Peca.vitrine_publica.is_(True))
    elif vitrine == "nao":
        query = query.filter(Peca.vitrine_publica.is_(False))
    pecas = query.order_by(Peca.criado_em.desc()).all()
    pecas, pagina, total_paginas = _paginar(pecas)
    # Tipos já cadastrados (para o filtro).
    tipos = [r[0] for r in db.session.query(Peca.tipo)
             .filter(Peca.tipo.isnot(None), Peca.tipo != "")
             .distinct().order_by(Peca.tipo).all()]
    return render_template("pecas.html", pecas=pecas, q=q, tipo=tipo, tipos=tipos,
                           vitrine=vitrine, pagina=pagina, total_paginas=total_paginas)


@bp.route("/pecas/comparar")
def comparar_pecas():
    """Comparação lado a lado de várias peças para análise de custo/preço."""
    ids = [int(x) for x in request.args.get("ids", "").split(",") if x.strip().isdigit()]
    pecas = Peca.query.filter(Peca.id.in_(ids)).all() if ids else []
    ordem = {pid: i for i, pid in enumerate(ids)}
    pecas.sort(key=lambda p: ordem.get(p.id, 999))
    return render_template("pecas_comparar.html", pecas=pecas)


@bp.route("/pecas/nova", methods=["GET", "POST"])
@bp.route("/pecas/<int:peca_id>/editar", methods=["GET", "POST"])
def form_peca(peca_id=None):
    peca = Peca.query.get_or_404(peca_id) if peca_id else None
    insumos = Insumo.query.order_by(Insumo.nome).all()
    is_nova = peca is None
    # Coleções ativas (select) + tipos já usados (datalist).
    colecoes_ativas = Colecao.query.filter_by(ativa=True).order_by(Colecao.nome).all()
    colecoes = [c.nome for c in colecoes_ativas]
    colecao_fotos = {c.nome: c.foto for c in colecoes_ativas if c.foto}
    tipos = [r[0] for r in db.session.query(Peca.tipo)
             .filter(Peca.tipo.isnot(None), Peca.tipo != "")
             .distinct().order_by(Peca.tipo).all()]

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("O nome da peça é obrigatório.", "erro")
            return render_template("peca_form.html", peca=peca, insumos=insumos, colecoes=colecoes, tipos=tipos, colecao_fotos=colecao_fotos)

        # Na criação: lê os insumos selecionados para montar a ficha técnica.
        # (Não dá baixa no estoque — isso só acontece ao Produzir.)
        linhas = []          # [(insumo, qtd_por_peca), ...]
        if is_nova:
            ids = request.form.getlist("insumo_id")
            qtds = request.form.getlist("quantidade_insumo")
            vistos = set()
            for iid, q in zip(ids, qtds, strict=False):
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

        promo_antes = bool(peca and peca.em_promocao)   # p/ aviso de promoção
        peca.nome = nome
        peca.vitrine_publica = request.form.get("vitrine_publica") == "on"
        peca.tipo = _txt("tipo", peca.tipo)
        peca.colecao = _txt("colecao", peca.colecao)
        peca.tags = _txt("tags", peca.tags)
        peca.descricao = _txt("descricao", peca.descricao)
        peca.composicao = _txt("composicao", peca.composicao)
        zona = request.form.get("zona_corpo", "").strip()
        if zona in ("superior", "inferior", "inteiro"):
            peca.zona_corpo = zona
        # Medidas: grade tamanho × medida → JSON. Só grava quando a grade foi enviada.
        if any(k.startswith("medida_") for k in request.form):
            md = {}
            for tam in MEDIDAS_TAMANHOS:
                vals = {c: request.form.get(f"medida_{tam}_{c}", "").strip()
                        for c, _ in MEDIDAS_CAMPOS}
                if any(vals.values()):
                    md[tam] = vals
            peca.medidas = json.dumps(md, ensure_ascii=False) if md else ""
        peca.custo_mao_de_obra = dinheiro(_num("custo_mao_de_obra", peca.custo_mao_de_obra))
        peca.custos_extras = dinheiro(_num("custos_extras", peca.custos_extras))
        peca.margem_percentual = _num("margem_percentual", peca.margem_percentual)
        peca.preco_etiqueta = dinheiro(_num("preco_etiqueta", peca.preco_etiqueta))
        peca.preco_promocional = dinheiro(_num("preco_promocional", peca.preco_promocional))
        peca.peso_g = _num("peso_g", peca.peso_g)
        peca.altura_cm = _num("altura_cm", peca.altura_cm)
        peca.largura_cm = _num("largura_cm", peca.largura_cm)
        peca.comprimento_cm = _num("comprimento_cm", peca.comprimento_cm)

        # --- Imagens: uploader unificado (várias fotos + escolha da principal) ---
        # Fotos novas enviadas (preservando a ordem de seleção).
        novas = []
        for arq in request.files.getlist("fotos"):
            nome_arq = _salvar_foto(arq)
            if nome_arq:
                novas.append(nome_arq)

        # Imagens existentes marcadas para remover (por nome de arquivo).
        remover = set(request.form.getlist("remover_existente"))

        # Conjunto atual (principal + galeria), preservando a ordem.
        existentes = ([peca.foto] if peca.foto else []) + [f.arquivo for f in peca.fotos]
        for f in existentes:
            if f in remover:
                _remover_foto(f)  # apaga do disco as descartadas
        mantidas = [f for f in existentes if f not in remover]

        # Lista final e escolha da principal.
        final = mantidas + novas
        escolha = request.form.get("principal", "")
        principal = None
        if escolha.startswith("nova:"):
            try:
                principal = novas[int(escolha.split(":", 1)[1])]
            except (ValueError, IndexError):
                principal = None
        elif escolha.startswith("existente:"):
            alvo = escolha.split(":", 1)[1]
            principal = alvo if alvo in final else None
        if principal is None:
            principal = final[0] if final else None

        # Reconstrói principal + galeria (a principal fica em primeiro).
        ordenadas = ([principal] + [f for f in final if f != principal]) if final else []
        for f in list(peca.fotos):            # recria a galeria do zero
            db.session.delete(f)
        peca.foto = ordenadas[0] if ordenadas else None
        for f in ordenadas[1:]:
            db.session.add(FotoPeca(peca=peca, arquivo=f))

        # Na criação: monta a ficha técnica (quantidade por peça).
        if is_nova and linhas:
            for insumo, qtd in linhas:
                db.session.add(PecaInsumo(peca=peca, insumo=insumo, quantidade=qtd))

        # SKU único gerado a partir do id (padrão SH-00000000). Garante o id via flush.
        db.session.flush()
        peca.sku = Peca.gerar_sku(peca.id)

        db.session.commit()
        _avisar_favoritos_promocao(peca, promo_antes)
        flash("Peça salva. Use 'Produzir' para fabricar e dar entrada no estoque.", "sucesso")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))

    return render_template("peca_form.html", peca=peca, insumos=insumos, colecoes=colecoes, tipos=tipos, colecao_fotos=colecao_fotos)


@bp.route("/pecas/<int:peca_id>")
def detalhe_peca(peca_id):
    peca = Peca.query.get_or_404(peca_id)
    insumos = Insumo.query.order_by(Insumo.nome).all()
    return render_template("peca_detalhe.html", peca=peca, insumos_disponiveis=insumos)


@bp.route("/pecas/<int:peca_id>/excluir", methods=["POST"])
def excluir_peca(peca_id):
    bloqueio = _exigir_admin()   # destrutivo: apaga fotos e cadastro
    if bloqueio:
        return bloqueio
    peca = Peca.query.get_or_404(peca_id)
    # Guarda: não apagar peça que já tem histórico (vendas ou ordens de produção).
    # Apagar quebraria recibos/vendas antigos (it.peca vira None → erro) e perderia
    # o custo registrado. Nesses casos, oculte da vitrine em vez de excluir.
    em_vendas = VendaItem.query.filter_by(peca_id=peca.id).count()
    em_producao = OrdemProducaoItem.query.filter_by(peca_id=peca.id).count()
    if em_vendas or em_producao:
        flash("Esta peça tem histórico (vendas/produção) e não pode ser excluída. "
              "Desmarque 'vitrine pública' para ocultá-la.", "erro")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))
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


@bp.route("/pecas/<int:peca_id>/produzir", methods=["POST"])
def produzir_peca(peca_id):
    """Produz N unidades de um tamanho: baixa os insumos da ficha e dá
    entrada no estoque da peça naquele tamanho (com histórico)."""
    peca = Peca.query.get_or_404(peca_id)
    disp_antes = peca.disponivel_total   # para o aviso "voltou ao estoque"
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
    _avisar_favoritos_voltou(peca, disp_antes)
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


@bp.route("/pecas/<int:peca_id>/margem", methods=["POST"])
def atualizar_margem(peca_id):
    """Atualiza a margem (%) da peça — ferramenta de precificação no detalhe."""
    peca = Peca.query.get_or_404(peca_id)
    peca.margem_percentual = _to_float(request.form.get("margem"))
    db.session.commit()
    flash(f"Margem atualizada para {peca.margem_percentual:g}%.", "sucesso")
    return redirect(url_for("main.detalhe_peca", peca_id=peca.id))


@bp.route("/pecas/<int:peca_id>/estoque/ajustar", methods=["POST"])
def ajustar_estoque_peca(peca_id):
    """Define manualmente a quantidade em estoque de um tamanho da peça."""
    peca = Peca.query.get_or_404(peca_id)
    disp_antes = peca.disponivel_total   # para o aviso "voltou ao estoque"
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
    _avisar_favoritos_voltou(peca, disp_antes)
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


@bp.route("/pecas/etiquetas")
def etiquetas_lote():
    """Impressão de várias etiquetas de uma vez (?ids=1,2,3)."""
    ids = [int(x) for x in request.args.get("ids", "").split(",") if x.strip().isdigit()]
    pecas = Peca.query.filter(Peca.id.in_(ids)).all() if ids else []
    ordem = {pid: i for i, pid in enumerate(ids)}       # preserva a ordem pedida
    pecas.sort(key=lambda p: ordem.get(p.id, 0))
    return render_template("etiquetas_lote.html", pecas=pecas)


@publico_bp.route("/robots.txt")
@limiter.exempt
def robots_txt():
    corpo = ("User-agent: *\n"
             "Disallow: /console/\n"
             "Disallow: /conta/\n"
             "Disallow: /publico/\n"
             f"Sitemap: {_link_publico('/sitemap.xml')}\n")
    return Response(corpo, mimetype="text/plain")


@publico_bp.route("/sitemap.xml")
@limiter.exempt
def sitemap_xml():
    """Sitemap: vitrine + páginas públicas das peças (para indexação)."""
    urls = [(_link_publico("/"), None)]
    for p in Peca.query.filter_by(vitrine_publica=True).all():
        urls.append((_link_publico(url_for("publico.peca_publica", peca_id=p.id)), p.criado_em))
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, dt_ in urls:
        lastmod = f"<lastmod>{dt_.date().isoformat()}</lastmod>" if dt_ else ""
        linhas.append(f"<url><loc>{loc}</loc>{lastmod}</url>")
    linhas.append("</urlset>")
    return Response("\n".join(linhas), mimetype="application/xml")


@publico_bp.route("/publico/sugestoes")
@limiter.limit("60 per minute")
def sugestoes_busca():
    """Autocomplete da busca da vitrine: nomes/coleções que casam com ?q=."""
    q = request.args.get("q", "").strip()
    out = []
    if len(q) >= 2:
        like = f"%{q}%"
        pecas = (Peca.query.filter(Peca.vitrine_publica.is_(True))
                 .filter(db.or_(Peca.nome.ilike(like), Peca.colecao.ilike(like),
                                Peca.tags.ilike(like)))
                 .order_by(Peca.nome).limit(8).all())
        out = [{"nome": p.nome, "url": url_for("publico.peca_publica", peca_id=p.id)}
               for p in pecas]
    return {"sugestoes": out}


def _cliente_esta_logado():
    """True se há um cliente logado na vitrine. Usado para NÃO cachear a página
    quando ela contém o menu/dados pessoais do cliente (senão o cache global
    serviria o menu 'Sair' e os dados de um cliente para outros visitantes)."""
    from .conta import _cliente_logado
    return _cliente_logado() is not None


@publico_bp.route("/peca/<int:peca_id>")
@limiter.limit("60 per minute")
def peca_publica(peca_id):
    """Página individual da peça — URL própria e compartilhável (com OG por peça)."""
    peca = Peca.query.get_or_404(peca_id)
    if not peca.vitrine_publica:
        abort(404)
    # Contador de views via UPDATE direto (não passa pelo ORM) — de propósito:
    # objeto Peca "sujo" no commit derrubaria o cache da vitrine a cada visita.
    db.session.execute(db.update(Peca).where(Peca.id == peca.id).values(views=Peca.views + 1))
    db.session.commit()
    colecao_fotos = {c.nome: c.foto for c in Colecao.query.all() if c.foto}
    whatsapp = Parametro.obter("whatsapp", "")
    foto = peca.foto or colecao_fotos.get(peca.colecao)
    og_image = url_for("static", filename="uploads/" + foto, _external=True) if foto else None
    meta_desc = (peca.descricao or "").strip() or f"{peca.nome} — ateliê Sabrina Hansen."
    # Avaliações aprovadas (prova social) + JSON-LD Product (rich results).
    avaliacoes = [a for a in peca.avaliacoes if a.aprovado]
    jsonld = {
        "@context": "https://schema.org", "@type": "Product",
        "name": peca.nome, "description": meta_desc,
        "sku": peca.sku or f"SH-{peca.id}",
        "image": [og_image] if og_image else [],
        "offers": {
            "@type": "Offer", "priceCurrency": "BRL",
            "price": f"{peca.preco_etiqueta_efetivo:.2f}",
            "availability": "https://schema.org/" + (
                "OutOfStock" if peca.esgotado else
                ("PreOrder" if peca.sob_encomenda else "InStock")),
            "url": url_for("publico.peca_publica", peca_id=peca.id, _external=True),
        },
    }
    if avaliacoes:
        jsonld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": f"{sum(a.nota for a in avaliacoes) / len(avaliacoes):.1f}",
            "reviewCount": len(avaliacoes),
        }
    resp = make_response(render_template(
        "peca_publica.html", peca=peca, tamanhos=TAMANHOS, colecao_fotos=colecao_fotos,
        whatsapp=whatsapp, og_image=og_image, meta_desc=meta_desc,
        avaliacoes=avaliacoes, jsonld=jsonld, medidas_padrao=MEDIDAS_FEMININAS,
        guia_medidas=Parametro.obter("guia_medidas", "")))
    if _cliente_esta_logado():
        resp.headers["Cache-Control"] = "no-store"
    return resp


def _foto_thumb_url(nome):
    """URL da miniatura da foto (ou da cheia), para JSON/JS."""
    if not nome:
        return ""
    thumb = f"thumb_{nome.rsplit('.', 1)[0]}.jpg"
    if os.path.exists(os.path.join(current_app.config["UPLOAD_FOLDER"], thumb)):
        return url_for("static", filename="uploads/" + thumb)
    return url_for("static", filename="uploads/" + nome)


@publico_bp.route("/publico/pecas")
@limiter.limit("60 per minute")
def pecas_info():
    """Info pública de peças por id (?ids=1,2,3) — usado pela página de favoritos."""
    ids = [int(x) for x in request.args.get("ids", "").split(",") if x.strip().isdigit()]
    out = []
    if ids:
        pecas = Peca.query.filter(Peca.id.in_(ids), Peca.vitrine_publica.is_(True)).all()
        ordem = {pid: i for i, pid in enumerate(ids)}
        pecas.sort(key=lambda p: ordem.get(p.id, 0))
        for p in pecas:
            out.append({
                "id": p.id, "nome": p.nome,
                "url": url_for("publico.peca_publica", peca_id=p.id),
                "foto": _foto_thumb_url(p.foto),
                "sob_encomenda": bool(p.sob_encomenda),
                "esgotado": bool(p.esgotado),
                # Esgotado exibe o preço de etiqueta (não é comprável, não vai ao carrinho).
                # Encomenda comprável mantém o sinal (preco_vitrine) — é o que o carrinho usa.
                "preco": float(p.preco_etiqueta_efetivo if (p.esgotado or not p.sob_encomenda) else p.preco_vitrine),
                "preco_de": (float(p.preco_base) if (not p.sob_encomenda and p.em_promocao) else None),
                "tamanhos": [{"t": t, "disp": p.disponivel_por_tamanho.get(t, 0) > 0} for t in TAMANHOS],
            })
    return {"pecas": out}


@publico_bp.route("/")                 # raiz: www.sabrinahansen.com.br
@publico_bp.route("/vitrine2")         # alias (mantém links antigos da prévia)
@publico_bp.route("/publico/vitrine")  # alias (links antigos)
@limiter.limit("60 per minute")
# Cacheia só a versão anônima (a logada tem menu/dados pessoais → pula o cache).
@cache.cached(timeout=60, query_string=True, unless=_cliente_esta_logado)
def vitrine_v2():
    """Vitrine pública (layout marketplace). Serve a raiz do site."""
    q = request.args.get("q", "").strip().lower()
    tipo = request.args.get("tipo", "").strip()
    colecao = request.args.get("colecao", "").strip()
    ordem = request.args.get("ordem", "").strip()
    tam_sel = [t for t in request.args.getlist("tamanho") if t in TAMANHOS]

    publicas = Peca.query.filter_by(vitrine_publica=True).all()
    pecas = publicas
    if q:
        pecas = [p for p in pecas
                 if q in p.nome.lower() or q in (p.colecao or "").lower() or q in (p.tags or "").lower()]
    if tipo:
        pecas = [p for p in pecas if p.tipo == tipo]
    if colecao:
        pecas = [p for p in pecas if (p.colecao or "") == colecao]
    if tam_sel:
        # Filtro de tamanho: só peças com estoque real no(s) tamanho(s) escolhido(s)
        # (peças sem estoque / sob encomenda não aparecem).
        pecas = [p for p in pecas
                 if any(p.disponivel_por_tamanho.get(t, 0) > 0 for t in tam_sel)]

    chaves = {"preco_asc": lambda p: p.preco_vitrine,
              "preco_desc": lambda p: -p.preco_vitrine,
              "nome": lambda p: p.nome.lower()}
    chave = chaves.get(ordem, lambda p: p.nome.lower())

    # Disponibilidade manda na ordem, sempre: em estoque primeiro, depois sob
    # encomenda (produzível) e por último as esgotadas. A ordenação escolhida
    # (preço/nome) vale dentro de cada grupo.
    def _grupo(p):
        if p.esgotado:
            return 2
        return 1 if p.sob_encomenda else 0
    pecas = sorted(pecas, key=lambda p: (_grupo(p), chave(p)))

    tipos = sorted({p.tipo for p in publicas if p.tipo})
    colecoes = sorted({p.colecao for p in publicas if p.colecao})
    colecao_fotos = {c.nome: c.foto for c in Colecao.query.all() if c.foto}
    whatsapp = Parametro.obter("whatsapp", "")
    limite_novo = datetime.utcnow() - timedelta(days=21)
    novos = {p.id for p in publicas if p.criado_em and p.criado_em >= limite_novo}
    meta_desc = Parametro.obter("vitrine_descricao",
                                "Peças exclusivas do ateliê Sabrina Hansen. Veja a coleção e faça seu pedido pelo WhatsApp.")
    og_peca = next((p for p in pecas if p.foto), None) or next((p for p in publicas if p.foto), None)
    og_image = (url_for("static", filename="uploads/" + og_peca.foto, _external=True)
                if og_peca else None)

    # Slides do carrossel da home: o banner_hero das campanhas vigentes.
    banners = [
        {"imagem": camp.banner_hero, "imagem_mobile": None,
         "titulo": camp.nome, "link": f"/campanha/{camp.slug}"}
        for camp in Campanha.query.filter_by(ativa=True).order_by(Campanha.criado_em.desc()).all()
        if camp.vigente and camp.banner_hero
    ]

    resp = make_response(render_template(
        "vitrine2.html", pecas=pecas, tipos=tipos, colecoes=colecoes, tamanhos=TAMANHOS,
        q=request.args.get("q", ""), tipo=tipo, colecao=colecao, ordem=ordem,
        tam_sel=tam_sel, colecao_fotos=colecao_fotos, whatsapp=whatsapp, novos=novos,
        total=len(pecas), meta_desc=meta_desc, og_image=og_image, banners=banners))
    if _cliente_esta_logado():
        resp.headers["Cache-Control"] = "no-store"   # página logada: não guardar no navegador
    return resp


@publico_bp.route("/campanha/<slug>")
@limiter.limit("60 per minute")
@cache.cached(timeout=60, query_string=True, unless=_cliente_esta_logado)
def campanha_publica(slug):
    """Página pública de uma campanha: banner + peças (com os filtros padrão da
    vitrine, aplicados dentro do conjunto da campanha)."""
    campanha = Campanha.por_slug(slug)
    if not campanha or not campanha.vigente:
        abort(404)

    q = request.args.get("q", "").strip().lower()
    tipo = request.args.get("tipo", "").strip()
    colecao = request.args.get("colecao", "").strip()
    ordem = request.args.get("ordem", "").strip()
    tam_sel = [t for t in request.args.getlist("tamanho") if t in TAMANHOS]

    publicas = Peca.query.filter_by(vitrine_publica=True).all()
    base = [p for p in publicas if campanha.inclui(p)]   # conjunto da campanha

    # Opções de filtro vêm só do conjunto da campanha.
    tipos = sorted({p.tipo for p in base if p.tipo})
    colecoes = sorted({p.colecao for p in base if p.colecao})

    pecas = base
    if q:
        pecas = [p for p in pecas
                 if q in p.nome.lower() or q in (p.colecao or "").lower() or q in (p.tags or "").lower()]
    if tipo:
        pecas = [p for p in pecas if p.tipo == tipo]
    if colecao:
        pecas = [p for p in pecas if (p.colecao or "") == colecao]
    if tam_sel:
        pecas = [p for p in pecas
                 if any(p.disponivel_por_tamanho.get(t, 0) > 0 for t in tam_sel)]

    chaves = {"preco_asc": lambda p: p.preco_vitrine,
              "preco_desc": lambda p: -p.preco_vitrine,
              "nome": lambda p: p.nome.lower()}
    chave = chaves.get(ordem, lambda p: p.nome.lower())

    def _grupo(p):
        if p.esgotado:
            return 2
        return 1 if p.sob_encomenda else 0
    pecas = sorted(pecas, key=lambda p: (_grupo(p), chave(p)))

    colecao_fotos = {c.nome: c.foto for c in Colecao.query.all() if c.foto}
    whatsapp = Parametro.obter("whatsapp", "")
    limite_novo = datetime.utcnow() - timedelta(days=21)
    novos = {p.id for p in publicas if p.criado_em and p.criado_em >= limite_novo}

    resp = make_response(render_template(
        "campanha.html", campanha=campanha, pecas=pecas, colecao_fotos=colecao_fotos,
        whatsapp=whatsapp, novos=novos, total=len(pecas), tipos=tipos, colecoes=colecoes,
        tamanhos=TAMANHOS, q=request.args.get("q", ""), tipo=tipo, colecao=colecao,
        ordem=ordem, tam_sel=tam_sel))
    if _cliente_esta_logado():
        resp.headers["Cache-Control"] = "no-store"
    return resp


@publico_bp.route("/publico/frete", methods=["POST"])
@csrf.exempt
@limiter.limit("30 per minute")
def frete_publico():
    """Calcula o frete do carrinho da vitrine. Recebe JSON {cep, itens:[{id,qtd}]};
    as dimensões vêm do banco (o cliente não as informa)."""
    dados = request.get_json(silent=True) or {}
    itens = dados.get("itens") or []
    ids = []
    quantidades = {}
    for it in itens:
        try:
            pid = int(it.get("id"))
            qtd = max(1, int(float(it.get("qtd", 1))))
        except (TypeError, ValueError):
            continue
        ids.append(pid)
        quantidades[pid] = quantidades.get(pid, 0) + qtd
    if not ids:
        return {"ok": False, "erro": "Carrinho vazio."}, 400

    # Soma o peso e empilha as alturas; usa a maior largura/comprimento (caixa que cabe tudo).
    # Valor do seguro = subtotal do carrinho (preço do servidor, nunca do cliente).
    peso = altura = 0.0
    largura = comprimento = 0.0
    valor_seguro = 0.0
    for peca in Peca.query.filter(Peca.id.in_(ids)).all():
        q = quantidades.get(peca.id, 0)
        peso += (peca.peso_g or 0) * q
        altura += (peca.altura_cm or 0) * q
        largura = max(largura, peca.largura_cm or 0)
        comprimento = max(comprimento, peca.comprimento_cm or 0)
        valor_seguro += float(peca.preco_vitrine) * q

    opcoes, erro = _frete_opcoes(
        dados.get("cep", ""), peso_g=peso, altura_cm=altura,
        largura_cm=largura, comprimento_cm=comprimento, valor_seguro=valor_seguro,
    )
    if erro:
        codigo = 400 if ("config" in erro or "CEP" in erro) else 502
        return {"ok": False, "erro": erro}, codigo
    return {"ok": True, "opcoes": opcoes}


@publico_bp.route("/publico/cupom", methods=["POST"])
@csrf.exempt
@limiter.limit("20 per minute")
def cupom_publico():
    """Valida um cupom na vitrine e devolve o desconto para o subtotal informado.
    Cupons pessoais (de aniversário) não são aplicados aqui — o cliente informa
    no WhatsApp e o ateliê confirma (evita vazar desconto exclusivo)."""
    dados = request.get_json(silent=True) or {}
    cod = str(dados.get("codigo", "")).strip().upper()
    try:
        subtotal = float(dados.get("subtotal", 0) or 0)
    except (TypeError, ValueError):
        subtotal = 0.0
    if not cod:
        return {"ok": False, "erro": "Informe um código."}, 400
    cupom = Cupom.query.filter(db.func.upper(Cupom.codigo) == cod).first()
    if not cupom or not cupom.valido:
        return {"ok": False, "erro": "Cupom inválido ou expirado."}, 200
    if cupom.cliente_id:
        return {"ok": False, "pessoal": True,
                "erro": "Cupom pessoal: informe no WhatsApp que confirmamos para você."}, 200
    return {
        "ok": True, "codigo": cupom.codigo, "tipo": cupom.tipo, "valor": cupom.valor,
        "desconto": cupom.desconto_para(subtotal),
        "rotulo": _rotulo_cupom(cupom),
    }


@publico_bp.route("/publico/newsletter", methods=["POST"])
@csrf.exempt
@limiter.limit("10 per minute")
def newsletter_inscrever():
    """Inscreve um e-mail na newsletter (rodapé da loja). Se for de um cliente,
    liga a flag aceita_novidades; senão guarda como inscrito avulso. Sugere criar
    conta quando o visitante está deslogado ou o e-mail não é de um cliente."""
    import re as _re
    dados = request.get_json(silent=True) or {}
    email = Cliente.normalizar_email(dados.get("email", ""))
    nome = str(dados.get("nome", "")).strip()[:160]
    if not _re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return {"ok": False, "erro": "E-mail inválido."}, 400

    cliente = Cliente.por_email(email)
    if cliente:
        cliente.aceita_novidades = True
    else:
        existente = NewsletterInscrito.query.filter_by(email=email).first()
        if not existente:
            db.session.add(NewsletterInscrito(email=email, nome=nome))
    db.session.commit()

    sugerir = (not _cliente_esta_logado()) or (cliente is None)
    return {"ok": True, "sugerir_cadastro": sugerir}


def _pix_publico(valor, txid):
    """Copia-e-cola do Pix para o total do pedido (se o Pix estiver configurado)."""
    chave = Parametro.obter("pix_chave", "")
    if not chave:
        return ""
    return _pix_payload(chave, Parametro.obter("pix_nome", ""),
                        Parametro.obter("pix_cidade", ""), valor, txid[:25])


def _frete_recalculado(cep, linhas, frete_nome):
    """Recalcula o frete no servidor para a opção escolhida — nunca confia no
    preço enviado pelo navegador. Retorna (valor, ok). ok=False quando não deu
    para recalcular (retirar em mãos retorna 0/True; API fora ou opção
    desconhecida retorna (None, False) e o chamador decide o fallback)."""
    if not frete_nome or "retirar" in frete_nome.lower():
        return 0.0, True
    ids = [x["id"] for x in linhas]
    peso = altura = largura = comprimento = 0.0
    valor_seguro = sum(float(x.get("preco", 0) or 0) * x["qtd"] for x in linhas)
    for peca in Peca.query.filter(Peca.id.in_(ids)).all():
        q = sum(x["qtd"] for x in linhas if x["id"] == peca.id)
        peso += (peca.peso_g or 0) * q
        altura += (peca.altura_cm or 0) * q
        largura = max(largura, peca.largura_cm or 0)
        comprimento = max(comprimento, peca.comprimento_cm or 0)
    opcoes, erro = _frete_opcoes(cep, peso_g=peso, altura_cm=altura, largura_cm=largura,
                                 comprimento_cm=comprimento, valor_seguro=valor_seguro)
    if erro:
        return None, False
    match = next((o for o in opcoes if o.get("nome") == frete_nome), None)
    if not match:
        return None, False
    try:
        return max(0.0, float(match.get("preco", 0) or 0)), True
    except (TypeError, ValueError):
        return None, False


@publico_bp.route("/publico/pedido", methods=["POST"])
@csrf.exempt
@limiter.limit("10 per minute")
def pedido_publico():
    """Recebe o pedido da vitrine + pré-cadastro do cliente e cria um Lead pendente.

    Nada toca estoque/relatórios aqui: só ao admin confirmar o lead a Venda é
    montada. Os preços são recalculados no servidor (não confiamos no cliente).
    """
    dados = request.get_json(silent=True) or {}
    cli = dados.get("cliente") or {}
    nome = str(cli.get("nome", "")).strip()
    if not nome:
        return {"ok": False, "erro": "Informe seu nome."}, 400
    telefone = str(cli.get("telefone", "")).strip()
    if len(re.sub(r"\D", "", telefone)) < 10:
        return {"ok": False, "erro": "Informe um WhatsApp válido com DDD."}, 400
    # E-mail opcional do convidado (melhora o casamento com a conta futura).
    email = Cliente.normalizar_email(str(cli.get("email", "")))
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return {"ok": False, "erro": "E-mail inválido — corrija ou deixe em branco."}, 400

    # Recalcula itens e preços a partir do banco.
    linhas, subtotal = [], 0.0
    for it in (dados.get("itens") or []):
        try:
            peca = Peca.query.get(int(it.get("id")))
        except (TypeError, ValueError):
            peca = None
        if not peca or peca.esgotado:
            continue                 # esgotada (sem insumos p/ produzir): não entra no pedido
        try:
            qtd = max(1, int(float(it.get("qtd", 1))))
        except (TypeError, ValueError):
            qtd = 1
        # Tamanho só dentro da grade — JSON forjado não cria item "XXL" (cai no
        # padrão "M" mais adiante, como tamanho vazio).
        tam = str(it.get("tam", "")).strip().upper()
        if tam not in TAMANHOS:
            tam = ""
        # Sob encomenda: o cliente paga o SINAL agora (preco_vitrine), mas o item
        # da venda registra o preço cheio — o restante fica como saldo a receber.
        preco = float(peca.preco_vitrine)
        preco_cheio = float(peca.preco_etiqueta_efetivo) if peca.sob_encomenda else preco
        subtotal += preco * qtd
        linhas.append({
            "id": peca.id, "nome": peca.nome, "tam": tam,
            "qtd": qtd, "preco": preco, "preco_cheio": preco_cheio,
            "encomenda": bool(peca.sob_encomenda),
        })
    if not linhas:
        return {"ok": False, "erro": "Seu pedido está vazio."}, 400
    subtotal = dinheiro(subtotal)

    # Frete — recalculado no servidor (não confiamos no preço enviado pelo
    # navegador). Calculado antes do cupom porque um cupom de frete precisa do
    # valor do frete para saber quanto descontar (limitado a ele).
    frete = dados.get("frete") or {}
    frete_nome = str(frete.get("nome", "")).strip()
    try:
        frete_cliente = max(0.0, float(frete.get("preco", 0) or 0))
    except (TypeError, ValueError):
        frete_cliente = 0.0
    frete_valor, recalculado = _frete_recalculado(
        str(cli.get("cep", "")).strip(), linhas, frete_nome)
    if not recalculado:
        # API de frete indisponível / opção não reconhecida: cai no valor exibido
        # ao cliente (o admin confere de qualquer jeito no WhatsApp).
        current_app.logger.warning("Frete não recalculado (%r); usando valor do cliente.", frete_nome)
        frete_valor = frete_cliente

    # Cupom (só geral — pessoal fica reservado à confirmação manual no WhatsApp).
    # Desconto de itens e de frete ficam em "baldes" separados: um cupom de
    # frete não deve reduzir o subtotal dos itens, e vice-versa.
    desconto_itens, desconto_frete, cupom_cod = 0.0, 0.0, ""
    cod = str((dados.get("cupom") or {}).get("codigo", "")).strip().upper()
    if cod:
        cupom = Cupom.query.filter(db.func.upper(Cupom.codigo) == cod).first()
        if cupom and cupom.valido and not cupom.cliente_id:
            if cupom.tipo == "frete":
                desconto_frete = cupom.desconto_frete_para(frete_valor)
            else:
                desconto_itens = cupom.desconto_para(subtotal)
            cupom_cod = cupom.codigo
    desconto = dinheiro(desconto_itens + desconto_frete)
    total = dinheiro(max(0.0, subtotal - desconto_itens) + max(0.0, frete_valor - desconto_frete))

    pedido = {
        "itens": linhas, "subtotal": subtotal, "desconto": desconto, "cupom": cupom_cod,
        "frete_nome": frete_nome, "frete_valor": frete_valor, "total": total,
    }
    # Resumo legível para a tela de Leads.
    linhas_txt = [f"• {x['qtd']}x {x['nome']}" + (f" ({x['tam']})" if x['tam'] else "")
                  + (f" [sob encomenda — sinal; peça {_brl(x['preco_cheio'])}]" if x['encomenda'] else "")
                  + f" — {_brl(x['preco'] * x['qtd'])}"
                  for x in linhas]
    resumo = "\n".join(linhas_txt)
    resumo += f"\nSubtotal: {_brl(subtotal)}"
    if desconto_itens:
        resumo += f"\nCupom {cupom_cod}: −{_brl(desconto_itens)}"
    elif desconto_frete:
        resumo += f"\nCupom {cupom_cod} (frete): −{_brl(desconto_frete)}"
    if frete_nome:
        frete_final = max(0.0, frete_valor - desconto_frete)
        resumo += f"\nFrete ({frete_nome}): {_brl(frete_final) if frete_final else 'grátis'}"
    resumo += f"\nTotal: {_brl(total)}"
    # Encomendas: o total acima é o sinal; o restante do preço cheio é cobrado
    # antes da entrega e fica registrado na venda como saldo a receber.
    restante_encomenda = dinheiro(sum((x["preco_cheio"] - x["preco"]) * x["qtd"]
                                      for x in linhas if x["encomenda"]))
    if restante_encomenda > 0:
        resumo += f"\nRestante das encomendas (antes da entrega): {_brl(restante_encomenda)}"

    # Cliente logado na vitrine? O pedido já vincula à conta dele (entra no
    # histórico da conta) e NÃO gera Lead. Convidado continua virando Lead.
    from .conta import _cliente_logado
    cliente = _cliente_logado()

    lead = None
    if cliente is None:
        lead = Lead(
            nome=nome, telefone=telefone, email=email,
            instagram=str(cli.get("instagram", "")).strip(),
            cep=str(cli.get("cep", "")).strip(), logradouro=str(cli.get("logradouro", "")).strip(),
            numero=str(cli.get("numero", "")).strip(), complemento=str(cli.get("complemento", "")).strip(),
            bairro=str(cli.get("bairro", "")).strip(), cidade=str(cli.get("cidade", "")).strip(),
            uf=str(cli.get("uf", "")).strip().upper()[:2],
            observacao=resumo, pedido_json=json.dumps(pedido, ensure_ascii=False),
        )
        db.session.add(lead)
        db.session.flush()
    else:
        # Atualiza o endereço/telefone da conta com o que foi informado no checkout
        # (só preenche campos vazios ou efetivamente enviados — mantém entrega correta).
        def _atualiza(campo, valor, upper=False):
            valor = str(valor or "").strip()
            if upper:
                valor = valor.upper()[:2]
            if valor:
                setattr(cliente, campo, valor)
        _atualiza("telefone", cli.get("telefone") or telefone)
        for c in ("cep", "logradouro", "numero", "complemento", "bairro", "cidade"):
            _atualiza(c, cli.get(c))
        _atualiza("uf", cli.get("uf"), upper=True)
        # Pedido feito: o carrinho salvo na conta deixa de ser "abandonado".
        cliente.carrinho_json = ""
        cliente.carrinho_em = None
        # Mantém "Meus endereços" coerente com o endereço usado no checkout:
        # reflete no endereço principal (cria um se a conta não tem nenhum).
        if cliente.tem_endereco:
            princ = next((e for e in cliente.enderecos if e.principal), None)
            if princ is None:
                princ = Endereco(cliente_id=cliente.id, destinatario=cliente.nome,
                                 principal=True,
                                 cobranca=not any(e.cobranca for e in cliente.enderecos))
                db.session.add(princ)
            for c in ("cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf"):
                setattr(princ, c, getattr(cliente, c))

    # Cria o pedido como PRÉ-PEDIDO na tela de vendas (não efetiva: sem baixa de
    # estoque). Marca itens sem estoque no tamanho como 'a produzir'.
    venda = Venda(
        status="pre-pedido", tipo="venda", pago=False, estoque_baixado=False,
        comprador=nome, lead_id=(lead.id if lead else None),
        cliente_id=(cliente.id if cliente else None), frete=frete_valor,
        desconto_total=desconto, cupom_codigo=cupom_cod,
    )
    db.session.add(venda)
    db.session.flush()
    for x in linhas:
        peca = Peca.query.get(x["id"])
        if not peca:
            continue
        tam = x["tam"] or "M"
        produzir = peca.disponivel_por_tamanho.get(tam, 0.0) < x["qtd"]
        if not produzir:
            # Reserva o estoque até o admin confirmar/descartar: some da
            # disponibilidade da vitrine e do balcão (disponível = qtd − reservado),
            # evitando vender no balcão a peça já pedida na vitrine.
            linha_est = _linha_estoque_peca(peca, tam, criar=True)
            linha_est.reservado += x["qtd"]
        db.session.add(VendaItem(
            venda=venda, peca_id=peca.id, tamanho=tam, quantidade=x["qtd"],
            preco_unitario=x["preco_cheio"], custo_unitario=peca.custo_total, produzir=produzir,
        ))
    db.session.commit()
    quem = f"conta {cliente.nome}" if cliente else nome
    _log("pedido_vitrine", f"{quem}: pré-pedido #{venda.id}, {len(linhas)} itens, total {_brl(total)}")
    _notificar_pedido_novo(venda, resumo)   # e-mail para o ateliê (se configurado)

    return {
        "ok": True, "lead_id": (lead.id if lead else None), "pedido_id": venda.id, "total": total,
        # Mesmo txid do detalhe da venda (PEDIDO<id>) para reconciliar o pagamento.
        "pix": _pix_publico(total, f"PEDIDO{venda.id}"),
        "whatsapp": Parametro.obter("whatsapp", ""), "resumo": resumo,
    }


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
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    kit = Kit.query.get_or_404(kit_id)
    db.session.delete(kit)
    db.session.commit()
    flash("Kit excluído.", "sucesso")
    return redirect(url_for("main.listar_kits"))


# --------------------------------------------------------------------------- #
# Avaliações (moderação)
# --------------------------------------------------------------------------- #
@bp.route("/avaliacoes")
def listar_avaliacoes():
    from ..models import Avaliacao
    pendentes = (Avaliacao.query.filter_by(aprovado=False)
                 .order_by(Avaliacao.criado_em.desc()).all())
    aprovadas = (Avaliacao.query.filter_by(aprovado=True)
                 .order_by(Avaliacao.criado_em.desc()).limit(50).all())
    return render_template("avaliacoes.html", pendentes=pendentes, aprovadas=aprovadas)


@bp.route("/avaliacoes/<int:avaliacao_id>/aprovar", methods=["POST"])
def aprovar_avaliacao(avaliacao_id):
    from ..models import Avaliacao
    av = Avaliacao.query.get_or_404(avaliacao_id)
    av.aprovado = not av.aprovado
    db.session.commit()
    flash("Avaliação " + ("aprovada — já aparece na loja." if av.aprovado else "ocultada."), "sucesso")
    return redirect(url_for("main.listar_avaliacoes"))


@bp.route("/avaliacoes/<int:avaliacao_id>/excluir", methods=["POST"])
def excluir_avaliacao(avaliacao_id):
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    from ..models import Avaliacao
    av = Avaliacao.query.get_or_404(avaliacao_id)
    db.session.delete(av)
    db.session.commit()
    flash("Avaliação excluída.", "sucesso")
    return redirect(url_for("main.listar_avaliacoes"))


# --------------------------------------------------------------------------- #
# Coleções
# --------------------------------------------------------------------------- #
@bp.route("/colecoes")
def listar_colecoes():
    colecoes = Colecao.query.order_by(Colecao.nome).all()
    # Quantidade de peças por coleção (casada pelo nome, case-insensitive).
    contagem = {}
    for c in colecoes:
        contagem[c.id] = Peca.query.filter(
            db.func.lower(Peca.colecao) == c.nome.lower()
        ).count()
    return render_template("colecoes.html", colecoes=colecoes, contagem=contagem)


@bp.route("/colecoes/nova", methods=["GET", "POST"])
@bp.route("/colecoes/<int:colecao_id>/editar", methods=["GET", "POST"])
def form_colecao(colecao_id=None):
    colecao = Colecao.query.get_or_404(colecao_id) if colecao_id else None

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("O nome da coleção é obrigatório.", "erro")
            return render_template("colecao_form.html", colecao=colecao)

        # Nome único (case-insensitive), ignorando a própria coleção em edição.
        existente = Colecao.por_nome(nome)
        if existente and (colecao is None or existente.id != colecao.id):
            flash("Já existe uma coleção com esse nome.", "erro")
            return render_template("colecao_form.html", colecao=colecao)

        nome_antigo = colecao.nome if colecao else None
        if colecao is None:
            colecao = Colecao()
            db.session.add(colecao)

        colecao.nome = nome
        colecao.slogan = request.form.get("slogan", "").strip()
        colecao.ativa = request.form.get("ativa") == "on"

        nova_foto = _salvar_foto(request.files.get("foto"))
        if nova_foto:
            _remover_foto(colecao.foto)
            colecao.foto = nova_foto

        # Se o nome mudou, mantém as peças vinculadas (casadas por nome).
        if nome_antigo and nome_antigo != nome:
            Peca.query.filter(
                db.func.lower(Peca.colecao) == nome_antigo.lower()
            ).update({Peca.colecao: nome}, synchronize_session=False)

        db.session.commit()
        flash("Coleção salva com sucesso.", "sucesso")
        return redirect(url_for("main.listar_colecoes"))

    return render_template("colecao_form.html", colecao=colecao)


@bp.route("/colecoes/<int:colecao_id>/toggle", methods=["POST"])
def toggle_colecao(colecao_id):
    colecao = Colecao.query.get_or_404(colecao_id)
    colecao.ativa = not colecao.ativa
    db.session.commit()
    return redirect(url_for("main.listar_colecoes"))


@bp.route("/colecoes/<int:colecao_id>/pecas")
def pecas_colecao(colecao_id):
    colecao = Colecao.query.get_or_404(colecao_id)
    pecas = Peca.query.filter(
        db.func.lower(Peca.colecao) == colecao.nome.lower()
    ).order_by(Peca.nome).all()
    return render_template("colecao_pecas.html", colecao=colecao, pecas=pecas, tamanhos_glob=TAMANHOS)


@bp.route("/colecoes/<int:colecao_id>/excluir", methods=["POST"])
def excluir_colecao(colecao_id):
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    colecao = Colecao.query.get_or_404(colecao_id)
    _remover_foto(colecao.foto)
    db.session.delete(colecao)
    db.session.commit()
    flash("Coleção excluída. As peças mantêm o nome da coleção.", "sucesso")
    return redirect(url_for("main.listar_colecoes"))


# --------------------------------------------------------------------------- #
# Loja online: banners do carrossel e campanhas com desconto.
# --------------------------------------------------------------------------- #
def _slugify(texto):
    """Gera slug url-safe (minúsculo, sem acento, hífens)."""
    base = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return base or "campanha"


def _slug_unico(nome, campanha_id=None):
    """Slug único a partir do nome (sufixo -2, -3... se colidir)."""
    base = _slugify(nome)
    slug = base
    i = 2
    while True:
        existente = Campanha.query.filter_by(slug=slug).first()
        if not existente or existente.id == campanha_id:
            return slug
        slug = f"{base}-{i}"
        i += 1


# ----- Campanhas -----
@bp.route("/campanhas")
def listar_campanhas():
    campanhas = Campanha.query.order_by(Campanha.criado_em.desc()).all()
    contagem = {c.id: len(c.pecas()) for c in campanhas}
    return render_template("campanhas.html", campanhas=campanhas, contagem=contagem)


@bp.route("/campanhas/nova", methods=["GET", "POST"])
@bp.route("/campanhas/<int:campanha_id>/editar", methods=["GET", "POST"])
def form_campanha(campanha_id=None):
    campanha = Campanha.query.get_or_404(campanha_id) if campanha_id else None
    tipos = sorted({p.tipo for p in Peca.query.all() if p.tipo})
    colecoes = sorted({c.nome for c in Colecao.query.all()})

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("O nome da campanha é obrigatório.", "erro")
            return render_template("campanha_form.html", campanha=campanha, tipos=tipos, colecoes=colecoes)

        novo = campanha is None
        if novo:
            campanha = Campanha()

        campanha.nome = nome
        # Gera o slug antes de anexar à sessão: a query dentro de _slug_unico
        # dispara autoflush, e uma campanha nova ainda sem slug violaria o NOT NULL.
        with db.session.no_autoflush:
            campanha.slug = _slug_unico(nome, campanha.id)
        if novo:
            db.session.add(campanha)
        campanha.subtitulo = request.form.get("subtitulo", "").strip()
        campanha.ativa = request.form.get("ativa") == "on"
        campanha.inicio = _to_date(request.form.get("inicio"))
        campanha.fim = _to_date(request.form.get("fim"))
        campanha.filtro_colecao = request.form.get("filtro_colecao", "").strip()
        campanha.filtro_tipo = request.form.get("filtro_tipo", "").strip()
        campanha.filtro_tags = request.form.get("filtro_tags", "").strip()
        dtipo = request.form.get("desconto_tipo", "percentual")
        campanha.desconto_tipo = dtipo if dtipo in ("percentual", "valor") else "percentual"
        campanha.desconto_valor = _to_float(request.form.get("desconto_valor"), 0.0)

        nova_h = _salvar_foto(request.files.get("banner_hero"), lado_max=2000)
        if nova_h:
            _remover_foto(campanha.banner_hero)
            campanha.banner_hero = nova_h
        nova_l = _salvar_foto(request.files.get("banner_landing"), lado_max=2000)
        if nova_l:
            _remover_foto(campanha.banner_landing)
            campanha.banner_landing = nova_l

        db.session.commit()
        flash("Campanha salva. Ajuste as peças em “Peças da campanha” se precisar.", "sucesso")
        return redirect(url_for("main.gerir_pecas_campanha", campanha_id=campanha.id))

    return render_template("campanha_form.html", campanha=campanha, tipos=tipos, colecoes=colecoes)


@bp.route("/campanhas/<int:campanha_id>/toggle", methods=["POST"])
def toggle_campanha(campanha_id):
    campanha = Campanha.query.get_or_404(campanha_id)
    campanha.ativa = not campanha.ativa
    db.session.commit()
    return redirect(url_for("main.listar_campanhas"))


@bp.route("/campanhas/<int:campanha_id>/excluir", methods=["POST"])
def excluir_campanha(campanha_id):
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    campanha = Campanha.query.get_or_404(campanha_id)
    _remover_foto(campanha.banner_hero)
    _remover_foto(campanha.banner_landing)
    db.session.delete(campanha)
    db.session.commit()
    flash("Campanha excluída.", "sucesso")
    return redirect(url_for("main.listar_campanhas"))


@bp.route("/campanhas/<int:campanha_id>/pecas")
def gerir_pecas_campanha(campanha_id):
    campanha = Campanha.query.get_or_404(campanha_id)
    pecas = Peca.query.order_by(Peca.colecao, Peca.nome).all()
    forcado = {e.peca_id: e.incluir for e in campanha.excecoes}
    linhas = []
    for p in pecas:
        casa = campanha.casa_filtro(p)
        if p.id in forcado:
            estado = "incluida" if forcado[p.id] else "excluida"
        else:
            estado = "auto" if casa else "fora"
        linhas.append({"peca": p, "casa": casa, "estado": estado,
                       "dentro": campanha.inclui(p)})
    return render_template("campanha_pecas.html", campanha=campanha, linhas=linhas)


@bp.route("/campanhas/<int:campanha_id>/pecas/<int:peca_id>", methods=["POST"])
def marcar_peca_campanha(campanha_id, peca_id):
    campanha = Campanha.query.get_or_404(campanha_id)
    Peca.query.get_or_404(peca_id)
    acao = request.form.get("acao", "auto")   # incluir | excluir | auto
    excecao = CampanhaPeca.query.filter_by(campanha_id=campanha.id, peca_id=peca_id).first()

    if acao == "auto":
        if excecao:
            db.session.delete(excecao)
    else:
        incluir = acao == "incluir"
        if excecao:
            excecao.incluir = incluir
        else:
            db.session.add(CampanhaPeca(campanha_id=campanha.id, peca_id=peca_id, incluir=incluir))

    db.session.commit()
    return redirect(url_for("main.gerir_pecas_campanha", campanha_id=campanha.id))


# ----- Newsletter -----
def _destinatarios_newsletter():
    """União deduplicada dos inscritos: clientes com opt-in + avulsos. Cliente
    tem precedência (nome/id). Retorna lista de dicts {email, nome, origem, cliente_id}."""
    clientes = (Cliente.query.filter_by(aceita_novidades=True)
                .filter(Cliente.email.isnot(None)).order_by(Cliente.nome).all())
    avulsos = NewsletterInscrito.query.order_by(NewsletterInscrito.criado_em.desc()).all()
    vistos, inscritos = set(), []
    for cli in clientes:
        e = (cli.email or "").strip().lower()
        if not e or e in vistos:
            continue
        vistos.add(e)
        inscritos.append({"email": cli.email, "nome": cli.nome, "origem": "cliente", "cliente_id": cli.id})
    for a in avulsos:
        e = (a.email or "").strip().lower()
        if not e or e in vistos:
            continue
        vistos.add(e)
        inscritos.append({"email": a.email, "nome": a.nome or "—", "origem": "avulso", "cliente_id": None})
    return inscritos


@bp.route("/newsletter")
def listar_newsletter():
    from ..emails import email_configurado
    inscritos = _destinatarios_newsletter()
    if request.args.get("csv"):
        linhas = [[i["email"], i["nome"], i["origem"]] for i in inscritos]
        return _csv_response(["E-mail", "Nome", "Origem"], linhas, "newsletter.csv")
    campanhas = [c for c in Campanha.query.order_by(Campanha.criado_em.desc()).all() if c.vigente]
    envios = NewsletterEnvio.query.order_by(NewsletterEnvio.criado_em.desc()).limit(30).all()
    return render_template("newsletter.html", inscritos=inscritos, total=len(inscritos),
                           campanhas=campanhas, email_ok=email_configurado(), envios=envios)


def _montar_newsletter(preview=False):
    """Monta o e-mail da newsletter a partir do formulário. Retorna (assunto, html)
    ou (None, mensagem_de_erro). Em preview, a imagem do corpo vira data URI (não
    grava em disco); no envio real, é salva em uploads."""
    assunto = request.form.get("assunto", "").strip()
    corpo = request.form.get("corpo", "").strip()
    campanha_id = request.form.get("campanha_id", "").strip()
    cta_texto = request.form.get("cta_texto", "").strip()
    cta_link = request.form.get("cta_link", "").strip()
    if not assunto or not corpo:
        return None, "Preencha o assunto e a mensagem."

    corpo_html = current_app.jinja_env.filters["md_leve"](corpo)   # markdown seguro

    banner_src = banner_link = None
    botoes = []
    if campanha_id.isdigit():
        camp = Campanha.query.get(int(campanha_id))
        if camp and camp.vigente:
            banner_link = url_for("publico.campanha_publica", slug=camp.slug, _external=True)
            img = camp.banner_landing or camp.banner_hero
            if img:
                banner_src = url_for("static", filename="uploads/" + img, _external=True)
            botoes.append({"texto": f"Ver {camp.nome}", "link": banner_link})

    if cta_texto and re.match(r"^https?://", cta_link, re.I):
        botoes.append({"texto": cta_texto, "link": cta_link})

    img_corpo_src = None
    arq_up = request.files.get("imagem_corpo")
    if preview:
        img_corpo_src = _imagem_data_uri(arq_up)     # inline, sem gravar
    else:
        arq = _salvar_foto(arq_up, lado_max=1200)
        if arq:
            img_corpo_src = url_for("static", filename="uploads/" + arq, _external=True)

    html = render_template(
        "email_newsletter.html", corpo_html=corpo_html, banner_src=banner_src,
        banner_link=banner_link, img_corpo_src=img_corpo_src, botoes=botoes)
    return assunto, html


def _imagem_data_uri(arquivo):
    """Lê o upload e devolve um data URI base64 (para a prévia, sem tocar o disco).
    None se não houver arquivo válido."""
    if not arquivo or arquivo.filename == "":
        return None
    import base64
    dados = arquivo.read()
    arquivo.seek(0)   # devolve o ponteiro (caso seja lido de novo)
    if not dados:
        return None
    mime = arquivo.mimetype or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(dados).decode()


@bp.route("/newsletter/previa", methods=["POST"])
def previa_newsletter():
    bloqueio = _exigir_admin()
    if bloqueio:
        return bloqueio
    assunto, html = _montar_newsletter(preview=True)
    if assunto is None:
        return f"<p style='font-family:sans-serif;padding:20px'>{html}</p>", 400
    # Mostra o e-mail exatamente como será enviado (numa aba nova).
    return html


@bp.route("/newsletter/enviar", methods=["POST"])
def enviar_newsletter():
    bloqueio = _exigir_admin()   # dispara e-mail externo em massa: só admin
    if bloqueio:
        return bloqueio
    from ..emails import email_configurado, enviar_lote_async
    if not email_configurado():
        flash("Envio de e-mail não configurado (RESEND_API_KEY/MAIL_FROM).", "erro")
        return redirect(url_for("main.listar_newsletter"))

    assunto, html = _montar_newsletter(preview=False)
    if assunto is None:
        flash(html, "erro")   # aqui 'html' é a mensagem de erro
        return redirect(url_for("main.listar_newsletter"))

    emails = [i["email"] for i in _destinatarios_newsletter()]
    n = enviar_lote_async(emails, assunto, html)
    # Guarda no histórico (HTML p/ visualizar + campos originais p/ reaproveitar).
    cid = request.form.get("campanha_id", "").strip()
    db.session.add(NewsletterEnvio(
        assunto=assunto, html=html, total=n,
        corpo=request.form.get("corpo", "").strip(),
        campanha_id=int(cid) if cid.isdigit() else None,
        cta_texto=request.form.get("cta_texto", "").strip(),
        cta_link=request.form.get("cta_link", "").strip()))
    db.session.commit()
    flash(f"Enviando a newsletter para {n} inscrito(s). O envio corre ao fundo.", "sucesso")
    return redirect(url_for("main.listar_newsletter"))


@bp.route("/newsletter/envio/<int:envio_id>")
def visualizar_envio(envio_id):
    envio = NewsletterEnvio.query.get_or_404(envio_id)
    return envio.html
