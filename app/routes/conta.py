"""Rotas: conta do cliente na vitrine pública (cadastro, login, preferências).

Sessão separada do ERP: usa `session['cliente_id']` (não mexe em `logado`/`admin`,
que são do console). Fica toda no `publico_bp` (raiz), fora da guarda de login do
blueprint `main`.
"""
import re
from datetime import datetime
from functools import wraps

from flask import (
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..emails import enviar_email, gerar_token_reset, ler_token_reset
from ..extensions import limiter
from ..models import Cliente, Endereco, Parametro, Venda, cpf_valido, db
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
    """Disponibiliza `cliente_logado` e `whatsapp` nos templates públicos."""
    try:
        return {"cliente_logado": _cliente_logado(), "whatsapp": Parametro.obter("whatsapp", "")}
    except Exception:  # noqa: BLE001 - nunca quebrar a vitrine por causa disto
        return {"cliente_logado": None, "whatsapp": ""}


def _confere_identidade(existente, email, telefone):
    """Para reivindicar um cadastro que já existe, os dados JÁ registrados nele
    (e-mail e/ou WhatsApp) precisam bater com os informados. Campos ausentes no
    registro não bloqueiam (serão preenchidos agora). Isso fecha o buraco de
    reivindicar a conta de alguém sabendo só o e-mail (ou só o telefone) quando o
    outro dado já está no cadastro. (OTP por WhatsApp seria a proteção definitiva.)"""
    if existente.email and Cliente.normalizar_email(existente.email) != Cliente.normalizar_email(email):
        return False
    if existente.telefone and Cliente.normalizar_whatsapp(existente.telefone) != Cliente.normalizar_whatsapp(telefone):
        return False
    return True


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
        # Só deixa reivindicar um cadastro pré-existente se os dados conferem.
        if existente and not erro and not _confere_identidade(existente, email, telefone):
            erro = ("Já existe um cadastro com esses dados, mas eles não conferem. "
                    "Fale com o ateliê pelo WhatsApp para ativar sua conta.")
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


@publico_bp.route("/conta/esqueci", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def conta_esqueci():
    """Envia um link de redefinição de senha por e-mail. Resposta sempre genérica
    (não revela quais e-mails têm conta)."""
    if request.method == "POST":
        email = Cliente.normalizar_email(request.form.get("email", ""))
        cliente = Cliente.por_email(email) if email else None
        if cliente and cliente.tem_conta:
            token = gerar_token_reset(cliente.id)
            link = url_for("publico.conta_redefinir", token=token, _external=True)
            html = render_template("email_reset.html", cliente=cliente, link=link)
            enviar_email(cliente.email, "Redefinir sua senha · Sabrina Hansen Atelier", html)
            _log("cliente_reset_solicitado", f"#{cliente.id} ({cliente.nome})")
        flash("Se este e-mail tiver conta, enviamos um link para redefinir a senha.", "sucesso")
        return redirect(url_for("publico.conta_entrar"))
    return render_template("conta_esqueci.html")


@publico_bp.route("/conta/redefinir/<token>", methods=["GET", "POST"])
@limiter.limit("20 per hour")
def conta_redefinir(token):
    cid = ler_token_reset(token)
    cliente = Cliente.query.get(cid) if cid else None
    if cliente is None or not cliente.tem_conta:
        flash("Link inválido ou expirado. Peça um novo.", "erro")
        return redirect(url_for("publico.conta_esqueci"))
    if request.method == "POST":
        senha = request.form.get("senha", "")
        if len(senha) < 6:
            flash("A senha precisa ter ao menos 6 caracteres.", "erro")
            return render_template("conta_redefinir.html", token=token)
        cliente.set_senha(senha)
        db.session.commit()
        _log("cliente_reset_concluido", f"#{cliente.id} ({cliente.nome})")
        session["cliente_id"] = cliente.id
        session["cliente_nome"] = cliente.nome
        flash("Senha redefinida! Você já está logada.", "sucesso")
        return redirect(url_for("publico.conta"))
    return render_template("conta_redefinir.html", token=token)


@publico_bp.route("/conta/sair")
def conta_sair():
    session.pop("cliente_id", None)
    session.pop("cliente_nome", None)
    # Sem flash: o destino é a vitrine (cacheada, não renderiza flash), então a
    # mensagem ficaria "presa" na sessão e apareceria empilhada na página seguinte.
    # O próprio menu já mostra "Entrar/Criar conta" = logout evidente.
    return redirect(url_for("publico.vitrine_publica"))


# --------------------------------------------------------------------------- #
# Área logada
# --------------------------------------------------------------------------- #
@publico_bp.route("/conta")
@_exigir_cliente
def conta():
    return redirect(url_for("publico.conta_pedidos"))


@publico_bp.route("/conta/painel")
@_exigir_cliente
def conta_painel():
    """Painel 'Minha conta' (estilo marketplace) — atalhos para pedidos, favoritos,
    dados e endereços. Aberto pelo 'Início' do menu da conta na Vitrine V2."""
    return render_template("conta_painel.html", whatsapp=Parametro.obter("whatsapp", ""))


@publico_bp.route("/conta/vales")
@_exigir_cliente
def conta_vales():
    """Vales de crédito do cliente (gerados em devoluções/trocas)."""
    from ..models import Vale
    cliente = _cliente_logado()
    vales = (Vale.query.filter_by(cliente_id=cliente.id)
             .order_by(Vale.criado_em.desc()).all())
    return render_template("conta_vales.html", cliente=cliente, vales=vales)


@publico_bp.route("/conta/senha", methods=["POST"])
@_exigir_cliente
def conta_alterar_senha():
    """Troca de senha: exige a senha atual + nova + confirmação."""
    cliente = _cliente_logado()
    atual = request.form.get("senha_atual", "")
    nova = request.form.get("nova_senha", "")
    conf = request.form.get("confirmar_senha", "")
    if not cliente.conferir_senha(atual):
        flash("Senha atual incorreta.", "erro")
    elif len(nova) < 6:
        flash("A nova senha precisa ter ao menos 6 caracteres.", "erro")
    elif nova != conf:
        flash("A confirmação não confere com a nova senha.", "erro")
    else:
        cliente.set_senha(nova)
        db.session.commit()
        _log("cliente_senha_trocada", f"#{cliente.id}")
        flash("Senha alterada com sucesso.", "sucesso")
    return redirect(url_for("publico.conta_preferencias"))


@publico_bp.route("/conta/favoritos")
@_exigir_cliente
def conta_favoritos():
    """Página 'Meus favoritos' (grade). Os itens vêm do localStorage e os dados
    atuais das peças são buscados em /publico/pecas."""
    return render_template("conta_favoritos.html", cliente=_cliente_logado())


@publico_bp.route("/conta/cartoes")
@_exigir_cliente
def conta_cartoes():
    """Meus cartões — reservado para quando houver pagamento online."""
    return render_template("conta_cartoes.html", cliente=_cliente_logado())


# --------------------------------------------------------------------------- #
# Meus endereços (múltiplos, com um principal)
# --------------------------------------------------------------------------- #
def _definir_principal(cliente, end):
    """Marca `end` como o único endereço principal (entrega) do cliente."""
    for e in cliente.enderecos:
        e.principal = (e.id == end.id)
    end.principal = True


def _definir_cobranca(cliente, end):
    """Marca `end` como o único endereço de cobrança do cliente."""
    for e in cliente.enderecos:
        e.cobranca = (e.id == end.id)
    end.cobranca = True


def _sincronizar_principal(cliente):
    """Copia o endereço principal para os campos de endereço do Cliente — o
    checkout e as preferências continuam usando esses campos."""
    princ = next((e for e in cliente.enderecos if e.principal), None)
    if not princ:
        return
    for campo in ("cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf"):
        setattr(cliente, campo, getattr(princ, campo))


@publico_bp.route("/conta/enderecos")
@_exigir_cliente
def conta_enderecos():
    cliente = _cliente_logado()
    editar = request.args.get("editar", type=int)
    em_edicao = Endereco.query.filter_by(id=editar, cliente_id=cliente.id).first() if editar else None
    return render_template("conta_enderecos.html", cliente=cliente,
                           enderecos=cliente.enderecos, em_edicao=em_edicao)


@publico_bp.route("/conta/enderecos/salvar", methods=["POST"])
@_exigir_cliente
def conta_endereco_salvar():
    cliente = _cliente_logado()
    form = request.form
    eid = form.get("id", type=int)
    if eid:
        end = Endereco.query.filter_by(id=eid, cliente_id=cliente.id).first_or_404()
    else:
        end = Endereco(cliente_id=cliente.id)
        db.session.add(end)
    end.apelido = form.get("apelido", "").strip()
    end.destinatario = form.get("destinatario", "").strip() or cliente.nome
    end.cep = form.get("cep", "").strip()
    end.logradouro = form.get("logradouro", "").strip()
    end.numero = form.get("numero", "").strip()
    end.complemento = form.get("complemento", "").strip()
    end.bairro = form.get("bairro", "").strip()
    end.cidade = form.get("cidade", "").strip()
    end.uf = form.get("uf", "").strip().upper()[:2]
    db.session.flush()
    # Primeiro endereço → vira principal e cobrança. Senão respeita os checkboxes.
    primeiro = Endereco.query.filter_by(cliente_id=cliente.id).count() == 1
    if form.get("principal") == "on" or primeiro:
        _definir_principal(cliente, end)
    if form.get("cobranca") == "on" or primeiro:
        _definir_cobranca(cliente, end)
    _sincronizar_principal(cliente)
    db.session.commit()
    _log("cliente_endereco", f"#{cliente.id}: endereço salvo (#{end.id})")
    flash("Endereço salvo.", "sucesso")
    return redirect(url_for("publico.conta_enderecos"))


@publico_bp.route("/conta/enderecos/<int:end_id>/principal", methods=["POST"])
@_exigir_cliente
def conta_endereco_principal(end_id):
    cliente = _cliente_logado()
    end = Endereco.query.filter_by(id=end_id, cliente_id=cliente.id).first_or_404()
    _definir_principal(cliente, end)
    _sincronizar_principal(cliente)
    db.session.commit()
    flash("Endereço principal atualizado.", "sucesso")
    return redirect(url_for("publico.conta_enderecos"))


@publico_bp.route("/conta/enderecos/<int:end_id>/cobranca", methods=["POST"])
@_exigir_cliente
def conta_endereco_cobranca(end_id):
    cliente = _cliente_logado()
    end = Endereco.query.filter_by(id=end_id, cliente_id=cliente.id).first_or_404()
    _definir_cobranca(cliente, end)
    db.session.commit()
    flash("Endereço de cobrança atualizado.", "sucesso")
    return redirect(url_for("publico.conta_enderecos"))


@publico_bp.route("/conta/enderecos/<int:end_id>/excluir", methods=["POST"])
@_exigir_cliente
def conta_endereco_excluir(end_id):
    cliente = _cliente_logado()
    end = Endereco.query.filter_by(id=end_id, cliente_id=cliente.id).first_or_404()
    era_principal, era_cobranca = end.principal, end.cobranca
    db.session.delete(end)
    db.session.flush()
    # Se apagou um papel, promove o primeiro restante para não ficar sem.
    resto = Endereco.query.filter_by(cliente_id=cliente.id).order_by(Endereco.id).first()
    if resto:
        if era_principal:
            _definir_principal(cliente, resto)
        if era_cobranca:
            _definir_cobranca(cliente, resto)
    _sincronizar_principal(cliente)
    db.session.commit()
    flash("Endereço excluído.", "sucesso")
    return redirect(url_for("publico.conta_enderecos"))


@publico_bp.route("/conta/pedidos")
@_exigir_cliente
def conta_pedidos():
    cliente = _cliente_logado()
    pedidos = (Venda.query.filter_by(cliente_id=cliente.id)
               .order_by(Venda.criado_em.desc()).all())
    return render_template("conta_pedidos.html", cliente=cliente, pedidos=pedidos)


@publico_bp.route("/conta/pedidos/<int:venda_id>")
@_exigir_cliente
def conta_pedido_detalhe(venda_id):
    cliente = _cliente_logado()
    venda = Venda.query.filter_by(id=venda_id, cliente_id=cliente.id).first_or_404()
    return render_template("conta_pedido_detalhe.html", cliente=cliente, venda=venda)


@publico_bp.route("/conta/pedidos/<int:venda_id>/recibo")
@_exigir_cliente
def conta_pedido_recibo(venda_id):
    """Recibo do próprio pedido do cliente (mesmo template do ERP)."""
    cliente = _cliente_logado()
    venda = Venda.query.filter_by(id=venda_id, cliente_id=cliente.id).first_or_404()
    return render_template("recibo.html", venda=venda)


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
        cpf = re.sub(r"\D", "", form.get("cpf", ""))
        if not erro and not cpf_valido(cpf):
            erro = "CPF inválido."
        if erro:
            flash(erro, "erro")
            return render_template("conta_preferencias.html", cliente=cliente, editar=True)

        cliente.nome = nome
        cliente.email = email
        cliente.telefone = telefone
        cliente.genero = form.get("genero", "").strip()
        cliente.cpf = cpf
        nasc = form.get("nascimento", "").strip()
        try:
            cliente.nascimento = datetime.strptime(nasc, "%Y-%m-%d").date() if nasc else None
        except ValueError:
            pass   # data inválida: mantém a atual
        cliente.tamanho_habitual = form.get("tamanho_habitual", "").strip().upper()
        cliente.aceita_novidades = form.get("aceita_novidades") == "on"
        # Endereço agora é gerido em "Meus endereços" — não é mexido aqui.

        # Troca de senha (opcional): só se preencher a nova.
        nova = form.get("nova_senha", "")
        if nova:
            if len(nova) < 6:
                flash("A nova senha precisa ter ao menos 6 caracteres.", "erro")
                return render_template("conta_preferencias.html", cliente=cliente, editar=True)
            cliente.set_senha(nova)

        session["cliente_nome"] = cliente.nome
        db.session.commit()
        _log("cliente_preferencias", f"{cliente.nome} <{cliente.email}>")
        flash("Informações salvas.", "sucesso")
        return redirect(url_for("publico.conta_preferencias"))

    return render_template("conta_preferencias.html", cliente=cliente,
                           editar=bool(request.args.get("editar")))
