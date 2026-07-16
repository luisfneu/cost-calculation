"""Rotas: estoque."""
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


@bp.route("/historico")
def historico():
    origem = request.args.get("origem", "").strip()   # "peca" | "insumo"
    tipo = request.args.get("tipo", "").strip()        # entrada|saida|producao|ajuste
    de = _to_date(request.args.get("de"))
    ate = _to_date(request.args.get("ate"))
    q = request.args.get("q", "").strip().lower()

    linhas = []
    if origem in ("", "peca"):
        for m in MovimentoPeca.query.all():
            linhas.append({
                "data": m.criado_em, "origem": "Peça", "item": m.peca.nome,
                "detalhe": m.tamanho, "tipo": m.tipo, "quantidade": m.quantidade, "obs": "",
            })
    if origem in ("", "insumo"):
        for m in MovimentoEstoque.query.all():
            linhas.append({
                "data": m.criado_em, "origem": "Insumo", "item": m.insumo.nome,
                "detalhe": m.insumo.unidade, "tipo": m.tipo,
                "quantidade": m.quantidade, "obs": m.observacao,
            })

    if tipo:
        linhas = [l for l in linhas if l["tipo"] == tipo]
    if de:
        linhas = [l for l in linhas if l["data"] and l["data"].date() >= de]
    if ate:
        linhas = [l for l in linhas if l["data"] and l["data"].date() <= ate]
    if q:
        linhas = [l for l in linhas if q in l["item"].lower()]

    linhas.sort(key=lambda l: l["data"] or datetime.min, reverse=True)
    total = len(linhas)
    linhas, pagina, total_paginas = _paginar(linhas)

    return render_template(
        "historico.html", linhas=linhas, total=total,
        pagina=pagina, total_paginas=total_paginas,
        origem=origem, f_tipo=tipo, q=request.args.get("q", ""),
        de=request.args.get("de", ""), ate=request.args.get("ate", ""),
        tipos=["entrada", "saida", "producao", "ajuste"],
    )


@bp.route("/estoque/inventario", methods=["GET", "POST"])
def inventario():
    """Contagem em massa do estoque de peças + definição do estoque mínimo.

    Campos do form por tamanho: cont_<peca_id>_<tam> (contado) e
    min_<peca_id>_<tam> (mínimo). Aplica ajustes só onde o valor mudou."""
    pecas = Peca.query.order_by(Peca.nome).all()
    if request.method == "GET":
        return render_template("inventario.html", pecas=pecas, tamanhos=TAMANHOS)

    ajustes = 0
    for peca in pecas:
        for tam in TAMANHOS:
            linha = _linha_estoque_peca(peca, tam)
            atual = linha.quantidade if linha else 0.0
            atual_min = linha.estoque_minimo if linha else 0.0

            cont_raw = request.form.get(f"cont_{peca.id}_{tam}", "")
            min_raw = request.form.get(f"min_{peca.id}_{tam}", "")
            novo_min = _to_float(min_raw) if min_raw != "" else atual_min

            # Só ajusta a quantidade se o campo foi preenchido.
            if cont_raw != "":
                novo = _to_float(cont_raw)
                if abs(novo - atual) > 0.0001:
                    if linha is None:
                        linha = _linha_estoque_peca(peca, tam, criar=True)
                    delta = novo - linha.quantidade
                    linha.quantidade = novo
                    db.session.add(MovimentoPeca(
                        peca=peca, tamanho=tam, tipo="ajuste", quantidade=delta,
                        observacao=f"Inventário: {atual:g} → {novo:g}",
                    ))
                    ajustes += 1

            # Mínimo (cria linha se necessário para guardar o mínimo).
            if abs(novo_min - atual_min) > 0.0001:
                if linha is None:
                    linha = _linha_estoque_peca(peca, tam, criar=True)
                linha.estoque_minimo = novo_min

    db.session.commit()
    _log("estoque", f"inventário de peças: {ajustes} ajuste(s)")
    flash(f"Inventário aplicado. {ajustes} ajuste(s) de quantidade.", "sucesso")
    return redirect(url_for("main.inventario"))


