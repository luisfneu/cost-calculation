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

from .models import (
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

bp = Blueprint("main", __name__)

# Endpoints acessíveis sem login (público / estáticos).
_PUBLICOS = {"main.login", "main.vitrine_publica", "static"}


@bp.before_app_request
def _exigir_login():
    if request.endpoint in _PUBLICOS:
        return None
    if not session.get("logado"):
        return redirect(url_for("main.login", next=request.path))
    return None


def _usuario_atual():
    """Nome do usuário logado (ou 'Admin' se entrou pela senha-mestre)."""
    return session.get("usuario", "")


def _is_admin():
    return bool(session.get("admin"))


def _log(acao, detalhe=""):
    """Registra uma ação na trilha de auditoria (login, vendas, estoque)."""
    db.session.add(Auditoria(usuario=_usuario_atual() or "?", acao=acao, detalhe=detalhe[:255]))
    # Commit deixado a cargo de quem chama, mas garantimos que persista:
    db.session.commit()


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_txt = request.form.get("login", "").strip()
        senha = request.form.get("senha", "")
        destino = request.args.get("next") or url_for("main.index")

        # 1) Usuário individual (se informado login e existir usuário ativo).
        if login_txt:
            u = Usuario.query.filter(db.func.lower(Usuario.login) == login_txt.lower()).first()
            if u and u.ativo and u.conferir_senha(senha):
                session["logado"] = True
                session["usuario"] = u.nome
                session["admin"] = u.admin
                _log("login", f"usuário {u.login}")
                return redirect(destino)
            flash("Login ou senha inválidos.", "erro")
            return render_template("login.html")

        # 2) Senha-mestre (acesso admin de emergência).
        if senha == current_app.config["APP_SENHA"]:
            session["logado"] = True
            session["usuario"] = "Admin"
            session["admin"] = True
            _log("login", "senha-mestre")
            return redirect(destino)

        flash("Login ou senha inválidos.", "erro")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    if session.get("logado"):
        _log("logout")
    session.clear()
    flash("Você saiu do sistema.", "sucesso")
    return redirect(url_for("main.login"))


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


def _paginar(itens, por_pagina=24):
    """Pagina uma lista em memória. Retorna (itens_da_pagina, pagina, total_paginas)."""
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    total = max(1, (len(itens) + por_pagina - 1) // por_pagina)
    pagina = min(pagina, total)
    ini = (pagina - 1) * por_pagina
    return itens[ini:ini + por_pagina], pagina, total


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


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@bp.route("/")
def index():
    pecas = Peca.query.order_by(Peca.criado_em.desc()).all()
    insumos = Insumo.query.order_by(Insumo.nome).all()
    alertas = [i for i in insumos if i.ativo and i.estoque_baixo]
    pecas_repor = [p for p in pecas if p.precisa_repor]
    vendas = Venda.query.all()
    totais_venda = {
        "receita": sum(v.receita for v in vendas),
        "lucro": sum(v.lucro for v in vendas),
        "qtd": sum(v.quantidade_total for v in vendas),
        "a_receber": sum(v.receita for v in vendas if not v.pago),
    }
    # Meta do mês.
    mes_atual = date.today().strftime("%Y-%m")
    receita_mes = sum(v.receita for v in vendas if _mes_de(v.criado_em) == mes_atual)
    meta = _to_float(Parametro.obter("meta_mensal", "0"))
    meta_pct = (receita_mes / meta * 100) if meta else 0

    # Lembretes extras: aniversariantes do mês e parcelas de crediário a receber.
    clientes = Cliente.query.all()
    aniversariantes = sorted(
        [c for c in clientes if c.aniversario_no_mes],
        key=lambda c: c.nascimento.day,
    )
    parcelas_abertas = [p for p in Parcela.query.all() if not p.pago]
    parcelas_vencidas = [p for p in parcelas_abertas if p.vencida]
    lembretes = {
        "aniversariantes": aniversariantes,
        "parcelas_abertas": len(parcelas_abertas),
        "parcelas_vencidas": len(parcelas_vencidas),
        "parcelas_valor_vencido": sum(p.valor for p in parcelas_vencidas),
    }
    return render_template(
        "index.html", pecas=pecas, insumos=insumos, alertas=alertas,
        pecas_repor=pecas_repor, lembretes=lembretes,
        totais_venda=totais_venda, n_clientes=len(clientes),
        meta=meta, receita_mes=receita_mes, meta_pct=meta_pct,
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


@bp.route("/historico")
def historico():
    mov_pecas = MovimentoPeca.query.order_by(MovimentoPeca.criado_em.desc()).limit(300).all()
    mov_insumos = MovimentoEstoque.query.order_by(MovimentoEstoque.criado_em.desc()).limit(300).all()
    return render_template("historico.html", mov_pecas=mov_pecas, mov_insumos=mov_insumos)


# --------------------------------------------------------------------------- #
# Estoque de peças: inventário, mínimos e reserva
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Ordens de produção + lista de compras
# --------------------------------------------------------------------------- #
@bp.route("/producao")
def listar_ordens():
    ordens = OrdemProducao.query.order_by(
        OrdemProducao.status, OrdemProducao.criado_em.desc()
    ).all()
    pecas = Peca.query.order_by(Peca.nome).all()
    return render_template("producao.html", ordens=ordens, pecas=pecas, tamanhos=TAMANHOS)


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
    return render_template(
        "crm.html", aniversariantes=aniversariantes, reativar=reativar,
        sem_compra=sem_compra, dias_inativo=dias_inativo, hoje=date.today(),
    )


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
        preco = _to_float(precos[i] if i < len(precos) else 0)
        desconto = _to_float(descontos[i] if i < len(descontos) else 0)
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
        valor = _to_float(valores[i] if i < len(valores) else 0)
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
    vendas_pag, pagina, total_paginas = _paginar(vendas)
    return render_template(
        "vendas_historico.html", vendas=vendas_pag, totais=totais,
        q=q, status=status, pagina=pagina, total_paginas=total_paginas,
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
    encomendas = (
        Venda.query.filter_by(tipo="encomenda").order_by(Venda.criado_em.desc()).all()
    )
    encomendas, pagina, total_paginas = _paginar(encomendas)
    return render_template(
        "encomendas.html", encomendas=encomendas, pagina=pagina, total_paginas=total_paginas
    )


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


@bp.route("/vendas/<int:venda_id>/status/<novo>", methods=["POST"])
def alterar_status_venda(venda_id, novo):
    venda = Venda.query.get_or_404(venda_id)
    if novo not in Venda.FLUXO:
        flash("Status inválido.", "erro")
        return redirect(request.referrer or url_for("main.listar_vendas"))
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


def _brl(v):
    return ("R$ " + f"{float(v or 0):,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------- #
# Pix "copia e cola" (BR Code / EMV) — sem dependências externas
# --------------------------------------------------------------------------- #
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


@bp.route("/configuracoes", methods=["GET", "POST"])
def configuracoes():
    if request.method == "POST":
        Parametro.definir("pix_chave", request.form.get("pix_chave", "").strip())
        Parametro.definir("pix_nome", request.form.get("pix_nome", "").strip())
        Parametro.definir("pix_cidade", request.form.get("pix_cidade", "").strip())
        Parametro.definir("meta_mensal", _to_float(request.form.get("meta_mensal")))
        db.session.commit()
        flash("Configurações salvas.", "sucesso")
        return redirect(url_for("main.configuracoes"))

    # Prévia do Pix com R$ 1,00 para o usuário conferir.
    previa = _pix_payload(
        Parametro.obter("pix_chave", ""), Parametro.obter("pix_nome", ""),
        Parametro.obter("pix_cidade", ""), valor=1.0, txid="TESTE",
    )
    cfg = {
        "pix_chave": Parametro.obter("pix_chave", ""),
        "pix_nome": Parametro.obter("pix_nome", ""),
        "pix_cidade": Parametro.obter("pix_cidade", ""),
        "meta_mensal": Parametro.obter("meta_mensal", "0"),
    }
    return render_template("configuracoes.html", cfg=cfg, pix_previa=previa)


# --------------------------------------------------------------------------- #
# Usuários e auditoria
# --------------------------------------------------------------------------- #
def _exigir_admin():
    if not _is_admin():
        flash("Acesso restrito a administradores.", "erro")
        return redirect(url_for("main.index"))
    return None


@bp.route("/usuarios")
def listar_usuarios():
    barrado = _exigir_admin()
    if barrado:
        return barrado
    usuarios = Usuario.query.order_by(Usuario.ativo.desc(), Usuario.nome).all()
    return render_template("usuarios.html", usuarios=usuarios)


@bp.route("/usuarios/novo", methods=["POST"])
def novo_usuario():
    barrado = _exigir_admin()
    if barrado:
        return barrado
    nome = request.form.get("nome", "").strip()
    login_txt = request.form.get("login", "").strip()
    senha = request.form.get("senha", "")
    if not nome or not login_txt or not senha:
        flash("Preencha nome, login e senha.", "erro")
        return redirect(url_for("main.listar_usuarios"))
    if Usuario.query.filter(db.func.lower(Usuario.login) == login_txt.lower()).first():
        flash("Já existe um usuário com esse login.", "erro")
        return redirect(url_for("main.listar_usuarios"))
    u = Usuario(nome=nome, login=login_txt, admin=bool(request.form.get("admin")))
    u.set_senha(senha)
    db.session.add(u)
    db.session.commit()
    flash(f"Usuário {u.login} criado.", "sucesso")
    return redirect(url_for("main.listar_usuarios"))


@bp.route("/usuarios/<int:usuario_id>/senha", methods=["POST"])
def redefinir_senha_usuario(usuario_id):
    barrado = _exigir_admin()
    if barrado:
        return barrado
    u = Usuario.query.get_or_404(usuario_id)
    senha = request.form.get("senha", "")
    if not senha:
        flash("Informe a nova senha.", "erro")
        return redirect(url_for("main.listar_usuarios"))
    u.set_senha(senha)
    db.session.commit()
    flash(f"Senha de {u.login} redefinida.", "sucesso")
    return redirect(url_for("main.listar_usuarios"))


@bp.route("/usuarios/<int:usuario_id>/toggle", methods=["POST"])
def toggle_usuario(usuario_id):
    barrado = _exigir_admin()
    if barrado:
        return barrado
    u = Usuario.query.get_or_404(usuario_id)
    u.ativo = not u.ativo
    db.session.commit()
    return redirect(url_for("main.listar_usuarios"))


@bp.route("/usuarios/<int:usuario_id>/excluir", methods=["POST"])
def excluir_usuario(usuario_id):
    barrado = _exigir_admin()
    if barrado:
        return barrado
    u = Usuario.query.get_or_404(usuario_id)
    db.session.delete(u)
    db.session.commit()
    flash("Usuário excluído.", "sucesso")
    return redirect(url_for("main.listar_usuarios"))


@bp.route("/auditoria")
def auditoria():
    registros = Auditoria.query.order_by(Auditoria.criado_em.desc()).limit(500).all()
    return render_template("auditoria.html", registros=registros)


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
    venda.frete = _to_float(request.form.get("frete"))
    venda.frete_cortesia = request.form.get("frete_cortesia") == "on"
    venda.marketplace_pct = _to_float(request.form.get("marketplace_pct"))
    venda.desconto_total = _to_float(request.form.get("desconto_total"))
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
    # Tamanho pré-selecionado via ?tamanho= (opcional).
    tam_sel = (request.args.get("tamanho") or "").strip().upper()
    if tam_sel not in TAMANHOS:
        tam_sel = ""
    return render_template("etiqueta.html", peca=peca, tamanhos=TAMANHOS, tam_sel=tam_sel)


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


# --------------------------------------------------------------------------- #
# Cupons de desconto
# --------------------------------------------------------------------------- #
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
    return {
        "ok": True, "codigo": cupom.codigo, "tipo": cupom.tipo, "valor": cupom.valor,
        "rotulo": (f"{cupom.valor:g}%" if cupom.tipo == "percentual" else _brl(cupom.valor)),
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
    tipo = "valor" if request.form.get("tipo") == "valor" else "percentual"
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


# --------------------------------------------------------------------------- #
# Vales (crédito de loja: presente / troca)
# --------------------------------------------------------------------------- #
def _gerar_codigo_vale():
    import random
    import string
    while True:
        cod = "VL-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Vale.query.filter_by(codigo=cod).first():
            return cod


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


# --------------------------------------------------------------------------- #
# Devolução / troca (gera vale-crédito)
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Kits / combos
# --------------------------------------------------------------------------- #
@bp.route("/kits")
def listar_kits():
    kits = Kit.query.order_by(Kit.ativo.desc(), Kit.nome).all()
    pecas = Peca.query.order_by(Peca.nome).all()
    return render_template("kits.html", kits=kits, pecas=pecas)


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
