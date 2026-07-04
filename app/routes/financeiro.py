"""Rotas: financeiro."""
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
    dinheiro,
)

from . import bp
from .helpers import *  # noqa: F401,F403


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
    total_movimentos = len(ledger)
    ledger, pagina, total_paginas = _paginar(ledger)

    recebido = sum(v.total_pago for v in vendas_f)
    a_receber = sum(v.saldo_receber for v in vendas_f)
    saidas_insumos = sum(_compra_valor(c) for c in compras_f)
    saidas_despesas = sum(d.valor for d in despesas_f if d.pago)
    saidas_total = saidas_insumos + saidas_despesas
    lucro = sum(v.lucro for v in vendas_f)

    # Recebido por forma de pagamento (a partir dos pagamentos).
    formas = {}
    for v in vendas_f:
        if v.pagamentos:
            for p in v.pagamentos:
                formas[p.forma or "—"] = formas.get(p.forma or "—", 0.0) + p.valor
        elif v.pago:
            formas[v.forma_pagamento or "—"] = formas.get(v.forma_pagamento or "—", 0.0) + v.receita

    # Contas a receber (com saldo) e a pagar (despesas pendentes).
    pendentes = sorted(
        [v for v in vendas if v.saldo_receber > 0.01],
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
        "a_receber_total": sum(v.saldo_receber for v in pendentes),
        "a_pagar_total": sum(d.valor for d in a_pagar),
    }

    return render_template(
        "contabilidade.html", ledger=ledger, kpis=kpis, formas=formas,
        pendentes=pendentes, a_pagar=a_pagar, meses=meses, mes_atual=mes, mes_label=_mes_label,
        pagina=pagina, total_paginas=total_paginas, total_movimentos=total_movimentos,
    )


@bp.route("/despesas")
def listar_despesas():
    despesas = Despesa.query.order_by(Despesa.pago, Despesa.vencimento).all()
    total_pendente = sum(d.valor for d in despesas if not d.pago)
    return render_template("despesas.html", despesas=despesas, total_pendente=total_pendente)


@bp.route("/contas-a-receber")
def contas_a_receber():
    """Parcelas de crediário em aberto + pedidos com saldo pendente."""
    from datetime import date as _date
    parcelas = [p for p in Parcela.query.all() if not p.pago]
    parcelas.sort(key=lambda p: (p.vencimento or _date.max, p.venda_id, p.numero))
    # Pedidos com saldo pendente que NÃO são crediário (pagamento parcial etc.).
    outros = [v for v in Venda.query.all() if v.saldo_receber > 0.01 and not v.parcelas]
    outros.sort(key=lambda v: (v.vencimento or _date.max, v.id))

    total = sum(p.valor for p in parcelas) + sum(v.saldo_receber for v in outros)
    total_vencido = (sum(p.valor for p in parcelas if p.vencida)
                     + sum(v.saldo_receber for v in outros if v.vencida))
    return render_template(
        "contas_a_receber.html", parcelas=parcelas, outros=outros,
        total=total, total_vencido=total_vencido, hoje=date.today(),
    )


