# -*- coding: utf-8 -*-
"""Repositório de plugins da Norte Agro no QGIS. Este arquivo é IGUAL nos três plugins.

Ao carregar, o plugin cadastra no QGIS o repositório da Norte Agro (endereço em repositorio_url.txt, gravado pelo
script 03_TESTES_E_FERRAMENTAS/publicar_repositorio.py). Com o repositório cadastrado:
* Complementos > Gerenciar e instalar complementos > Todos: os plugins da Norte Agro aparecem pelo nome;
* ao abrir o QGIS ele confere o repositório e avisa "Há uma atualização..."; a pessoa clica em Atualizar.

Repositório PRIVADO (linha "privado=1" em repositorio_url.txt): o GitHub só entrega os arquivos com uma chave de
leitura (token). Enquanto ela não estiver configurada, aparece na barra do QGIS o aviso "Configurar acesso"; a pessoa
cola a chave UMA vez, ela fica guardada no cofre de autenticação do QGIS (protegido pela senha mestra) e é testada
na hora. A chave nunca fica no plugin. Uma vez por dia, ao abrir o QGIS, a chave é conferida em segundo plano: se o
GitHub recusar (chave vencida ou cancelada), o aviso volta para a pessoa colar a chave nova. Sem internet, não avisa.
Sem repositorio_url.txt (ou vazio) não faz nada. Se a pessoa desligar o repositório no QGIS, ele continua desligado.
"""
import os

NOME = "Norte Agro Projetos"
ARQUIVO_URL = "repositorio_url.txt"
GRUPO = "app/plugin_repositories"
NOME_CHAVE = "Norte Agro - acesso aos plugins (GitHub)"
_AVISO = "naAvisoAcessoRepositorio"
_ULTIMA_CONFERENCIA = "norteagro/repositorio/ultima_conferencia"   # uma conferência por dia (data AAAA-MM-DD)


def _ler_config():
    """{"url": endereço do plugins.xml, "privado": bool}."""
    url, privado = "", False
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ARQUIVO_URL), encoding="utf-8") as fp:
            for linha in fp:
                linha = linha.strip()
                if not linha or linha.startswith("#"):
                    continue
                if linha.lower().replace(" ", "") in ("privado=1", "privado=true", "privado=sim"):
                    privado = True
                elif not url:
                    url = linha
    except Exception:
        pass
    return {"url": url, "privado": privado}


def url_repositorio():
    """Endereço do plugins.xml da Norte Agro ('' se não houver)."""
    return _ler_config()["url"]


def _chave_repositorio(url):
    """Nome com que o repositório está cadastrado no QGIS (a pessoa pode ter renomeado) ou None."""
    from qgis.core import QgsSettings
    s = QgsSettings()
    s.beginGroup(GRUPO)
    try:
        for k in s.childGroups():
            if s.value(k + "/url", "", type=str) == url:
                return k
    finally:
        s.endGroup()
    return None


def registrar_repositorio():
    """Cadastra (ou atualiza o endereço do) repositório da Norte Agro no QGIS. True se ficou cadastrado."""
    url = url_repositorio()
    if not url:
        return False
    try:
        from qgis.core import QgsSettings
        if _chave_repositorio(url):   # já cadastrado (talvez com outro nome): não mexe
            return True
        s = QgsSettings()
        s.setValue(f"{GRUPO}/{NOME}/url", url)   # novo, ou o mesmo nome com endereço antigo
        if s.value(f"{GRUPO}/{NOME}/enabled") is None:
            s.setValue(f"{GRUPO}/{NOME}/enabled", True)
        if s.value(f"{GRUPO}/{NOME}/authcfg") is None:
            s.setValue(f"{GRUPO}/{NOME}/authcfg", "")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- repositório privado: chave de leitura
def acesso_configurado():
    """True se o repositório é público ou se já tem uma chave guardada no QGIS."""
    cfg = _ler_config()
    if not cfg["url"] or not cfg["privado"]:
        return True
    try:
        from qgis.core import QgsApplication, QgsSettings
        chave = _chave_repositorio(cfg["url"]) or NOME
        authcfg = QgsSettings().value(f"{GRUPO}/{chave}/authcfg", "", type=str)
        return bool(authcfg) and authcfg in QgsApplication.authManager().configIds()
    except Exception:
        return False


