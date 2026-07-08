"""Rotas: vendas."""
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
    dinheiro,
)
from . import bp
from .helpers import *  # noqa: F401,F403


@bp.route("/vendas")
def listar_vendas():
    return _render_historico()


@bp.route("/vendas/nova", methods=["GET", "POST"])
def registrar_venda():
    if request.method == "GET":
        return _render_form_pedido("venda")
    return _processar_pedido("venda")


@bp.route("/encomendas")
def listar_encomendas():
    """Itens que precisam ser produzidos, atrelados às suas vendas.

    Inclui itens marcados 'produzir' (faltantes de um pedido) e os itens de
    pedidos do tipo 'encomenda' (feitos sob medida), enquanto não produzidos.
    """
    itens = (
        VendaItem.query.join(Venda)
        .filter(
            VendaItem.produzido.is_(False),
            Venda.status != "pre-pedido",          # só depois de confirmar o pedido
            db.or_(VendaItem.produzir.is_(True), Venda.tipo == "encomenda"),
        )
        .order_by(Venda.criado_em.desc(), VendaItem.id).all()
    )
    # Agrupa por venda, preservando a ordem (venda mais recente primeiro).
    grupos = []
    indice = {}
    for it in itens:
        if it.venda_id not in indice:
            indice[it.venda_id] = len(grupos)
            grupos.append((it.venda, []))
        grupos[indice[it.venda_id]][1].append(it)
    return render_template("encomendas.html", grupos=grupos, total_itens=len(itens))


@bp.route("/encomendas/item/<int:item_id>/produzido", methods=["POST"])
def marcar_item_produzido(item_id):
    item = VendaItem.query.get_or_404(item_id)
    item.produzido = not item.produzido
    db.session.commit()
    estado = "produzido" if item.produzido else "reaberto"
    _log("producao_encomenda", f"item #{item.id} ({item.peca.nome}) {estado}")
    return redirect(request.referrer or url_for("main.listar_encomendas"))


@bp.route("/encomendas/nova", methods=["GET", "POST"])
def registrar_encomenda():
    if request.method == "GET":
        return _render_form_pedido("encomenda")
    return _processar_pedido("encomenda")


@bp.route("/vendas/<int:venda_id>/baixar-estoque", methods=["POST"])
def baixar_estoque_venda(venda_id):
    venda = Venda.query.get_or_404(venda_id)
    if venda.estoque_baixado:
        flash("Estoque desta venda já foi baixado.", "erro")
        return redirect(request.referrer or url_for("main.listar_vendas"))
    agrup = {}
    for it in venda.itens:
        agrup[(it.peca_id, it.tamanho)] = agrup.get((it.peca_id, it.tamanho), 0.0) + it.quantidade
    faltando = _validar_estoque_pecas(agrup)
    if faltando:
        flash("Sem estoque para baixar: " + "; ".join(faltando) + ". Produza as peças primeiro.", "erro")
        return redirect(request.referrer or url_for("main.listar_vendas"))
    _baixar_estoque_venda(venda)
    db.session.commit()
    flash(f"Estoque baixado para o pedido #{venda.id}.", "sucesso")
    return redirect(request.referrer or url_for("main.listar_vendas"))


@bp.route("/vendas/<int:venda_id>/confirmar-pedido", methods=["POST"])
def confirmar_pedido(venda_id):
    """Confirma um pré-pedido da vitrine: efetiva a venda (baixa o estoque dos
    itens disponíveis; os de produção seguem para Encomendas)."""
    venda = Venda.query.get_or_404(venda_id)
    if venda.status != "pre-pedido":
        flash("Este pedido já foi confirmado.", "erro")
        return redirect(url_for("main.visualizar_venda", venda_id=venda.id))
    baixou = False
    for it in venda.itens:
        if it.produzir:
            continue   # item de encomenda: baixa/produz depois (tela de Encomendas)
        linha = _linha_estoque_peca(it.peca, it.tamanho, criar=True)
        linha.quantidade -= it.quantidade
        db.session.add(MovimentoPeca(
            peca=it.peca, tamanho=it.tamanho, tipo="saida", quantidade=it.quantidade,
            observacao=f"Venda #{venda.id} (vitrine)",
        ))
        baixou = True
    venda.estoque_baixado = baixou
    venda.status = "realizado"
    db.session.commit()
    _log("pedido_confirmado", f"pré-pedido #{venda.id} confirmado")
    n_prod = len(venda.itens_a_produzir)
    extra = f" · {n_prod} item(ns) para produzir em Encomendas" if n_prod else ""
    flash(f"Pedido #{venda.id} confirmado{extra}.", "sucesso")
    return redirect(url_for("main.visualizar_venda", venda_id=venda.id))


