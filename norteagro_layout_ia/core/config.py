# -*- coding: utf-8 -*-
"""Configurações do plugin (QgsSettings) e cofre de chaves (QgsAuthManager).

Chaves de API nunca ficam em QgsSettings nem em texto puro: vão para o gerenciador de
autenticação do QGIS (protegido pela senha mestra). Em QgsSettings fica só o id da
configuração de autenticação.
"""

import os

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

from .identidade import VARIAVEIS_RT

RAIZ = "norteagro_layout_ia"
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
ASSINATURA_RAMON = os.path.join(_ASSETS, "assinatura_rt.png")
LOGO_PADRAO = os.path.join(_ASSETS, "logo_norteagro.png")


def assinatura_padrao(nome_rt):
    """A assinatura que acompanha o plugin é do Ramon: só entra sozinha quando ele é o RT do perfil."""
    if "ramon" in (nome_rt or "").lower() and os.path.isfile(ASSINATURA_RAMON):
        return ASSINATURA_RAMON
    return ""


def logo():
    caminho = valor("logo", "") or ""
    return caminho if os.path.isfile(caminho) else LOGO_PADRAO
FONTE_PADRAO = "Google Earth, SICAR"


def _s():
    return QgsSettings()


def valor(chave, padrao=None, tipo=None):
    v = _s().value(f"{RAIZ}/{chave}", padrao)
    if tipo is bool:
        return v in (True, "true", "True", 1, "1")
    if tipo is int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return padrao
    if tipo is float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return padrao
    return v


def definir(chave, v):
    _s().setValue(f"{RAIZ}/{chave}", v)


# ---------------------------------------------------------------- responsável técnico
def perfil_rt():
    """Perfil do responsável técnico salvo nas configurações (padrão do escritório)."""
    perfil = {}
    for var, _rot, padrao in VARIAVEIS_RT:
        perfil[var] = valor(f"rt/{var}", padrao)
    caminho = valor("rt/assinatura", "") or ""
    perfil["assinatura"] = caminho if os.path.isfile(caminho) else assinatura_padrao(perfil.get("na_responsavel"))
    return perfil


def salvar_perfil_rt(perfil):
    for var, _rot, _p in VARIAVEIS_RT:
        if var in perfil:
            definir(f"rt/{var}", perfil[var])
    if "assinatura" in perfil:
        definir("rt/assinatura", perfil["assinatura"])


# ---------------------------------------------------------------- elaboração e fontes
def historico_elaboracao():
    v = valor("elaboracao/historico", [])
    if isinstance(v, str):
        v = [v] if v else []
    return [x for x in (v or []) if x]


def lembrar_elaboracao(nome):
    nome = (nome or "").strip()
    if not nome:
        return
    hist = [nome] + [x for x in historico_elaboracao() if x != nome]
    definir("elaboracao/historico", hist[:15])


def fontes_extras_usadas():
    v = valor("fontes/extras", [])
    if isinstance(v, str):
        v = [v] if v else []
    return [x for x in (v or []) if x]


def lembrar_fontes(fontes):
    extras = [f for f in fontes if f and f != FONTE_PADRAO]
    hist = extras + [x for x in fontes_extras_usadas() if x not in extras]
    definir("fontes/extras", hist[:20])


# ---------------------------------------------------------------- chaves de API
def salvar_chave(provedor, chave):
    """Guarda a chave no gerenciador de autenticação do QGIS. Retorna (ok, mensagem)."""
    am = QgsApplication.authManager()
    if am.isDisabled():
        return False, "O gerenciador de autenticação do QGIS está desativado nesta instalação."
    if not am.masterPasswordIsSet():
        if not am.setMasterPassword(True):
            return False, "Defina a senha mestra do QGIS para guardar a chave com segurança."
    cfg = QgsAuthMethodConfig("Basic")
    cfg.setName(f"NorteAgro Layout IA - {provedor}")
    cfg.setConfig("username", provedor)
    cfg.setConfig("password", chave)
    antigo = valor(f"ia/{provedor}/authcfg", "")
    if antigo:
        cfg.setId(antigo)
        ok = am.updateAuthenticationConfig(cfg)
    else:
        res = am.storeAuthenticationConfig(cfg)
        ok = res[0] if isinstance(res, tuple) else bool(res)
        if isinstance(res, tuple) and len(res) > 1 and hasattr(res[1], "id"):
            cfg = res[1]
    if not ok or not cfg.id():
        return False, "Não foi possível guardar a chave no cofre do QGIS."
    definir(f"ia/{provedor}/authcfg", cfg.id())
    return True, "Chave guardada no gerenciador de autenticação do QGIS."


def ler_chave(provedor):
    authcfg = valor(f"ia/{provedor}/authcfg", "")
    if not authcfg:
        return None
    am = QgsApplication.authManager()
    cfg = QgsAuthMethodConfig()
    ok = am.loadAuthenticationConfig(authcfg, cfg, True)
    if isinstance(ok, tuple):
        ok, cfg = ok[0], ok[1] if len(ok) > 1 else cfg
    if not ok:
        return None
    return cfg.config("password") or None


def apagar_chave(provedor):
    authcfg = valor(f"ia/{provedor}/authcfg", "")
    if authcfg:
        QgsApplication.authManager().removeAuthenticationConfig(authcfg)
    definir(f"ia/{provedor}/authcfg", "")