TEXTO_SEM_CHAVE = "Para receber as atualizações dos plugins, configure o acesso (só uma vez)."
TEXTO_CHAVE_RECUSADA = ("A chave de acesso às atualizações dos plugins não funciona mais (venceu ou foi cancelada). "
                        "Peça a chave nova ao responsável e configure o acesso.")
_CONFERENCIA = []   # mantém a conferência viva até a resposta chegar


def avisar_se_precisa_acesso(iface):
    """Uma vez por sessão (mesmo com os três plugins): sem chave, mostra o aviso; com chave, confere em segundo plano
    se o GitHub ainda a aceita e mostra o aviso se não aceitar."""
    try:
        from qgis.PyQt.QtCore import QCoreApplication, QTimer
        cfg = _ler_config()
        app = QCoreApplication.instance()
        if app is None or app.property(_AVISO) or not cfg["url"] or not cfg["privado"]:
            return
        app.setProperty(_AVISO, True)
        if not _repositorio_ligado(cfg["url"]):
            return   # a pessoa desligou o repositório no QGIS: não incomoda
        if not acesso_configurado():
            QTimer.singleShot(4000, lambda: _mostrar_aviso(iface))   # depois que o QGIS terminar de abrir
        elif _conferir_hoje():
            QTimer.singleShot(8000, lambda: _conferir_chave(iface))
    except Exception:
        pass


def _repositorio_ligado(url):
    from qgis.core import QgsSettings
    chave = _chave_repositorio(url) or NOME
    return QgsSettings().value(f"{GRUPO}/{chave}/enabled", True, type=bool)


def _conferir_hoje():
    """True uma vez por dia (a conferência destrava o cofre do QGIS e pode pedir a senha mestra)."""
    try:
        from datetime import date
        from qgis.core import QgsSettings
        hoje = date.today().isoformat()
        s = QgsSettings()
        if s.value(_ULTIMA_CONFERENCIA, "", type=str) == hoje:
            return False
        s.setValue(_ULTIMA_CONFERENCIA, hoje)
        return True
    except Exception:
        pass


def _conferir_chave(iface):
    """Pede o plugins.xml com a chave guardada, sem travar o QGIS. Avisa se o GitHub recusar."""
    try:
        from qgis.core import QgsNetworkContentFetcher, QgsSettings
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtNetwork import QNetworkRequest
        url = url_repositorio()
        chave = _chave_repositorio(url) or NOME
        authcfg = QgsSettings().value(f"{GRUPO}/{chave}/authcfg", "", type=str)
        busca = QgsNetworkContentFetcher()
        _CONFERENCIA.append(busca)

        def chegou():
            try:
                resposta = busca.reply()
                status = resposta.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) if resposta else None
                if status in (401, 403, 404):   # o GitHub responde 404 para repositório privado sem chave válida
                    _mostrar_aviso(iface, TEXTO_CHAVE_RECUSADA)
            except Exception:
                pass
            finally:
                if busca in _CONFERENCIA:
                    _CONFERENCIA.remove(busca)
        busca.finished.connect(chegou)
        busca.fetchContent(QUrl(url), authcfg)
    except Exception:
        pass


def _mostrar_aviso(iface, texto=TEXTO_SEM_CHAVE):
    try:
        from qgis.core import Qgis
        from qgis.PyQt.QtWidgets import QPushButton
        barra = iface.messageBar()
        msg = barra.createMessage("Norte Agro", texto)
        botao = QPushButton("Configurar acesso")
        msg.layout().addWidget(botao)

        def abrir():
            if configurar_acesso(iface.mainWindow()):
                barra.popWidget(msg)
        botao.clicked.connect(abrir)
        nivel = getattr(Qgis, "Info", None)
        if nivel is None:
            nivel = Qgis.MessageLevel.Info
        barra.pushWidget(msg, nivel, 0)
    except Exception:
        pass


def _testar(url, authcfg):
    """Baixa o plugins.xml com a chave. True se o GitHub entregou a lista."""
    from qgis.core import QgsBlockingNetworkRequest
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest
    req = QgsBlockingNetworkRequest()
    req.setAuthCfg(authcfg)
    erro = req.get(QNetworkRequest(QUrl(url)), True)
    if int(erro) != 0:
        return False
    return b"<plugins" in bytes(req.reply().content())