@bp.route("/vendas/<int:venda_id>/status/<novo>", methods=["POST"])
def alterar_status_venda(venda_id, novo):
    venda = Venda.query.get_or_404(venda_id)
    if venda.status == "pre-pedido":
        flash("Confirme o pré-pedido antes de avançar o status.", "erro")
        return redirect(request.referrer or url_for("main.visualizar_venda", venda_id=venda.id))
    if novo not in Venda.FLUXO:
        flash("Status inválido.", "erro")
        return redirect(request.referrer or url_for("main.listar_vendas"))
    # Não libera envio/entrega enquanto houver item de encomenda por produzir.
    if novo in ("enviado", "entregue") and venda.producao_pendente:
        flash("Há itens de encomenda ainda não produzidos. Conclua a produção antes de enviar/entregar.", "erro")
        return redirect(request.referrer or url_for("main.visualizar_venda", venda_id=venda.id))
    # Só libera envio/entrega depois do pagamento — crediário já é liberado.
    if novo in ("enviado", "entregue") and venda.saldo_receber > 0.01 and not venda.eh_crediario:
        flash("Registre o pagamento antes de enviar/entregar o pedido.", "erro")
        return redirect(request.referrer or url_for("main.visualizar_venda", venda_id=venda.id))
    venda.status = novo
    # Crediário: o 'pago' fica a cargo do pagamento das parcelas (não força aqui).
    if not venda.eh_crediario:
        venda.pago = novo in ("pago", "enviado", "entregue")
    db.session.commit()
    flash(f"Pedido #{venda.id}: {venda.status_label}.", "sucesso")
    return redirect(request.referrer or url_for("main.visualizar_venda", venda_id=venda.id))


@bp.route("/vendas/<int:venda_id>")
def visualizar_venda(venda_id):
    venda = Venda.query.get_or_404(venda_id)
    chave = Parametro.obter("pix_chave", "")
    pix_cfg = None
    if chave:
        pix_cfg = {
            "chave": chave,
            "nome": Parametro.obter("pix_nome", ""),
            "cidade": Parametro.obter("pix_cidade", ""),
        }
    return render_template(
        "venda_detalhe.html", venda=venda, recibo_texto=_texto_recibo(venda),
        pix_cfg=pix_cfg,
    )


@bp.route("/vendas/<int:venda_id>/recibo")
def recibo_venda(venda_id):
    venda = Venda.query.get_or_404(venda_id)
    return render_template("recibo.html", venda=venda)


