"""Envio de e-mail (Resend) e tokens de redefinição de senha.

O token é assinado (itsdangerous) com a SECRET_KEY e carrega o id do cliente +
carimbo de tempo — nada é gravado no banco. Expira sozinho.

HTTP fork-safe: usa ProxyHandler({}) para NÃO consultar o proxy do sistema no
macOS, que crasha o worker forkado do Gunicorn (mesmo motivo de _frete_opcoes).
"""
import hashlib
import json
import os
import urllib.request

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT_RESET = "reset-senha-v1"


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_SALT_RESET)


def _versao_senha(senha_hash):
    """'Versão' derivada do hash da senha: muda quando a senha muda, invalidando
    tokens de reset antigos (não são reutilizáveis após o uso). Passa por
    SHA-256 para não expor o hash no token — o payload do itsdangerous é
    legível (só assinado, não criptografado)."""
    return hashlib.sha256((senha_hash or "").encode()).hexdigest()[:16]


def gerar_token_reset(cliente):
    """Token assinado para redefinir a senha do cliente (id + versão da senha)."""
    return _serializer().dumps({"cid": int(cliente.id), "v": _versao_senha(cliente.senha_hash)})


def ler_token_reset(token, max_age=3600):
    """(cliente_id, versao) do token válido; (None, None) se inválido/expirado (1h)."""
    try:
        dados = _serializer().loads(token, max_age=max_age)
        return int(dados["cid"]), str(dados.get("v", ""))
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None, None


def token_confere_com(cliente, versao):
    """True se a versão do token bate com a senha ATUAL do cliente."""
    return bool(cliente) and versao == _versao_senha(cliente.senha_hash)


def enviar_email_async(destino, assunto, html):
    """Dispara o envio em uma thread — não bloqueia a requisição (ex.: checkout
    da vitrine não espera o Resend responder)."""
    import threading
    app = current_app._get_current_object()

    def _job():
        with app.app_context():
            enviar_email(destino, assunto, html)

    threading.Thread(target=_job, daemon=True).start()


def email_configurado():
    return bool(os.environ.get("RESEND_API_KEY", "").strip()
                and os.environ.get("MAIL_FROM", "").strip())


def enviar_email(destino, assunto, html):
    """Envia um e-mail via Resend. Retorna True se aceito. Nunca lança: registra
    warning e devolve False (o fluxo de 'esqueci a senha' não pode quebrar)."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    remetente = os.environ.get("MAIL_FROM", "").strip()
    if not api_key or not remetente:
        current_app.logger.warning("E-mail não enviado: RESEND_API_KEY/MAIL_FROM ausentes.")
        return False
    payload = {"from": remetente, "to": [destino], "subject": assunto, "html": html}
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}", "User-Agent": "cost-calculation"},
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=15) as resp:
            resp.read()
        return True
    except Exception as e:  # noqa: BLE001 - falha de envio não deve derrubar a requisição
        current_app.logger.warning("Falha ao enviar e-mail (Resend): %s", e)
        return False
