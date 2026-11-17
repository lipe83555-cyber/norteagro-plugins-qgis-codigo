# -*- coding: utf-8 -*-
"""Padronização/remocão de camadas com nomes fora do padrão do escritório."""
from . import compat
import glob
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from qgis.core import QgsProject, QgsVectorLayer

from .estilo import (
    PainelPendencias, alertar, botao_destrutivo, botao_principal, botao_secundario,
    cabecalho, confirmar, configurar_alerta_texto, configurar_caminho, dialogo_acoes,
    erro, informar, preparar_dialogo, secao, sucesso,
)
from .catalogo import indice_catalogo_avulsa
from .operacoes import codigo_tipo_geometria, metricas_camada, remover_camada_segura, substituir_conteudo


def _pasta_mapa_valida(plugin):
    pasta, srid = plugin.memoria_basica()
    return (pasta if pasta and os.path.isdir(pasta) else ""), srid


class DialogoDestinoExterno(QDialog):
    """Pede pasta/SRC/KML quando não existe pasta Norte Agro configurada."""
    def __init__(self, plugin, srid_sugerido="", parent=None):
        super().__init__(parent or plugin.iface.mainWindow()); self.plugin=plugin
        preparar_dialogo(self,"destino_padronizacao","Norte Agro - Destino da camada padrão",(620,360)); self.resize(720,430)
        raiz=QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho("Destino da camada padrão","Escolha onde criar a camada padronizada e onde manter seu espelho KML."))
        raiz.addWidget(secao("Destino")); form=QFormLayout(); form.setVerticalSpacing(8); raiz.addLayout(form)
        hp=QHBoxLayout(); self.pasta=QLabel("-"); configurar_caminho(self.pasta,""); bp=botao_secundario("Escolher...",self); bp.clicked.connect(self._pasta); hp.addWidget(self.pasta,1); hp.addWidget(bp); form.addRow("Pasta de destino:",hp)
        self.src=QComboBox(); self.src.addItem("Selecione...",""); self.src.addItem("EPSG:31982 - SIRGAS 2000 / UTM 22S","EPSG:31982"); self.src.addItem("EPSG:31983 - SIRGAS 2000 / UTM 23S","EPSG:31983")
        idx=self.src.findData(srid_sugerido); self.src.setCurrentIndex(idx if idx>=0 else 0); form.addRow("SRC:",self.src)
        hk=QHBoxLayout(); self.kml=QLabel("-"); configurar_caminho(self.kml,""); bk=botao_secundario("Alterar...",self); bk.clicked.connect(self._kml); hk.addWidget(self.kml,1); hk.addWidget(bk); form.addRow("Pasta do KML:",hk)
        self.pendencias=PainelPendencias(self); raiz.addWidget(self.pendencias); raiz.addStretch()
        b=QHBoxLayout(); b.addStretch(); canc=botao_secundario("Fechar",self); canc.clicked.connect(self.reject); self.ok=botao_principal("Continuar",self); self.ok.clicked.connect(self._validar); b.addWidget(canc); b.addWidget(self.ok); raiz.addLayout(b)
        self.src.currentIndexChanged.connect(self._atualizar_pendencias); self._atualizar_pendencias()

    def _pasta(self):
        p=QFileDialog.getExistingDirectory(self,"Escolha a pasta de destino",os.path.expanduser("~"))
        if p:
            configurar_caminho(self.pasta,p); configurar_caminho(self.kml,self.plugin.sugerir_kml_dir(p)); self._atualizar_pendencias()
    def _kml(self):
        atual=self.kml.toolTip() if self.kml.toolTip() else os.path.expanduser("~")
        p=QFileDialog.getExistingDirectory(self,"Escolha a pasta do KML",atual)
        if p: configurar_caminho(self.kml,p); self._atualizar_pendencias()
    def _atualizar_pendencias(self):
        pasta=self.pasta.toolTip() or ""; kml=self.kml.toolTip() or ""; faltas=[]
        if not os.path.isdir(pasta): faltas.append("Escolha uma pasta de destino válida.")
        if not self.src.currentData(): faltas.append("Escolha o SRC.")
        if not kml: faltas.append("Informe a pasta do KML.")
        self.pendencias.definir(faltas); self.ok.setEnabled(not faltas)
    def _validar(self):
        self._atualizar_pendencias()
        if self.ok.isEnabled(): self.accept()
    def valores(self): return self.pasta.toolTip() or "", str(self.src.currentData() or ""), self.kml.toolTip() or ""


