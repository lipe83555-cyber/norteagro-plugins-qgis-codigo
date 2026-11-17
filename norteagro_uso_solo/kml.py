# -*- coding: utf-8 -*-
"""Espelho KML automático e seguro das camadas gerenciadas pelo plugin."""
from . import compat
import os
import shutil
from datetime import datetime

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QTimer
from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsMessageLog,
    QgsProject, QgsVectorFileWriter, QgsVectorLayer,
)


class GerenciadorKML:
    """Guarda somente IDs/slots; nunca mantém QgsVectorLayer entre ações."""

    def __init__(self, plugin):
        self.plugin = plugin
        self._slots = {}  # layer_id -> {slot, arquivo, kml_dir}
        self._sinais_registrados = False

    def log(self, texto, nivel=compat.MSG_CRITICO):
        QgsMessageLog.logMessage(str(texto), "NorteAgro", nivel)

    def registrar_sinais(self):
        if self._sinais_registrados:
            return
        projeto = QgsProject.instance()
        projeto.layersWillBeRemoved.connect(self._antes_remover_camadas)
        projeto.cleared.connect(self._projeto_limpo)
        projeto.readProject.connect(self._projeto_lido)
        self._sinais_registrados = True

    def desregistrar_sinais(self):
        if not self._sinais_registrados:
            return
        projeto = QgsProject.instance()
        for sinal, slot in (
            (projeto.layersWillBeRemoved, self._antes_remover_camadas),
            (projeto.cleared, self._projeto_limpo),
            (projeto.readProject, self._projeto_lido),
        ):
            try:
                sinal.disconnect(slot)
            except Exception:
                pass
        self._sinais_registrados = False

    @staticmethod
    def _layer_id(camada_ou_id):
        if isinstance(camada_ou_id, str):
            return camada_ou_id
        if camada_ou_id is None:
            return ""
        try:
            if sip.isdeleted(camada_ou_id):
                return ""
            return str(camada_ou_id.id())
        except (RuntimeError, Exception):
            return ""

    def desconectar(self, camada_ou_id):
        """Remove o registro mesmo quando o wrapper C++ da camada já foi apagado."""
        layer_id = self._layer_id(camada_ou_id)
        if not layer_id and isinstance(camada_ou_id, str):
            layer_id = camada_ou_id
        if not layer_id:
            return
        registro = self._slots.pop(layer_id, None)
        if not registro:
            return
        camada = QgsProject.instance().mapLayer(layer_id)
        if camada is None:
            return
        try:
            if sip.isdeleted(camada):
                return
            camada.afterCommitChanges.disconnect(registro["slot"])
        except (RuntimeError, TypeError):
            pass
        except Exception:
            pass

    def desconectar_todos(self):
        for layer_id in list(self._slots):
            self.desconectar(layer_id)
        self._slots.clear()

    def _antes_remover_camadas(self, ids_ou_camadas):
        """Aceita ambas as sobrecargas de QgsProject.layersWillBeRemoved no PyQt."""
        for item in list(ids_ou_camadas or []):
            layer_id = str(item) if isinstance(item, str) else self._layer_id(item)
            if layer_id:
                self.desconectar(layer_id)

    def _projeto_limpo(self, *args):
        # layersWillBeRemoved normalmente já desconectou os sinais. Aqui só eliminamos
        # qualquer registro residual, sem tocar em wrappers antigos.
        self._slots.clear()

    def _projeto_lido(self, *args):
        self._slots.clear()
        try:
            self.plugin.adotar_camadas_antigas()
        except Exception as exc:
            self.log(f"Falha ao adotar camadas antigas após abrir projeto: {exc}")
        QTimer.singleShot(0, self.reconectar)

    def _apos_commit(self, layer_id):
        camada = QgsProject.instance().mapLayer(layer_id)
        if camada is None:
            self._slots.pop(layer_id, None)
            return
        try:
            if sip.isdeleted(camada):
                self._slots.pop(layer_id, None)
                return
            self.exportar_automatico(camada)
        except RuntimeError:
            self._slots.pop(layer_id, None)
        except Exception as exc:
            self.log(f"Falha no espelho KML após commit: {exc}")

    def conectar(self, camada):
        try:
            if camada is None or sip.isdeleted(camada) or not isinstance(camada, QgsVectorLayer):
                return
            layer_id = str(camada.id())
            arquivo = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
            if not arquivo:
                return
            if layer_id in self._slots:
                return
            slot = lambda lid=layer_id: self._apos_commit(lid)
            camada.afterCommitChanges.connect(slot)
            self._slots[layer_id] = {
                "slot": slot,
                "arquivo": arquivo,
                "kml_dir": str(camada.customProperty("norteagro/kml_dir", "") or ""),
            }
        except RuntimeError:
            return

    @staticmethod
    def _fonte_dentro_da_pasta(camada, pasta):
        try:
            fonte = os.path.abspath(str(camada.dataProvider().dataSourceUri()).split("|", 1)[0])
            raiz = os.path.abspath(pasta)
            return os.path.commonpath([os.path.normcase(fonte), os.path.normcase(raiz)]) == os.path.normcase(raiz)
        except Exception:
            return False

    def diretorio_kml(self, camada):
        """Retorna a raiz KML, sem a subpasta da camada."""
        try:
            proprio = str(camada.customProperty("norteagro/kml_dir", "") or "").strip()
        except RuntimeError:
            return ""
        if proprio:
            return os.path.abspath(proprio)
        pasta, _ = self.plugin.memoria_basica()
        return os.path.join(pasta, "kml") if pasta else ""

    def pasta_camada_real(self, camada):
        """Subpasta do KML = pasta real onde o SHP está, nunca o nome exibido atual."""
        fonte = self.plugin._fonte(camada)
        if fonte and fonte.lower().endswith(".shp"):
            nome = os.path.basename(os.path.dirname(fonte))
            if nome:
                return nome
        try:
            return str(camada.customProperty("norteagro/pasta_camada", "") or "").strip()
        except RuntimeError:
            return ""

    def caminho_kml(self, camada):
        arquivo = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
        raiz = self.diretorio_kml(camada)
        pasta_camada = self.pasta_camada_real(camada)
        if not arquivo or not raiz or not pasta_camada:
            return ""
        return os.path.join(raiz, pasta_camada, arquivo + ".kml")

    def _migrar_kml_solto(self, camada, destino):
        """Preserva KML legado solto em kml/_antigos/AAAA-MM-DD antes da nova gravação."""
        raiz = self.diretorio_kml(camada)
        arquivo = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
        if not raiz or not arquivo:
            return
        antigo = os.path.join(raiz, arquivo + ".kml")
        if not os.path.isfile(antigo) or os.path.normcase(os.path.abspath(antigo)) == os.path.normcase(os.path.abspath(destino)):
            return
        pasta_antigos = os.path.join(raiz, "_antigos", datetime.now().strftime("%Y-%m-%d"))
        os.makedirs(pasta_antigos, exist_ok=True)
        alvo = os.path.join(pasta_antigos, arquivo + ".kml")
        if os.path.exists(alvo):
            base, ext = os.path.splitext(alvo)
            alvo = base + "_" + datetime.now().strftime("%H%M%S") + ext
        shutil.move(antigo, alvo)
        self.log(f"KML legado movido para {alvo}", compat.MSG_INFO)

    def reconectar(self):
        """Reconecta normais e avulsas apenas com camadas vivas do projeto atual."""
        self.desconectar_todos()
        pasta, _ = self.plugin.memoria_basica()
        raiz_shp = os.path.join(pasta, "shapefiles") if pasta and os.path.isdir(pasta) else ""
        indice = self.plugin.indice_atual()
        total = 0; mudou = False  # v3.9.10: só marca o projeto como alterado se gravou alguma propriedade
        for camada in list(QgsProject.instance().mapLayers().values()):
            if not isinstance(camada, QgsVectorLayer):
                continue
            try:
                if sip.isdeleted(camada):
                    continue
                arquivo = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
                if arquivo:
                    if not camada.customProperty("norteagro/pasta_camada", ""):
                        pasta_real = self.pasta_camada_real(camada)
                        if pasta_real:
                            camada.setCustomProperty("norteagro/pasta_camada", pasta_real); mudou = True
                    self.conectar(camada); total += 1; continue
                if not raiz_shp or not self._fonte_dentro_da_pasta(camada, raiz_shp):
                    continue
                fonte = self.plugin._fonte(camada)
                if not fonte.lower().endswith(".shp"):
                    continue
                arquivo = os.path.splitext(os.path.basename(fonte))[0].upper()
                entrada = indice.get(arquivo)
                camada.setCustomProperty("norteagro/arquivo", arquivo)
                camada.setCustomProperty("norteagro/nome", entrada["nome"] if entrada else arquivo)
                camada.setCustomProperty("norteagro/pasta_camada", os.path.basename(os.path.dirname(fonte)))
                self.conectar(camada); total += 1; mudou = True
            except RuntimeError:
                continue
        if mudou:
            QgsProject.instance().setDirty(True)
        return total

    def automatico(self, camada):
        """v3.9.9: cópia KML automática. Camada criada em outra pasta (kml_dir próprio) segue
        sempre; nas da pasta do mapa vale a escolha do modelo de pastas (norteagro_kml_automatico)."""
        try:
            if str(camada.customProperty("norteagro/kml_dir", "") or "").strip():
                return True
        except RuntimeError:
            return False
        from qgis.core import QgsExpressionContextUtils
        return str(QgsExpressionContextUtils.projectScope(QgsProject.instance()).variable("norteagro_kml_automatico") or "1") != "0"

    def exportar_automatico(self, camada):
        """Grava o espelho KML só quando o projeto usa KML automático."""
        if not self.automatico(camada):
            return False, "KML automático desligado neste projeto.", ""
        return self.exportar(camada, silencioso=True)

    def exportar(self, camada, silencioso=False):
        """Exporta EPSG:4326 com simbologia para kml/<pasta real da camada>/<ARQUIVO>.kml."""
        try:
            if camada is None or sip.isdeleted(camada):
                return False, "Camada não está mais no projeto.", ""
            arquivo = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
            destino = self.caminho_kml(camada)
            if not arquivo or not destino:
                return False, "Pasta KML, pasta da camada ou identificação ausente.", ""
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            self._migrar_kml_solto(camada, destino)
            op = QgsVectorFileWriter.SaveVectorOptions()
            op.driverName = "KML"; op.fileEncoding = "UTF-8"
            op.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
            op.symbologyExport = compat.SIMBOLOGIA_POR_FEICAO
            op.ct = QgsCoordinateTransform(
                camada.crs(), QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsProject.instance().transformContext()
            )
            resultado = QgsVectorFileWriter.writeAsVectorFormatV3(
                camada, destino, QgsProject.instance().transformContext(), op
            )
            if resultado[0] != QgsVectorFileWriter.WriterError.NoError:
                detalhe = resultado[1] if len(resultado) > 1 else str(resultado[0])
                raise RuntimeError(str(detalhe))
            return True, "", destino
        except Exception as exc:
            arquivo = ""
            try:
                arquivo = str(camada.customProperty("norteagro/arquivo", "") or "")
            except Exception:
                pass
            self.log(f"Erro ao exportar KML de {arquivo or 'camada'}: {exc}")
            if not silencioso:
                self.plugin.aviso_erro(f"Falha ao exportar KML de {arquivo or 'camada'}:\n{exc}")
            return False, str(exc), ""

    def camadas_para_exportar(self):
        selecionadas = list(self.plugin.iface.layerTreeView().selectedLayers() or [])
        base = selecionadas if selecionadas else list(QgsProject.instance().mapLayers().values())
        saida = []
        for camada in base:
            try:
                if isinstance(camada, QgsVectorLayer) and not sip.isdeleted(camada) and camada.customProperty("norteagro/arquivo", ""):
                    saida.append(camada)
            except RuntimeError:
                continue
        return saida

    def exportar_todos(self):
        gravados, falhas = [], []
        for camada in self.camadas_para_exportar():
            certo, erro, destino = self.exportar(camada, silencioso=True)
            if certo:
                gravados.append(destino)
            else:
                try:
                    nome = camada.name()
                except Exception:
                    nome = "camada"
                falhas.append(f"{nome}: {erro}")
        return gravados, falhas
