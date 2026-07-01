"""Rotas da aplicação."""
import os
import uuid

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.utils import secure_filename

from .models import Insumo, MovimentoEstoque, Peca, PecaInsumo, db

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


def _registrar_movimento(insumo, tipo, quantidade, observacao=""):
    """Aplica um movimento de estoque e registra no histórico."""
    if tipo == "entrada":
        insumo.estoque += quantidade
    else:  # saida
        insumo.estoque -= quantidade
    db.session.add(
        MovimentoEstoque(insumo=insumo, tipo=tipo, quantidade=quantidade, observacao=observacao)
    )


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@bp.route("/")
def index():
    pecas = Peca.query.order_by(Peca.criado_em.desc()).all()
    insumos = Insumo.query.order_by(Insumo.nome).all()
    alertas = [i for i in insumos if i.estoque_baixo]
    return render_template("index.html", pecas=pecas, insumos=insumos, alertas=alertas)


# --------------------------------------------------------------------------- #
# Insumos (estoque)
# --------------------------------------------------------------------------- #
@bp.route("/insumos")
def listar_insumos():
    insumos = Insumo.query.order_by(Insumo.nome).all()
    return render_template("insumos.html", insumos=insumos)


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
        insumo.fornecedor = request.form.get("fornecedor", "").strip()
        # Estoque inicial só é definido na criação; depois é alterado por movimentos.
        if insumo_id is None:
            insumo.estoque = _to_float(request.form.get("estoque"))

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

    if tipo not in ("entrada", "saida") or quantidade <= 0:
        flash("Informe um tipo válido e uma quantidade maior que zero.", "erro")
        return redirect(url_for("main.listar_insumos"))

    if tipo == "saida" and quantidade > insumo.estoque:
        flash(f"Estoque insuficiente de '{insumo.nome}' (disponível: {insumo.estoque}).", "erro")
        return redirect(url_for("main.listar_insumos"))

    _registrar_movimento(insumo, tipo, quantidade, observacao)
    db.session.commit()
    flash(f"Movimento de estoque registrado para '{insumo.nome}'.", "sucesso")
    return redirect(url_for("main.listar_insumos"))


# --------------------------------------------------------------------------- #
# Peças
# --------------------------------------------------------------------------- #
@bp.route("/pecas")
def listar_pecas():
    pecas = Peca.query.order_by(Peca.criado_em.desc()).all()
    return render_template("pecas.html", pecas=pecas)


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

        # Na criação: lê os insumos selecionados e o nº de peças a produzir.
        linhas = []          # [(insumo, qtd_por_peca), ...]
        num_pecas = 1
        if is_nova:
            num_pecas = _to_float(request.form.get("quantidade_pecas"), padrao=1) or 1
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

            # Valida estoque ANTES de gravar qualquer coisa.
            faltando = [
                f"{ins.nome} (precisa {qtd * num_pecas:g}, tem {ins.estoque:g} {ins.unidade})"
                for ins, qtd in linhas
                if qtd * num_pecas > ins.estoque
            ]
            if faltando:
                flash("Estoque insuficiente para produzir: " + "; ".join(faltando), "erro")
                return render_template("peca_form.html", peca=peca, insumos=insumos)

        if peca is None:
            peca = Peca()
            db.session.add(peca)

        peca.nome = nome
        peca.descricao = request.form.get("descricao", "").strip()
        peca.custo_mao_de_obra = _to_float(request.form.get("custo_mao_de_obra"))
        peca.custos_extras = _to_float(request.form.get("custos_extras"))
        peca.margem_percentual = _to_float(request.form.get("margem_percentual"))

        # Foto (opcional).
        nova_foto = _salvar_foto(request.files.get("foto"))
        if nova_foto:
            _remover_foto(peca.foto)
            peca.foto = nova_foto

        # Na criação: monta a ficha técnica e dá baixa no estoque (qtd × nº peças).
        if is_nova and linhas:
            for insumo, qtd in linhas:
                db.session.add(PecaInsumo(peca=peca, insumo=insumo, quantidade=qtd))
                _registrar_movimento(
                    insumo, "saida", qtd * num_pecas,
                    observacao=f"Produção inicial de {num_pecas:g}x '{peca.nome}'",
                )

        db.session.commit()
        if is_nova and linhas:
            flash(
                f"Peça criada. Produzidas {num_pecas:g} unidade(s) e estoque de "
                f"{len(linhas)} insumo(s) baixado.", "sucesso",
            )
        else:
            flash("Peça salva.", "sucesso")
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
    db.session.delete(peca)
    db.session.commit()
    flash("Peça excluída.", "sucesso")
    return redirect(url_for("main.listar_pecas"))


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
    """Baixa do estoque os insumos necessários para produzir N unidades da peça."""
    peca = Peca.query.get_or_404(peca_id)
    unidades = _to_float(request.form.get("unidades"), padrao=1) or 1

    if not peca.insumos:
        flash("Adicione insumos à ficha técnica antes de produzir.", "erro")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))

    # Verifica se há estoque suficiente para todos os insumos.
    faltando = [
        item.insumo.nome
        for item in peca.insumos
        if item.quantidade * unidades > item.insumo.estoque
    ]
    if faltando:
        flash("Estoque insuficiente para: " + ", ".join(faltando), "erro")
        return redirect(url_for("main.detalhe_peca", peca_id=peca.id))

    for item in peca.insumos:
        _registrar_movimento(
            item.insumo,
            "saida",
            item.quantidade * unidades,
            observacao=f"Produção de {unidades:g}x '{peca.nome}'",
        )
    db.session.commit()
    flash(f"Produção registrada: {unidades:g} unidade(s) de '{peca.nome}'. Estoque atualizado.", "sucesso")
    return redirect(url_for("main.detalhe_peca", peca_id=peca.id))