@bp.route("/estoque/inventario-insumos", methods=["GET", "POST"])
def inventario_insumos():
    """Contagem/correção do estoque de insumos + estoque mínimo.

    Campos por insumo: cont_<insumo_id> (contado) e min_<insumo_id> (mínimo).
    A diferença vira um movimento de entrada/saída (sem alterar o custo médio)."""
    insumos = Insumo.query.order_by(Insumo.nome).all()
    if request.method == "GET":
        return render_template("inventario_insumos.html", insumos=insumos)

    ajustes = 0
    for insumo in insumos:
        cont_raw = request.form.get(f"cont_{insumo.id}", "")
        min_raw = request.form.get(f"min_{insumo.id}", "")

        if min_raw != "":
            insumo.estoque_minimo = _to_float(min_raw)

        if cont_raw != "":
            novo = _to_float(cont_raw)
            delta = novo - insumo.estoque
            if abs(delta) > 0.0001:
                if delta > 0:
                    _registrar_movimento(insumo, "entrada", delta, observacao="Inventário (correção)")
                else:
                    _registrar_movimento(insumo, "saida", -delta, observacao="Inventário (correção)")
                ajustes += 1

    db.session.commit()
    flash(f"Inventário de insumos aplicado. {ajustes} ajuste(s).", "sucesso")
    return redirect(url_for("main.inventario_insumos"))


@bp.route("/pecas/<int:peca_id>/estoque/reservar", methods=["POST"])
def reservar_peca(peca_id):
    """Reserva unidades de um tamanho (ficam indisponíveis para nova venda)."""
    peca = Peca.query.get_or_404(peca_id)
    tamanho = request.form.get("tamanho", "").strip().upper()
    qtd = _to_float(request.form.get("quantidade"))
    if tamanho not in TAMANHOS or qtd <= 0:
        flash("Informe tamanho e quantidade válidos para reservar.", "erro")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))
    linha = _linha_estoque_peca(peca, tamanho, criar=True)
    livre = max(0.0, linha.quantidade - linha.reservado)
    if qtd > livre:
        flash(f"Só há {livre:g} un. disponível no tamanho {tamanho} para reservar.", "erro")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))
    linha.reservado += qtd
    db.session.add(MovimentoPeca(
        peca=peca, tamanho=tamanho, tipo="reserva", quantidade=qtd,
        observacao=(request.form.get("observacao") or "Reserva").strip(),
    ))
    db.session.commit()
    _log("estoque", f"reserva {qtd:g}x {peca.nome} tam {tamanho}")
    flash(f"{qtd:g} un. reservada(s) no tamanho {tamanho}.", "sucesso")
    return redirect(url_for("main.detalhe_peca", peca_id=peca.id))


@bp.route("/pecas/<int:peca_id>/estoque/liberar-reserva", methods=["POST"])
def liberar_reserva_peca(peca_id):
    """Libera unidades reservadas de um tamanho."""
    peca = Peca.query.get_or_404(peca_id)
    tamanho = request.form.get("tamanho", "").strip().upper()
    qtd = _to_float(request.form.get("quantidade"))
    linha = _linha_estoque_peca(peca, tamanho)
    if not linha or qtd <= 0:
        flash("Nada a liberar.", "erro")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))
    qtd = min(qtd, linha.reservado)
    linha.reservado = max(0.0, linha.reservado - qtd)
    db.session.add(MovimentoPeca(
        peca=peca, tamanho=tamanho, tipo="libera", quantidade=qtd,
        observacao="Liberação de reserva",
    ))
    db.session.commit()
    flash(f"{qtd:g} un. liberada(s) da reserva no tamanho {tamanho}.", "sucesso")
    return redirect(url_for("main.detalhe_peca", peca_id=peca.id))


@bp.route("/producao")
def listar_ordens():
    ordens = OrdemProducao.query.order_by(
        OrdemProducao.status, OrdemProducao.criado_em.desc()
    ).all()
    pecas = Peca.query.order_by(Peca.nome).all()
    return render_template("producao.html", ordens=ordens, pecas=pecas, tamanhos=TAMANHOS)


@bp.route("/producao/nova", methods=["POST"])
def nova_ordem():
    ordem = OrdemProducao(descricao=request.form.get("descricao", "").strip())
    _itens_ordem_do_form(ordem)
    if not ordem.itens:
        flash("Adicione ao menos uma peça/tamanho à ordem.", "erro")
        return redirect(url_for("main.listar_ordens"))
    db.session.add(ordem)
    db.session.commit()
    return redirect(url_for("main.detalhe_ordem", ordem_id=ordem.id))


@bp.route("/producao/de-minimos")
def nova_ordem_from_minimos():
    """Cria uma ordem já preenchida com o que está abaixo do estoque mínimo."""
    ordem = OrdemProducao(descricao="Reposição de estoque mínimo")
    for peca in Peca.query.order_by(Peca.nome).all():
        for f in peca.abaixo_minimo:
            ordem.itens.append(OrdemProducaoItem(
                peca_id=peca.id, tamanho=f["tamanho"],
                quantidade=float(math.ceil(f["faltam"])),
            ))
    if not ordem.itens:
        flash("Nenhuma peça abaixo do estoque mínimo.", "sucesso")
        return redirect(url_for("main.listar_ordens"))
    db.session.add(ordem)
    db.session.commit()
    return redirect(url_for("main.detalhe_ordem", ordem_id=ordem.id))


