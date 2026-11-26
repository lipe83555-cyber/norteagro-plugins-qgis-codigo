# -*- coding: utf-8 -*-
"""Configurações do plugin (QgsSettings) e cofre de chaves (QgsAuthManager).

Chaves de API nunca ficam em QgsSettings nem em texto puro: vão para o gerenciador de
autenticação do QGIS (protegido pela senha mestra). Em QgsSettings fica só o id da
configuração de autenticação.
"""

import hashlib
import os
import re
import unicodedata

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

from .identidade import VARIAVEIS_RT

RAIZ = "norteagro_layout_ia"
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
LOGO_PADRAO = os.path.join(_ASSETS, "logo_norteagro.png")


def assinatura_padrao(nome_rt):
    """v0.32.7: o plugin não traz assinatura de ninguém; cada RT escolhe a sua em Configurações."""
    return ""


def logo():
    """Logo do cabeçalho da janela do plugin (a escolhida ou a do plugin)."""
    caminho = valor("logo", "") or ""
    return caminho if os.path.isfile(caminho) else LOGO_PADRAO


def logo_planta():
    """v0.32.7: logo que vai para as plantas: só a escolhida em Configurações (sem logo de fábrica)."""
    caminho = valor("logo", "") or ""
    return caminho if os.path.isfile(caminho) else ""
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


# ---------------------------------------------------------------- limpeza única (v0.32.7)
# Versões antigas traziam de fábrica o responsável técnico e a assinatura de uma pessoa do escritório. Quem salvou
# esses dados nas Configurações fica sem eles ao atualizar. A comparação é por hash, para o nome, o registro e a
# imagem não aparecerem no código.
_HASH_NOME_ANTIGO = "1c55bae8f4d3902489c31643c85de978b587d2821f59a4ea2862d5cb7e3ae010"
_HASH_REGISTRO_ANTIGO = "181dd15062a5b951179cb0b6304262d904c757eb8da3c3646a104e65b279ee28"
_HASH_ASSINATURA_ANTIGA = "7ff0bdec1ea5a98af6db66221189f18c5cf5d6fd055cebf7299fef088e5f76ff"
_CHAVE_LIMPEZA = "limpeza/rt_0_32_7"


def _hash_texto(t):
    t = "".join(c for c in unicodedata.normalize("NFD", str(t or "")) if unicodedata.category(c) != "Mn")
    return hashlib.sha256(re.sub(r"\s+", " ", t).strip().lower().encode("utf-8")).hexdigest()


def _hash_arquivo(caminho):
    try:
        with open(caminho, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""


def limpar_rt_antigo():
    """Roda uma vez por perfil do QGIS. Tira o RT e a assinatura que vinham de fábrica nas versões antigas.
    Devolve True se apagou alguma coisa (para avisar a pessoa)."""
    if valor(_CHAVE_LIMPEZA, False, bool):
        return False
    apagou = False
    nome = valor("rt/na_responsavel", "") or ""
    registro = re.sub(r"\D", "", str(valor("rt/na_crea", "") or ""))
    do_antigo = (bool(nome) and _hash_texto(nome) == _HASH_NOME_ANTIGO) or \
        (bool(registro) and hashlib.sha256(registro.encode("utf-8")).hexdigest() == _HASH_REGISTRO_ANTIGO)
    if do_antigo:
        for chave in ("rt/na_responsavel", "rt/na_crea"):
            _s().remove(f"{RAIZ}/{chave}")
        apagou = True
    ass = valor("rt/assinatura", "") or ""
    ass_antiga = bool(ass) and os.path.isfile(ass) and _hash_arquivo(ass) == _HASH_ASSINATURA_ANTIGA
    if ass and (ass_antiga or do_antigo):
        _s().remove(f"{RAIZ}/rt/assinatura")
        apagou = True
        pasta_dados = os.path.normcase(os.path.abspath(os.path.join(QgsApplication.qgisSettingsDirPath(), RAIZ)))
        # só apaga a cópia da assinatura antiga que fica na pasta de dados do próprio plugin
        if ass_antiga and os.path.normcase(os.path.dirname(os.path.abspath(ass))) == pasta_dados:
            try:
                os.remove(ass)
            except OSError:
                pass
    definir(_CHAVE_LIMPEZA, True)
    return apagou


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
