"""Funções auxiliares compartilhadas entre as rotas."""
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

__all__ = ['_usuario_atual', '_is_admin', '_log', '_to_float', '_to_date', '_extensao_permitida', '_salvar_foto', '_otimizar_imagem', '_remover_foto', '_copiar_foto', '_linha_estoque_peca', '_paginar', '_validar_estoque_pecas', '_baixar_estoque_venda', '_restaurar_estoque_venda', '_registrar_movimento', '_itens_ordem_do_form', '_pecas_para_venda', '_dados_pedido_do_form', '_itens_do_form', '_pagamentos_do_form', '_aplicar_pagamentos', '_agrupar', '_itens_crus_do_form', '_render_historico', '_pecas_com_estoque', '_render_form_pedido', '_pfnum', '_prefill_de_venda', '_processar_pedido', '_brl', '_rotulo_cupom', '_pix_ascii', '_emv', '_pix_crc16', '_pix_payload', '_pix_da_venda', '_texto_recibo', '_exigir_admin', '_add_meses', '_gerar_parcelas', '_mes_de', '_mes_label', '_csv_response', '_gerar_codigo_vale', '_salvar_itens_kit', '_frete_opcoes']


def _usuario_atual():
    """Nome do usuário logado (ou 'Admin' se entrou pela senha-mestre)."""
    return session.get("usuario", "")


def _is_admin():
    return bool(session.get("admin"))


def _log(acao, detalhe=""):
    """Registra uma ação na trilha de auditoria (login, vendas, estoque)."""
    db.session.add(Auditoria(usuario=_usuario_atual() or "sistema", acao=acao, detalhe=detalhe[:255]))
    # Commit deixado a cargo de quem chama, mas garantimos que persista:
    db.session.commit()


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
    caminho = os.path.join(current_app.config["UPLOAD_FOLDER"], nome)
    arquivo.save(caminho)
    _otimizar_imagem(caminho)
    return nome


def _otimizar_imagem(caminho, lado_max=1200):
    """Redimensiona a imagem para no máx. `lado_max` px (se Pillow disponível)."""
    try:
        from PIL import Image
    except ImportError:
        return
    try:
        with Image.open(caminho) as img:
            if max(img.size) <= lado_max:
                return
            img.thumbnail((lado_max, lado_max))
            img.save(caminho)
    except Exception:  # noqa: BLE001 — otimização é best-effort
        pass


def _remover_foto(nome):
    if not nome:
        return
    caminho = os.path.join(current_app.config["UPLOAD_FOLDER"], nome)
    if os.path.exists(caminho):
        os.remove(caminho)


def _copiar_foto(nome):
    """Copia um arquivo de foto para um novo nome (para não compartilhar arquivo)."""
    if not nome:
        return None
    origem = os.path.join(current_app.config["UPLOAD_FOLDER"], nome)
    if not os.path.exists(origem):
        return None
    ext = nome.rsplit(".", 1)[-1]
    novo = f"{uuid.uuid4().hex}.{ext}"
    import shutil
    shutil.copyfile(origem, os.path.join(current_app.config["UPLOAD_FOLDER"], novo))
    return novo


def _linha_estoque_peca(peca, tamanho, criar=False):
    """Retorna a linha de estoque da peça no tamanho (cria se pedido)."""
    linha = next((e for e in peca.estoques if e.tamanho == tamanho), None)
    if linha is None and criar:
        linha = EstoquePeca(peca=peca, tamanho=tamanho, quantidade=0.0)
        db.session.add(linha)
    return linha


def _por_pagina(padrao=15):
    """Lê 'por_pagina' da URL (default 15). Valor <= 0 significa 'todos'."""
    try:
        return int(request.args.get("por_pagina", padrao))
    except (TypeError, ValueError):
        return padrao