@bp.route("/vendas/<int:venda_id>/editar", methods=["GET", "POST"])
def editar_venda(venda_id):
    venda = Venda.query.get_or_404(venda_id)
    acao = url_for("main.editar_venda", venda_id=venda.id)

    if request.method == "GET":
        itens, pedido = _prefill_de_venda(venda)
        return _render_form_pedido("editar", itens, pedido, acao=acao, venda=venda)

    def _re_render():
        return _render_form_pedido("editar", _itens_crus_do_form(), request.form,
                                   acao=acao, venda=venda)

    linhas, erro = _itens_do_form()
    if erro:
        flash(erro, "erro")
        return _re_render()

    # Ajusta o estoque só se a venda já tinha estoque baixado.
    if venda.estoque_baixado:
        retornos = {}
        for it in venda.itens:
            retornos[(it.peca_id, it.tamanho)] = retornos.get((it.peca_id, it.tamanho), 0.0) + it.quantidade
        necessarios = _agrupar(linhas)
        for (pid, tam), need in necessarios.items():
            peca = Peca.query.get(pid)
            linha = _linha_estoque_peca(peca, tam)
            disp = (linha.quantidade if linha else 0.0) + retornos.get((pid, tam), 0.0)
            if need > disp:
                flash(f"Estoque insuficiente de '{peca.nome}' tam {tam} (disponível: {disp:g}).", "erro")
                return _re_render()
        for chave in set(retornos) | set(necessarios):
            pid, tam = chave
            net = necessarios.get(chave, 0.0) - retornos.get(chave, 0.0)
            if net == 0:
                continue
            peca = Peca.query.get(pid)
            linha = _linha_estoque_peca(peca, tam, criar=True)
            linha.quantidade -= net
            db.session.add(MovimentoPeca(
                peca=peca, tamanho=tam, tipo="saida" if net > 0 else "estorno",
                quantidade=abs(net), observacao=f"Edição de venda #{venda.id}",
            ))

    # Refaz os itens e atualiza os dados do pedido. NÃO mexe em pagamentos,
    # vencimento nem parcelas (isso é feito na tela do pedido).
    for it in list(venda.itens):
        db.session.delete(it)
    venda.itens = []
    for l in linhas:
        db.session.add(VendaItem(
            venda=venda, peca=l["peca"], tamanho=l["tamanho"],
            quantidade=l["quantidade"], preco_unitario=l["preco"],
            desconto=l["desconto"], custo_unitario=l["peca"].custo_total,
        ))
    cid = request.form.get("cliente_id", type=int)
    venda.frete = dinheiro(_to_float(request.form.get("frete")))
    venda.frete_cortesia = request.form.get("frete_cortesia") == "on"
    venda.marketplace_pct = _to_float(request.form.get("marketplace_pct"))
    venda.desconto_total = dinheiro(_to_float(request.form.get("desconto_total")))
    venda.cliente_id = cid if cid else None
    db.session.flush()

    # Recalcula o pago com os pagamentos que já existem (a receita pode ter mudado).
    venda.pago = venda.total_pago >= venda.receita - 0.01
    if not venda.pago and venda.status == "pago":
        venda.status = "realizado"

    db.session.commit()
    _log("venda", f"pedido #{venda.id} editado")
    flash("Venda atualizada.", "sucesso")
    return redirect(url_for("main.visualizar_venda", venda_id=venda.id))


@bp.route("/vendas/<int:venda_id>/excluir", methods=["POST"])
def excluir_venda(venda_id):
    venda = Venda.query.get_or_404(venda_id)
    # Devolve ao estoque só se a venda tinha baixado estoque (não é orçamento/encomenda).
    if venda.estoque_baixado:
        for it in venda.itens:
            linha = _linha_estoque_peca(it.peca, it.tamanho, criar=True)
            linha.quantidade += it.quantidade
            db.session.add(MovimentoPeca(
                peca=it.peca, tamanho=it.tamanho, tipo="estorno", quantidade=it.quantidade,
                observacao=f"Estorno por exclusão de venda #{venda.id}",
            ))
    vid = venda.id
    db.session.delete(venda)
    db.session.commit()
    _log("venda", f"pedido #{vid} excluído")
    flash("Venda excluída.", "sucesso")
    return redirect(url_for("main.listar_vendas"))


@bp.route("/vendas/<int:venda_id>/pagar", methods=["POST"])
def marcar_pago(venda_id):
    """Quita a venda: registra um pagamento para o saldo restante."""
    venda = Venda.query.get_or_404(venda_id)
    saldo = venda.saldo_receber
    if saldo > 0:
        db.session.add(Pagamento(
            venda=venda, forma=(venda.forma_pagamento or "Dinheiro").split(" + ")[-1],
            valor=saldo,
        ))
    venda.pago = True
    if venda.status == "realizado":
        venda.status = "pago"
    db.session.commit()
    flash(f"Venda #{venda.id} quitada.", "sucesso")
    return redirect(request.referrer or url_for("main.contabilidade"))