@bp.route("/fluxo-caixa")
def fluxo_caixa():
    """Projeção de caixa: a receber (crediário + saldos) e a pagar (despesas),
    agrupados por mês de vencimento, com saldo do mês e saldo acumulado."""
    hoje = date.today()
    MESES = int(request.args.get("meses", 6) or 6)
    MESES = max(3, min(MESES, 12))

    # A receber: parcelas de crediário em aberto + saldos pendentes de pedidos.
    receber = [(p.vencimento, p.valor) for p in Parcela.query.filter_by(pago=False).all()]
    for v in Venda.query.all():
        if v.saldo_receber > 0.01 and not v.parcelas:
            receber.append((v.vencimento, v.saldo_receber))
    # A pagar: despesas em aberto.
    pagar = [(d.vencimento, d.valor) for d in Despesa.query.filter_by(pago=False).all()]

    # Janela de meses a partir do mês atual.
    meses = [(_add_meses(hoje.replace(day=1), i)).strftime("%Y-%m") for i in range(MESES)]
    limite = meses[-1]

    def distribuir(itens):
        atraso = sem_data = alem = 0.0
        por_mes = {k: 0.0 for k in meses}
        for venc, val in itens:
            if venc is None:
                sem_data += val
            elif venc < hoje:
                atraso += val
            else:
                chave = venc.strftime("%Y-%m")
                if chave in por_mes:
                    por_mes[chave] += val
                elif chave > limite:
                    alem += val
                else:  # mês passado mas ainda >= hoje não ocorre; salvaguarda
                    atraso += val
        return atraso, sem_data, por_mes, alem

    r_atraso, r_semdata, r_mes, r_alem = distribuir(receber)
    p_atraso, p_semdata, p_mes, p_alem = distribuir(pagar)

    linhas = []
    acumulado = 0.0

    def add_linha(label, rec, pag, conta_acumulado=True, destaque=None):
        nonlocal acumulado
        saldo = dinheiro(rec - pag)
        if conta_acumulado:
            acumulado = dinheiro(acumulado + saldo)
        linhas.append({
            "label": label, "receber": dinheiro(rec), "pagar": dinheiro(pag),
            "saldo": saldo, "acumulado": acumulado if conta_acumulado else None,
            "destaque": destaque,
        })

    if r_atraso or p_atraso:
        add_linha("Em atraso", r_atraso, p_atraso, destaque="atraso")
    for k in meses:
        add_linha(_mes_label(k), r_mes[k], p_mes[k])
    if r_alem or p_alem:
        add_linha(f"Após {_mes_label(limite)}", r_alem, p_alem)
    if r_semdata or p_semdata:
        add_linha("Sem vencimento", r_semdata, p_semdata, conta_acumulado=False)

    tot_receber = dinheiro(sum(v for _, v in receber))
    tot_pagar = dinheiro(sum(v for _, v in pagar))
    return render_template(
        "fluxo_caixa.html", linhas=linhas, meses=MESES,
        tot_receber=tot_receber, tot_pagar=tot_pagar,
        saldo_final=dinheiro(tot_receber - tot_pagar), hoje=hoje,
    )


@bp.route("/parcelas/<int:parcela_id>/pagar", methods=["POST"])
def pagar_parcela(parcela_id):
    p = Parcela.query.get_or_404(parcela_id)
    if p.pago:
        flash("Parcela já recebida.", "erro")
        return redirect(request.referrer or url_for("main.contas_a_receber"))
    p.pago = True
    p.pago_em = datetime.now()
    venda = p.venda
    db.session.add(Pagamento(venda=venda, forma=f"Crediário {p.rotulo}", valor=p.valor))
    venda.pago = venda.total_pago >= venda.receita - 0.01
    if venda.crediario_quitado and venda.status == "crediario":
        venda.status = "pago"
    db.session.commit()
    _log("pagamento", f"parcela {p.rotulo} pedido #{venda.id}: {_brl(p.valor)}")
    flash(f"Parcela {p.rotulo} do pedido #{venda.id} recebida.", "sucesso")
    return redirect(request.referrer or url_for("main.contas_a_receber"))


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
    d.valor = dinheiro(_to_float(request.form.get("valor")))
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


