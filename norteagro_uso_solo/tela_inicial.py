# -*- coding: utf-8 -*-
"""Tela inicial para escolher o modelo de pastas, onde criar, os nomes das pastas mãe e o SRC.
v0.0.0: o modelo pode ter várias pastas mãe; cada uma ganha um campo de nome (ex.: o nome da fazenda)."""
import os
import re

from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QVBoxLayout, QWidget,
)

from .estilo import (
    PainelPendencias, alertar, botao_principal, botao_secundario, cabecalho,
    configurar_caminho, confirmar, icone_tema, preparar_dialogo, secao,
)


class TelaInicial(QDialog):
    def __init__(self, plugin, pasta_antiga="", srid_antigo="", parent=None):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin = plugin
        self.campos_maes = []   # [(nome no modelo, QLineEdit, valor sugerido)]
        self._modelo_campos = None; self._digitados = {}   # nomes digitados, por modelo (voltar ao modelo devolve os nomes)
        self.nome = None        # campo da pasta mãe onde ficam as camadas (ou o primeiro)
        preparar_dialogo(self, "tela_inicial", "Norte Agro - Configurar pasta do mapa", (620, 420))
        self.resize(760, 640)

        raiz = QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho(
            "Configurar pasta do mapa",
            "Escolha o modelo de pastas, onde criar e o nome de cada pasta mãe (por exemplo, o nome da fazenda).",
            os.path.join(os.path.dirname(__file__), "icon.png"),
        ))

        # v3.9.6: modelo de estrutura de pastas do escritório (pastas, camadas e tema de cores).
        raiz.addWidget(secao("1. Modelo de pastas"))
        linha_mod = QHBoxLayout(); self.modelo = QComboBox(); self.modelo.currentIndexChanged.connect(self._descrever_modelo)
        editar = botao_secundario("Modelos...", self); editar.clicked.connect(self._editar_modelos)
        linha_mod.addWidget(self.modelo, 1); linha_mod.addWidget(editar)
        form_mod = QFormLayout(); form_mod.addRow("Modelo:", linha_mod); raiz.addLayout(form_mod)
        self.modelo_info = QLabel(); self.modelo_info.setProperty("naSubtitle", True); self.modelo_info.setWordWrap(True); raiz.addWidget(self.modelo_info)

        raiz.addWidget(secao("2. Onde criar"))
        form = QFormLayout(); form.setHorizontalSpacing(12); form.setVerticalSpacing(8); raiz.addLayout(form)
        linha_local = QHBoxLayout()
        self.local = QLineEdit(); self.local.setReadOnly(True); self.local.setToolTip("Pasta onde as pastas mãe do modelo serão criadas (ex.: a pasta dos clientes).")
        escolher = botao_secundario("Escolher...", self); escolher.setIcon(icone_tema("/mActionFileOpen.svg")); escolher.clicked.connect(self.escolher_local)
        linha_local.addWidget(self.local,1); linha_local.addWidget(escolher); form.addRow("Criar dentro de:", linha_local)

        raiz.addWidget(secao("3. Nomes das pastas mãe"))
        self.caixa_maes = QWidget(); self.form_maes = QFormLayout(self.caixa_maes); self.form_maes.setContentsMargins(0, 0, 0, 0)
        self.form_maes.setHorizontalSpacing(12); self.form_maes.setVerticalSpacing(8); raiz.addWidget(self.caixa_maes)
        self.sem_maes = QLabel("Este modelo não tem pasta mãe: as pastas vão direto na pasta escolhida acima.")
        self.sem_maes.setProperty("naSubtitle", True); self.sem_maes.setWordWrap(True); raiz.addWidget(self.sem_maes)
        form_mapa = QFormLayout(); raiz.addLayout(form_mapa)
        self.caminho_mapa = QLabel(); self.caminho_mapa.setProperty("naSubtitle", True); self.caminho_mapa.setWordWrap(True)
        self.caminho_mapa.setToolTip("Onde o plugin grava as camadas do QGIS. Muda em Modelos > Estrutura de pastas > Pasta do mapa aqui.")
        form_mapa.addRow("Camadas do QGIS em:", self.caminho_mapa)

        raiz.addWidget(secao("4. Sistema de referência"))
        self.src = QComboBox()
        self.src.addItem("EPSG:31982 - SIRGAS 2000 / UTM 22S", "EPSG:31982")
        self.src.addItem("EPSG:31983 - SIRGAS 2000 / UTM 23S", "EPSG:31983")
        self.src.setToolTip("SRC usado na criação das camadas do mapa.")
        form_src = QFormLayout(); form_src.addRow("SRC:", self.src); raiz.addLayout(form_src)

        self.pendencias = PainelPendencias(self); raiz.addWidget(self.pendencias)
        raiz.addStretch(1)
        botoes = QHBoxLayout(); botoes.addStretch()
        cancelar = botao_secundario("Fechar", self); cancelar.clicked.connect(self.reject)
        self.criar = botao_principal("Criar estrutura", self); self.criar.clicked.connect(self.confirmar)
        botoes.addWidget(cancelar); botoes.addWidget(self.criar); raiz.addLayout(botoes)
        self._preencher_modelos()

        if pasta_antiga:
            from .modelos import ajustar_ao_disco, modelo_pasta, pastas_maes
            modelo = modelo_pasta(self.modelo.currentData())
            base, ajustado = ajustar_ao_disco(pasta_antiga, modelo)
            if base is not None:
                self.local.setText(base)
                for (orig, campo, _), novo in zip(self.campos_maes, pastas_maes(ajustado)):
                    campo.setText(novo)
            else:
                self.local.setText(os.path.dirname(os.path.abspath(pasta_antiga)))
                if self.nome is not None:
                    self.nome.setText(os.path.basename(os.path.abspath(pasta_antiga)))
        if srid_antigo in ("EPSG:31982", "EPSG:31983"):
            self.src.setCurrentIndex(0 if srid_antigo == "EPSG:31982" else 1)
        self.local.textChanged.connect(self._validar)
        self._validar()

    def _preencher_modelos(self, manter=None):
        from .modelos import PADRAO, modelos_pasta
        from qgis.core import QgsExpressionContextUtils, QgsProject
        atual = manter or str(QgsExpressionContextUtils.projectScope(QgsProject.instance()).variable("norteagro_modelo_pasta") or PADRAO)
        self.modelo.blockSignals(True); self.modelo.clear()
        for m in modelos_pasta():
            self.modelo.addItem(m["nome"], m["nome"])
        i = self.modelo.findData(atual); self.modelo.setCurrentIndex(i if i >= 0 else 0); self.modelo.blockSignals(False)
        self._descrever_modelo()

    def _modelo_normalizado(self):
        from .modelos import modelo_pasta, normalizar_modelo_pasta
        m = modelo_pasta(self.modelo.currentData())
        return normalizar_modelo_pasta(m) if m else None

    def _descrever_modelo(self, *_):
        from .modelos import pastas_do_plugin
        n = self._modelo_normalizado()
        if not n:
            self.modelo_info.setText(""); self._montar_campos(None); return
        mapa = n["pasta_mapa"]
        extras = [(mapa + "/" + f) if mapa else f for f in pastas_do_plugin(n)]
        texto = "Pastas: " + (", ".join(n["pastas"] + extras) or "nenhuma")
        if not n["gerar_kml"]: texto += " | Sem KML automático (o modelo não tem pasta kml na pasta do mapa)"
        texto += f" | Camadas: {len(n['camadas'])}" if n["camadas"] else " | Camadas: escolhidas depois, em Criar/gerenciar camadas"
        if n["tema_cores"]: texto += f" | Tema de cores: {n['tema_cores']}"
        self.modelo_info.setText(texto)
        self._montar_campos(n)
        if hasattr(self, "criar"):
            self._validar()

    def _montar_campos(self, n):
        """Um campo de nome para cada pasta mãe do modelo. O que a pessoa já digitou é mantido ao trocar de modelo:
        voltando a um modelo, voltam os nomes dele; num modelo novo, os campos seguem a mesma ordem."""
        from .modelos import pastas_maes
        anteriores = [(c.text().strip(), sugerido) for _, c, sugerido in self.campos_maes]
        if self._modelo_campos is not None:
            self._digitados[self._modelo_campos] = {orig: c.text() for orig, c, _ in self.campos_maes if c.text().strip() != orig}
        self._modelo_campos = n["nome"] if n else None
        memoria = self._digitados.get(self._modelo_campos)
        while self.form_maes.rowCount():
            self.form_maes.removeRow(0)
        self.campos_maes = []; self.nome = None
        maes = pastas_maes(n) if n else []
        mae_mapa = (n["pasta_mapa"].split("/")[0] if n and n["pasta_mapa"] else "").casefold()
        for i, nome in enumerate(maes):
            campo = QLineEdit(nome); campo.setPlaceholderText("Ex.: Fazenda Norte")
            campo.setToolTip(f'No modelo esta pasta mãe se chama "{nome}". Troque, por exemplo, pelo nome da fazenda.')
            if memoria and nome in memoria:
                campo.setText(memoria[nome])
            elif i < len(anteriores) and anteriores[i][0] and anteriores[i][0] != anteriores[i][1]:
                campo.setText(anteriores[i][0])
            campo.textChanged.connect(self._validar)
            rotulo = f"Pasta mãe {i + 1}" + (" (camadas)" if nome.casefold() == mae_mapa else "") + ":"
            self.form_maes.addRow(rotulo, campo); self.campos_maes.append((nome, campo, nome))
            if self.nome is None or nome.casefold() == mae_mapa:
                self.nome = campo
        self.sem_maes.setVisible(not maes)

    def nomes_maes(self):
        """{nome no modelo: nome digitado}."""
        return {orig: campo.text().strip() for orig, campo, _ in self.campos_maes}

    def _modelo_final(self):
        from .modelos import modelo_pasta, renomear_maes
        m = modelo_pasta(self.modelo.currentData())
        if not m:
            return None
        final = renomear_maes(m, self.nomes_maes()); final["nome"] = m["nome"]
        return final

    def _pasta_mapa_final(self, base):
        from .modelos import caminho_pasta_mapa
        m = self._modelo_final()
        return caminho_pasta_mapa(base, m) if m else base

    def _editar_modelos(self):
        atual = self.modelo.currentData(); self.plugin.abrir_modelos(self, 0); self._preencher_modelos(atual)

    def escolher_local(self):
        inicio = self.local.text() or os.path.expanduser("~")
        pasta = QFileDialog.getExistingDirectory(self, "Escolha onde criar as pastas", inicio)
        if pasta:
            self.local.setText(pasta)

    @staticmethod
    def nome_valido(nome):
        nome = nome.strip()
        return bool(nome) and not bool(re.search(r'[\\/:*?"<>|]', nome)) and not nome.endswith(".")

    def _validar(self):
        if not hasattr(self, "criar"):
            return
        local = self.local.text().strip(); pend = []
        if not os.path.isdir(local): pend.append("Escolha onde criar as pastas (Criar dentro de).")
        nomes = [c.text().strip() for _, c, _ in self.campos_maes]
        for i, nome in enumerate(nomes):
            if not self.nome_valido(nome):
                pend.append(f'Pasta mãe {i + 1}: informe um nome válido, sem \\ / : * ? " < > | e sem ponto no final.')
        if len({x.casefold() for x in nomes}) != len(nomes):
            pend.append("Duas pastas mãe estão com o mesmo nome.")
        if local and not pend:
            mapa = self._pasta_mapa_final(local)
            configurar_caminho(self.caminho_mapa, "a própria pasta escolhida" if os.path.normcase(mapa) == os.path.normcase(local) else mapa, 90)
        else:
            configurar_caminho(self.caminho_mapa, "", 90)
        self.pendencias.definir(pend); self.criar.setEnabled(not pend)

    def confirmar(self):
        self._validar()
        if not self.criar.isEnabled(): return
        local = self.local.text().strip(); modelo = self._modelo_final()
        mapa = os.path.abspath(self._pasta_mapa_final(local))
        if os.path.exists(mapa) and os.path.normcase(mapa) != os.path.normcase(os.path.abspath(local)) or \
                os.path.isdir(os.path.join(mapa, "shapefiles")):
            frase = "A pasta já existe e contém a estrutura shapefiles. Usar a pasta existente?" if os.path.isdir(os.path.join(mapa,"shapefiles")) else "A pasta já existe. Criar a estrutura Norte Agro dentro dela?"
            if not confirmar(self, "Usar pasta existente", frase, "Usar pasta" if os.path.isdir(os.path.join(mapa,"shapefiles")) else "Criar estrutura"):
                return
        if self.plugin.configurar_pasta(mapa, self.src.currentData(), self, modelo=modelo, nomes=self.nomes_maes()): self.accept()