@bp.route("/vendas/<int:venda_id>/receber", methods=["POST"])
def receber_pagamento(venda_id):
    """Registra um pagamento parcial (ex.: recebimento do saldo de um sinal)."""
    venda = Venda.query.get_or_404(venda_id)
    valor = _to_float(request.form.get("valor"))
    forma = request.form.get("forma", "").strip() or "Dinheiro"
    if valor <= 0:
        flash("Informe um valor maior que zero.", "erro")
        return redirect(request.referrer or url_for("main.contabilidade"))
    db.session.add(Pagamento(venda=venda, forma=forma, valor=valor))
    venda.pago = (venda.total_pago + valor) >= venda.receita - 0.01
    if venda.pago and venda.status == "realizado":
        venda.status = "pago"
    db.session.commit()
    flash(f"Pagamento de {valor:.2f} registrado no pedido #{venda.id}.", "sucesso")
    return redirect(request.referrer or url_for("main.contabilidade"))


@bp.route("/vendas/<int:venda_id>/pagamentos", methods=["POST"])
def receber_pagamentos(venda_id):
    """Adiciona pagamentos (múltiplas formas). Só dinheiro pode exceder o saldo
    (o excesso vira troco). Formas eletrônicas não podem passar do saldo."""
    venda = Venda.query.get_or_404(venda_id)

    # Crediário: cobre todo o saldo em parcelas (não marca como pago).
    formas = request.form.getlist("pag_forma")
    if "Crediário" in formas:
        if venda.parcelas:
            flash("Este pedido já tem um crediário.", "erro")
            return redirect(url_for("main.visualizar_venda", venda_id=venda.id))
        n = int(_to_float(request.form.get("cred_parcelas"), padrao=1)) or 1
        inicio = _to_date(request.form.get("cred_inicio")) or date.today()
        total = round(venda.saldo_receber, 2)
        _gerar_parcelas(venda, total, n, inicio)
        if venda.status == "realizado":
            venda.status = "crediario"
        db.session.commit()
        _log("crediario", f"pedido #{venda.id}: {n}x de {_brl(total / n)}")
        flash(f"Crediário criado: {n} parcela(s). O pedido foi liberado e as parcelas "
              f"estão em Contas a receber.", "sucesso")
        return redirect(url_for("main.visualizar_venda", venda_id=venda.id))

    pags = _pagamentos_do_form()
    if not pags:
        flash("Adicione ao menos um pagamento com valor.", "erro")
        return redirect(url_for("main.visualizar_venda", venda_id=venda.id))

    restante = round(venda.saldo_receber, 2)
    troco = 0.0
    novos = []
    # Processa as formas eletrônicas primeiro, dinheiro por último.
    for p in sorted(pags, key=lambda x: x["forma"] == "Dinheiro"):
        if p["forma"] != "Dinheiro":
            if p["valor"] > restante + 0.01:
                flash(f"Pagamento em {p['forma']} (R$ {p['valor']:.2f}) maior que o saldo "
                      f"(R$ {restante:.2f}). Só dinheiro permite troco.", "erro")
                return redirect(url_for("main.visualizar_venda", venda_id=venda.id))
            aplicado = p["valor"]
        else:
            aplicado = min(p["valor"], max(0.0, restante))
            troco += p["valor"] - aplicado
        restante = round(restante - aplicado, 2)
        if aplicado > 0.001:
            novos.append({**p, "valor": aplicado})

    for p in novos:
        db.session.add(Pagamento(venda=venda, **p))
    if "vencimento" in request.form:
        venda.vencimento = _to_date(request.form.get("vencimento"))
    venda.pago = venda.total_pago >= venda.receita - 0.01
    if venda.pago and venda.status == "realizado":
        venda.status = "pago"
    db.session.commit()
    total_novos = sum(p["valor"] for p in novos)
    _log("pagamento", f"pedido #{venda.id}: {_brl(total_novos)}")
    msg = f"Pagamento registrado (R$ {total_novos:.2f})."
    if troco > 0.01:
        msg += f" Troco: R$ {troco:.2f}."
    flash(msg, "sucesso")
    return redirect(url_for("main.visualizar_venda", venda_id=venda.id))