@bp.route("/relatorio")
def relatorio():
    todas = Venda.query.all()
    anos = sorted({v.criado_em.year for v in todas if v.criado_em}, reverse=True)
    ano_sel = request.args.get("ano", "").strip()
    if ano_sel.isdigit():
        vendas = [v for v in todas if v.criado_em and v.criado_em.year == int(ano_sel)]
    else:
        ano_sel = ""
        vendas = todas

    # KPIs do período.
    receita = sum(v.receita for v in vendas)
    custo = sum(v.custo_total for v in vendas)
    lucro = sum(v.lucro for v in vendas)
    qtd_pecas = sum(v.quantidade_total for v in vendas)
    n_vendas = len(vendas)
    kpis = {
        "receita": receita, "lucro": lucro, "custo": custo,
        "n_vendas": n_vendas, "qtd_pecas": qtd_pecas,
        "ticket": (receita / n_vendas) if n_vendas else 0.0,
        "margem": (lucro / receita * 100) if receita else 0.0,
    }

    # Série mensal (receita/custo/lucro).
    por_mes = {}
    for v in vendas:
        k = _mes_de(v.criado_em)
        m = por_mes.setdefault(k, {"receita": 0.0, "custo": 0.0, "lucro": 0.0, "qtd": 0.0})
        m["receita"] += v.receita
        m["custo"] += v.custo_total
        m["lucro"] += v.lucro
        m["qtd"] += v.quantidade_total
    serie = [{"mes": k, "label": _mes_label(k), **por_mes[k]} for k in sorted(por_mes)]

    # Comparativo mês-a-mês: variação (%) de cada mês vs o mês anterior.
    def _variacao(atual, base):
        return ((atual - base) / base * 100) if base else None
    for i, s in enumerate(serie):
        ant = serie[i - 1] if i > 0 else None
        for campo in ("receita", "lucro", "qtd"):
            s[f"{campo}_var"] = _variacao(s[campo], ant[campo]) if ant else None

    # Resumo destacado dos dois meses mais recentes.
    comparativo = None
    if len(serie) >= 2:
        atual, anterior = serie[-1], serie[-2]
        comparativo = {
            "atual": atual, "anterior": anterior,
            "receita_var": _variacao(atual["receita"], anterior["receita"]),
            "lucro_var": _variacao(atual["lucro"], anterior["lucro"]),
            "qtd_var": _variacao(atual["qtd"], anterior["qtd"]),
        }

    # Ranking de peças (por receita) + curva ABC.
    ranking = {}
    for v in vendas:
        for it in v.itens:
            r = ranking.setdefault(it.peca.nome, {"qtd": 0.0, "receita": 0.0})
            r["qtd"] += it.quantidade
            r["receita"] += it.subtotal_receita
    ordenadas = sorted(ranking.items(), key=lambda x: x[1]["receita"], reverse=True)
    mais_vendidas = [{"nome": n, **r} for n, r in ordenadas[:10]]
    total_rank = sum(r["receita"] for _, r in ordenadas) or 1.0
    abc = {"A": 0, "B": 0, "C": 0}
    curva = []
    acumulado = 0.0
    for nome, r in ordenadas:
        acumulado += r["receita"]
        pct_acum = acumulado / total_rank * 100
        classe = "A" if pct_acum <= 80 else ("B" if pct_acum <= 95 else "C")
        abc[classe] += 1
        curva.append({"nome": nome, "receita": r["receita"], "qtd": r["qtd"],
                      "pct_acum": pct_acum, "classe": classe})

    # Receita por coleção.
    por_colecao = {}
    for v in vendas:
        for it in v.itens:
            col = it.peca.colecao or "Sem coleção"
            por_colecao[col] = por_colecao.get(col, 0.0) + it.subtotal_receita
    colecoes = sorted(por_colecao.items(), key=lambda x: x[1], reverse=True)

    # Recebido por forma de pagamento (crediário agrupado).
    formas = {}
    for v in vendas:
        for p in v.pagamentos:
            nome = "Crediário" if p.forma.startswith("Crediário") else (p.forma or "Outros")
            formas[nome] = formas.get(nome, 0.0) + p.valor
    formas = sorted(formas.items(), key=lambda x: x[1], reverse=True)

    return render_template(
        "relatorio.html", serie=serie, mais_vendidas=mais_vendidas, colecoes=colecoes,
        kpis=kpis, anos=anos, ano_sel=ano_sel, curva=curva, abc=abc, formas=formas,
        comparativo=comparativo, hoje=date.today(),
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
