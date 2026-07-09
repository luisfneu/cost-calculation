"""Envio de e-mail (Resend) e tokens de redefinição de senha.

O token é assinado (itsdangerous) com a SECRET_KEY e carrega o id do cliente +
carimbo de tempo — nada é gravado no banco. Expira sozinho.

HTTP fork-safe: usa ProxyHandler({}) para NÃO consultar o proxy do sistema no
macOS, que crasha o worker forkado do Gunicorn (mesmo motivo de _frete_opcoes).
"""
import json
import os
import urllib.request

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT_RESET = "reset-senha-v1"


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_SALT_RESET)


def gerar_token_reset(cliente_id):
    """Token assinado para redefinir a senha do cliente."""
    return _serializer().dumps({"cid": int(cliente_id)})


def ler_token_reset(token, max_age=3600):
    """cliente_id do token válido; None se inválido/adulterado/expirado (1h)."""
    try:
        dados = _serializer().loads(token, max_age=max_age)
        return int(dados["cid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None


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
