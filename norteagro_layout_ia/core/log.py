# -*- coding: utf-8 -*-
"""Registro de mensagens do plugin.

Dentro do QGIS as mensagens vão para o painel "Mensagens de log", aba
"NorteAgro Layout". Fora do QGIS (testes) vão para a saída padrão.
"""

TAG = "NorteAgro Layout"

try:  # pragma: no cover - depende do QGIS
    from qgis.core import QgsMessageLog
    from . import compat

    _NIVEIS = {
        "info": compat.MSG_INFO,
        "aviso": compat.MSG_AVISO,
        "erro": compat.MSG_CRITICO,
        "ok": compat.MSG_SUCESSO,
    }

    def registrar(texto, nivel="info"):
        QgsMessageLog.logMessage(str(texto), TAG, _NIVEIS.get(nivel, compat.MSG_INFO))

except Exception:  # pragma: no cover - fora do QGIS
    def registrar(texto, nivel="info"):
        print(f"[{TAG}][{nivel}] {texto}")


def info(texto):
    registrar(texto, "info")


def aviso(texto):
    registrar(texto, "aviso")


def erro(texto):
    registrar(texto, "erro")


def ok(texto):
    registrar(texto, "ok")