@bp.route("/frete/calcular", methods=["POST"])
def calcular_frete():
    opcoes, erro = _frete_opcoes(
        request.form.get("cep", ""),
        peso_g=_to_float(request.form.get("peso")),
        altura_cm=_to_float(request.form.get("altura")),
        largura_cm=_to_float(request.form.get("largura")),
        comprimento_cm=_to_float(request.form.get("comprimento")),
    )
    if erro:
        codigo = 400 if "config" in erro or "CEP" in erro else 502
        return {"ok": False, "erro": erro}, codigo
    return {"ok": True, "opcoes": opcoes}


@bp.route("/cupons")
def listar_cupons():
    cupons = Cupom.query.order_by(Cupom.ativo.desc(), Cupom.codigo).all()
    return render_template("cupons.html", cupons=cupons)


@bp.route("/cupons/validar", methods=["POST"])
def validar_cupom():
    """Valida um cupom e devolve tipo/valor (JSON) para prévia do desconto na venda."""
    cod = request.form.get("codigo", "").strip().upper()
    if not cod:
        return {"ok": False, "erro": "Informe um código."}
    cupom = Cupom.query.filter(db.func.upper(Cupom.codigo) == cod).first()
    if not cupom:
        return {"ok": False, "erro": "Cupom não encontrado."}
    if not cupom.valido:
        return {"ok": False, "erro": "Cupom inválido ou expirado."}
    # Cupom pessoal (ex.: aniversário) só vale para o cliente dono.
    if cupom.cliente_id:
        cid = request.form.get("cliente_id", type=int)
        if cid != cupom.cliente_id:
            dono = cupom.cliente.nome if cupom.cliente else "outro cliente"
            return {"ok": False, "erro": f"Cupom exclusivo de {dono}. Selecione esse cliente na venda."}
    return {
        "ok": True, "codigo": cupom.codigo, "tipo": cupom.tipo, "valor": cupom.valor,
        "rotulo": _rotulo_cupom(cupom),
    }


@bp.route("/cupons/novo", methods=["POST"])
def salvar_cupom():
    codigo = request.form.get("codigo", "").strip().upper()
    if not codigo:
        flash("Informe o código do cupom.", "erro")
        return redirect(url_for("main.listar_cupons"))
    if Cupom.query.filter(db.func.upper(Cupom.codigo) == codigo).first():
        flash("Já existe um cupom com esse código.", "erro")
        return redirect(url_for("main.listar_cupons"))
    tipo = request.form.get("tipo", "percentual")
    if tipo not in ("percentual", "valor", "frete"):
        tipo = "percentual"
    c = Cupom(
        codigo=codigo, tipo=tipo, valor=_to_float(request.form.get("valor")),
        validade=_to_date(request.form.get("validade")),
        max_usos=int(_to_float(request.form.get("max_usos"))) or None,
    )
    db.session.add(c)
    db.session.commit()
    flash("Cupom criado.", "sucesso")
    return redirect(url_for("main.listar_cupons"))


@bp.route("/cupons/<int:cupom_id>/toggle", methods=["POST"])
def toggle_cupom(cupom_id):
    c = Cupom.query.get_or_404(cupom_id)
    c.ativo = not c.ativo
    db.session.commit()
    return redirect(url_for("main.listar_cupons"))


@bp.route("/cupons/<int:cupom_id>/excluir", methods=["POST"])
def excluir_cupom(cupom_id):
    c = Cupom.query.get_or_404(cupom_id)
    db.session.delete(c)
    db.session.commit()
    flash("Cupom excluído.", "sucesso")
    return redirect(url_for("main.listar_cupons"))


@bp.route("/vales")
def listar_vales():
    vales = Vale.query.order_by(Vale.criado_em.desc()).all()
    clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template("vales.html", vales=vales, clientes=clientes)


@bp.route("/vales/novo", methods=["POST"])
def salvar_vale():
    valor = _to_float(request.form.get("valor"))
    if valor <= 0:
        flash("Informe um valor maior que zero.", "erro")
        return redirect(url_for("main.listar_vales"))
    cid = request.form.get("cliente_id", type=int)
    v = Vale(
        codigo=_gerar_codigo_vale(), tipo="presente",
        valor_inicial=valor, saldo=valor, cliente_id=cid or None,
        observacao=request.form.get("observacao", "").strip(),
    )
    db.session.add(v)
    db.session.commit()
    flash(f"Vale-presente {v.codigo} criado (R$ {valor:.2f}).", "sucesso")
    return redirect(url_for("main.listar_vales"))