def _guardar(am, metodo, token, id_existente):
    """Cria (ou atualiza) a configuração de autenticação no cofre do QGIS. Devolve o id ou ''."""
    from qgis.core import QgsAuthMethodConfig
    cfg = QgsAuthMethodConfig()
    cfg.setName(NOME_CHAVE)
    cfg.setMethod(metodo)
    if metodo == "APIHeader":
        cfg.setConfig("Authorization", "token " + token)
    else:
        cfg.setConfig("username", "token")
        cfg.setConfig("password", token)
    if id_existente:
        cfg.setId(id_existente)
        return id_existente if am.updateAuthenticationConfig(cfg) else ""
    r = am.storeAuthenticationConfig(cfg)
    ok, cfg = (r if isinstance(r, tuple) else (r, cfg))
    return cfg.id() if ok else ""


def configurar_acesso(parent=None):
    """Janela para colar a chave de leitura do GitHub. True se ficou configurado e testado."""
    from qgis.core import QgsApplication, QgsSettings
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel, QLineEdit, QMessageBox,
                                     QVBoxLayout)
    cfg = _ler_config()
    if not cfg["url"]:
        QMessageBox.information(parent, "Norte Agro", "Este plugin não tem o endereço do repositório da Norte Agro.")
        return False
    registrar_repositorio()
    chave_repo = _chave_repositorio(cfg["url"]) or NOME

    dlg = QDialog(parent)
    dlg.setWindowTitle("Norte Agro - acesso às atualizações")
    dlg.setMinimumWidth(520)
    lay = QVBoxLayout(dlg)
    texto = QLabel("Os plugins da Norte Agro ficam num repositório privado. Cole aqui a chave de leitura (token do "
                   "GitHub) que o responsável pelos plugins passou. Ela fica guardada no cofre do QGIS (pode ser "
                   "que o QGIS peça a senha mestra) e só é preciso fazer isto uma vez.")
    texto.setWordWrap(True)
    lay.addWidget(texto)
    campo = QLineEdit()
    campo.setEchoMode(QLineEdit.EchoMode.Password)
    campo.setPlaceholderText("github_pat_...")
    lay.addWidget(campo)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.button(QDialogButtonBox.StandardButton.Ok).setText("Salvar e testar")
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    if not dlg.exec():
        return False
    token = "".join(campo.text().split())
    campo.clear()
    if len(token) < 20:
        QMessageBox.warning(parent, "Norte Agro", "Essa chave está curta demais. Copie a chave inteira e tente de novo.")
        return False

    am = QgsApplication.authManager()
    if not am.masterPasswordIsSet() and not am.setMasterPassword(True):
        QMessageBox.warning(parent, "Norte Agro", "Sem a senha mestra do QGIS a chave não pode ser guardada. Nada foi alterado.")
        return False
    s = QgsSettings()
    antigo = s.value(f"{GRUPO}/{chave_repo}/authcfg", "", type=str)
    antigo = antigo if antigo in am.configIds() else ""
    metodos = [m for m in ("APIHeader", "Basic") if m in am.authMethodsKeys()]
    novo = ""   # a chave nova é testada numa configuração própria; a antiga só sai se a nova funcionar
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        for metodo in metodos:
            novo = _guardar(am, metodo, token, novo)
            if novo and _testar(cfg["url"], novo):
                s.setValue(f"{GRUPO}/{chave_repo}/authcfg", novo)
                s.setValue(f"{GRUPO}/{chave_repo}/enabled", True)
                if antigo and antigo != novo:
                    am.removeAuthenticationConfig(antigo)
                QApplication.restoreOverrideCursor()
                QMessageBox.information(parent, "Norte Agro",
                                        "Acesso configurado e testado. O QGIS vai avisar quando houver atualização dos "
                                        "plugins (Complementos > Gerenciar e instalar complementos).")
                return True
        if novo:
            am.removeAuthenticationConfig(novo)   # não deixa no cofre uma chave que não funcionou
    finally:
        if QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
    QMessageBox.warning(parent, "Norte Agro",
                        "O GitHub não aceitou essa chave (ou não há internet). Confira se a chave foi copiada inteira e "
                        "se ela dá leitura ao repositório dos plugins. Nada foi alterado.")
    return False
