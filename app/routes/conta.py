"""Rotas: conta do cliente na vitrine pública (cadastro, login, preferências).

Sessão separada do ERP: usa `session['cliente_id']` (não mexe em `logado`/`admin`,
que são do console). Fica toda no `publico_bp` (raiz), fora da guarda de login do
blueprint `main`.
"""
import re
from functools import wraps

from flask import (
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..extensions import limiter
from ..models import Cliente, Venda, db
from . import publico_bp
from .helpers import _log

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email_valido(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))


def _cliente_logado():
    """Cliente da sessão da vitrine (ou None). Limpa sessão órfã."""
    cid = session.get("cliente_id")
    if not cid:
        return None
    cliente = Cliente.query.get(cid)
    if cliente is None:
        session.pop("cliente_id", None)
        session.pop("cliente_nome", None)
    return cliente


def _exigir_cliente(f):
    """Protege rotas da área do cliente: redireciona ao login se deslogado."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _cliente_logado():
            flash("Entre na sua conta para continuar.", "erro")
            return redirect(url_for("publico.conta_entrar", next=request.path))
        return f(*args, **kwargs)
    return wrapper


@publico_bp.app_context_processor
def _injetar_cliente_logado():
    """Disponibiliza `cliente_logado` nos templates públicos (estado do menu)."""
    try:
        return {"cliente_logado": _cliente_logado()}
    except Exception:  # noqa: BLE001 - nunca quebrar a vitrine por causa disto
        return {"cliente_logado": None}


def _ler_endereco(form, alvo, preservar=False):
    """Copia os campos de endereço do form para um Cliente.

    preservar=True: só grava os campos **preenchidos** — não apaga dados já
    existentes com valores em branco. Usado ao reivindicar um cadastro de balcão
    (feito no ERP): o cliente pode não redigitar o endereço, e não queremos zerar
    o que o ateliê já tinha.
    """
    campos = {
        "cep": form.get("cep", "").strip(),
        "logradouro": form.get("logradouro", "").strip(),
        "numero": form.get("numero", "").strip(),
        "complemento": form.get("complemento", "").strip(),
        "bairro": form.get("bairro", "").strip(),
        "cidade": form.get("cidade", "").strip(),
        "uf": form.get("uf", "").strip().upper()[:2],
    }
    for campo, valor in campos.items():
        if valor or not preservar:
            setattr(alvo, campo, valor)


# --------------------------------------------------------------------------- #
# Cadastro
# --------------------------------------------------------------------------- #
@publico_bp.route("/conta/cadastro", methods=["GET", "POST"])
@limiter.limit("20 per hour", methods=["POST"])
def conta_cadastro():
    if _cliente_logado():
        return redirect(url_for("publico.conta"))

    if request.method == "POST":
        form = request.form
        nome = form.get("nome", "").strip()
        email = Cliente.normalizar_email(form.get("email", ""))
        senha = form.get("senha", "")
        telefone = form.get("telefone", "").strip()

        erro = None
        if not nome:
            erro = "Informe seu nome."
        elif not _email_valido(email):
            erro = "Informe um e-mail válido."
        elif len(senha) < 6:
            erro = "A senha precisa ter ao menos 6 caracteres."
        elif len(re.sub(r"\D", "", telefone)) < 10:
            erro = "Informe um WhatsApp válido com DDD."

        # E-mail já existe: se aquele cliente ainda NÃO tem senha (cadastro só de
        # balcão, feito pelo ateliê), deixamos ele "reivindicar" a conta definindo
        # a senha agora. Se já tem senha, é conta de verdade: manda fazer login.
        existente = None if erro else Cliente.por_email(email)
        # Sem e-mail casado: tenta pelo WhatsApp, evitando duplicar um cadastro de
        # balcão (ERP) que não tinha e-mail. Se o WhatsApp já é de uma conta real,
        # manda fazer login (não cria segundo cadastro).
        if existente is None and not erro:
            por_zap = Cliente.por_whatsapp(telefone)
            if por_zap and por_zap.tem_conta:
                erro = "Já existe uma conta com esse WhatsApp. Faça login."
            elif por_zap:
                existente = por_zap
        if existente and existente.tem_conta:
            erro = "Já existe uma conta com esse e-mail. Faça login."
        if erro:
            flash(erro, "erro")
            return render_template("conta_cadastro.html", dados=form)

        if existente:                       # reivindica cadastro de balcão existente
            cliente = existente
            cliente.nome = nome
            cliente.email = email           # casado por WhatsApp pode não ter e-mail ainda
            cliente.telefone = telefone
            cliente.aceita_novidades = form.get("aceita_novidades") == "on"
            # preservar=True: não zera o endereço já cadastrado no ERP se o cliente
            # deixar os campos em branco no cadastro da vitrine.
            _ler_endereco(form, cliente, preservar=True)
            cliente.set_senha(senha)
            msg = f"Bem-vinda de volta, {cliente.nome}! Sua conta está pronta."
        else:
            cliente = Cliente(nome=nome, email=email, telefone=telefone,
                              aceita_novidades=form.get("aceita_novidades") == "on")
            cliente.set_senha(senha)
            _ler_endereco(form, cliente)
            db.session.add(cliente)
            msg = f"Bem-vinda, {cliente.nome}! Sua conta foi criada."
        db.session.commit()
        session["cliente_id"] = cliente.id
        session["cliente_nome"] = cliente.nome
        _log("cliente_cadastro", f"{cliente.nome} <{cliente.email}>")
        flash(msg, "sucesso")
        return redirect(request.args.get("next") or url_for("publico.conta"))

    return render_template("conta_cadastro.html", dados={})


# --------------------------------------------------------------------------- #
# Login / logout
# --------------------------------------------------------------------------- #
@publico_bp.route("/conta/entrar", methods=["GET", "POST"])
@limiter.limit("20 per hour", methods=["POST"])
def conta_entrar():
    if _cliente_logado():
        return redirect(url_for("publico.conta"))

    if request.method == "POST":
        email = request.form.get("email", "")
        senha = request.form.get("senha", "")
        cliente = Cliente.por_email(email)
        if cliente and cliente.tem_conta and cliente.conferir_senha(senha):
            session["cliente_id"] = cliente.id
            session["cliente_nome"] = cliente.nome
            _log("cliente_login", f"{cliente.nome} <{cliente.email}>")
            flash(f"Olá de novo, {cliente.nome}!", "sucesso")
            return redirect(request.args.get("next") or url_for("publico.conta"))
        flash("E-mail ou senha incorretos.", "erro")

    return render_template("conta_entrar.html", email=request.form.get("email", ""))


@publico_bp.route("/conta/sair")
def conta_sair():
    session.pop("cliente_id", None)
    session.pop("cliente_nome", None)
    flash("Você saiu da sua conta.", "sucesso")
    return redirect(url_for("publico.vitrine_publica"))


# --------------------------------------------------------------------------- #
# Área logada
# --------------------------------------------------------------------------- #
@publico_bp.route("/conta")
@_exigir_cliente
def conta():
    return redirect(url_for("publico.conta_pedidos"))


@publico_bp.route("/conta/pedidos")
@_exigir_cliente
def conta_pedidos():
    cliente = _cliente_logado()
    pedidos = (Venda.query.filter_by(cliente_id=cliente.id)
               .order_by(Venda.criado_em.desc()).all())
    return render_template("conta_pedidos.html", cliente=cliente, pedidos=pedidos)


@publico_bp.route("/conta/preferencias", methods=["GET", "POST"])
@_exigir_cliente
def conta_preferencias():
    cliente = _cliente_logado()

    if request.method == "POST":
        form = request.form
        nome = form.get("nome", "").strip()
        email = Cliente.normalizar_email(form.get("email", ""))
        telefone = form.get("telefone", "").strip()

        erro = None
        if not nome:
            erro = "Informe seu nome."
        elif not _email_valido(email):
            erro = "Informe um e-mail válido."
        else:
            outro = Cliente.por_email(email)
            if outro and outro.id != cliente.id:
                erro = "Esse e-mail já está em uso por outra conta."
        if erro:
            flash(erro, "erro")
            return render_template("conta_preferencias.html", cliente=cliente)

        cliente.nome = nome
        cliente.email = email
        cliente.telefone = telefone
        cliente.tamanho_habitual = form.get("tamanho_habitual", "").strip().upper()
        cliente.aceita_novidades = form.get("aceita_novidades") == "on"
        _ler_endereco(form, cliente)

        # Troca de senha (opcional): só se preencher a nova.
        nova = form.get("nova_senha", "")
        if nova:
            if len(nova) < 6:
                flash("A nova senha precisa ter ao menos 6 caracteres.", "erro")
                return render_template("conta_preferencias.html", cliente=cliente)
            cliente.set_senha(nova)

        session["cliente_nome"] = cliente.nome
        db.session.commit()
        _log("cliente_preferencias", f"{cliente.nome} <{cliente.email}>")
        flash("Preferências salvas.", "sucesso")
        return redirect(url_for("publico.conta_preferencias"))

    return render_template("conta_preferencias.html", cliente=cliente)