@bp.route("/producao/<int:ordem_id>")
def detalhe_ordem(ordem_id):
    ordem = OrdemProducao.query.get_or_404(ordem_id)
    pecas = Peca.query.order_by(Peca.nome).all()
    return render_template("producao_detalhe.html", ordem=ordem, pecas=pecas, tamanhos=TAMANHOS)


@bp.route("/producao/<int:ordem_id>/item/add", methods=["POST"])
def add_item_ordem(ordem_id):
    ordem = OrdemProducao.query.get_or_404(ordem_id)
    if ordem.status != "aberta":
        flash("Ordem já concluída.", "erro")
        return redirect(url_for("main.detalhe_ordem", ordem_id=ordem.id))
    _itens_ordem_do_form(ordem)
    db.session.commit()
    return redirect(url_for("main.detalhe_ordem", ordem_id=ordem.id))


@bp.route("/producao/<int:ordem_id>/item/<int:item_id>/excluir", methods=["POST"])
def excluir_item_ordem(ordem_id, item_id):
    item = OrdemProducaoItem.query.get_or_404(item_id)
    if item.ordem_id != ordem_id or item.ordem.status != "aberta":
        flash("Não é possível remover este item.", "erro")
        return redirect(url_for("main.detalhe_ordem", ordem_id=ordem_id))
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("main.detalhe_ordem", ordem_id=ordem_id))


@bp.route("/producao/<int:ordem_id>/concluir", methods=["POST"])
def concluir_ordem(ordem_id):
    ordem = OrdemProducao.query.get_or_404(ordem_id)
    if ordem.status == "concluida":
        flash("Ordem já concluída.", "erro")
        return redirect(url_for("main.detalhe_ordem", ordem_id=ordem.id))
    if not ordem.itens:
        flash("Ordem sem itens.", "erro")
        return redirect(url_for("main.detalhe_ordem", ordem_id=ordem.id))
    # Disponibilidade antes, por peça (para o aviso "voltou ao estoque").
    disp_antes = {}
    for it in ordem.itens:
        disp_antes.setdefault(it.peca_id, it.peca.disponivel_total)
    # Valida os insumos pela necessidade agregada.
    if not ordem.insumos_suficientes:
        faltam = ", ".join(f"{c['insumo'].nome} (faltam {c['comprar']:g})" for c in ordem.lista_compras)
        flash("Estoque de insumos insuficiente: " + faltam + ". Veja a lista de compras.", "erro")
        return redirect(url_for("main.detalhe_ordem", ordem_id=ordem.id))
    # Produz cada item: baixa insumos e dá entrada no estoque da peça.
    for it in ordem.itens:
        for pi in it.peca.insumos:
            _registrar_movimento(
                pi.insumo, "saida", pi.quantidade * it.quantidade,
                observacao=f"Ordem de produção #{ordem.id}: {it.quantidade:g}x '{it.peca.nome}' tam {it.tamanho}",
            )
        linha = _linha_estoque_peca(it.peca, it.tamanho, criar=True)
        linha.quantidade += it.quantidade
        db.session.add(MovimentoPeca(
            peca=it.peca, tamanho=it.tamanho, tipo="producao", quantidade=it.quantidade,
            observacao=f"Ordem de produção #{ordem.id}",
        ))
    ordem.status = "concluida"
    ordem.concluido_em = datetime.now()
    db.session.commit()
    vistas = set()
    for it in ordem.itens:
        if it.peca_id not in vistas:
            vistas.add(it.peca_id)
            _avisar_favoritos_voltou(it.peca, disp_antes.get(it.peca_id, 0.0))
    _log("estoque", f"produção concluída ordem #{ordem.id}: {ordem.total_unidades:g} peça(s)")
    flash(f"Ordem #{ordem.id} concluída: {ordem.total_unidades:g} peça(s) produzida(s).", "sucesso")
    return redirect(url_for("main.detalhe_ordem", ordem_id=ordem.id))


@bp.route("/producao/<int:ordem_id>/excluir", methods=["POST"])
def excluir_ordem(ordem_id):
    ordem = OrdemProducao.query.get_or_404(ordem_id)
    db.session.delete(ordem)
    db.session.commit()
    flash("Ordem excluída.", "sucesso")
    return redirect(url_for("main.listar_ordens"))
