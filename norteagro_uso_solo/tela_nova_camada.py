# -*- coding: utf-8 -*-
"""Diálogo para criar camadas personalizadas sem catalogá-las automaticamente."""
from . import compat
import os

from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QVBoxLayout,
)
from qgis.core import Qgis, QgsLayerTreeGroup, QgsProject, QgsRenderContext, QgsStyle, QgsVectorLayer
from qgis.gui import QgsMapLayerComboBox, QgsSymbolSelectorDialog

from .catalogo import (
    EXPLICACAO_LUGAR, LUGARES_QUADRO, catalogar_escritorio, normalizar_arquivo, simbolo_padrao, simbolo_para_xml,
)
from .estilo import (
    PainelPendencias, alertar, botao_principal, botao_secundario, cabecalho,
    confirmar, dialogo_acoes, preparar_dialogo, secao,
)


class CampoLugarQuadro:
    """v3.9.6: escolha de onde a camada personalizada entra no Quadro de Áreas."""
    def __init__(self, form, parent, atual="OUTRAS"):
        self.combo = QComboBox(parent)
        for cod, texto, _quadro, _expl in LUGARES_QUADRO:
            self.combo.addItem(texto, cod)
        self.info = QLabel(parent); self.info.setWordWrap(True); self.info.setProperty("naSubtitle", True)
        self.combo.currentIndexChanged.connect(self._explicar)
        form.addRow("No Quadro de Áreas:", self.combo); form.addRow("", self.info)
        self.definir(atual)

    def definir(self, codigo):
        i = self.combo.findData(str(codigo or "OUTRAS").upper())
        self.combo.setCurrentIndex(i if i >= 0 else self.combo.findData("OUTRAS")); self._explicar()

    def ajustar_tipo(self, tipo):
        """Só polígono tem área para entrar num quadro; linha e ponto ficam fora."""
        poligono = str(tipo or "P") == "P"
        if not poligono and self.combo.isEnabled():
            self._antes = self.combo.currentData(); self.definir("NENHUM")
        elif poligono and not self.combo.isEnabled():
            self.definir(getattr(self, "_antes", None) or "OUTRAS")
        self.combo.setEnabled(poligono); self._explicar()

    def _explicar(self, *_args):
        if not self.combo.isEnabled() and self.combo.currentData() == "NENHUM":
            self.info.setText("Linhas e pontos não têm área: aparecem só na aba Todas as camadas (comprimento ou quantidade).")
        else:
            self.info.setText(EXPLICACAO_LUGAR.get(self.combo.currentData(), ""))

    def codigo(self):
        return str(self.combo.currentData() or "OUTRAS")


def escolher_lugar_quadro(parent, nome, atual, tipo="P"):
    """Diálogo curto para mudar o lugar no quadro de uma camada já existente."""
    dlg = QDialog(parent); preparar_dialogo(dlg, "lugar_quadro", "Norte Agro - Lugar no Quadro de Áreas", (560, 260))
    raiz = QVBoxLayout(dlg); raiz.setContentsMargins(16, 16, 16, 16); raiz.setSpacing(12)
    raiz.addWidget(cabecalho("Lugar no Quadro de Áreas", f"Onde {nome} entra na planilha do cálculo."))
    form = QFormLayout(); raiz.addLayout(form); campo = CampoLugarQuadro(form, dlg, atual); campo.ajustar_tipo(tipo)
    raiz.addStretch(); botoes = QHBoxLayout(); botoes.addStretch()
    cancelar = botao_secundario("Fechar", dlg); ok = botao_principal("Salvar", dlg)
    cancelar.clicked.connect(dlg.reject); ok.clicked.connect(dlg.accept); ok.setEnabled(str(tipo or "P") == "P")
    botoes.addWidget(cancelar); botoes.addWidget(ok); raiz.addLayout(botoes)
    dlg._campo = campo
    return campo.codigo() if compat.aceito(dlg.exec()) else None


