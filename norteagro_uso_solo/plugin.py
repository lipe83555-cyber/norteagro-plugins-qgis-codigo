# -*- coding: utf-8 -*-
"""Registro e controlador principal do plugin Norte Agro - Uso do Solo."""
from . import compat
import glob
import json
import os
import re
import shutil
import time
import unicodedata
from datetime import datetime
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog
from .compat import QAction
from qgis.core import (
    QgsApplication, QgsMapLayer,
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransformContext, QgsExpressionContextUtils, QgsField,
    QgsFields, QgsLayerTreeLayer, QgsMessageLog, QgsProject, QgsSingleSymbolRenderer,
    QgsVectorFileWriter, QgsVectorLayer
)
from .catalogo import (
    GRUPOS_BASE, apelidos_manuais_projeto, catalogo_completo, extras_projeto,
    indice_catalogo, indice_reconhecimento, limpar_nome_pasta, pasta_camada_entrada,
    salvar_extras_projeto, simbolo_entrada, verificar_catalogo
)
from .kml import GerenciadorKML
from .estilo import alertar, confirmar, erro, sucesso


# grupo de menu compartilhado com o plugin "Layout de plantas" (norteagro_layout_ia)
MENU = "&Norte Agro Projetos"

class NorteAgroPlugin:
    """Coordena telas, arquivos, grupos, memória por projeto e KML."""

    def __init__(self, iface):
        self.iface = iface
        self.acao = None
        self.kml = GerenciadorKML(self)
        self._catalogo_aviso_assinatura = ""
        self._catalogo_invalidos = set()

    def initGui(self):
        """Registra um único acesso, no grupo de menu "Norte Agro Projetos" (o mesmo do plugin
        Layout de plantas, que fica ao lado) e na barra de ferramentas."""
        try:  # cadastra o repositório da Norte Agro no QGIS (aviso de atualização e instalação pelo nome)
            from .repositorio_norteagro import avisar_se_precisa_acesso, registrar_repositorio
            registrar_repositorio()
            avisar_se_precisa_acesso(self.iface)
        except Exception:
            pass
        try:  # vídeos da Ajuda que vieram na atualização: baixa em segundo plano os que faltam
            from .videos_ajuda import iniciar_sincronizacao
            iniciar_sincronizacao()
        except Exception:
            pass
        icone = QIcon(os.path.join(os.path.dirname(__file__), "icon.png"))
        self.acao = QAction(icone, "Criar camadas e calcular áreas", self.iface.mainWindow())
        self.acao.setToolTip("Norte Agro Projetos: criar camadas e calcular áreas")
        self.acao.triggered.connect(self.abrir)
        self.iface.addToolBarIcon(self.acao)
        self.iface.addPluginToMenu(MENU, self.acao)
        # v3.9.8: um único item no menu (Norte Agro > Uso do Solo). Referências e Modelos
        # ficam dentro do plugin: tela inicial, Ferramentas, Configurar pasta e Calcular áreas.
        self.acao_referencias = None
        self.acao_modelos = None
        # v0.6.0: os vídeos ficam dentro da Ajuda (?), ao lado de cada assunto - nada a mais no menu.
        self.acao_videos = None
        self.kml.registrar_sinais()
        self._verificar_catalogo_ui()
        QTimer.singleShot(0, self.kml.reconectar)

    def unload(self):
        try:
            from .videos_ajuda import parar_sincronizacao
            parar_sincronizacao()
        except Exception:
            pass
        self.kml.desconectar_todos()
        self.kml.desregistrar_sinais()
        if self.acao:
            try:
                self.acao.triggered.disconnect(self.abrir)
            except Exception:
                pass
            self.iface.removeToolBarIcon(self.acao)
            self.iface.removePluginMenu(MENU, self.acao)
            self.acao = None
        if getattr(self, "acao_referencias", None):
            try:
                self.iface.removePluginMenu(MENU, self.acao_referencias)
            except Exception:
                pass
            self.acao_referencias = None
        if getattr(self, "acao_modelos", None):
            try:
                self.iface.removePluginMenu(MENU, self.acao_modelos)
            except Exception:
                pass
            self.acao_modelos = None
        if getattr(self, "acao_videos", None):
            try:
                self.iface.removePluginMenu(MENU, self.acao_videos)
            except Exception:
                pass
            self.acao_videos = None

    def log(self, texto, nivel=compat.MSG_CRITICO):
        QgsMessageLog.logMessage(str(texto), "NorteAgro", nivel)

    def aviso_erro(self, texto):
        erro(self.iface.mainWindow(), "Norte Agro", str(texto))

    def memoria_basica(self):
        projeto = QgsProject.instance()
        escopo = QgsExpressionContextUtils.projectScope(projeto)
        pasta = str(escopo.variable("norteagro_pasta") or "")
        srid = str(escopo.variable("norteagro_srid") or "")
        return pasta, srid


    def definir_variavel(self, nome, valor):
        projeto = QgsProject.instance()
        QgsExpressionContextUtils.setProjectVariable(projeto, nome, valor)
        projeto.setDirty(True)

    def _verificar_catalogo_ui(self):
        """Audita o catálogo; avisa uma vez por conjunto de problemas e mantém o plugin aberto."""
        try:
            resultado = verificar_catalogo(QgsProject.instance())
            problemas = list(resultado.get("problemas", []))
            self._catalogo_invalidos = set(resultado.get("invalidos", set()))
            assinatura = "\n".join(problemas)
            if problemas:
                for problema in problemas:
                    self.log("Catálogo: " + problema, compat.MSG_AVISO)
                if assinatura != self._catalogo_aviso_assinatura:
                    alertar(
                        self.iface.mainWindow(), "Conferência do catálogo",
                        "Foram encontrados problemas no catálogo. As camadas afetadas ficam desabilitadas para criação até a correção.",
                        problemas[:20]
                    )
                    self._catalogo_aviso_assinatura = assinatura
            else:
                self._catalogo_aviso_assinatura = ""
            return resultado
        except Exception as exc:
            self.log(f"Falha ao verificar catálogo: {exc}")
            return {"problemas": [str(exc)], "invalidos": set()}

    def entrada_valida(self, arquivo):
        return str(arquivo or "").upper() not in self._catalogo_invalidos

    def catalogo_atual(self):
        """Catálogo visível + grupos vazios criados somente neste projeto."""
        self._verificar_catalogo_ui()
        bruto = catalogo_completo(QgsProject.instance())
        saida = {}
        for grupo in GRUPOS_BASE:
            saida[grupo] = bruto.get(grupo, [])
        for grupo in self.grupos_projeto():
            if grupo not in saida:
                saida[grupo] = bruto.get(grupo, [])
        for grupo, itens in bruto.items():
            if grupo not in saida:
                saida[grupo] = itens
        return saida

    def indice_atual(self):
        return indice_catalogo(QgsProject.instance())

    def entrada(self, arquivo):
        return self.indice_atual().get(str(arquivo).upper())

    def grupos_projeto(self):
        """Grupos criados localmente neste .qgz; nunca são configuração global."""
        escopo = QgsExpressionContextUtils.projectScope(QgsProject.instance())
        try:
            dados = json.loads(str(escopo.variable("norteagro_grupos") or "[]"))
            return [str(x).strip() for x in dados if str(x).strip()] if isinstance(dados, list) else []
        except Exception:
            return []

    def salvar_grupos_projeto(self, grupos):
        limpos = []
        for nome in grupos:
            nome = str(nome).strip()
            if nome and nome not in limpos and nome not in GRUPOS_BASE:
                limpos.append(nome)
        QgsExpressionContextUtils.setProjectVariable(
            QgsProject.instance(), "norteagro_grupos", json.dumps(limpos, ensure_ascii=False)
        )
        QgsProject.instance().setDirty(True)

    @staticmethod
    def chave_grupo(nome):
        texto = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode("ascii")
        return " ".join(texto.casefold().split())

    def nomes_grupos_existentes(self):
        nomes = list(self.catalogo_atual().keys())
        for no in QgsProject.instance().layerTreeRoot().children():
            if hasattr(no, "name") and no.name() not in nomes:
                nomes.append(no.name())
        return nomes

    def criar_grupo_projeto(self, nome):
        """Cria somente o grupo na árvore e grava seu nome no projeto; não cria pasta."""
        nome = str(nome or "").strip()
        if not nome:
            return False, "O nome do grupo não pode ficar vazio."
        chave = self.chave_grupo(nome)
        if any(self.chave_grupo(x) == chave for x in self.nomes_grupos_existentes()):
            return False, "Já existe um grupo com esse nome."
        grupos = self.grupos_projeto(); grupos.append(nome); self.salvar_grupos_projeto(grupos)
        raiz = QgsProject.instance().layerTreeRoot()
        # Insere depois dos grupos padrão e dos grupos locais já existentes.
        conhecidos = set(GRUPOS_BASE) | set(grupos)
        pos = 0
        for i, no in enumerate(raiz.children()):
            if isinstance(no, type(raiz)) and no.name() in conhecidos:
                pos = i + 1
            elif hasattr(no, "name") and no.name() in conhecidos:
                pos = i + 1
        raiz.insertGroup(pos, nome)
        QgsProject.instance().setDirty(True)
        return True, ""

    def grupo_pode_ser_apagado(self, nome):
        if not nome or nome in GRUPOS_BASE:
            return False
        if nome in self.grupos_projeto():
            return True
        return any(str(x.get("grupo", "")) == nome for x in extras_projeto(QgsProject.instance()))

    def _mover_com_retry(self, origem, destino, limite_s=15.0):
        """v3.9.4: tenta por até 15 s (Google Drive/antivírus seguram arquivos por instantes)."""
        import gc
        erro = None; inicio = time.time()
        while True:
            try:
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                shutil.move(origem, destino)
                return True, ""
            except Exception as exc:
                erro = exc
                if time.time() - inicio >= limite_s:
                    return False, str(erro)
                QApplication.processEvents(); gc.collect(); time.sleep(0.5)

    def dados_grupo_apagar(self, nome):
        """Monta a prévia da exclusão, incluindo camadas externas arrastadas para o grupo."""
        pasta, _ = self.memoria_basica(); raiz_shp = os.path.join(pasta, "shapefiles") if pasta else ""
        arvore = QgsProject.instance().layerTreeRoot(); grupo = arvore.findGroup(nome)
        internos, externos, vistos = [], [], set()
        if grupo:
            for no in grupo.findLayers():
                camada = no.layer()
                if not camada: continue
                fonte = self._fonte(camada)
                arquivo = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
                if not arquivo and fonte.lower().endswith(".shp"):
                    arquivo = os.path.splitext(os.path.basename(fonte))[0].upper()
                registro = {"layer_id": camada.id(), "nome": camada.name(), "arquivo": arquivo, "fonte": fonte}
                if fonte and raiz_shp and self._dentro(fonte, raiz_shp): internos.append(registro)
                else: externos.append(registro)
                if arquivo: vistos.add(arquivo)
        # Inclui extras locais do grupo que estejam no disco mas não estejam carregados.
        for entrada in extras_projeto(QgsProject.instance()):
            arquivo = str(entrada.get("arquivo", "")).upper()
            if str(entrada.get("grupo", "")) != nome or not arquivo or arquivo in vistos: continue
            # Se a camada está carregada em outro grupo, ela não pertence mais visualmente ao grupo apagado.
            if self.camada_plugin(arquivo): continue
            shp = self.caminho_shp(arquivo)
            internos.append({"layer_id": "", "nome": entrada.get("nome", arquivo), "arquivo": arquivo, "fonte": shp})
            vistos.add(arquivo)
        return internos, externos

    def apagar_grupo_projeto(self, nome):
        """Apaga grupo local; só dados dentro da pasta do mapa são movidos para _apagados."""
        if not self.grupo_pode_ser_apagado(nome):
            return {"erro": "Este grupo não pode ser apagado."}
        from .operacoes import remover_camada_segura
        projeto = QgsProject.instance(); pasta, _ = self.memoria_basica()
        raiz_shp = os.path.join(pasta, "shapefiles") if pasta else ""
        instante = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        apagados = os.path.join(pasta, "_apagados", instante) if pasta else ""
        internos, externos = self.dados_grupo_apagar(nome)
        falhas, movidos, removidos = [], [], []

        # Resolve por ID somente na hora da ação; nenhum QgsVectorLayer fica guardado entre ações.
        for reg in internos + externos:
            lid = str(reg.get("layer_id") or "")
            if not lid:
                continue
            camada = projeto.mapLayer(lid)
            if camada is None:
                continue
            mover = reg in internos
            res = remover_camada_segura(self, camada, mover_interna=mover, instante=instante)
            if res.get("falha"):
                falhas.append(f"{reg.get('nome')}: {res['falha']}")
            elif res.get("movida"):
                movidos.append(f"{reg.get('nome')} → {res.get('destino')}")
            else:
                removidos.append(f"{reg.get('nome')} ({reg.get('fonte') or 'camada temporária/serviço'})")

        # Extras locais não carregados: move pela fonte real já descoberta, sem inventar nome de pasta.
        for reg in internos:
            if reg.get("layer_id"):
                continue
            fonte = str(reg.get("fonte") or "")
            arquivo = str(reg.get("arquivo") or "").upper()
            if not fonte or not raiz_shp or not self._dentro(fonte, raiz_shp):
                continue
            pasta_camada = os.path.dirname(fonte)
            if not os.path.isdir(pasta_camada):
                continue
            nome_pasta = os.path.basename(pasta_camada)
            destino_shp = os.path.join(apagados, "shapefiles", nome_pasta)
            ok, erro = self._mover_com_retry(pasta_camada, destino_shp)
            if not ok:
                falhas.append(f"{reg.get('nome')}: {erro}"); continue
            # Subpasta KML segue a pasta real do SHP.
            kml_sub = os.path.join(pasta, "kml", nome_pasta)
            if os.path.isdir(kml_sub):
                ok, erro = self._mover_com_retry(kml_sub, os.path.join(apagados, "kml", nome_pasta))
                if not ok:
                    falhas.append(f"KML {arquivo}: {erro}")
            elif arquivo:
                legado = os.path.join(pasta, "kml", arquivo + ".kml")
                if os.path.isfile(legado):
                    destino_legado = os.path.join(apagados, "kml", nome_pasta, arquivo + ".kml")
                    ok, erro = self._mover_com_retry(legado, destino_legado)
                    if not ok:
                        falhas.append(f"KML legado {arquivo}: {erro}")
            movidos.append(f"{reg.get('nome')} → {destino_shp}")

        arqs = {str(r.get("arquivo") or "").upper() for r in internos + externos if r.get("arquivo")}
        extras = [x for x in extras_projeto(projeto)
                  if str(x.get("grupo", "")) != nome and str(x.get("arquivo", "")).upper() not in arqs]
        salvar_extras_projeto(projeto, extras)
        self.salvar_grupos_projeto([g for g in self.grupos_projeto() if g != nome])
        grupo = projeto.layerTreeRoot().findGroup(nome)
        if grupo:
            projeto.layerTreeRoot().removeChildNode(grupo)
        projeto.setDirty(True)
        if projeto.fileName():
            if not projeto.write():
                falhas.append("O projeto não pôde ser salvo ao final.")
        elif not self.garantir_projeto_salvo(self.iface.mainWindow()):
            falhas.append("O projeto não foi salvo ao final.")
        return {"movidos": movidos, "removidos": removidos, "falhas": falhas, "apagados": apagados,
                "camadas": len(internos) + len(externos)}

    def preparar_estrutura(self, pasta, modelo=None):
        """v3.9.6: shapefiles, kml e projetos sempre; demais pastas vêm do modelo (padrão: layout e plantas pdf)."""
        from .modelos import criar_pastas
        os.makedirs(pasta, exist_ok=True)
        return criar_pastas(pasta, modelo)

    @staticmethod
    def _nome_imovel(pasta, modelo=None):
        """Nome sugerido para o .qgz. v0.0.0: o nome da pasta mãe onde ficam as camadas (ex.: o nome da fazenda);
        se ela ainda se chama "MAPA USO DO SOLO", o nome da pasta de cima, como antes."""
        try:
            from .modelos import NOME_MAE_PADRAO, modelo_pasta, pasta_mae
            if modelo is None:
                modelo = modelo_pasta(str(QgsExpressionContextUtils.projectScope(QgsProject.instance()).variable("norteagro_modelo_pasta") or ""))
            mae = pasta_mae(pasta, modelo) if modelo else None
            if mae and os.path.basename(mae.rstrip(os.sep)).casefold() != NOME_MAE_PADRAO.casefold():
                return os.path.basename(mae.rstrip(os.sep)) or "projeto"
        except Exception:
            pass
        return os.path.basename(os.path.dirname(pasta.rstrip(os.sep))) or "projeto"

    @staticmethod
    def _pasta_projetos(pasta):
        """v3.9.9: sugere salvar o .qgz em projetos/ se existir; senão, na própria pasta do mapa."""
        return os.path.join(pasta, "projetos") if os.path.isdir(os.path.join(pasta, "projetos")) else pasta

    @staticmethod
    def _gravar_opcoes_modelo(modelo):
        from .modelos import normalizar_modelo_pasta
        m = normalizar_modelo_pasta(modelo)
        QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), "norteagro_modelo_pasta", modelo.get("nome", ""))
        QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), "norteagro_kml_automatico", "1" if m["gerar_kml"] else "0")

    def aplicar_modelo_pasta(self, modelo):
        """v3.9.6: cria as pastas, as camadas e aplica o tema de cores de um modelo na pasta do projeto."""
        from .modelos import aplicar_tema, criar_pastas, entradas_camadas_modelo, modelo_pasta, normalizar_modelo_pasta, tema_cores
        modelo = modelo_pasta(modelo) if isinstance(modelo, str) else modelo
        if not modelo:
            raise ValueError("Modelo de pastas não encontrado.")
        try:  # v0.0.0: nomes que as pastas mãe receberam em Configurar pasta (ex.: o nome da fazenda)
            from .modelos import renomear_maes
            guardado = json.loads(str(QgsExpressionContextUtils.projectScope(QgsProject.instance()).variable("norteagro_nomes_maes") or "{}"))
            if guardado.get("modelo") == modelo.get("nome") and guardado.get("nomes"):
                nome = modelo.get("nome"); modelo = renomear_maes(modelo, guardado["nomes"]); modelo["nome"] = nome
        except Exception:
            pass
        pasta, _srid = self.memoria_basica()
        if not pasta or not os.path.isdir(pasta):
            raise RuntimeError("Configure a pasta do mapa antes de aplicar um modelo.")
        from .modelos import camadas_ausentes_modelo
        indice = self.indice_atual()
        resumo = {"pastas": criar_pastas(pasta, modelo), "criadas": [], "carregadas": [], "falhas": [], "tema": None, "tema_ausente": "",
                  "ausentes": camadas_ausentes_modelo(modelo, indice)}
        for entrada, nova in entradas_camadas_modelo(modelo, indice):
            if nova:
                self.salvar_extra_projeto(dict(entrada))
            ok, acao, erro = self.criar_ou_carregar(entrada["arquivo"])
            if not ok:
                resumo["falhas"].append(f"{entrada.get('nome') or entrada['arquivo']}: {erro}")
            else:
                resumo["criadas" if acao == "criada" else "carregadas"].append(entrada.get("nome") or entrada["arquivo"])
        nome_tema = normalizar_modelo_pasta(modelo).get("tema_cores")
        if nome_tema:
            if tema_cores(nome_tema):
                # Só as camadas gravadas na pasta do mapa (nunca camadas externas abertas no projeto).
                from .modelos import camadas_do_plugin
                resumo["tema"] = aplicar_tema(nome_tema, QgsProject.instance(), gravar_qml=True,
                                              camadas=camadas_do_plugin(QgsProject.instance(), so_da_pasta=True))
            else:
                resumo["tema_ausente"] = nome_tema
        self._gravar_opcoes_modelo(modelo)
        QgsProject.instance().setDirty(True)
        return resumo

    @staticmethod
    def texto_resumo_modelo(resumo):
        linhas = []
        if resumo.get("pastas"): linhas.append("Pastas criadas: " + ", ".join(resumo["pastas"]))
        if resumo.get("criadas"): linhas.append(f"Camadas criadas ({len(resumo['criadas'])}): " + ", ".join(resumo["criadas"]))
        if resumo.get("carregadas"): linhas.append(f"Já existiam e foram carregadas ({len(resumo['carregadas'])}): " + ", ".join(resumo["carregadas"]))
        if resumo.get("tema"):
            aplicadas, sem, erros = resumo["tema"]
            linhas.append(f"Tema de cores aplicado em {len(aplicadas)} camada(s)" + (f"; {len(sem)} sem cor no tema mantiveram o estilo" if sem else ""))
            linhas += [f"Cor não aplicada - {e}" for e in erros]
        if resumo.get("tema_ausente"): linhas.append(f'O tema de cores "{resumo["tema_ausente"]}" não existe mais; as cores padrão foram mantidas.')
        if resumo.get("ausentes"): linhas.append("Não estão mais no catálogo (não criadas): " + ", ".join(resumo["ausentes"]))
        linhas += [f"Falhou - {f}" for f in resumo.get("falhas") or []]
        return linhas

    def configurar_pasta(self, pasta, srid, parent=None, modelo=None, nomes=None):
        """Cria estrutura, grava memória apenas no projeto e oferece salvar .qgz.
        v0.0.0: `nomes` = {pasta mãe no modelo: nome usado neste projeto}; fica guardado no projeto."""
        try:
            from .modelos import modelo_pasta
            modelo = modelo_pasta(modelo) if isinstance(modelo, str) else modelo
            pasta = os.path.abspath(pasta)
            self.preparar_estrutura(pasta, modelo)
            projeto = QgsProject.instance()
            if modelo:
                QgsExpressionContextUtils.setProjectVariable(projeto, "norteagro_nomes_maes",
                                                             json.dumps({"modelo": modelo.get("nome", ""), "nomes": nomes or {}}, ensure_ascii=False))
            QgsExpressionContextUtils.setProjectVariable(projeto, "norteagro_pasta", pasta)
            QgsExpressionContextUtils.setProjectVariable(projeto, "norteagro_srid", srid)
            escopo = QgsExpressionContextUtils.projectScope(projeto)
            if escopo.variable("norteagro_extras") is None:
                QgsExpressionContextUtils.setProjectVariable(projeto, "norteagro_extras", "[]")
            projeto.setDirty(True)
            self.kml.desconectar_todos()
            if not projeto.fileName():
                salvar_agora = confirmar(
                    parent or self.iface.mainWindow(), "Salvar projeto QGIS",
                    "O projeto ainda não foi salvo. Salve o .qgz para manter a memória da pasta ao fechar o QGIS.",
                    "Salvar agora", "Continuar sem salvar"
                )
                if salvar_agora:
                    nome_imovel = self._nome_imovel(pasta, modelo)
                    sugerido = os.path.join(self._pasta_projetos(pasta), nome_imovel + ".qgz")
                    arq, _ = QFileDialog.getSaveFileName(
                        parent or self.iface.mainWindow(), "Salvar projeto QGIS", sugerido, "Projeto QGIS (*.qgz)"
                    )
                    if arq:
                        if not arq.lower().endswith(".qgz"):
                            arq += ".qgz"
                        if not projeto.write(arq):
                            alertar(parent or self.iface.mainWindow(), "Projeto não salvo", "Não foi possível salvar o projeto .qgz.")
                else:
                    alertar(parent or self.iface.mainWindow(), "Projeto não salvo", "Sem salvar o projeto, a memória da pasta será perdida ao fechar.")
            self.adotar_camadas_antigas()
            self.kml.reconectar()
            if modelo and (modelo.get("camadas") or modelo.get("tema_cores")):
                resumo = self.aplicar_modelo_pasta(modelo)
                (alertar if (resumo["falhas"] or resumo.get("ausentes")) else sucesso)(parent or self.iface.mainWindow(), "Modelo aplicado",
                    f'Estrutura criada com o modelo "{modelo.get("nome")}".', self.texto_resumo_modelo(resumo))
            elif modelo:
                self._gravar_opcoes_modelo(modelo)
            return True
        except Exception as exc:
            self.log(f"Erro ao configurar pasta: {exc}")
            self.aviso_erro(f"Não foi possível configurar a pasta:\n{exc}")
            return False

    def abrir(self):
        """Ícone principal: sempre mostra a escolha, sem criar/gravar nada."""
        from .tela_escolha import TelaEscolha
        dlg = TelaEscolha(self)
        if not compat.aceito(dlg.exec()):
            return
        if dlg.modo == "gerenciar":
            self.abrir_gerenciamento()
        elif dlg.modo == "avulsa":
            self.abrir_avulsa()
        elif dlg.modo == "areas":
            self.abrir_areas()
        elif dlg.modo == "semad":
            self.abrir_semad()

    def abrir_modelos(self, parent=None, aba=0):
        from .tela_modelos import TelaModelos
        return TelaModelos(self, parent or self.iface.mainWindow(), aba).exec()

    def abrir_referencias(self):
        from .tela_referencias import abrir_referencias
        abrir_referencias(self, self.iface.mainWindow())

    def abrir_gerenciamento(self):
        """Fluxo existente: lista direta se a pasta do projeto for válida."""
        from .tela_inicial import TelaInicial
        from .tela_camadas import TelaCamadas
        pasta, srid = self.memoria_basica()
        if pasta and os.path.isdir(pasta) and srid in ("EPSG:31982", "EPSG:31983"):
            self.adotar_camadas_antigas()
            self.kml.reconectar()
            TelaCamadas(self).exec()
            return
        if pasta and not os.path.isdir(pasta):
            alertar(
                self.iface.mainWindow(), "Pasta não encontrada",
                "A pasta gravada neste projeto não existe mais. Escolha o local novamente."
            )
        dlg = TelaInicial(self, pasta_antiga=pasta, srid_antigo=srid)
        if compat.aceito(dlg.exec()):
            TelaCamadas(self).exec()

    def abrir_semad(self, parent=None):
        """v0.5.0: camadas da SEMAD (SIGA) no imóvel: murundus, APP de relevo (recortadas) e UC (inteiras)."""
        from .tela_semad import TelaSemad
        return TelaSemad(self, parent or self.iface.mainWindow()).exec()

    def abrir_videos(self, parent=None, ferramenta=""):
        """v0.6.0: os vídeos ficam na Ajuda, ao lado do texto de cada assunto."""
        from .tela_ajuda import abrir_ajuda
        return abrir_ajuda(parent or self.iface.mainWindow(), ferramenta or "comecar")

    def abrir_avulsa(self, parent=None):
        """Cria camadas do catálogo em uma pasta escolhida, sem alterar a memória do mapa."""
        from .tela_avulsa import TelaAvulsa
        return TelaAvulsa(self, parent or self.iface.mainWindow()).exec()

    def abrir_areas(self):
        """Acesso direto ao cálculo: não cria pasta e não grava variáveis Norte Agro."""
        from .tela_areas import TelaAreas
        TelaAreas(self, self.iface.mainWindow(), modo_so_calcular=True).exec()

    def trocar_pasta(self, parent=None):
        from .tela_inicial import TelaInicial
        pasta, srid = self.memoria_basica()
        return compat.aceito(TelaInicial(self, pasta_antiga=pasta, srid_antigo=srid, parent=parent).exec())

    def _projeto_lido(self, *args):
        self.kml.desconectar_todos()
        self.adotar_camadas_antigas()
        self.kml.reconectar()

    @staticmethod
    def _fonte(camada):
        """Caminho real do provider; usa dataSourceUri e só recorre a source() como fallback."""
        try:
            if camada is None:
                return ""
            bruto = ""
            if hasattr(camada, "dataProvider") and camada.dataProvider():
                bruto = str(camada.dataProvider().dataSourceUri() or "")
            if not bruto and hasattr(camada, "source"):
                bruto = str(camada.source() or "")
            caminho = compat.arquivo_da_fonte(bruto)  # v0.7.0: camada aberta pela pasta -> o arquivo de dentro dela
            return os.path.abspath(caminho) if caminho and (os.path.isabs(caminho) or re.match(r"^[A-Za-z]:[\\/]", caminho)) else caminho
        except Exception:
            return ""

    @staticmethod
    def _dentro(caminho, pasta):
        try:
            a = os.path.normcase(os.path.abspath(caminho)); b = os.path.normcase(os.path.abspath(pasta))
            return os.path.commonpath([a, b]) == b
        except Exception:
            return False

    def caminhos_shp_possiveis(self, raiz_destino, entrada):
        """Novo formato (nome de exibição) + formato legado (ARQUIVO), sem mover nada existente."""
        arquivo = str((entrada or {}).get("arquivo", "") or "").upper()
        if not arquivo:
            return []
        raiz = os.path.abspath(str(raiz_destino or ""))
        pasta_nova = pasta_camada_entrada(entrada)
        caminhos = [
            os.path.join(raiz, pasta_nova, arquivo + ".shp"),
            os.path.join(raiz, arquivo, arquivo + ".shp"),
        ]
        saida = []
        for caminho in caminhos:
            if os.path.normcase(caminho) not in {os.path.normcase(x) for x in saida}:
                saida.append(caminho)
        return saida

    def localizar_shp(self, raiz_destino, entrada):
        """Retorna existente em qualquer formato; se não existir, retorna o caminho NOVO."""
        candidatos = self.caminhos_shp_possiveis(raiz_destino, entrada)
        for caminho in candidatos:
            if os.path.isfile(caminho):
                return caminho
        return candidatos[0] if candidatos else ""

    def caminho_shp(self, arquivo):
        pasta, _ = self.memoria_basica()
        entrada = self.entrada(arquivo)
        if not pasta or not entrada:
            return ""
        return self.localizar_shp(os.path.join(pasta, "shapefiles"), entrada)

    def camada_por_fonte(self, caminho):
        """Retorna a camada vetorial já carregada para exatamente a mesma fonte local."""
        alvo = os.path.normcase(os.path.abspath(str(caminho or "")))
        if not alvo:
            return None
        for camada in QgsProject.instance().mapLayers().values():
            if isinstance(camada, QgsVectorLayer) and os.path.normcase(self._fonte(camada)) == alvo:
                return camada
        return None

    def camadas_avulsas(self, arquivo=""):
        """Lista camadas marcadas como avulsas; opcionalmente filtra pelo ARQUIVO."""
        alvo = str(arquivo or "").upper()
        saida = []
        for camada in QgsProject.instance().mapLayers().values():
            if not isinstance(camada, QgsVectorLayer):
                continue
            if str(camada.customProperty("norteagro/avulsa", "") or "") != "1":
                continue
            arq = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
            if not alvo or arq == alvo:
                saida.append(camada)
        return saida

    def sugerir_kml_dir(self, destino):
        """Regra única para sugerir a pasta KML de camadas criadas fora do fluxo principal."""
        destino = os.path.abspath(str(destino or ""))
        pasta_mapa, _ = self.memoria_basica()
        if pasta_mapa and os.path.isdir(pasta_mapa):
            raiz_shp = os.path.join(pasta_mapa, "shapefiles")
            if self._dentro(destino, raiz_shp):
                return os.path.join(pasta_mapa, "kml")
        atual = destino
        # Nível 0 = própria pasta de destino; depois sobe no máximo 3 níveis.
        for _ in range(4):
            try:
                dirs = {nome.casefold(): nome for nome in os.listdir(atual) if os.path.isdir(os.path.join(atual, nome))}
                if "kml" in dirs and "shapefiles" in dirs:
                    return os.path.join(atual, dirs["kml"])
            except Exception:
                pass
            pai = os.path.dirname(atual)
            if not pai or pai == atual:
                break
            atual = pai
        return os.path.join(destino, "kml")

    def adotar_camadas_antigas(self):
        """Adiciona propriedades a SHPs antigos da pasta, sem usar o nome da camada para identificá-los."""
        pasta, _ = self.memoria_basica()
        if not pasta:
            return 0
        raiz = os.path.join(pasta, "shapefiles")
        indice = self.indice_atual(); total = 0
        for camada in QgsProject.instance().mapLayers().values():
            if not isinstance(camada, QgsVectorLayer) or camada.customProperty("norteagro/arquivo", ""):
                continue
            fonte = self._fonte(camada)
            if not fonte or not self._dentro(fonte, raiz) or not fonte.lower().endswith(".shp"):
                continue
            arquivo = os.path.splitext(os.path.basename(fonte))[0].upper()
            entrada = indice.get(arquivo)
            camada.setCustomProperty("norteagro/arquivo", arquivo)
            camada.setCustomProperty("norteagro/nome", entrada["nome"] if entrada else arquivo)
            camada.setCustomProperty("norteagro/pasta_camada", os.path.basename(os.path.dirname(fonte)))
            self.kml.conectar(camada); total += 1
        if total:
            QgsProject.instance().setDirty(True)
        return total

    def camada_plugin(self, arquivo):
        """Identifica exclusivamente pelas propriedades customizadas, nunca pelo nome exibido."""
        pasta, _ = self.memoria_basica()
        for camada in QgsProject.instance().mapLayers().values():
            if not isinstance(camada, QgsVectorLayer):
                continue
            if str(camada.customProperty("norteagro/arquivo", "") or "") != arquivo:
                continue
            if pasta and self._dentro(self._fonte(camada), pasta):
                return camada
        return None

    def nome_no_qgis(self, entrada):
        """Camadas novas sempre entram com o nome técnico 00_<ARQUIVO>."""
        return "00_" + entrada["arquivo"]

    def _wkb(self, tipo):
        # Multi* facilita substituições e geometrias corrigidas sem deixar de ser ponto/linha/polígono.
        return {"P": compat.WKB_MULTIPOLIGONO, "L": compat.WKB_MULTILINHA, "Pt": compat.WKB_MULTIPONTO}[tipo]

    def _grupo(self, nome):
        raiz = QgsProject.instance().layerTreeRoot()
        grupo = raiz.findGroup(nome)
        if grupo:
            return grupo
        if nome in GRUPOS_BASE:
            return raiz.insertGroup(min(GRUPOS_BASE.index(nome), len(raiz.children())), nome)
        return raiz.addGroup(nome)

    def _posicao_no_grupo(self, grupo_nome, arquivo):
        itens = self.catalogo_atual().get(grupo_nome, [])
        ordem = {e["arquivo"]: i for i, e in enumerate(itens)}
        alvo = ordem.get(arquivo, 99999); pos = 0
        grupo = QgsProject.instance().layerTreeRoot().findGroup(grupo_nome)
        if not grupo:
            return 0
        for no in grupo.children():
            if not isinstance(no, QgsLayerTreeLayer):
                continue
            camada = no.layer(); outro = str(camada.customProperty("norteagro/arquivo", "") or "") if camada else ""
            if outro in ordem and ordem[outro] < alvo:
                pos += 1
        return pos

    def _aplicar_estilo(self, camada, entrada, qml):
        # v3.9.4: o QML guarda só a aparência. Antes ele gravava e recarregava as
        # propriedades personalizadas da camada, o que apagava norteagro/avulsa e
        # norteagro/kml_dir logo após a criação (KML ia para a pasta errada).
        categorias = compat.categorias_sem_propriedades()
        if os.path.isfile(qml):
            props = {k: camada.customProperty(k) for k in camada.customPropertyKeys() if str(k).startswith("norteagro/")}
            camada.loadNamedStyle(qml, categories=categorias)
            for k, v in props.items():
                camada.setCustomProperty(k, v)
        else:
            camada.setRenderer(QgsSingleSymbolRenderer(simbolo_entrada(entrada)))
            retorno = camada.saveNamedStyle(qml, categories=categorias)
            if isinstance(retorno, tuple) and len(retorno) > 1 and not bool(retorno[1]):
                raise RuntimeError(f"Falha ao salvar QML: {retorno[0]}")
        camada.triggerRepaint()

    def criar_ou_carregar_destino(self, entrada, raiz_destino, srid, kml_dir="", avulsa=False,
                                  carregar_existente=True):
        """Função única de criação/carga usada pela tela normal, avulsa e padronização."""
        if not entrada or not entrada.get("arquivo"):
            return False, "falha", "Camada não encontrada no catálogo.", None
        arquivo = str(entrada["arquivo"]).upper()
        if not self.entrada_valida(arquivo):
            return False, "falha", "Esta camada está desabilitada porque o catálogo possui uma inconsistência relacionada a ela.", None
        raiz_destino = os.path.abspath(str(raiz_destino or ""))
        if raiz_destino and not os.path.isdir(raiz_destino):
            # v0.0.0: modelos novos não criam shapefiles antes da hora; nasce aqui, com a primeira camada da pasta do mapa.
            pasta_mapa, _ = self.memoria_basica()
            if pasta_mapa and os.path.isdir(pasta_mapa) and \
                    os.path.normcase(raiz_destino) == os.path.normcase(os.path.join(os.path.abspath(pasta_mapa), "shapefiles")):
                os.makedirs(raiz_destino, exist_ok=True)
        if not raiz_destino or not os.path.isdir(raiz_destino):
            return False, "falha", "Pasta de destino inválida.", None
        shp = self.localizar_shp(raiz_destino, entrada)
        qml = os.path.splitext(shp)[0] + ".qml"
        try:
            existente = os.path.isfile(shp)
            if existente and not carregar_existente:
                return True, "existente", "", self.camada_por_fonte(shp)
            if not existente:
                base = os.path.splitext(shp)[0]
                parciais = [p for p in glob.glob(base + ".*") if os.path.splitext(p)[1].lower() != ".qml"]
                if parciais:
                    raise RuntimeError("Existem arquivos parciais com o mesmo nome. Nada foi sobrescrito: " + ", ".join(os.path.basename(p) for p in parciais))
                os.makedirs(os.path.dirname(shp), exist_ok=True)
                campos = QgsFields(); campos.append(QgsField("id", compat.CAMPO_INTEIRO))
                crs = QgsCoordinateReferenceSystem(srid)
                if not crs.isValid():
                    raise RuntimeError("SRC inválido para a nova camada.")
                op = QgsVectorFileWriter.SaveVectorOptions(); op.driverName = "ESRI Shapefile"; op.fileEncoding = "UTF-8"
                contexto = QgsCoordinateTransformContext(QgsProject.instance().transformContext())
                writer = QgsVectorFileWriter.create(shp, campos, self._wkb(entrada["tipo"]), crs, contexto, op)
                if not writer or writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
                    raise RuntimeError(writer.errorMessage() if writer else "Falha ao criar o Shapefile.")
                del writer
            camada = self.camada_por_fonte(shp)
            if camada:
                # Se estava carregada manualmente, adota o padrão visual 00_<ARQUIVO>.
                # Camada já gerenciada preserva eventual nome ajustado pelo usuário.
                ja_gerenciada = bool(camada.customProperty("norteagro/arquivo", ""))
                if not ja_gerenciada:
                    camada.setName("00_" + arquivo)
                    raiz_arvore = QgsProject.instance().layerTreeRoot()
                    no = raiz_arvore.findLayer(camada.id())
                    if no:
                        no.setUseLayerName(True)
                    grupo = self._grupo(entrada.get("grupo") or "Uso do Solo")
                    # Cria primeiro o novo nó e só depois remove o antigo, evitando que
                    # uma camada já carregada fique momentaneamente sem nó na árvore.
                    novo_no = grupo.insertLayer(self._posicao_no_grupo(entrada.get("grupo") or "Uso do Solo", arquivo), camada)
                    if no and no is not novo_no:
                        pai_antigo = no.parent()
                        if pai_antigo:
                            pai_antigo.removeChildNode(no)
                    if entrada.get("grupo") == "Ocultos (Salvar na pasta)" and novo_no:
                        novo_no.setItemVisibilityChecked(False)
                camada.setCustomProperty("norteagro/arquivo", arquivo)
                camada.setCustomProperty("norteagro/nome", entrada.get("nome", arquivo))
                camada.setCustomProperty("norteagro/pasta_camada", os.path.basename(os.path.dirname(shp)))
            else:
                camada = QgsVectorLayer(shp, "00_" + arquivo, "ogr")
                if not camada.isValid():
                    raise RuntimeError("O Shapefile não pôde ser carregado.")
                camada.setCustomProperty("norteagro/arquivo", arquivo)
                camada.setCustomProperty("norteagro/nome", entrada.get("nome", arquivo))
                camada.setCustomProperty("norteagro/pasta_camada", os.path.basename(os.path.dirname(shp)))
                self._aplicar_estilo(camada, entrada, qml)
                projeto = QgsProject.instance(); projeto.addMapLayer(camada, False)
                grupo = self._grupo(entrada.get("grupo") or "Uso do Solo")
                grupo.insertLayer(self._posicao_no_grupo(entrada.get("grupo") or "Uso do Solo", arquivo), camada)
                no = grupo.findLayer(camada.id())
                if entrada.get("grupo") == "Ocultos (Salvar na pasta)" and no:
                    no.setItemVisibilityChecked(False)
            if entrada.get("personalizada") and entrada.get("origem") in ("avulsa", "projeto"):
                # v3.9.6: a camada carrega a própria definição (nome, tipo, grupo, lugar no quadro)
                # para ser reconhecida no cálculo mesmo fora dos extras do projeto.
                camada.setCustomProperty("norteagro/definicao", json.dumps(
                    {k: entrada.get(k) for k in ("arquivo", "nome", "tipo", "grupo", "quadro") if entrada.get(k) is not None},
                    ensure_ascii=False))
            if avulsa:
                camada.setCustomProperty("norteagro/avulsa", "1")
                camada.setCustomProperty("norteagro/kml_dir", os.path.abspath(str(kml_dir or self.sugerir_kml_dir(raiz_destino))))
                # Grupo novo de uma camada personalizada avulsa pertence somente a este projeto.
                grupo_av = str(entrada.get("grupo") or "").strip()
                if entrada.get("origem") == "avulsa" and grupo_av and grupo_av not in GRUPOS_BASE and grupo_av not in self.grupos_projeto():
                    grupos = self.grupos_projeto(); grupos.append(grupo_av); self.salvar_grupos_projeto(grupos)
            else:
                camada.removeCustomProperty("norteagro/avulsa")
                camada.removeCustomProperty("norteagro/kml_dir")
            # Se o QML existia, reaplica; se não, a criação acima já o salvou.
            if os.path.isfile(qml):
                self._aplicar_estilo(camada, entrada, qml)
            self.kml.conectar(camada); QgsProject.instance().setDirty(True)
            return True, "criada" if not existente else "carregada", "", camada
        except Exception as exc:
            self.log(f"Erro em {arquivo}: {exc}")
            return False, "falha", str(exc), None

    def criar_ou_carregar(self, arquivo, _semad_interno=False):
        """Wrapper do fluxo principal, mantendo a API já usada pelas telas existentes.
        v0.5.0: camada da SEMAD (grupo "SEMAD - SIGA") é criada consultando o SIGA - ver criar_semad."""
        if not _semad_interno:
            from . import semad
            if semad.eh_semad(arquivo):
                return self.criar_semad(arquivo)
        entrada = self.entrada(arquivo)
        pasta, srid = self.memoria_basica()
        if not entrada or not pasta:
            return False, "falha", "Pasta do mapa ou camada do catálogo não definida."
        ok, acao, erro, _ = self.criar_ou_carregar_destino(
            entrada, os.path.join(pasta, "shapefiles"), srid,
            kml_dir=os.path.join(pasta, "kml"), avulsa=False, carregar_existente=True
        )
        return ok, acao, erro


    def criar_semad(self, arquivo):
        """v0.5.0: cria/atualiza UMA camada da SEMAD consultando o SIGA agora. Devolve (ok, acao, texto):
        acao "criada"/"atualizada"; "sem_dados" (nada no imóvel, a camada não é criada); "sem_imovel"/"imovel_vazio"
        (falta a Área Total do Imóvel com desenho); "falha"."""
        from . import semad
        try:
            resultados, problema = semad.gerar(self, [arquivo])
        except Exception as exc:
            self.log(f"SEMAD {arquivo}: {exc}")
            return False, "falha", str(exc)
        if problema:
            return False, problema, semad.texto_problema_imovel(problema)
        res = resultados[0]
        if res["situacao"] == "erro":
            return False, "falha", "SIGA: " + res["erro"]
        if res["situacao"] == "nao_tem":
            return True, "sem_dados", semad.linha_resultado(res)
        return True, res.get("acao") or "atualizada", semad.linha_resultado(res)

    def _camadas_para_renomear(self):
        """Usa a seleção do painel; sem seleção, usa todas as camadas vetoriais/raster."""
        selecionadas = list(self.iface.layerTreeView().selectedLayers() or [])
        base = selecionadas if selecionadas else list(QgsProject.instance().mapLayers().values())
        saida = []
        for camada in base:
            # QgsMapLayer cobre vetor e raster; excluímos apenas objetos sem setName/customProperty.
            if hasattr(camada, "setName") and hasattr(camada, "customProperty"):
                saida.append(camada)
        return saida

    @staticmethod
    def _nome_legivel(nome):
        """Fallback para camada fora do catálogo: tira 00_ e troca _ por espaço."""
        texto = str(nome or "")
        if texto.startswith("00_"):
            texto = texto[3:]
        return " ".join(texto.replace("_", " ").split()).strip()

    def _arquivo_reconhecido_para_nome(self, camada):
        """Retorna ARQUIVO de catálogo por propriedade ou pelo reconhecedor da Parte A."""
        indice = indice_reconhecimento(QgsProject.instance())
        try:
            prop = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
        except Exception:
            prop = ""
        if prop in indice:
            return prop
        if not isinstance(camada, QgsVectorLayer):
            return ""
        try:
            from .areas import prever_reconhecimentos
            _, srid = self.memoria_basica()
            if not srid:
                crs = QgsProject.instance().crs()
                srid = crs.authid() if crs.isValid() else "EPSG:31982"
            manuais = apelidos_manuais_projeto(QgsProject.instance())
            prev, _ = prever_reconhecimentos([camada], srid, indice, manuais, {})
            arq = str(prev.get(camada.id(), {}).get("arquivo", "") or "")
            return arq if arq in indice else ""
        except Exception:
            return ""

    def ajustar_nomes_qgis(self):
        """Usa nome oficial do catálogo quando reconhecida; outras mantêm a regra antiga."""
        alteracoes = []
        raiz = QgsProject.instance().layerTreeRoot()
        indice = indice_reconhecimento(QgsProject.instance())
        for camada in self._camadas_para_renomear():
            antes = str(camada.name())
            arquivo = self._arquivo_reconhecido_para_nome(camada)
            if arquivo and arquivo in indice:
                depois = str(indice[arquivo].get("nome") or arquivo)
            elif "_" in antes:
                depois = self._nome_legivel(antes)
            else:
                continue
            if not depois or depois == antes:
                continue
            if not camada.customProperty("norteagro/nome_original", ""):
                camada.setCustomProperty("norteagro/nome_original", antes)
            camada.setName(depois)
            no = raiz.findLayer(camada.id())
            if no:
                no.setUseLayerName(True)
            alteracoes.append((antes, depois))
        if alteracoes:
            QgsProject.instance().setDirty(True)
        return len(alteracoes), alteracoes

    def voltar_nomes_arquivo(self):
        """Restaura exatamente o nome salvo; nunca reconstrói o nome por espaços."""
        candidatas = []
        for camada in self._camadas_para_renomear():
            original = str(camada.customProperty("norteagro/nome_original", "") or "")
            if original and str(camada.name()) != original:
                candidatas.append((camada, original))
        if not candidatas:
            return 0, []
        alteracoes = []
        raiz = QgsProject.instance().layerTreeRoot()
        for camada, original in candidatas:
            antes = str(camada.name())
            camada.setName(original)
            camada.removeCustomProperty("norteagro/nome_original")
            no = raiz.findLayer(camada.id())
            if no:
                no.setUseLayerName(True)
            alteracoes.append((antes, original))
        QgsProject.instance().setDirty(True)
        return len(alteracoes), alteracoes

    def salvar_extra_projeto(self, entrada):
        extras = extras_projeto(QgsProject.instance())
        extras = [x for x in extras if str(x.get("arquivo", "")).upper() != entrada["arquivo"]]
        extras.append(entrada)
        salvar_extras_projeto(QgsProject.instance(), extras)

    def garantir_projeto_salvo(self, parent=None):
        """Usado antes de renomear a pasta; retorna False se o usuário cancelar/falhar."""
        projeto = QgsProject.instance(); pasta, _ = self.memoria_basica()
        if projeto.fileName():
            return bool(projeto.write())
        nome_imovel = self._nome_imovel(pasta)
        sugerido = os.path.join(self._pasta_projetos(pasta), nome_imovel + ".qgz")
        arq, _ = QFileDialog.getSaveFileName(parent or self.iface.mainWindow(), "Salvar projeto QGIS", sugerido, "Projeto QGIS (*.qgz)")
        if not arq:
            return False
        if not arq.lower().endswith(".qgz"):
            arq += ".qgz"
        return bool(projeto.write(arq))
