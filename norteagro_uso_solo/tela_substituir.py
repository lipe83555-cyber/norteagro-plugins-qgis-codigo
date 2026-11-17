# -*- coding: utf-8 -*-
"""Substituição segura do conteúdo de uma camada, com backup e rollback."""
from . import compat
import os

from qgis.PyQt.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout
from qgis.core import Qgis, QgsProject
from qgis.gui import QgsMapLayerComboBox

from .estilo import alertar, botao_destrutivo, botao_secundario, cabecalho, confirmar, configurar_alerta_texto, preparar_dialogo, secao, sucesso
from .operacoes import metricas_camada, remover_camada_segura, substituir_conteudo


class TelaSubstituir(QDialog):
    def __init__(self, plugin, arquivo_destino=None, parent=None):
        super().__init__(parent or plugin.iface.mainWindow()); self.plugin=plugin
        preparar_dialogo(self,"tela_substituir","Norte Agro - Substituir camada",(620,430)); self.resize(720,520)
        raiz=QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho("Substituir conteúdo","Troque as feições de uma camada mantendo arquivo, grupo, estilo e KML.",os.path.join(os.path.dirname(__file__),"icon.png")))
        raiz.addWidget(secao("Destino")); fd=QFormLayout(); raiz.addLayout(fd); self.destino=QComboBox(); fd.addRow("Camada:",self.destino); self.info_destino=QLabel(); self.info_destino.setWordWrap(True); fd.addRow("Conteúdo atual:",self.info_destino)
        raiz.addWidget(secao("Origem")); fo=QFormLayout(); raiz.addLayout(fo); self.origem=QgsMapLayerComboBox(); self.origem.setAllowEmptyLayer(True,"Selecione a origem..."); fo.addRow("Camada:",self.origem); self.info_origem=QLabel(); self.info_origem.setWordWrap(True); fo.addRow("Novo conteúdo:",self.info_origem); self.aviso_area=configurar_alerta_texto(QLabel()); raiz.addWidget(self.aviso_area)
        raiz.addWidget(secao("Opções")); self.corrigir=QCheckBox("Corrigir geometrias antes (native:fixgeometries)"); self.corrigir.setChecked(True); self.remover=QCheckBox("Remover a camada de origem do projeto depois"); raiz.addWidget(self.corrigir); raiz.addWidget(self.remover); raiz.addStretch()
        botoes=QHBoxLayout(); botoes.addStretch(); fechar=botao_secundario("Fechar",self); fechar.clicked.connect(self.reject); executar=botao_destrutivo("Substituir",self); executar.clicked.connect(self.executar); botoes.addWidget(fechar); botoes.addWidget(executar); raiz.addLayout(botoes)
        self._popular_destinos(arquivo_destino); self.destino.currentIndexChanged.connect(self.destino_mudou); self.origem.layerChanged.connect(self.atualizar_metricas); self.destino_mudou()

    def _popular_destinos(self,preferido):
        indice=self.plugin.indice_atual(); selecionado=0
        for arquivo,entrada in indice.items():
            if os.path.isfile(self.plugin.caminho_shp(arquivo)):
                self.destino.addItem(entrada["nome"],arquivo)
                if arquivo==preferido: selecionado=self.destino.count()-1
        if self.destino.count(): self.destino.setCurrentIndex(selecionado)

    def camada_destino(self):
        arquivo=self.destino.currentData()
        if not arquivo: return None
        camada=self.plugin.camada_plugin(arquivo)
        if not camada:
            ok,_,_=self.plugin.criar_ou_carregar(arquivo); camada=self.plugin.camada_plugin(arquivo) if ok else None
        return camada

    def destino_mudou(self):
        destino=self.camada_destino(); self.origem.setExceptedLayerList([destino] if destino else []); self.atualizar_metricas()

    def _srid(self, camada):
        _, srid = self.plugin.memoria_basica()
        if srid:
            return srid
        try:
            return camada.crs().authid() if camada and not camada.crs().isGeographic() else "EPSG:31982"
        except Exception:
            return "EPSG:31982"

    def atualizar_metricas(self,*_):
        # v3.9.4: metricas_camada devolve (quantidade, área em ha) no SRC do mapa.
        destino=self.camada_destino(); origem=self.origem.currentLayer()
        md=mo=None
        try:
            if destino: md=metricas_camada(destino,self._srid(destino))
            if origem: mo=metricas_camada(origem,self._srid(destino or origem))
        except Exception as exc:
            self.plugin.log(f"Falha ao medir camadas para substituir: {exc}")
        poligono=bool(destino) and destino.geometryType()==compat.GEOM_POLIGONO
        def texto(m):
            if m is None: return "-"
            return f"{m[0]} feição(ões)" + (f" - {m[1]:.4f} ha" if poligono else "")
        self.info_destino.setText(texto(md)); self.info_origem.setText(texto(mo))
        if poligono and md is not None and mo is not None:
            self.aviso_area.setText(f"Área atual: {md[1]:.4f} ha | Nova área: {mo[1]:.4f} ha | Diferença: {mo[1]-md[1]:+.4f} ha")
        else:
            self.aviso_area.clear()

    def executar(self):
        destino=self.camada_destino(); origem=self.origem.currentLayer()
        if not destino or not origem: alertar(self,"Substituir camada","Escolha destino e origem."); return
        if destino.id()==origem.id(): alertar(self,"Substituir camada","A origem não pode ser a própria camada de destino."); return
        if destino.geometryType()!=origem.geometryType(): alertar(self,"Geometria incompatível","Polígono só pode substituir polígono, linha só linha e ponto só ponto."); return
        self.atualizar_metricas()
        if not confirmar(self,"Substituir conteúdo","O conteúdo atual será substituído. Um backup será criado antes da operação.","Substituir",destrutivo=True,detalhes=[self.info_destino.text(),self.info_origem.text(),self.aviso_area.text()]): return
        try:
            # v3.9.4: chamada com a assinatura correta; registros sem geometria não são copiados.
            resultado=substituir_conteudo(destino,origem,self.corrigir.isChecked(),criar_backup=True,ignorar_sem_geometria=True)
        except Exception as exc:
            self.plugin.log(f"Falha ao substituir {destino.name()}: {exc}")
            alertar(self,"Substituição não concluída","O conteúdo original foi preservado (nenhuma alteração foi gravada).",[str(exc)]); return
        try: self.plugin.kml.exportar_automatico(destino)
        except Exception: pass
        detalhes=[f"Feições gravadas: {resultado.get('feicoes',0)}", f"Backup: {resultado.get('backup','')}"]
        if resultado.get("sem_geometria_ignoradas"): detalhes.append(f"Registros sem geometria não copiados: {resultado['sem_geometria_ignoradas']}")
        if self.remover.isChecked():
            res=remover_camada_segura(self.plugin,origem,mover_interna=False)
            detalhes.append("Origem removida do projeto (o arquivo não foi apagado)." if res.get("removida") else f"Não foi possível remover a origem: {res.get('falha','')}")
        sucesso(self,"Substituição concluída","A camada foi substituída com backup.",detalhes); self.accept()
