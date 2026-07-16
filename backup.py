"""Backup consistente do banco + fotos.

Uso:
    python backup.py

Gera em ./backups/<data-hora>/ :
  - costcalc.db  (cópia íntegra via API .backup do SQLite; segura mesmo com o
    app rodando e com WAL ligado)
  - uploads.zip  (todas as fotos)

Mantém os últimos BACKUP_MANTER backups (padrão 14) e apaga os mais antigos.
Se BACKUP_OFFSITE_DIR estiver definido no .env, copia cada backup também para
lá (ex.: pasta do iCloud Drive / disco externo) — backup no mesmo disco do
banco não protege contra falha do disco.
Agende com cron/launchd (ver DEPLOY.md) para rodar diariamente.
"""
import datetime
import glob
import os
import shutil
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))

try:  # lê o .env (BACKUP_MANTER / BACKUP_OFFSITE_DIR) mesmo rodando via cron
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, ".env"))
except ImportError:
    pass

DB = os.path.join(BASE, "instance", "costcalc.db")
UPLOADS = os.path.join(BASE, "app", "static", "uploads")
DEST = os.path.join(BASE, "backups")
MANTER = int(os.environ.get("BACKUP_MANTER", "14"))
OFFSITE = os.path.expanduser(os.environ.get("BACKUP_OFFSITE_DIR", "").strip())


def main():
    if not os.path.exists(DB):
        print("Banco não encontrado:", DB)
        return
    os.makedirs(DEST, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    pasta = os.path.join(DEST, stamp)
    os.makedirs(pasta, exist_ok=True)

    # 1) Banco: snapshot íntegro (a API .backup lida com transações/WAL).
    origem = sqlite3.connect(DB)
    destino = sqlite3.connect(os.path.join(pasta, "costcalc.db"))
    with destino:
        origem.backup(destino)
    origem.close()
    destino.close()

    # 2) Fotos.
    if os.path.isdir(UPLOADS) and os.listdir(UPLOADS):
        shutil.make_archive(os.path.join(pasta, "uploads"), "zip", UPLOADS)

    # 3) Rotação: mantém apenas os últimos MANTER.
    antigos = sorted(glob.glob(os.path.join(DEST, "*")))
    for velho in antigos[:-MANTER] if MANTER > 0 else []:
        shutil.rmtree(velho, ignore_errors=True)

    # 4) Cópia offsite (outro disco/iCloud), com a mesma rotação.
    if OFFSITE:
        try:
            os.makedirs(OFFSITE, exist_ok=True)
            shutil.copytree(pasta, os.path.join(OFFSITE, stamp), dirs_exist_ok=True)
            antigos_off = sorted(glob.glob(os.path.join(OFFSITE, "*")))
            for velho in antigos_off[:-MANTER] if MANTER > 0 else []:
                shutil.rmtree(velho, ignore_errors=True)
            print("Cópia offsite:", os.path.join(OFFSITE, stamp))
        except OSError as exc:
            print("AVISO: cópia offsite falhou:", exc)

    print("Backup concluído:", pasta)


if __name__ == "__main__":
    main()