class DialogoPadronizar(QDialog):
    def __init__(self, plugin, camada, arquivo_sugerido="", srid_sugerido="", parent=None):
        super().__init__(parent or plugin.iface.mainWindow()); self.plugin=plugin; self.layer_id=str(camada.id())
        self.indice=indice_catalogo_avulsa(QgsProject.instance()); preparar_dialogo(self,"padronizar_camada","Norte Agro - Criar camada padrão com este conteúdo",(640,430)); self.resize(760,520)
        raiz=QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho("Criar camada padrão com este conteúdo","Copie o conteúdo para uma camada do catálogo sem renomear o arquivo de origem."))
        raiz.addWidget(secao("Origem")); origem=QLabel(f"{camada.name()}\n{plugin._fonte(camada) or 'temporária/serviço'}"); origem.setWordWrap(True); origem.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); raiz.addWidget(origem)
        raiz.addWidget(secao("Destino")); form=QFormLayout(); form.setVerticalSpacing(8); raiz.addLayout(form)
        self.destino=QComboBox()
        for arq,e in sorted(self.indice.items(),key=lambda kv:(kv[1].get('grupo',''),kv[1].get('nome',''))):
            self.destino.addItem(str(e.get('nome',arq)),arq); idx_item=self.destino.count()-1
            self.destino.setItemData(idx_item,f"ARQUIVO: {arq}",Qt.ItemDataRole.ToolTipRole)
            if hasattr(plugin,"entrada_valida") and not plugin.entrada_valida(arq):
                try: self.destino.model().item(idx_item).setEnabled(False)
                except Exception: pass
                self.destino.setItemData(idx_item,f"ARQUIVO: {arq}\nEntrada com problema no catálogo.",Qt.ItemDataRole.ToolTipRole)
        if arquivo_sugerido in self.indice: self.destino.setCurrentIndex(self.destino.findData(arquivo_sugerido))
        else: self.destino.setCurrentIndex(-1)
        form.addRow("Camada padrão:",self.destino)
        raiz.addWidget(secao("Opções")); self.corrigir=QCheckBox("Corrigir geometrias antes (native:fixgeometries)"); self.corrigir.setChecked(True); raiz.addWidget(self.corrigir)
        self.info=configurar_alerta_texto(QLabel()); self.info.setProperty("naAlertText",False); raiz.addWidget(self.info)
        self.pendencias=PainelPendencias(self); raiz.addWidget(self.pendencias); raiz.addStretch()
        b=QHBoxLayout(); b.addStretch(); canc=botao_secundario("Fechar",self); canc.clicked.connect(self.reject); self.ok=botao_principal("Padronizar",self); self.ok.clicked.connect(self.accept); b.addWidget(canc); b.addWidget(self.ok); raiz.addLayout(b)
        self.destino.currentIndexChanged.connect(self._atualizar_info); self._atualizar_info()

    def _camada(self): return QgsProject.instance().mapLayer(self.layer_id)

    def _atualizar_info(self):
        arq=str(self.destino.currentData() or ""); e=self.indice.get(arq); camada=self._camada(); faltas=[]
        if camada is None:
            self.info.setProperty("naAlertText",True); self.info.setText("A camada de origem não está mais no projeto."); faltas.append("A camada de origem não está mais no projeto.")
        elif not e:
            self.info.setProperty("naAlertText",False); self.info.setText("Escolha a camada padrão de destino."); faltas.append("Escolha a camada padrão de destino.")
        else:
            origem=codigo_tipo_geometria(camada); compat=origem==e.get("tipo")
            self.info.setProperty("naAlertText",not compat); self.info.setText(f"Tipo origem: {origem or 'desconhecido'} | destino: {e.get('tipo')} - " + ("geometria compatível." if compat else "geometria incompatível."))
            if not compat: faltas.append("O tipo de geometria da origem é incompatível com o destino.")
        self.info.style().unpolish(self.info); self.info.style().polish(self.info)
        self.pendencias.definir(faltas); self.ok.setEnabled(not faltas)

    def arquivo(self): return str(self.destino.currentData() or "")