def _paginar(itens, por_pagina=None):
    """Pagina uma lista em memória. Retorna (itens_da_pagina, pagina, total_paginas).

    O tamanho vem da URL (?por_pagina=N); o argumento define o default da tela.
    """
    pp = _por_pagina(por_pagina or 15)
    if pp <= 0:  # "todos"
        pp = max(1, len(itens))
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    total = max(1, (len(itens) + pp - 1) // pp)
    pagina = min(pagina, total)
    ini = (pagina - 1) * pp
    return itens[ini:ini + pp], pagina, total


def _validar_estoque_pecas(agrupado):
    """Retorna lista de faltas (strings) para {(peca_id, tamanho): qtd}.
    Considera o estoque disponível (quantidade − reservado)."""
    faltando = []
    for (pid, tam), need in agrupado.items():
        peca = Peca.query.get(pid)
        linha = _linha_estoque_peca(peca, tam)
        disp = linha.disponivel if linha else 0.0
        if need > disp:
            faltando.append(f"{peca.nome} tam {tam} (disponível {disp:g}, precisa {need:g})")
    return faltando


def _baixar_estoque_venda(venda):
    """Dá baixa no estoque das peças de uma venda (marca estoque_baixado)."""
    for it in venda.itens:
        linha = _linha_estoque_peca(it.peca, it.tamanho, criar=True)
        linha.quantidade -= it.quantidade
        db.session.add(MovimentoPeca(
            peca=it.peca, tamanho=it.tamanho, tipo="saida", quantidade=it.quantidade,
            observacao=f"Venda #{venda.id}",
        ))
    venda.estoque_baixado = True


def _restaurar_estoque_venda(venda):
    """Devolve ao estoque as peças de uma venda (desfaz a baixa)."""
    for it in venda.itens:
        linha = _linha_estoque_peca(it.peca, it.tamanho, criar=True)
        linha.quantidade += it.quantidade
        db.session.add(MovimentoPeca(
            peca=it.peca, tamanho=it.tamanho, tipo="estorno", quantidade=it.quantidade,
            observacao=f"Estorno venda #{venda.id}",
        ))
    venda.estoque_baixado = False


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


def _itens_ordem_do_form(ordem):
    """Lê peca_id[]/tamanho[]/quantidade[] e (re)popula os itens da ordem."""
    peca_ids = request.form.getlist("peca_id")
    tamanhos = request.form.getlist("tamanho")
    quantidades = request.form.getlist("quantidade")
    for i, pid in enumerate(peca_ids):
        pid = int(pid) if pid else 0
        tam = (tamanhos[i] if i < len(tamanhos) else "").strip().upper()
        qtd = _to_float(quantidades[i]) if i < len(quantidades) else 0
        if not pid or tam not in TAMANHOS or qtd <= 0:
            continue
        ordem.itens.append(OrdemProducaoItem(peca_id=pid, tamanho=tam, quantidade=qtd))


def _pecas_para_venda():
    """Peças disponíveis para venda/encomenda (todas com preço)."""
    return Peca.query.order_by(Peca.nome).all()


def _dados_pedido_do_form():
    cid = request.form.get("cliente_id", type=int)
    return {
        "frete": _to_float(request.form.get("frete")),
        "frete_cortesia": request.form.get("frete_cortesia") == "on",
        "marketplace_pct": _to_float(request.form.get("marketplace_pct")),
        "desconto_total": _to_float(request.form.get("desconto_total")),
        "cliente_id": cid if cid else None,
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
        preco = dinheiro(_to_float(precos[i] if i < len(precos) else 0))
        desconto = dinheiro(_to_float(descontos[i] if i < len(descontos) else 0))
        if not peca or tam not in TAMANHOS or qtd <= 0:
            continue
        linhas.append({"peca": peca, "tamanho": tam, "quantidade": qtd, "preco": preco, "desconto": desconto})
    if not linhas:
        return [], "Adicione ao menos um item com peça, tamanho e quantidade válidos."
    return linhas, None


def _pagamentos_do_form():
    """Lê as linhas de pagamento do formulário."""
    formas = request.form.getlist("pag_forma")
    valores = request.form.getlist("pag_valor")
    parcelas = request.form.getlist("pag_parcelas")
    taxas = request.form.getlist("pag_taxa")
    pags = []
    for i, forma in enumerate(formas):
        valor = dinheiro(_to_float(valores[i] if i < len(valores) else 0))
        if valor <= 0:
            continue
        pags.append({
            "forma": forma.strip() or "—",
            "valor": valor,
            "parcelas": int(_to_float(parcelas[i] if i < len(parcelas) else 1) or 1),
            "taxa_pct": _to_float(taxas[i] if i < len(taxas) else 0),
        })
    return pags


def _aplicar_pagamentos(venda, pags):
    """Substitui os pagamentos da venda e sincroniza status/forma/pago."""
    for p in list(venda.pagamentos):
        db.session.delete(p)
    venda.pagamentos = []
    for p in pags:
        db.session.add(Pagamento(venda=venda, **p))
    formas = list(dict.fromkeys(p["forma"] for p in pags))
    venda.forma_pagamento = " + ".join(formas)
    # Calcula direto da lista (não usa total_pago, que tem fallback legado).
    total = sum(p["valor"] for p in pags)
    venda.pago = total >= venda.receita - 0.01
    if not venda.pago:
        # Sem pagamento total, o pedido volta para "Aguardando pagamento",
        # mesmo que já estivesse enviado/entregue.
        venda.status = "realizado"
    elif venda.status == "realizado":
        venda.status = "pago"


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


def _render_historico():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()  # "pago" | "pendente" | ""
    de = _to_date(request.args.get("de"))
    ate = _to_date(request.args.get("ate"))
    vendas = Venda.query.order_by(Venda.criado_em.desc()).all()
    if q:
        ql = q.lower()
        vendas = [v for v in vendas if ql in (v.cliente_nome or "").lower()]
    if status == "pago":
        vendas = [v for v in vendas if v.pago]
    elif status == "pendente":
        vendas = [v for v in vendas if not v.pago]
    if de:
        vendas = [v for v in vendas if v.criado_em and v.criado_em.date() >= de]
    if ate:
        vendas = [v for v in vendas if v.criado_em and v.criado_em.date() <= ate]
    # Pré-pedidos aparecem na lista, mas não entram nos totais (ainda não confirmados).
    confirmadas = [v for v in vendas if not v.eh_pre_pedido]
    totais = {
        "receita": sum(v.receita for v in confirmadas),
        "custo": sum(v.custo_total for v in confirmadas),
        "lucro": sum(v.lucro for v in confirmadas),
        "qtd": sum(v.quantidade_total for v in confirmadas),
    }
    vendas_pag, pagina, total_paginas = _paginar(vendas)
    return render_template(
        "vendas_historico.html", vendas=vendas_pag, totais=totais,
        q=q, status=status,
        de=request.args.get("de", ""), ate=request.args.get("ate", ""),
        pagina=pagina, total_paginas=total_paginas,
    )


def _pecas_com_estoque():
    """Peças com ao menos 1 unidade disponível em algum tamanho (venda com estoque)."""
    return [p for p in Peca.query.order_by(Peca.nome).all() if p.disponivel_total >= 1]


def _render_form_pedido(modo, prefill_itens=None, prefill_pedido=None, acao=None, venda=None):
    # Venda: só peças com estoque. Encomenda/edição: todas (mantém itens do pedido).
    pecas = _pecas_com_estoque() if modo == "venda" else Peca.query.order_by(Peca.nome).all()
    kits = Kit.query.filter_by(ativo=True).order_by(Kit.nome).all()
    return render_template(
        "venda_nova.html", modo=modo, pecas=pecas, kits=kits,
        clientes=Cliente.query.order_by(Cliente.nome).all(),
        prefill_itens=prefill_itens or [], prefill_pedido=prefill_pedido or {},
        acao=acao, venda=venda,
    )


def _pfnum(v):
    """Formata número para prefill de campo (vazio quando 0)."""
    return "" if not v else (f"{v:g}")


def _prefill_de_venda(venda):
    itens = [{
        "peca_id": it.peca_id, "tamanho": it.tamanho, "quantidade": it.quantidade,
        "preco": it.preco_unitario, "desconto": it.desconto,
    } for it in venda.itens]
    pedido = {
        "cliente_id": venda.cliente_id,
        "frete": _pfnum(venda.frete),
        "frete_cortesia": venda.frete_cortesia,
        "marketplace_pct": _pfnum(venda.marketplace_pct),
        "desconto_total": _pfnum(venda.desconto_total),
    }
    return itens, pedido


def _processar_pedido(modo):
    def _erro(msg):
        flash(msg, "erro")
        return _render_form_pedido(modo, _itens_crus_do_form(), request.form)

    linhas, erro = _itens_do_form()
    if erro:
        return _erro(erro)

    # Venda exige estoque (comportamento antigo). Encomenda não baixa.
    if modo == "venda":
        faltando = _validar_estoque_pecas(_agrupar(linhas))
        if faltando:
            return _erro("Estoque insuficiente: " + "; ".join(faltando)
                         + ". Use 'Encomenda' para vender sem estoque.")

    venda = Venda(**_dados_pedido_do_form())
    venda.tipo = modo
    venda.vendedor = _usuario_atual()
    db.session.add(venda)
    for l in linhas:
        db.session.add(VendaItem(
            venda=venda, peca=l["peca"], tamanho=l["tamanho"],
            quantidade=l["quantidade"], preco_unitario=l["preco"],
            desconto=l["desconto"], custo_unitario=l["peca"].custo_total,
        ))
    db.session.flush()

    # Cupom de desconto (opcional).
    cod = request.form.get("cupom", "").strip().upper()
    if cod:
        cupom = Cupom.query.filter(db.func.upper(Cupom.codigo) == cod).first()
        if cupom and cupom.valido:
            if cupom.tipo == "frete":
                # Desconto sobre o frete efetivamente cobrado (0 se já é cortesia)
                # — mantém venda.frete como registro do valor nominal do envio.
                frete_efetivo = 0.0 if venda.frete_cortesia else (venda.frete or 0.0)
                venda.desconto_total += cupom.desconto_frete_para(frete_efetivo)
            else:
                venda.desconto_total += cupom.desconto_para(venda.receita_itens)
            venda.cupom_codigo = cupom.codigo
            cupom.usos += 1
        else:
            flash(f"Cupom '{cod}' inválido ou expirado — ignorado.", "erro")

    if modo == "venda":
        # Venda: pedido é fechado sem pagamento (status "Pedido feito"); baixa estoque.
        _baixar_estoque_venda(venda)
        db.session.commit()
        _log("venda", f"pedido #{venda.id} registrado ({_brl(venda.receita)})")
        flash("Pedido registrado. Agora registre o pagamento.", "sucesso")
        return redirect(url_for("main.visualizar_venda", venda_id=venda.id))

    # Encomenda: mantém pagamento no cadastro e não baixa estoque.
    _aplicar_pagamentos(venda, _pagamentos_do_form())
    venda.estoque_baixado = False
    db.session.commit()
    _log("encomenda", f"encomenda #{venda.id} registrada ({_brl(venda.receita)})")
    flash("Encomenda registrada. Produza as peças e use 'Baixar estoque'.", "sucesso")
    return redirect(url_for("main.listar_encomendas"))


def _brl(v):
    return ("R$ " + f"{float(v or 0):,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")


def _rotulo_cupom(cupom):
    """Texto curto do desconto do cupom, para prévia (ERP e vitrine)."""
    if cupom.tipo == "percentual":
        return f"{cupom.valor:g}%"
    if cupom.tipo == "frete":
        return "frete grátis" if not cupom.valor else f"até {_brl(cupom.valor)} de frete"
    return _brl(cupom.valor)


def _pix_ascii(texto, limite):
    """Remove acentos, mantém ASCII e recorta (nome/cidade do recebedor)."""
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return t.upper().strip()[:limite]


def _emv(tag, valor):
    return f"{tag}{len(valor):02d}{valor}"


def _pix_crc16(payload):
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def _pix_payload(chave, nome, cidade, valor=0.0, txid="***"):
    """Monta o código Pix 'copia e cola' (payload BR Code) para uma chave estática."""
    chave = (chave or "").strip()
    if not chave:
        return ""
    nome = _pix_ascii(nome, 25) or "RECEBEDOR"
    cidade = _pix_ascii(cidade, 15) or "CIDADE"
    txid = re.sub(r"[^A-Za-z0-9]", "", txid or "***")[:25] or "***"

    mai = _emv("00", "br.gov.bcb.pix") + _emv("01", chave)
    campos = _emv("00", "01") + _emv("26", mai) + _emv("52", "0000") + _emv("53", "986")
    if valor and valor > 0:
        campos += _emv("54", f"{valor:.2f}")
    campos += _emv("58", "BR") + _emv("59", nome) + _emv("60", cidade)
    campos += _emv("62", _emv("05", txid))
    campos += "6304"
    return campos + _pix_crc16(campos)


def _pix_da_venda(venda):
    """Retorna (payload, valor) para o saldo da venda, ou (None, 0) se não configurado."""
    chave = Parametro.obter("pix_chave", "")
    if not chave:
        return None, 0.0
    valor = venda.saldo_receber if venda.saldo_receber > 0.01 else venda.receita
    payload = _pix_payload(
        chave, Parametro.obter("pix_nome", ""), Parametro.obter("pix_cidade", ""),
        valor=valor, txid=f"PEDIDO{venda.id}",
    )
    return payload, valor


def _texto_recibo(venda):
    """Recibo em texto puro para enviar no WhatsApp."""
    linhas = [
        "*Sabrina Hansen Atelier*",
        f"Recibo do pedido #{venda.id}",
        venda.criado_em.strftime("%d/%m/%Y") if venda.criado_em else "",
    ]
    if venda.cliente_nome:
        linhas.append(f"Cliente: {venda.cliente_nome}")
    linhas.append("")
    for it in venda.itens:
        tam = f" ({it.tamanho})" if it.tamanho else ""
        linhas.append(f"• {it.quantidade:g}x {it.peca.nome}{tam} — {_brl(it.subtotal_receita)}")
    linhas.append("")
    if venda.frete and not venda.frete_cortesia:
        linhas.append(f"Frete: {_brl(venda.frete)}")
    if venda.desconto_geral > 0:
        linhas.append(f"Desconto: -{_brl(venda.desconto_geral)}")
    linhas.append(f"*Total: {_brl(venda.receita)}*")
    if venda.saldo_receber > 0.01:
        linhas.append(f"Pago: {_brl(venda.total_pago)} · Saldo: {_brl(venda.saldo_receber)}")
    else:
        linhas.append("Pagamento: quitado ✅")
    linhas.append("")
    linhas.append("Obrigada pela preferência! 💛")
    return "\n".join(l for l in linhas if l is not None)


def _exigir_admin():
    if not _is_admin():
        flash("Acesso restrito a administradores.", "erro")
        return redirect(url_for("main.index"))
    return None


def _add_meses(d, k):
    """Retorna a data d + k meses (ajustando o dia ao fim do mês quando preciso)."""
    total = d.month - 1 + k
    ano = d.year + total // 12
    mes = total % 12 + 1
    dia = min(d.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia)


def _gerar_parcelas(venda, total, n, inicio):
    """Cria n parcelas somando 'total', mensais a partir de 'inicio'."""
    n = max(1, int(n))
    base = round(total / n, 2)
    acumulado = 0.0
    for k in range(n):
        valor = round(total - acumulado, 2) if k == n - 1 else base
        acumulado += valor
        db.session.add(Parcela(
            venda=venda, numero=k + 1, total=n, valor=valor,
            vencimento=_add_meses(inicio, k),
        ))


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


def _gerar_codigo_vale():
    import random
    import string
    while True:
        cod = "VL-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Vale.query.filter_by(codigo=cod).first():
            return cod


def _salvar_itens_kit(kit):
    """Lê os campos peca_id[]/quantidade[] do form e regrava os itens do kit."""
    for it in list(kit.itens):
        db.session.delete(it)
    peca_ids = request.form.getlist("peca_id")
    quantidades = request.form.getlist("quantidade")
    for i, pid in enumerate(peca_ids):
        pid = int(pid) if pid else 0
        if not pid:
            continue
        qtd = _to_float(quantidades[i]) if i < len(quantidades) else 1.0
        if qtd <= 0:
            qtd = 1.0
        kit.itens.append(KitItem(peca_id=pid, quantidade=qtd))


def _frete_opcoes(cep_destino, peso_g=0.0, altura_cm=0.0, largura_cm=0.0, comprimento_cm=0.0):
    """Consulta o Melhor Envio e devolve (opcoes, erro).

    opcoes: lista de {nome, preco, prazo, rapido?} (a mais rápida + as mais baratas).
    erro:   mensagem (str) ou None. Dimensões em 0 caem para um padrão razoável.
    """
    import json
    import urllib.request

    token = os.environ.get("MELHOR_ENVIO_TOKEN", "").strip()
    cep_origem = os.environ.get("CEP_ORIGEM", "").strip()
    if not token or not cep_origem:
        return [], "Frete não configurado. Defina MELHOR_ENVIO_TOKEN e CEP_ORIGEM."

    cep = re.sub(r"\D", "", cep_destino or "")
    if len(cep) != 8:
        return [], "CEP de destino inválido."

    payload = {
        "from": {"postal_code": re.sub(r"\D", "", cep_origem)},
        "to": {"postal_code": cep},
        "package": {
            "weight": (float(peso_g) / 1000) or 0.3,   # kg
            "height": float(altura_cm) or 5,
            "width": float(largura_cm) or 20,
            "length": float(comprimento_cm) or 30,
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
        # ProxyHandler({}) explícito: NÃO consulta o proxy do sistema (evita o
        # crash de fork-safety do Obj-C no macOS dentro do worker do Gunicorn).
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=15) as resp:
            dados = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        return [], f"Falha ao consultar frete: {e}"

    def _preco(o):
        try:
            return float(o["preco"])
        except (TypeError, ValueError):
            return float("inf")

    opcoes = [
        {"nome": o.get("name"), "preco": o.get("price"), "prazo": o.get("delivery_time")}
        for o in dados if not o.get("error") and o.get("price")
    ]
    # Mantém a mais barata de cada serviço (sem repetir nome).
    unicas = {}
    for o in opcoes:
        if o["nome"] not in unicas or _preco(o) < _preco(unicas[o["nome"]]):
            unicas[o["nome"]] = o
    lista = list(unicas.values())

    # Seleciona: a mais rápida + as mais baratas (sem repetir), no máx. 4.
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
    return selecionadas, None
