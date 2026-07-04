"""Pacote de rotas. Mantém o blueprint único 'main'."""
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

bp = Blueprint("main", __name__)

# Endpoints acessíveis sem login (público / estáticos).
_PUBLICOS = {"main.login", "main.vitrine_publica", "main.health", "static"}


@bp.before_app_request
def _exigir_login():
    if request.endpoint in _PUBLICOS:
        return None
    if not session.get("logado"):
        return redirect(url_for("main.login", next=request.path))
    return None


# Reexporta helpers para compatibilidade (ex.: testes usam app.routes._pix_payload).
# Importa os módulos de rota para registrá-los no blueprint.
from . import catalogo, clientes, estoque, financeiro, sistema, vendas  # noqa: E402,F401
from .helpers import *  # noqa: E402,F401,F403