def _apagar_nova_criacao(plugin, camada):
    """Em falha, libera a camada vazia do QGIS sem apagar definitivamente os arquivos."""
    if not camada:
        return
    try:
        plugin.kml.desconectar(camada.id())
        if camada.isEditable():
            camada.rollBack()
        QgsProject.instance().removeMapLayer(camada.id())
    except Exception as exc:
        plugin.log(f"Falha ao liberar destino novo após erro de padronização: {exc}")


def padronizar_camada(plugin, camada, arquivo_sugerido="", srid_sugerido="", parent=None,
                       base_externa=None, kml_externo=None, perguntar_original=True,
                       destino_forcado="", corrigir_forcado=True, mostrar_resumo=True):
    """Cria/carrega o padrão e reutiliza o mesmo fluxo de substituição/backup."""
    if not isinstance(camada,QgsVectorLayer): return False,"Camada de origem inválida."
    origem_id = str(camada.id())
    indice=indice_catalogo_avulsa(QgsProject.instance())
    dlg=None
    if destino_forcado:
        arquivo=str(destino_forcado).upper(); entrada=indice.get(arquivo); corrigir=bool(corrigir_forcado)
    else:
        dlg=DialogoPadronizar(plugin,camada,arquivo_sugerido,srid_sugerido,parent)
        if not compat.aceito(dlg.exec()): return False,"cancelado"
        arquivo=dlg.arquivo(); entrada=indice.get(arquivo); corrigir=dlg.corrigir.isChecked()
    camada = QgsProject.instance().mapLayer(origem_id)
    if not isinstance(camada, QgsVectorLayer):
        alertar(parent or dlg or plugin.iface.mainWindow(),"Padronizar camada","A camada de origem não está mais no projeto.")
        return False,"origem removida"
    if not entrada: alertar(parent or dlg or plugin.iface.mainWindow(),"Padronizar camada","Escolha uma camada padrão de destino."); return False,"destino ausente"
    if codigo_tipo_geometria(camada)!=entrada.get('tipo'):
        alertar(parent or dlg or plugin.iface.mainWindow(),"Padronizar camada","O tipo de geometria da origem é incompatível com a camada padrão escolhida."); return False,"geometria incompatível"

    pasta_mapa,srid_mapa=_pasta_mapa_valida(plugin); avulsa=not bool(pasta_mapa)
    if pasta_mapa:
        raiz=os.path.join(pasta_mapa,'shapefiles'); kml_dir=os.path.join(pasta_mapa,'kml'); srid=srid_mapa
    elif base_externa:
        raiz=base_externa; kml_dir=kml_externo or plugin.sugerir_kml_dir(raiz); srid=srid_sugerido
    else:
        dd=DialogoDestinoExterno(plugin,srid_sugerido,parent or dlg or plugin.iface.mainWindow())
        if not compat.aceito(dd.exec()): return False,"cancelado"
        raiz,srid,kml_dir=dd.valores()
    shp=plugin.localizar_shp(raiz,entrada)
    if os.path.normcase(os.path.abspath(plugin._fonte(camada) or ''))==os.path.normcase(os.path.abspath(shp)):
        alertar(parent or dlg or plugin.iface.mainWindow(),"Padronizar camada","A camada de origem já é o próprio arquivo padrão de destino."); return False,"mesma fonte"
    existente=os.path.isfile(shp); destino_existente=plugin.camada_por_fonte(shp)
    if existente:
        if not destino_existente:
            ok,acao,erro,destino_existente=plugin.criar_ou_carregar_destino(entrada,raiz,srid,kml_dir=kml_dir,avulsa=avulsa,carregar_existente=True)
            if not ok: alertar(parent or dlg or plugin.iface.mainWindow(),"Padronizar camada",erro); return False,erro
        q1,a1=metricas_camada(destino_existente,srid); q2,a2=metricas_camada(camada,srid)
        texto=(f"O arquivo padrão {arquivo} já existe e seu conteúdo será substituído com backup.\n\n"
               f"Destino atual: {q1} feição(ões), {a1:.4f} ha\nOrigem: {q2} feição(ões), {a2:.4f} ha\n\nContinuar?")
        if not confirmar(parent or dlg or plugin.iface.mainWindow(),"Substituir camada padrão",texto,"Substituir","Cancelar",destrutivo=True):
            return False,"cancelado"
        destino=destino_existente; nova=False
    else:
        ok,acao,erro,destino=plugin.criar_ou_carregar_destino(entrada,raiz,srid,kml_dir=kml_dir,avulsa=avulsa,carregar_existente=True)
        if not ok: alertar(parent or dlg or plugin.iface.mainWindow(),"Padronizar camada",erro); return False,erro
        nova=True
    try:
        resultado=substituir_conteudo(destino,camada,corrigir,criar_backup=not nova,ignorar_sem_geometria=True)
        plugin.kml.exportar_automatico(destino)
        _,antes=metricas_camada(camada,srid); _,depois=metricas_camada(destino,srid)
    except Exception as exc:
        if nova: _apagar_nova_criacao(plugin,destino)
        plugin.log(f"Falha ao padronizar {camada.name()} -> {arquivo}: {exc}")
        erro(parent or dlg or plugin.iface.mainWindow(),"Padronizar camada","Não foi possível padronizar a camada.",str(exc))
        return False,str(exc)

    acao_original="mantida"
    if perguntar_original:
        pasta_cfg,_=plugin.memoria_basica(); raiz_cfg=os.path.join(pasta_cfg,'shapefiles') if pasta_cfg else ''
        interna=bool(raiz_cfg and plugin._dentro(plugin._fonte(camada),raiz_cfg))
        acoes=[("Manter no projeto",QMessageBox.ButtonRole.AcceptRole),("Remover do projeto",QMessageBox.ButtonRole.DestructiveRole)]
        if interna: acoes.append(("Remover e mover arquivos para _apagados",QMessageBox.ButtonRole.DestructiveRole))
        escolha=dialogo_acoes(parent or dlg or plugin.iface.mainWindow(),"Camada original","A camada padrão foi criada com sucesso. O que fazer com a camada original?",None,acoes,"info","Manter no projeto")
        if escolha=="Remover do projeto":
            res=remover_camada_segura(plugin,camada,mover_interna=False); acao_original="removida do projeto" if res.get('removida') else "falha ao remover"
        elif escolha=="Remover e mover arquivos para _apagados":
            res=remover_camada_segura(plugin,camada,mover_interna=True); acao_original=("movida para "+res.get('destino','')) if res.get('movida') else ("removida; falha ao mover: "+res.get('falha',''))
    texto=f"Camada padrão: {arquivo}\nFeições: {destino.featureCount()}\nÁrea origem: {antes:.4f} ha\nÁrea padrão: {depois:.4f} ha\nDiferença: {abs(antes-depois):.6f} ha"
    if resultado.get('backup'): texto+=f"\nBackup: {resultado['backup']}"
    if resultado.get("sem_geometria_ignoradas"):
        texto += f"\nRegistros sem geometria não copiados: {resultado['sem_geometria_ignoradas']}"
    texto+=f"\nOriginal: {acao_original}"
    if mostrar_resumo:
        sucesso(parent or dlg or plugin.iface.mainWindow(),"Padronização concluída","A camada padrão foi criada com sucesso.",texto)
    return True,arquivo