class TelaNovaCamada(QDialog):
    def __init__(self, plugin, parent=None, somente_definicao=False, inicial=None):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin=plugin; self.simbolo=simbolo_padrao("P"); self.somente_definicao=bool(somente_definicao); self.entrada_resultado=None
        preparar_dialogo(self,"tela_nova_camada","Norte Agro - Nova camada",(600,560)); self.resize(700,640)
        raiz=QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho("Nova camada","Defina a identificação, o tipo, o grupo, o lugar no Quadro de Áreas e o estilo da camada.",os.path.join(os.path.dirname(__file__),"icon.png")))
        raiz.addWidget(secao("Identificação")); form=QFormLayout(); form.setVerticalSpacing(8); raiz.addLayout(form)
        self.nome=QLineEdit(); self.nome.textChanged.connect(self.atualizar_arquivo); form.addRow("Nome:",self.nome)
        self.arquivo=QLabel(); self.arquivo.setProperty("naSubtitle",True); form.addRow("Arquivo gerado:",self.arquivo)
        raiz.addWidget(secao("Tipo e grupo")); fg=QFormLayout(); raiz.addLayout(fg)
        self.tipo=QComboBox(); self.tipo.addItem("Polígono","P"); self.tipo.addItem("Linha","L"); self.tipo.addItem("Ponto","Pt"); self.tipo.currentIndexChanged.connect(self.tipo_mudou); fg.addRow("Tipo:",self.tipo)
        self.grupo=QComboBox(); self.preencher_grupos(); fg.addRow("Grupo:",self.grupo)
        self.lugar=CampoLugarQuadro(fg,self)
        raiz.addWidget(secao("Estilo")); he=QHBoxLayout(); self.preview=QLabel(); self.preview.setFixedSize(48,48); editar=botao_secundario("Editar estilo",self); editar.clicked.connect(self.editar_estilo); he.addWidget(self.preview); he.addWidget(editar); he.addStretch(); raiz.addLayout(he)
        copiar_box=QHBoxLayout(); self.copiar_combo=QgsMapLayerComboBox(); self.copiar_combo.setAllowEmptyLayer(True,"Selecione uma camada..."); copiar=botao_secundario("Copiar de outra camada",self); copiar.clicked.connect(self.copiar_estilo); copiar_box.addWidget(self.copiar_combo,1); copiar_box.addWidget(copiar); raiz.addLayout(copiar_box)
        self.pendencias=PainelPendencias(self); raiz.addWidget(self.pendencias); raiz.addStretch()
        botoes=QHBoxLayout(); botoes.addStretch(); cancelar=botao_secundario("Fechar",self); cancelar.clicked.connect(self.reject); self.ok=botao_principal("Usar camada" if self.somente_definicao else "Criar camada",self); self.ok.clicked.connect(self.confirmar); botoes.addWidget(cancelar); botoes.addWidget(self.ok); raiz.addLayout(botoes)
        self.nome.textChanged.connect(self.validar); self.tipo_mudou(); self.atualizar_preview()
        self._arquivo_permitido = ""
        if inicial: self._preencher(inicial)
        self.validar()

    def _preencher(self, e):
        """v3.9.8: editar uma definição já existente (ex.: camada nova de um modelo de pastas)."""
        from .catalogo import simbolo_de_xml
        self._arquivo_permitido = normalizar_arquivo(e.get("arquivo") or e.get("nome") or "")
        self.nome.setText(str(e.get("nome") or ""))
        i = self.tipo.findData(e.get("tipo") or "P"); self.tipo.setCurrentIndex(max(0, i))
        g = self.grupo.findData(e.get("grupo"))
        if g < 0 and e.get("grupo"):
            self.grupo.insertItem(self.grupo.count() - 1, e["grupo"], e["grupo"]); g = self.grupo.findData(e["grupo"])
        if g >= 0: self.grupo.setCurrentIndex(g)
        self.lugar.definir(e.get("quadro") or "OUTRAS"); self.lugar.ajustar_tipo(self.tipo.currentData())
        try:
            simb = simbolo_de_xml(e.get("estilo_xml") or "") if e.get("estilo_xml") else None
            if simb: self.simbolo = simb; self.atualizar_preview()
        except Exception:
            pass
        self.ok.setText("Salvar alterações")

    def preencher_grupos(self):
        grupos=list(self.plugin.catalogo_atual().keys())
        for no in QgsProject.instance().layerTreeRoot().children():
            if isinstance(no,QgsLayerTreeGroup) and no.name() not in grupos: grupos.append(no.name())
        for grupo in grupos: self.grupo.addItem(grupo,grupo)
        self.grupo.addItem("Novo grupo...","__novo__")

    def atualizar_arquivo(self): self.arquivo.setText(normalizar_arquivo(self.nome.text()) or "-")

    def validar(self):
        nome=self.nome.text().strip(); arquivo=normalizar_arquivo(nome); pend=[]
        if not nome or not arquivo: pend.append("Informe o nome da camada.")
        elif arquivo in self.plugin.indice_atual() and arquivo != getattr(self, "_arquivo_permitido", ""): pend.append(f"Já existe uma camada com o ARQUIVO {arquivo}.")
        self.pendencias.definir(pend); self.ok.setEnabled(not pend)

    def tipo_mudou(self):
        tipo=self.tipo.currentData()
        if hasattr(self,"lugar"): self.lugar.ajustar_tipo(tipo)
        self.simbolo=simbolo_padrao(tipo); filtro={"P":compat.FILTRO_POLIGONO,"L":compat.FILTRO_LINHA,"Pt":compat.FILTRO_PONTO}[tipo]; self.copiar_combo.setFilters(filtro); self.atualizar_preview()

    def camada_preview(self):
        geom={"P":"MultiPolygon","L":"MultiLineString","Pt":"MultiPoint"}[self.tipo.currentData()]; return QgsVectorLayer(f"{geom}?crs=EPSG:31982","preview","memory")

    def atualizar_preview(self):
        if not self.simbolo: return
        from qgis.core import QgsSymbolLayerUtils
        icone=QgsSymbolLayerUtils.symbolPreviewIcon(self.simbolo,QSize(42,42)); self.preview.setPixmap(icone.pixmap(QSize(42,42)))

    def editar_estilo(self):
        camada = self.camada_preview()
        novo = compat.editar_simbolo(self.simbolo, self, camada)
        if novo is not None: self.simbolo = novo; self.atualizar_preview()

    def copiar_estilo(self):
        camada=self.copiar_combo.currentLayer()
        if not camada: alertar(self,"Copiar estilo","Escolha uma camada do projeto."); return
        try:
            simbolos=camada.renderer().symbols(QgsRenderContext()) if camada.renderer() else []
            if not simbolos: raise RuntimeError("A camada não possui um símbolo compatível para copiar.")
            self.simbolo=simbolos[0].clone(); self.atualizar_preview()
        except Exception as exc: alertar(self,"Copiar estilo",str(exc))

    def grupo_escolhido(self):
        if self.grupo.currentData()!="__novo__": return self.grupo.currentData()
        nome,ok=QInputDialog.getText(self,"Novo grupo","Nome do novo grupo:"); nome=nome.strip(); return nome if ok and nome else ""

    def confirmar(self):
        self.validar()
        if not self.ok.isEnabled(): return
        nome=self.nome.text().strip(); arquivo=normalizar_arquivo(nome); grupo=self.grupo_escolhido()
        if not grupo: alertar(self,"Nova camada","Informe um grupo válido."); return
        entrada={"arquivo":arquivo,"nome":nome,"tipo":self.tipo.currentData(),"grupo":grupo,"estilo_xml":simbolo_para_xml(self.simbolo),"personalizada":True,"origem":"avulsa","ordem":100000,"quadro":self.lugar.codigo()}
        if self.somente_definicao: self.entrada_resultado=entrada; self.accept(); return
        entrada["origem"]="projeto"; self.plugin.salvar_extra_projeto(entrada); ok,acao,erro=self.plugin.criar_ou_carregar(arquivo)
        if not ok: alertar(self,"Nova camada","A definição foi salva neste projeto, mas a camada não pôde ser criada.",[erro]); return
        camada=self.plugin.camada_plugin(arquivo)
        if camada: self.plugin.kml.conectar(camada)
        if confirmar(self,"Catalogar camada","Deseja catalogar esta camada para usar em outros projetos?","Catalogar"):
            try: catalogar_escritorio(entrada); dialogo_acoes(self,"Camada criada",f"Camada criada e catalogada: {nome}\nNo Quadro de Áreas: {self.lugar.combo.currentText()}",acoes=[("Fechar",0)],nivel="sucesso")
            except Exception as exc: self.plugin.log(f"Catálogo do escritório inacessível: {exc}"); alertar(self,"Catálogo do escritório","A camada foi criada apenas neste projeto.",[str(exc)])
        else: dialogo_acoes(self,"Camada criada",f"Camada criada apenas neste projeto: {nome}\nNo Quadro de Áreas: {self.lugar.combo.currentText()}",acoes=[("Fechar",0)],nivel="sucesso")
        self.accept()