@bp.route("/vales/<int:vale_id>/desativar", methods=["POST"])
def desativar_vale(vale_id):
    v = Vale.query.get_or_404(vale_id)
    v.ativo = not v.ativo
    db.session.commit()
    return redirect(url_for("main.listar_vales"))


@bp.route("/vendas/<int:venda_id>/usar-vale", methods=["POST"])
def usar_vale(venda_id):
    venda = Venda.query.get_or_404(venda_id)
    cod = request.form.get("codigo", "").strip().upper()
    vale = Vale.query.filter(db.func.upper(Vale.codigo) == cod).first()
    if not vale or not vale.disponivel:
        flash("Vale inválido, sem saldo ou inativo.", "erro")
        return redirect(url_for("main.visualizar_venda", venda_id=venda.id))
    aplicado = min(vale.saldo, venda.saldo_receber)
    if aplicado <= 0.01:
        flash("Nada a aplicar (pedido já quitado).", "erro")
        return redirect(url_for("main.visualizar_venda", venda_id=venda.id))
    db.session.add(Pagamento(venda=venda, forma=f"Vale {vale.codigo}", valor=aplicado))
    vale.saldo = round(vale.saldo - aplicado, 2)
    venda.pago = venda.total_pago >= venda.receita - 0.01
    if venda.pago and venda.status == "realizado":
        venda.status = "pago"
    db.session.commit()
    flash(f"Vale {vale.codigo} aplicado: R$ {aplicado:.2f} (saldo do vale: R$ {vale.saldo:.2f}).", "sucesso")
    return redirect(url_for("main.visualizar_venda", venda_id=venda.id))


@bp.route("/vendas/<int:venda_id>/devolucao", methods=["GET", "POST"])
def devolucao_venda(venda_id):
    venda = Venda.query.get_or_404(venda_id)
    if request.method == "GET":
        return render_template("devolucao.html", venda=venda)

    # Lê as quantidades a devolver por item.
    total_credito = 0.0
    itens_devolvidos = []
    for it in venda.itens:
        qtd = _to_float(request.form.get(f"qtd_{it.id}"))
        qtd = min(max(0.0, qtd), it.quantidade)
        if qtd <= 0:
            continue
        # valor proporcional (com desconto do item aplicado)
        valor_unit = it.subtotal_receita / it.quantidade if it.quantidade else 0
        total_credito += valor_unit * qtd
        itens_devolvidos.append((it, qtd, valor_unit))

    if not itens_devolvidos:
        flash("Selecione ao menos um item e quantidade para devolver.", "erro")
        return redirect(url_for("main.devolucao_venda", venda_id=venda.id))

    # Devolve ao estoque e reduz a quantidade do item na venda.
    for it, qtd, _vu in itens_devolvidos:
        if venda.estoque_baixado:
            linha = _linha_estoque_peca(it.peca, it.tamanho, criar=True)
            linha.quantidade += qtd
            db.session.add(MovimentoPeca(
                peca=it.peca, tamanho=it.tamanho, tipo="estorno", quantidade=qtd,
                observacao=f"Devolução do pedido #{venda.id}",
            ))
        it.quantidade -= qtd
        if it.quantidade <= 0.001:
            db.session.delete(it)

    # Gera um vale-troca com o valor devolvido.
    vale = Vale(
        codigo=_gerar_codigo_vale(), tipo="troca",
        valor_inicial=round(total_credito, 2), saldo=round(total_credito, 2),
        cliente_id=venda.cliente_id,
        observacao=f"Devolução do pedido #{venda.id}",
    )
    db.session.add(vale)
    db.session.commit()
    flash(f"Devolução registrada. Vale-troca {vale.codigo} gerado: R$ {total_credito:.2f}.", "sucesso")
    return redirect(url_for("main.listar_vales"))