def remover_camada_com_confirmacao(plugin, camada, parent=None):
    """Remove sem apagar definitivamente: interna vai para _apagados; externa só sai do projeto."""
    fonte=plugin._fonte(camada) or "camada temporária/serviço"
    pasta,_=plugin.memoria_basica(); raiz=os.path.join(pasta,'shapefiles') if pasta else ''
    interna=bool(raiz and plugin._dentro(plugin._fonte(camada),raiz))
    classe="DENTRO da pasta do mapa (será movida para _apagados)" if interna else "FORA da pasta do mapa (somente será removida do projeto)"
    texto=f"Remover a camada?\n\nNome: {camada.name()}\nCaminho: {fonte}\nSituação: {classe}\n\nNenhum arquivo será apagado definitivamente."
    if not confirmar(parent or plugin.iface.mainWindow(),"Remover camada",texto,"Remover","Cancelar",destrutivo=True): return False
    res=remover_camada_segura(plugin,camada,mover_interna=interna)
    if res.get('falha'):
        alertar(parent or plugin.iface.mainWindow(),"Remover camada","A camada foi removida do projeto, mas houve falha ao mover arquivos.",res["falha"])
    elif res.get('movida'):
        sucesso(parent or plugin.iface.mainWindow(),"Remover camada","Camada removida e arquivos movidos.",res["destino"])
    else:
        sucesso(parent or plugin.iface.mainWindow(),"Remover camada","Camada removida do projeto.",["Arquivos externos não foram alterados."])
    return True


class DialogoPadronizarTodas(QDialog):
    """Prévia em tabela; por segurança, o lote mantém as originais no projeto."""
    def __init__(self, plugin, candidatos, srid, base, parent=None):
        super().__init__(parent or plugin.iface.mainWindow()); self.plugin=plugin
        self.candidatos=[(str(camada.id()), arquivo) for camada, arquivo in candidatos]
        preparar_dialogo(self,"padronizar_todas","Norte Agro - Padronizar todas as reconhecidas",(760,520)); self.resize(980,650)
        raiz=QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho("Padronizar camadas reconhecidas","Revise os destinos e desmarque o que não deseja padronizar. As originais serão mantidas no projeto."))
        raiz.addWidget(secao("Camadas"))
        self.tabela=QTableWidget(len(candidatos),4); self.tabela.setHorizontalHeaderLabels(["✓","Nome atual","Destino padrão","Pasta"]); raiz.addWidget(self.tabela,1)
        indice=indice_catalogo_avulsa(QgsProject.instance())
        for i,(layer_id,arquivo) in enumerate(self.candidatos):
            camada=QgsProject.instance().mapLayer(layer_id); ck=QTableWidgetItem(); ck.setFlags(ck.flags()|Qt.ItemFlag.ItemIsUserCheckable); ck.setCheckState(Qt.CheckState.Checked); self.tabela.setItem(i,0,ck)
            entrada=indice.get(arquivo,{})
            self.tabela.setItem(i,1,QTableWidgetItem(camada.name() if camada else "(camada removida)")); self.tabela.setItem(i,2,QTableWidgetItem(str(entrada.get("nome") or arquivo))); self.tabela.setItem(i,3,QTableWidgetItem(os.path.dirname(plugin.localizar_shp(base,entrada)) if entrada else base))
            if camada is None: ck.setCheckState(Qt.CheckState.Unchecked); ck.setFlags(ck.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        self.tabela.resizeColumnsToContents(); raiz.addStretch()
        b=QHBoxLayout(); b.addStretch(); canc=botao_secundario("Fechar",self); canc.clicked.connect(self.reject); ok=botao_principal("Padronizar selecionadas",self); ok.clicked.connect(self.accept); b.addWidget(canc); b.addWidget(ok); raiz.addLayout(b)
    def marcadas(self):
        saida=[]
        for i,(layer_id,arquivo) in enumerate(self.candidatos):
            if self.tabela.item(i,0).checkState()!=Qt.CheckState.Checked: continue
            camada=QgsProject.instance().mapLayer(layer_id)
            if camada is not None: saida.append((camada,arquivo))
        return saida

