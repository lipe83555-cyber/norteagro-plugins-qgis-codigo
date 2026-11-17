# -*- coding: utf-8 -*-
"""v0.3.0: confere e corrige o DESENHO das camadas antes do cálculo de áreas.

Ideias trazidas do app Bússola SIGCAR (ferramenta de sobreposição), adaptadas às regras do Quadro de Áreas:

* Fora do imóvel: toda camada é recortada no limite do imóvel, menos a hidrografia (rios, nascentes, barramentos,
  cacimbas, tanques, lagoas e veredas), que pode passar do limite. Feição inteira fora é apagada (com aviso) e
  recorte grande (> 1.000 m²) pede para conferir o limite do imóvel.
* Sobreposição entre camadas que dividem o mesmo "todo" (as mesmas regras do cálculo, topologia.py):
  imóvel -> Suprimida depois/antes, Consolidada, Vegetação; APP Total -> APP Suprimida depois/antes, Consolidada,
  Preservada; Reserva Legal -> Suprimida, Consolidada, Preservada; Área Suprimida do período -> APP, RL e Passível.
  - Faixa fina (largura média < 1 m) é erro de traçado: sai sozinha da camada de menor prioridade (a mesma
    prioridade do cálculo).
  - Mancha larga é conflito de classificação (a mesma terra mapeada como duas coisas): o plugin PERGUNTA qual
    camada cede a área, sugerindo a de menor prioridade.
  - O corte usa a diferença "robusta" do Bússola: tenta sem grade e com grade de 1 mm, fica com o resultado que
    deixa menos sobra sobre a camada vencedora e repete até não sobrar nada; fiapos (< 1 mm) são descartados.
* Filha fora do pai: APP Preservada/Consolidada/Suprimida fora da APP Total, APP Suprimida fora da Área Suprimida do
  período, RL Suprimida e Passível do período fora da Área Suprimida do período -> recortadas.
* Frestas entre classes (mais finas que 0,5 m ou menores que 1 m²) são somadas à classe vizinha de maior divisa,
  exatamente como o cálculo faz; vazio maior vira "Área sem classificação" (só aviso: precisa desenhar).
* Geometria: registros sem geometria, geometria inválida (corrigida pelo método Structure, que não faz área sumir),
  lascas soltas (< 0,01 m² ou < 1 mm de largura), feições repetidas e feições da mesma camada sobrepostas (a
  repetição sai da feição de baixo).

Nada é gravado em `executar`; `gravar` faz cópia de segurança (_backup ao lado de cada arquivo) e altera as
camadas numa sessão de edição. Depois disso o cálculo vê camadas limpas e o quadro bate com o desenho.
"""
from . import compat
import os
import shutil
from datetime import datetime

from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsFeatureRequest, QgsGeometry,
    QgsProject, QgsRectangle, QgsSpatialIndex, QgsVectorLayer, QgsWkbTypes,
)

from . import topologia as topo
from .areas import (
    APP_SUBCLASSES, PERIODOS_ANTROPIZADA, PRIORIDADE_ANTROPIZADA_PADRAO, PRIORIDADE_APP_PADRAO,
    PRIORIDADE_FECHAMENTO_PADRAO, PRIORIDADE_RESERVA_PADRAO, VIA_PRIORIDADE, _kml_espelho_ids,
    AGUA_FECHAMENTO, SUPRESSAO_ANTES_DA_AGUA, _ordenar_prioridade, _src_assumido, contar_feicoes, pode_sair_do_imovel, prever_reconhecimentos, HIDRO_PODE_SAIR,
)
from .catalogo import FECHAMENTO_PADRAO, configuracao_geometrica

# Hidrografia: a única que pode sair do imóvel. Personalizadas com lugar "HIDRO" também.
LIVRES_DO_IMOVEL = {"AREA_DO_IMOVEL"} | set(HIDRO_PODE_SAIR)
# v0.4.0: camada de total -> partes. True: o total é a soma exata das partes (tira o que sobra e completa o que falta);
# False: o total só não pode passar das partes (RL Suprimida dentro da Área Suprimida antes/depois).
# v0.4.0 (pedido do escritório): camadas que a correção NUNCA altera - só são calculadas, cada uma sozinha:
# as de APP e as camadas de total da supressão (Área Suprimida e Supressão em Área Passível).
APP_INTOCAVEIS = {"APP_TOTAL", "APP_PRESERVADA", "APP_CONSOLIDADA", "APP_SUPRIMIDA", "APP_ANTROPIZADA_ANTES_2019",
                  "APP_ANTROPIZADA_APOS_2019", "AREA_SUPRIMIDA", "SUPRESSAO_PASSIVEL_TOTAL"}
TOTAIS_SOMA = {"RESERVA_SUPRIMIDA": False}
TOTAIS_PARTES = {
    "RESERVA_SUPRIMIDA": ["AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019"],
}
# v0.4.0: subclasse certa de cada uso do solo, para classificar a APP sem classe pelo que está embaixo
COBERTURA_PARA = {
    "Área de Preservação Permanente": {
        "AREA_SUPRIMIDA_ANTES_2019": "APP_ANTROPIZADA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019": "APP_ANTROPIZADA_APOS_2019",
        "AREA_CONSOLIDADA": "APP_CONSOLIDADA", "AREA_DE_VEGETACAO": "APP_PRESERVADA",
    },
}
LARGURA_FAIXA_M = 1.0        # Bússola: LARGURA_MAX_RECORTE_M - abaixo disso é erro de traçado
AREA_PONTO_M2 = 0.01         # Bússola: PECA_QUE_VALE_PONTO_M2 - peça que não vale nada
LARGURA_FIAPO_M = 0.001      # fiapo de corte
# v0.7.0: abaixo de 0,1 mm de largura a peça é ruído numérico: o GEOS "perde" faixas assim ao juntar camadas (caso real:
# fio de 0,02 mm x 700 m na Área Consolidada de um imóvel de cliente). Peça assim sai sempre e buraco assim é ignorado.
LARGURA_RUIDO_M = 0.0001
AREA_RUIDO_M2 = 1e-4         # sobra numérica ignorada nas sobreposições
REVISAR_FORA_M2 = 1000.0     # Bússola: OUTSIDE_REVIEW_AREA_M2
REVISAR_CORTE_M2 = 500.0     # Bússola: COVERAGE_REVIEW_AREA_M2
AREA_LASCA_M2 = 1.0          # v0.4.0: mesma régua do cálculo (G1: parte menor que 1 m² é lasca)
DIVISA_MIN_M2 = 0.005        # faixa de 2 cm x ~25 cm: divisa comum mínima para somar uma fresta à vizinha
FRESTA_AREA_M2 = topo.LASCA_AREA_M2
# v0.5.0: fresta de traçado = parte onde não cabe um círculo deste diâmetro (qualquer comprimento)
LARGURA_FRESTA_M = 2.0
# v0.5.0: buraco onde cabe um círculo deste diâmetro é área sem desenho de verdade (a sugestão é deixar)
LARGURA_BURACO_M = 10.0

ROTULO_ACAO = {"auto": "corrige sozinho", "escolha": "você escolhe", "info": "só aviso"}


# ---------------------------------------------------------------- geometria
def _diametro_interno(g):
    """Diâmetro do maior círculo que cabe dentro da parte (polo de inacessibilidade). Mede a LARGURA de verdade de
    uma faixa, sem depender do comprimento dela."""
    try:
        a = float(g.area())
        if a <= 0:
            return 0.0
        prec = max(0.02, min(1.0, (a ** 0.5) / 200.0))
        res = g.poleOfInaccessibility(prec)
        dist = float(res[1]) if isinstance(res, (tuple, list)) else 0.0
        return 2.0 * dist
    except Exception:
        return 2.0 * _largura_m(g)


def _largura_m(g):
    try:
        p = float(g.length())
        return (2.0 * float(g.area()) / p) if p > 0 else 0.0
    except Exception:
        return 0.0


def _sem_fiapos(g):
    """Tira partes que não valem nada (< 0,01 m²) ou que são fiapos de corte (< 1 mm de largura)."""
    partes = topo.partes_simples(g)
    boas = [p for p in partes if topo.area_plana(p) >= AREA_PONTO_M2 and _largura_m(p) >= LARGURA_FIAPO_M]
    if len(boas) == len(partes):
        return g if partes else None
    return topo.juntar(boas)


def _resto(r, remover):
    if topo.vazia(r):
        return 0.0
    try:
        s = r.intersection(remover)
        return 0.0 if topo.vazia(s) else topo.area_plana(topo._so_partes_poligonais(s))
    except Exception:
        return float("inf")


def diferenca_robusta(base, remover, params):
    """Diferença que não deixa sobra em cima da camada que ganhou. v0.5.0: a conta EXATA é sempre a escolhida; a grade
    de 1 mm só entra se o GEOS falhar. Antes, quando a conta exata deixava uma sobra numérica, ficava a versão na grade
    - e a grade arredondava a FEIÇÃO INTEIRA (meio milímetro em cada vértice), criando sobreposições e frestas novas com
    as vizinhas em toda a divisa (a correção seguinte sempre achava "faixas finas" de novo). None = a feição sumiu."""
    if topo.vazia(base):
        return None
    if topo.vazia(remover):
        return base
    try:
        if not base.boundingBox().intersects(remover.boundingBox()):
            return base
    except Exception:
        pass
    atual = base
    for _volta in range(3):
        r = None
        for p in (None, params):
            if p is None and _volta > 0 and r is not None:
                break
            try:
                r = atual.difference(remover) if p is None else atual.difference(remover, p)
            except Exception:
                r = None
            if r is not None and not r.isNull():
                break
            r = None
        if r is None:
            try:
                r = topo.diferenca(atual, remover, params)
            except Exception:
                return atual
            return None if r is None else _sem_fiapos(r)
        if r.isEmpty():
            return None
        r = topo._so_partes_poligonais(r)
        if r is None:
            return None
        r = _sem_fiapos(r)
        if r is None:
            return None
        sobra = _resto(r, remover)
        atual = r
        if sobra <= AREA_RUIDO_M2:
            break
    return atual


def _preparar(g):
    """Motor GEOS preparado (contains/intersects muito mais rápidos contra o mesmo limite)."""
    try:
        e = QgsGeometry.createGeometryEngine(g.constGet())
        e.prepareGeometry()
        return e
    except Exception:
        return None


def _contem(motor, limite, g):
    try:
        return motor.contains(g.constGet()) if motor is not None else limite.contains(g)
    except Exception:
        return False


def _toca(motor, limite, g):
    try:
        return motor.intersects(g.constGet()) if motor is not None else limite.intersects(g)
    except Exception:
        return True


def _pecas(g):
    """Partes poligonais com área > ruído."""
    return [p for p in topo.partes_simples(g) if topo.area_plana(p) > AREA_RUIDO_M2]


def _texto_area(m2):
    m2 = float(m2 or 0.0)
    if m2 >= 10000:
        return f"{m2 / 10000.0:,.4f} ha".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{m2:,.2f} m²".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------- camada de trabalho
class CamadaTrabalho:
    """Feições de uma camada no SRC do cálculo (metros). Guarda o que mudou para gravar depois."""

    def __init__(self, layer, arquivo, nome, crs_usado, alvo):
        self.layer = layer
        self.arquivo = arquivo
        self.nome = nome
        geom = layer.geometryType()
        self.tipo = "P" if geom == compat.GEOM_POLIGONO else ("L" if geom == compat.GEOM_LINHA else "Pt")
        ctx = QgsProject.instance().transformContext()
        self.crs_usado = crs_usado
        self.ida = QgsCoordinateTransform(crs_usado, alvo, ctx) if crs_usado != alvo else None
        self.volta = QgsCoordinateTransform(alvo, crs_usado, ctx) if crs_usado != alvo else None
        self.base = {}          # fid -> geometria original (trabalho) ou None
        self.base_original = {}
        self.geoms = {}
        self.mudou = set()
        self.apagar = set()
        self.mudou_acum = set()  # v0.4.0: mudanças das passadas anteriores (correção em mais de uma passada)
        self.apagar_acum = set()
        self.editavel, self.motivo = self._pode_editar()
        self._uniao = None
        self._indice = None
        self._caixas = {}

    def _pode_editar(self):
        lay = self.layer
        try:
            if lay.isEditable() and lay.isModified():
                # v0.7.0: só barra se há alteração não salva (edição aberta sem mudança não atrapalha)
                return False, "a camada tem edição NÃO SALVA: salve (ou descarte) a edição dela e calcule de novo"
            caps = lay.dataProvider().capabilities()
            pode = compat.tem_capacidade(caps, compat.CAP_MUDAR_GEOMETRIA) and \
                compat.tem_capacidade(caps, compat.CAP_APAGAR_FEICOES)
            if not pode:
                return False, "o formato da camada não deixa alterar o desenho"
            prov = str(lay.providerType() or "").lower()
            if prov == "ogr":
                fonte = _arquivo_da_camada(lay)
                if not fonte or os.path.splitext(fonte)[1].lower() not in (".shp", ".gpkg"):
                    return False, "só Shapefile e GeoPackage são corrigidos (os outros formatos não têm cópia de segurança)"
            elif prov != "memory":
                return False, "camada de serviço/banco: não é alterada"
        except Exception as exc:
            return False, str(exc)
        return True, ""

    def carregar(self):
        req = QgsFeatureRequest().setNoAttributes()
        for f in self.layer.getFeatures(req):
            g = QgsGeometry(f.geometry()) if f.hasGeometry() else None
            if g is not None and not g.isNull() and self.ida is not None:
                try:
                    g.transform(self.ida)
                except Exception:
                    g = None
            self.base[f.id()] = None if topo.vazia(g) else g
        self.sem_geometria = [fid for fid, g in self.base.items() if g is None]
        self.base_original = dict(self.base)

    def voltar_ao_original(self):
        self.base = dict(self.base_original)
        self.sem_geometria = [fid for fid, g in self.base_original.items() if g is None]
        self.mudou_acum, self.apagar_acum = set(), set()

    def consolidar(self):
        """Fim de uma passada: o resultado vira a base da próxima, e o que mudou fica guardado para gravar."""
        self.mudou_acum |= self.mudou
        self.apagar_acum |= self.apagar
        self.base = {fid: (None if (fid in self.apagar or g is None) else QgsGeometry(g)) for fid, g in self.geoms.items()}

    def mudou_nesta(self):
        return bool(self.mudou or self.apagar)

    def reiniciar(self):
        self.geoms = {k: (QgsGeometry(v) if v is not None else None) for k, v in self.base.items()}
        self.mudou, self.apagar, self._uniao = set(), set(), None
        # v0.3.0 (otimização): índice espacial das feições; antes cada fresta/corte varria a camada inteira.
        self._indice = QgsSpatialIndex()
        self._caixas = {}
        for fid, g in self.geoms.items():
            if g is not None:
                self._indexar(fid, g)

    def _indexar(self, fid, g):
        caixa = QgsRectangle(g.boundingBox())
        caixa.grow(0.05)
        antiga = self._caixas.get(fid)
        if antiga is not None and antiga.contains(caixa):
            return
        if antiga is not None:
            caixa.combineExtentWith(antiga)
        self._caixas[fid] = caixa
        self._indice.addFeature(fid, caixa)

    # --- edição em memória
    def vivas(self):
        return [(fid, g) for fid, g in self.geoms.items() if g is not None and fid not in self.apagar]

    def perto(self, caixa):
        """Feições vivas cuja caixa encosta em `caixa` (pelo índice espacial), em ordem de fid."""
        if self._indice is None:
            return [(fid, g) for fid, g in self.vivas() if g.boundingBox().intersects(caixa)]
        ids = sorted(set(self._indice.intersects(caixa)))
        return [(fid, self.geoms[fid]) for fid in ids if fid not in self.apagar and self.geoms.get(fid) is not None]

    def definir(self, fid, g):
        if getattr(self, "somente_leitura", False):
            return
        self._uniao = None
        if topo.vazia(g):
            self.apagar.add(fid)
            self.geoms[fid] = None
        else:
            self.geoms[fid] = g
            self.mudou.add(fid)
            if self._indice is not None:
                self._indexar(fid, g)

    def remover(self, fid):
        if getattr(self, "somente_leitura", False):
            return
        self._uniao = None
        self.apagar.add(fid)

    def uniao(self, params):
        if self._uniao is None and self.tipo == "P":
            self._uniao = topo.uniao([g for _, g in self.vivas()], params)
        return self._uniao

    def tirar(self, remover, params):
        """Tira `remover` de todas as feições. Devolve (área tirada m², feições que sumiram)."""
        if topo.vazia(remover):
            return 0.0, 0
        # cada pedaço só é tirado das feições perto dele (índice), e cada feição só vê os pedaços dela
        por_feicao = {}
        for peca in topo.partes_simples(remover) or [remover]:
            for fid, _g in self.perto(peca.boundingBox()):
                por_feicao.setdefault(fid, []).append(peca)
        tirada, sumiram = 0.0, 0
        for fid in sorted(por_feicao):
            g = self.geoms.get(fid)
            if g is None or fid in self.apagar:
                continue
            rem = topo.juntar(por_feicao[fid])
            try:
                if not g.intersects(rem):
                    continue
            except Exception:
                continue
            antes = topo.area_plana(g)
            ng = diferenca_robusta(g, rem, params)
            depois = topo.area_plana(ng)
            if ng is not None and abs(antes - depois) < AREA_RUIDO_M2:
                continue
            tirada += max(0.0, antes - depois)
            if ng is None:
                sumiram += 1
            self.definir(fid, ng)
        return tirada, sumiram

    def alterada(self):
        return bool(self.mudou or self.apagar or self.mudou_acum or self.apagar_acum)


def _arquivo_da_camada(layer):
    try:
        bruto = str(layer.dataProvider().dataSourceUri() or layer.source() or "")
        # v0.7.0: camada aberta pela PASTA ("pasta|layername=X") é o arquivo X.shp de dentro dela; antes ela era
        # tratada como "não é Shapefile", ficava sem correção e o quadro continuava diferente do desenho.
        return os.path.abspath(compat.arquivo_da_fonte(bruto)) if bruto else ""
    except Exception:
        return ""


# ---------------------------------------------------------------- motor
class Correcao:
    def __init__(self, camadas, srid, indice, manuais=None, overrides=None, pasta_mapa="", config=None, progresso=None):
        self.progresso = progresso
        self.srid = srid
        self.alvo = QgsCoordinateReferenceSystem(srid)
        self.indice = indice or {}
        self.params = topo.parametros_geometria(self.alvo)
        self.config = dict(config or configuracao_geometrica())
        try:
            self.largura_fresta = float(self.config.get("largura_max_lasca_m", topo.LARGURA_LASCA_M))
        except Exception:
            self.largura_fresta = topo.LARGURA_LASCA_M
        self.camadas = {}        # arquivo -> CamadaTrabalho
        self.ignoradas = []      # (nome, motivo)
        self.problemas = []
        self.conflitos = []
        self._ids_conflito = {}
        self.descartadas = set()  # ids das camadas que ficam fora (repetidas)
        self._escolher(camadas, manuais or {}, overrides or {}, pasta_mapa)
        for lista in self._candidatas.values():
            for c in lista:
                c.carregar()

    # --- quais camadas
    def nome(self, arquivo):
        e = self.indice.get(arquivo) or {}
        return str(e.get("nome") or e.get("nome_exibicao") or arquivo)

    def _intocavel(self, arquivo):
        """v0.4.0 (pedido do escritório): APP e camadas de total da supressão só são calculadas, nunca alteradas."""
        return bool(self.config.get("app_separada", True)) and str(arquivo).upper() in APP_INTOCAVEIS

    def _livre(self, arquivo):
        if arquivo in LIVRES_DO_IMOVEL:
            return True
        if arquivo in {str(x).upper() for x in (self.config.get("nao_recortar") or [])}:
            return True
        return pode_sair_do_imovel(arquivo, self.indice)

    def _escolher(self, camadas, manuais, overrides, pasta_mapa):
        """v0.4.0: guarda TODAS as candidatas de cada classe. Quando a mesma classe vem de arquivos diferentes
        (ex.: o SHP da pasta do mapa e um KML do DAI), a escolha é decisão técnica, feita em executar()."""
        previsoes, _amb = prever_reconhecimentos(camadas, self.srid, self.indice, manuais, overrides)
        try:
            espelhos = _kml_espelho_ids(camadas, previsoes, pasta_mapa)
        except Exception:
            espelhos = set()
        self._pasta_mapa_norm = os.path.normcase(os.path.abspath(pasta_mapa)) if pasta_mapa else ""
        por_arquivo = {}
        for c in camadas:
            rec = previsoes.get(c.id(), {})
            arq = str(rec.get("arquivo") or "")
            if not isinstance(c, QgsVectorLayer) or not c.isValid() or c.id() in espelhos:
                continue
            if rec.get("referencia") or rec.get("ignorar") or not arq or arq not in self.indice:
                continue
            por_arquivo.setdefault(arq, []).append((c, rec))
        self._candidatas = {}     # arq -> [CamadaTrabalho] (um por arquivo de origem)
        self._mesmo_arquivo = {}  # id da camada repetida (mesmo arquivo) -> nome da que ficou
        for arq, grupo in por_arquivo.items():
            por_fonte = {}
            for c, rec in grupo:
                chave = c.id() if str(c.providerType()).lower() == "memory" else (_arquivo_da_camada(c) or c.id())
                por_fonte.setdefault(os.path.normcase(chave), []).append((c, rec))
            lista = []
            for fonte, mesmos in por_fonte.items():
                usada, rec = max(mesmos, key=lambda x: (VIA_PRIORIDADE.get(x[1].get("via"), 0), contar_feicoes(x[0])))
                for outra, _r in mesmos:
                    if outra.id() != usada.id():
                        self._mesmo_arquivo[outra.id()] = (outra.name(), usada.name(), arq)
                try:
                    src, _assumido = _src_assumido(usada, self.srid)
                    crs = QgsCoordinateReferenceSystem(src)
                except Exception:
                    crs = usada.crs()
                if not crs.isValid():
                    self.ignoradas.append((usada.name(), "camada sem SRC"))
                    continue
                t = CamadaTrabalho(usada, arq, self.nome(arq), crs, self.alvo)
                t._via = VIA_PRIORIDADE.get(rec.get("via"), 0)
                t.somente_leitura = self._intocavel(arq)
                lista.append(t)
            if lista:
                self._candidatas[arq] = lista
                self.camadas[arq] = max(lista, key=self._nota_candidata)

    def _nota_candidata(self, t):
        """Qual camada sugerir quando a mesma classe vem de arquivos diferentes: a que dá para corrigir
        (Shapefile/GeoPackage), da pasta do mapa, reconhecida com mais certeza, com mais feições."""
        fonte = os.path.normcase(os.path.abspath(_arquivo_da_camada(t.layer) or ""))
        na_pasta = bool(self._pasta_mapa_norm) and fonte.startswith(self._pasta_mapa_norm + os.sep)
        # v0.7.0: camada vazia nunca é a sugerida (a mesma regra do cálculo, areas._prioridade_registro)
        tem_desenho = any(g is not None for g in t.base_original.values()) if t.base_original else contar_feicoes(t.layer) > 0
        return (tem_desenho, bool(t.editavel), na_pasta, getattr(t, "_via", 0), contar_feicoes(t.layer))

    @staticmethod
    def _rotulo_candidata(t):
        fonte = _arquivo_da_camada(t.layer) or t.layer.source()
        ext = os.path.splitext(fonte)[1].lstrip(".").upper() or t.layer.providerType()
        pasta = os.path.basename(os.path.dirname(fonte)) if fonte else ""
        return f"Usar '{t.layer.name()}' ({ext}{', pasta ' + pasta if pasta else ''})" + ("" if t.editavel else " - não dá para corrigir")

    def _escolher_repetidas(self):
        """Em cada classe com mais de uma camada (arquivos diferentes), pergunta qual vale; as outras ficam de fora
        da correção e do cálculo (self.descartadas)."""
        self.descartadas = set(self._mesmo_arquivo)
        for lid, (nome_outra, nome_usada, arq) in self._mesmo_arquivo.items():
            self.problemas.append({"codigo": "A", "arquivo": arq, "camada": nome_outra,
                                   "titulo": f"Mesmo arquivo carregado de novo: contada uma vez só ('{nome_usada}')",
                                   "acao": "auto", "area_m2": None, "qtd": None, "geom": None, "grave": False, "detalhe": ""})
        for arq, lista in self._candidatas.items():
            if len(lista) < 2:
                self.camadas[arq] = lista[0]
                continue
            sugerida = max(lista, key=self._nota_candidata)
            ident = f"DUP|{arq}"
            escolha = self._decidir(
                ident, "Camadas repetidas",
                f"{self.nome(arq)}: {len(lista)} camadas diferentes para a mesma classe ("
                + ", ".join(t.layer.name() for t in lista) + ") - qual vale?",
                0.0, None, [(t.layer.id(), self._rotulo_candidata(t)) for t in lista], sugerida.layer.id())
            usada = next((t for t in lista if t.layer.id() == escolha), sugerida)
            self.camadas[arq] = usada
            for t in lista:
                if t is not usada:
                    self.descartadas.add(t.layer.id())
                    self.problemas.append({"codigo": "A", "arquivo": arq, "camada": t.layer.name(),
                                           "titulo": f"Fora do cálculo: a classe {self.nome(arq)} usa '{usada.layer.name()}'",
                                           "acao": "escolha", "area_m2": None, "qtd": None, "geom": None,
                                           "grave": False, "detalhe": ""})

    def _passo(self, texto):
        """Mostra o andamento e deixa o QGIS respirar (não fica 'Não respondendo' em projeto grande)."""
        try:
            if self.progresso:
                self.progresso(texto)
            from qgis.PyQt.QtWidgets import QApplication
            QApplication.processEvents()
        except Exception:
            pass

    # --- registro
    def _problema(self, codigo, arquivo, titulo, acao="auto", area_m2=None, qtd=None, geom=None, grave=False,
                  detalhe=""):
        # v0.5.0: ajuste automático menor que 0,01 m² é poeira numérica (vem de mudar de SRC e voltar): é feito, mas
        # não aparece na lista - senão toda correção nova "achava" de novo algo para corrigir.
        if acao == "auto" and area_m2 is not None and float(area_m2) < AREA_PONTO_M2 and not grave:
            return
        self.problemas.append({
            "codigo": codigo, "arquivo": arquivo, "camada": self.nome(arquivo) if arquivo else "",
            "titulo": titulo, "acao": acao, "area_m2": area_m2, "qtd": qtd, "geom": geom, "grave": bool(grave),
            "detalhe": detalhe,
        })

    def _decidir(self, ident, quadro, descricao, area_m2, geom, opcoes, sugestao):
        """v0.4.0: pergunta técnica que não é "quem cede" (ex.: recorte grande no limite). Entra na tabela de
        decisões da tela com as opções dadas; devolve a opção escolhida (ou a sugestão)."""
        escolha = self.escolhas.get(ident, sugestao)
        escolha = escolha if escolha in [o[0] for o in opcoes] else sugestao
        self.conflitos.append({"id": ident, "quadro": quadro, "descricao": descricao, "area_m2": area_m2, "pecas": 1,
                               "geom": geom, "opcoes": list(opcoes), "sugestao": sugestao, "cede": escolha})
        return escolha

    # --- execução
    def executar(self, escolhas=None):
        """Roda tudo em memória. `escolhas`: {id do conflito: arquivo que cede}. Devolve o relatório."""
        self.escolhas = dict(escolhas or {})
        self.problemas, self.conflitos, self._ids_conflito = [], [], {}
        self._proibidos = {}
        self._cache_app_sem_sup = None
        for lista in self._candidatas.values():
            for c in lista:
                c.voltar_ao_original()
        self._escolher_repetidas()
        for c in self.camadas.values():
            c.reiniciar()
        for nome, motivo in self.ignoradas:
            self.problemas.append({"codigo": "A", "arquivo": "", "camada": nome, "titulo": f"Não corrigida: {motivo}",
                                   "acao": "info", "area_m2": None, "qtd": None, "geom": None, "grave": False, "detalhe": ""})
        for c in self.camadas.values():
            if self._intocavel(c.arquivo):
                continue
            self._passo(f"Conferindo a geometria de {c.nome}...")
            self._limpar_geometrias(c)
            if c.tipo == "P":
                self._sobreposicao_interna(c)
        self._passo("Conferindo o que está fora do imóvel...")
        self._fora_do_imovel()
        self._quadros()
        self._passadas_extras()
        for c in self.camadas.values():
            if c.alterada() and not c.editavel:
                self._problema("A", c.arquivo, f"Não será corrigida: {c.motivo}", "info")
        return self.relatorio()

    def _passadas_extras(self, maximo=4):
        """v0.4.0: a própria correção pode deixar lascas, frestas e faixas finas novas (ex.: um recorte encosta em
        outra classe). Repete a conferência sobre o resultado, com as mesmas decisões, até não sobrar nada
        (no máximo `maximo` vezes). Assim tudo fica certo numa rodada só."""
        ajustes = 0
        for _n in range(maximo):
            if not any(c.mudou_nesta() for c in self.camadas.values()):
                break
            for c in self.camadas.values():
                c.consolidar(); c.reiniciar()
            guarda = (self.problemas, self.conflitos)
            self.problemas, self.conflitos = [], []
            self._passada_extra = True
            try:
                for c in self.camadas.values():
                    if self._intocavel(c.arquivo):
                        continue
                    c.sem_geometria = []
                    self._limpar_geometrias(c)
                    if c.tipo == "P":
                        self._sobreposicao_interna(c)
                self._fora_do_imovel()
                self._quadros()
                novos = [p for p in self.problemas if p["acao"] in ("auto", "escolha")]
            finally:
                self.problemas, self.conflitos = guarda
                self._passada_extra = False
            if not novos:
                break
            ajustes += len(novos)
        if ajustes:
            self._problema("Z", "", f"Conferência repetida sobre o resultado: {ajustes} ajuste(s) fino(s) "
                           f"(lascas, frestas e faixas que a própria correção criou)")

    def nao_corrigidas(self):
        """v0.7.0: camadas que precisavam de correção mas não puderam ser alteradas: {nome no QGIS: motivo}."""
        saida = {}
        for c in self.camadas.values():
            if c.alterada() and not c.editavel:
                try:
                    nome = c.layer.name()
                except Exception:
                    nome = c.nome
                saida[nome] = c.motivo or "não foi possível alterar"
        return saida

    def relatorio(self):
        return {"problemas": list(self.problemas), "conflitos": list(self.conflitos),
                "corrigir": any(p["acao"] in ("auto", "escolha") for p in self.problemas) or bool(self.conflitos),
                "camadas": {a: c.nome for a, c in self.camadas.items()}}

    # 1) geometria de cada feição
    def _limpar_geometrias(self, c):
        sem, invalidas, var_inv, lascas_n, lascas_m2, dup = 0, 0, 0.0, 0, 0.0, 0
        vistos = {}
        vazio_im = None  # v0.7.0: área sem desenho do imóvel (calculada só se houver lasca para decidir)
        for fid in c.sem_geometria:
            if fid not in c.apagar:
                sem += 1
                c.remover(fid)
        for fid, g in c.vivas():
            if c.tipo != "P":
                continue
            ng = g
            try:
                valida = g.isGeosValid()
            except Exception:
                valida = False
            if not valida:
                antes = topo.area_plana(g)
                ng = topo.so_poligonos(g)
                dv = topo.area_plana(ng) - antes
                # v0.5.0: inválida só por arredondamento (anel que encosta nele mesmo por 1e-9 depois de mudar de SRC):
                # corrige em silêncio, não é erro de desenho e não deve aparecer de novo a cada correção
                if abs(dv) >= AREA_PONTO_M2:
                    invalidas += 1
                    var_inv += dv
            if ng is not None:
                partes = topo.partes_simples(ng)
                minimo = AREA_PONTO_M2 if c.arquivo == "AREA_DO_IMOVEL" else AREA_LASCA_M2
                boas = [p for p in partes if topo.area_plana(p) >= minimo and _largura_m(p) >= LARGURA_FIAPO_M]
                if len(boas) != len(partes) and c.arquivo != "AREA_DO_IMOVEL":
                    # v0.5.0: lasca (< 1 m²) só sai se OUTRA classe do mesmo quadro tem divisa de verdade com ela para
                    # recebê-la. Se não tem, ela voltaria para esta mesma camada (vai-e-volta a cada correção): fica.
                    # v0.7.0: a mesma regra vale para o FIAPO (< 1 mm de largura) e o PÓ (< 0,01 m²). Antes eles saíam
                    # sempre; o buraco fino que ficava voltava para a mesma camada como fresta e o fiapo reaparecia -
                    # a correção "achava" sempre a mesma coisa de novo (caso real: fio de 0,013 m² e ~700 m colado na
                    # Área Consolidada). Só o que é menor que o ruído numérico (o buraco dele é ignorado) sai sempre.
                    if c.arquivo in self._classes_do_imovel() and vazio_im is None:
                        vazio_im = self._vazio_do_imovel() or False
                    boas = [p for p in partes if p in boas or (topo.area_plana(p) > AREA_RUIDO_M2 and
                            _largura_m(p) >= LARGURA_RUIDO_M and (not self._tem_vizinha_real(c.arquivo, p) or
                            (c.arquivo in self._classes_do_imovel() and self._encosta_no_vazio(p, vazio_im or None))))]
                if len(boas) != len(partes):
                    lascas_n += len(partes) - len(boas)
                    lascas_m2 += sum(topo.area_plana(p) for p in partes) - sum(topo.area_plana(p) for p in boas)
                    ng = topo.juntar(boas)
            if ng is None:
                c.definir(fid, None)
                continue
            # repetida: mesma caixa e mesma área, confirmada pela diferença simétrica
            bb = ng.boundingBox()
            chave = (round(bb.xMinimum(), 2), round(bb.yMinimum(), 2), round(bb.xMaximum(), 2),
                     round(bb.yMaximum(), 2), round(topo.area_plana(ng), 2))
            outro = vistos.get(chave)
            if outro is not None:
                try:
                    if topo.area_plana(ng.symDifference(outro)) < AREA_PONTO_M2:
                        dup += 1
                        c.remover(fid)
                        continue
                except Exception:
                    pass
            vistos[chave] = ng
            if ng is not g:
                c.definir(fid, ng)
        if sem:
            self._problema("G1", c.arquivo, f"{sem} registro(s) sem geometria apagado(s)", qtd=sem)
        if invalidas:
            self._problema("G1", c.arquivo, f"{invalidas} geometria(s) inválida(s) corrigida(s) "
                           f"(variação {var_inv:+.2f} m²)", qtd=invalidas)
        if lascas_n:
            self._problema("G1", c.arquivo, f"{lascas_n} lasca(s) solta(s) apagada(s) (partes menores que 1 m² ou com "
                           f"menos de 1 mm de largura; o buraco é somado à classe vizinha)", area_m2=lascas_m2, qtd=lascas_n)
        if dup:
            self._problema("A6", c.arquivo, f"{dup} feição(ões) repetida(s) apagada(s)", qtd=dup)

    # 2) feições da mesma camada sobrepostas
    def _sobreposicao_interna(self, c):
        feitas = set()
        total, qtd, pecas = 0.0, 0, []
        for fid in sorted(fid for fid, _g in c.vivas()):
            g = c.geoms.get(fid)
            if g is None or fid in c.apagar:
                continue
            viz = [h for f2, h in c.perto(g.boundingBox()) if f2 in feitas]
            if viz:
                try:
                    cobre = viz[0] if len(viz) == 1 else topo.uniao(viz, self.params)
                    inter = topo.intersecao(g, cobre, self.params)
                except Exception:
                    inter, cobre = None, None
                a = topo.area_plana(inter)
                if a > AREA_RUIDO_M2:
                    ng = diferenca_robusta(g, cobre, self.params)
                    total += a
                    qtd += 1
                    pecas.append(inter)
                    c.definir(fid, ng)
            feitas.add(fid)
        if qtd:
            self._problema("G5", c.arquivo, f"{qtd} feição(ões) desta camada por cima de outra da mesma camada: "
                           f"a repetição saiu da de baixo", area_m2=total, qtd=qtd, geom=topo.juntar(pecas))

    # 3) fora do imóvel
    def _fora_do_imovel(self):
        imovel_c = self.camadas.get("AREA_DO_IMOVEL")
        imovel = imovel_c.uniao(self.params) if imovel_c else None
        if topo.vazia(imovel):
            if self.camadas:
                self._problema("G2", "", "Sem a camada Área do Imóvel: o recorte no limite não foi feito", "info")
            return
        self._imovel = imovel
        caixa_im = imovel.boundingBox()
        motor = _preparar(imovel)
        for arq, c in self.camadas.items():
            if self._livre(arq) or self._intocavel(arq):
                continue
            perdida, maior, cortadas, sumiram, foras, cortes = 0.0, 0.0, 0, 0, [], []
            comp_fora = 0.0
            for fid, g in c.vivas():
                try:
                    if caixa_im.contains(g.boundingBox()) and _contem(motor, imovel, g):
                        continue
                except Exception:
                    pass
                if c.tipo == "Pt":
                    if not _toca(motor, imovel, g):
                        sumiram += 1
                        c.remover(fid)
                    continue
                if c.tipo == "L":
                    try:
                        dentro = g.intersection(imovel)
                        antes = float(g.length())
                        depois = 0.0 if topo.vazia(dentro) else float(dentro.length())
                    except Exception:
                        continue
                    if antes - depois > 0.01:
                        comp_fora += antes - depois
                        cortadas += 1
                        if topo.vazia(dentro) or depois <= 0:
                            sumiram += 1
                            c.remover(fid)
                        else:
                            c.definir(fid, dentro)
                    continue
                try:
                    fora = topo.diferenca(g, imovel, self.params)
                except Exception:
                    continue
                a_fora = topo.area_plana(fora)
                if a_fora < AREA_PONTO_M2:
                    continue
                dentro = topo.intersecao(g, imovel, self.params)
                dentro = _sem_fiapos(dentro) if dentro is not None else None
                perdida += a_fora
                maior = max(maior, a_fora)
                cortadas += 1
                foras.append(fora)
                if dentro is None:
                    sumiram += 1
                cortes.append((fid, dentro))
            if c.tipo == "P" and cortadas:
                grave = maior > REVISAR_FORA_M2 or sumiram > 0
                det = []
                if maior > REVISAR_FORA_M2:
                    det.append(f"o maior recorte foi de {_texto_area(maior)}: recorte desse tamanho não é imprecisão "
                               f"de traçado, confira se o limite do imóvel está certo")
                if sumiram:
                    det.append(f"{sumiram} feição(ões) estavam INTEIRAMENTE fora do imóvel e serão apagadas")
                g_fora = topo.juntar(foras)
                recortar = True
                if grave:  # v0.4.0: avaliação técnica - pergunta em vez de só avisar
                    recortar = self._decidir(
                        f"FORA|{arq}", "Fora do imóvel",
                        f"{self.nome(arq)}: {_texto_area(perdida)} fora do limite do imóvel"
                        + (f" ({sumiram} feição(ões) inteira(s) fora)" if sumiram else ""),
                        perdida, g_fora,
                        [("recortar", "Recortar no limite do imóvel"),
                         ("manter", "Não mexer (o limite do imóvel pode estar errado)")], "recortar") == "recortar"
                if recortar:
                    for fid, dentro in cortes:
                        c.definir(fid, dentro)
                    self._problema("G2", arq, f"Parte fora do imóvel recortada no limite ({cortadas} feição(ões))",
                                   "escolha" if grave else "auto", area_m2=perdida, qtd=cortadas, geom=g_fora,
                                   grave=grave, detalhe="; ".join(det))
                else:
                    self._problema("G2", arq, "Parte fora do imóvel mantida (decisão técnica): o quadro conta só a "
                                   "parte dentro do imóvel", "escolha", area_m2=perdida, qtd=cortadas, geom=g_fora,
                                   grave=True, detalhe="confira o limite do imóvel")
            elif c.tipo == "L" and cortadas:
                self._problema("G2", arq, f"Linha fora do imóvel recortada ({comp_fora:,.1f} m em {cortadas} feição(ões))",
                               qtd=cortadas, grave=sumiram > 0)
            elif c.tipo == "Pt" and sumiram:
                self._problema("G2", arq, f"{sumiram} ponto(s) fora do imóvel apagado(s)", qtd=sumiram, grave=True)

    # 4) quadros (mesmas regras do cálculo)
    def _personalizadas(self):
        """v0.5.0: camadas personalizadas por lugar no quadro, na MESMA ordem do cálculo (nome, sem diferenciar
        maiúsculas). Antes a correção não olhava para elas e o cálculo descontava as sobreposições -> diferença."""
        saida = {}
        try:
            from .catalogo import lugar_quadro
        except Exception:
            return saida
        for arq, c in self.camadas.items():
            if c.tipo != "P":
                continue
            try:
                cod = lugar_quadro(self.indice.get(arq))
            except Exception:
                cod = ""
            if cod:
                saida.setdefault(cod, []).append(arq)
        for cod in saida:
            saida[cod].sort(key=lambda a: self.nome(a).casefold())
        return saida

    def _app_dentro_da_suprimida(self):
        """v0.5.0: APP Suprimida do período é, por definição, Área Suprimida do mesmo período. Como as camadas de APP
        não são alteradas, a parte da APP Suprimida que está fora da Área Suprimida é SOMADA à Área Suprimida (a
        Suprimida tem a maior prioridade no imóvel, então as outras coberturas cedem esse pedaço). Sem isso o quadro
        da Área antropizada nunca fecha (APP + RL + Passível ficava maior que a Área Suprimida)."""
        imovel = getattr(self, "_imovel", None)
        for _per, sup_arq, app_arq, *_r in PERIODOS_ANTROPIZADA:
            sc, ac = self.camadas.get(sup_arq), self.camadas.get(app_arq)
            if sc is None or ac is None or sc.tipo != "P" or ac.tipo != "P" or self._intocavel(sup_arq):
                continue
            app = ac.uniao(self.params)
            if topo.vazia(app):
                continue
            if imovel is not None:
                app = topo.intersecao(app, imovel, self.params)
            sup = sc.uniao(self.params)
            try:
                falta = topo.diferenca(app, sup, self.params) if not topo.vazia(sup) else app
            except Exception:
                continue
            # v0.7.0: a parte da APP Suprimida que está em cima da Área Suprimida do OUTRO período não é somada: a mesma
            # terra não foi suprimida antes E depois de 2019. Somar fazia o quadro do imóvel tirar de volta (sobreposição
            # entre os dois períodos) e a correção nunca terminava igual (caso real de cliente, 38 m²). Como as
            # camadas de APP não são alteradas, fica só o aviso para conferir a APP.
            outra_arq = next((x[1] for x in PERIODOS_ANTROPIZADA if x[1] != sup_arq), None)
            oc = self.camadas.get(outra_arq) if outra_arq else None
            og = oc.uniao(self.params) if (oc is not None and oc.tipo == "P") else None
            if not topo.vazia(og) and not topo.vazia(falta):
                try:
                    na_outra = topo.intersecao(falta, og, self.params)
                    falta = topo.diferenca(falta, og, self.params)
                except Exception:
                    na_outra = None
                a_outra = 0.0 if topo.vazia(na_outra) else topo.area_plana(na_outra)
                if a_outra >= 1.0:
                    self._problema("T2", app_arq, f"{self.nome(app_arq)} em cima de {self.nome(outra_arq)}: "
                                   f"{_texto_area(a_outra)} não somados a {self.nome(sup_arq)} (a mesma área não pode ser "
                                   f"suprimida nos dois períodos) - confira a camada de APP", "info",
                                   area_m2=a_outra, geom=na_outra)
            if topo.vazia(falta):
                continue
            # v0.7.0: pedaço menor que uma lasca (1 m²) que nem encosta na Área Suprimida não é somado: viraria lasca
            # solta, a limpeza de lascas apagaria e a próxima passada somaria de novo (vai-e-volta; caso real de
            # cliente, 0,2 m²). No quadro ele fica de fora da Área antropizada, como a APP Suprimida que sobra.
            def _encosta_na_sup(peca):
                if topo.vazia(sup):
                    return False
                try:
                    return topo.area_plana(peca.buffer(0.02, 2).intersection(sup)) >= DIVISA_MIN_M2
                except Exception:
                    return True
            pecas = [p for p in topo.partes_simples(falta) if topo.area_plana(p) > AREA_RUIDO_M2 and
                     (topo.area_plana(p) >= AREA_LASCA_M2 or _encosta_na_sup(p))]
            if not pecas:
                continue
            area = sum(topo.area_plana(p) for p in pecas)
            if area < AREA_PONTO_M2:
                continue
            g = topo.juntar(pecas)
            somar = True
            if area > REVISAR_CORTE_M2:
                somar = self._decidir(
                    f"APPSUP|{app_arq}", "Área antropizada",
                    f"{self.nome(app_arq)}: {_texto_area(area)} fora de {self.nome(sup_arq)}", area, g,
                    [("somar", f"Somar esse pedaço à {self.nome(sup_arq)} (APP Suprimida é Área Suprimida)"),
                     ("manter", "Não mexer (confira a APP Suprimida)")], "somar") == "somar"
            if not somar:
                self._problema("T2", app_arq, f"{self.nome(app_arq)} fora de {self.nome(sup_arq)} mantida (decisão técnica)",
                               "escolha", area_m2=area, geom=g, grave=True,
                               detalhe="o quadro da Área antropizada não vai fechar com a Área Suprimida")
                continue
            for peca in pecas:
                fid = self._feicao_destino(sc, peca)
                if fid is None:
                    continue
                try:
                    ng = topo.uniao([sc.geoms.get(fid), peca], self.params)
                except Exception:
                    ng = None
                if ng is not None:
                    sc.definir(fid, ng)
            self._problema("T2", sup_arq, f"{self.nome(app_arq)} que estava fora de {self.nome(sup_arq)} somada a "
                           f"{self.nome(sup_arq)}", "escolha" if area > REVISAR_CORTE_M2 else "auto", area_m2=area,
                           qtd=len(pecas), geom=g)

    def _quadros(self):
        cfg = self.config
        fechamento = [str(x).upper() for x in cfg.get("fechamento", FECHAMENTO_PADRAO)]
        if cfg.get("fechamento_inclui_hidrografia") and "HIDROGRAFIA" not in fechamento:
            fechamento.append("HIDROGRAFIA")
        fechamento = [x for x in dict.fromkeys(fechamento) if x in self.indice]
        pers = self._personalizadas()
        # v0.5.0: personalizadas do quadro do imóvel entram no fim do fechamento, como no cálculo
        for arq in pers.get("IMOVEL", []):
            if arq not in fechamento:
                fechamento.append(arq)
        imovel = getattr(self, "_imovel", None)
        self._app_dentro_da_suprimida()
        # Água (rio, barramento...) nunca é consolidada nem vegetação: ganha sempre e entra no quadro na linha
        # Hidrografia (o cálculo faz o mesmo), então tirar o rio da Consolidada não deixa área sem classificação.
        agua = []
        if imovel is not None and cfg.get("agua_no_fechamento", True):
            for a in AGUA_FECHAMENTO:
                ca = self.camadas.get(a)
                ua = ca.uniao(self.params) if (ca and ca.tipo == "P") else None
                try:
                    if ua is not None and topo.area_plana(topo.intersecao(ua, imovel, self.params)) >= 1.0:
                        agua.append(a)
                except Exception:
                    continue
        sup = [x for x in SUPRESSAO_ANTES_DA_AGUA if x in fechamento] if agua else []
        prio_f = sup + agua + _ordenar_prioridade([x for x in fechamento if x not in AGUA_FECHAMENTO and x not in sup],
                                                  cfg.get("prioridade_fechamento") or PRIORIDADE_FECHAMENTO_PADRAO)
        # v0.5.0: a Área Suprimida também recebe frestas (o cálculo faz assim). O pedaço novo é classificado no
        # quadro da Área antropizada logo abaixo (RL Suprimida ou Passível), então não volta a ser fresta.
        self._quadro("Áreas Totais do Imóvel", imovel, self.nome("AREA_DO_IMOVEL"), prio_f, sempre_ganham=set(agua),
                     convivem=(set(agua), set(sup)))

        app_c = self.camadas.get("APP_TOTAL")
        app_total = app_c.uniao(self.params) if app_c else None
        extras = {}
        for _p, sup_arq, app_arq, *_r in PERIODOS_ANTROPIZADA:
            sc = self.camadas.get(sup_arq)
            sg = sc.uniao(self.params) if sc else None
            if not topo.vazia(sg):
                extras[app_arq] = (self.nome(sup_arq), sg)
        prio_app = _ordenar_prioridade(list(APP_SUBCLASSES), cfg.get("prioridade_app") or PRIORIDADE_APP_PADRAO)
        if not cfg.get("app_separada", True):
            self._quadro("Área de Preservação Permanente", app_total, self.nome("APP_TOTAL"), prio_app, extras,
                         pai_arq="APP_TOTAL")

        prio_rl = _ordenar_prioridade(list(PRIORIDADE_RESERVA_PADRAO), cfg.get("prioridade_reserva") or PRIORIDADE_RESERVA_PADRAO)
        # v0.5.0: as subclasses da RL ficam DENTRO da Reserva Legal (regra P2); antes só a sobreposição era vista.
        rl_c = self.camadas.get("RESERVA_LEGAL")
        rl_g = rl_c.uniao(self.params) if (rl_c is not None and rl_c.tipo == "P") else None
        todas_rl = all(a in self.camadas for a in PRIORIDADE_RESERVA_PADRAO)
        self._quadro("Reserva Legal", rl_g, self.nome("RESERVA_LEGAL"), prio_rl, absorver=todas_rl)
        self._passivel_fora_app_rl()

        prio_ant = [x for x in [str(y).upper() for y in (cfg.get("prioridade_antropizada") or PRIORIDADE_ANTROPIZADA_PADRAO)]
                    if x in ("RL", "PASSIVEL")]
        for x in ("RL", "PASSIVEL"):
            if x not in prio_ant:
                prio_ant.append(x)
        for _per, sup_arq, app_arq, rl_direto, pas_arq, quadro, _crl, _cs in PERIODOS_ANTROPIZADA:
            sc = self.camadas.get(sup_arq)
            pai = sc.uniao(self.params) if sc else None
            rl_arq = rl_direto if rl_direto in self.camadas else "RESERVA_SUPRIMIDA"
            filhos = [app_arq] + [(rl_arq if x == "RL" else pas_arq) for x in prio_ant]
            # A APP já foi resolvida no quadro da APP e a RL (inteira) é usada no quadro da Reserva: aqui só a
            # Supressão Passível cede (por definição ela fica fora da APP e da RL).
            # v0.5.0: só a APP não recebe frestas (igual ao cálculo); a RL Suprimida recebe.
            self._quadro(quadro, pai, self.nome(sup_arq), filhos, fixos={app_arq, rl_arq},
                         sem_recorte={"RESERVA_SUPRIMIDA", app_arq}, sem_lasca={app_arq}, pai_arq=sup_arq,
                         definicao=(rl_arq, pas_arq))

        # Quadros que SOMAM camadas: sobreposição entre elas conta duas vezes no total.
        # Área Hidrográfica: a feição específica (barramento, tanque...) fica com a área; o rio cede.
        self._quadro("Área Hidrográfica", None, "", ["BARRAGEM", "TANQUE", "CACIMBA", "LAGOA_NATURAL", "HIDROGRAFIA"],
                     absorver=False)
        self._quadro("Área Total de Compensação", None, "", ["COMPENSACAO_DANOS", "COMPENSACAO_FLORESTAL",
                                                               "AREA_RECOMPOSICAO"], absorver=False)
        self._personalizadas_somadas(pers)
        self._totais()

    def _passivel_fora_app_rl(self):
        """v0.5.0 (regra P3): Supressão em Área Passível é, por definição, supressão FORA da APP e FORA da Reserva Legal.
        A parte da Passível que está dentro da APP Total ou da RL sai da Passível (faixa fina sozinha; mancha larga,
        você escolhe). O buraco que fica na Área Suprimida é classificado pela definição no quadro de baixo."""
        regioes = [(a, self._uniao_classes([a])) for a in ("APP_TOTAL", "RESERVA_LEGAL") if a in self.camadas]
        regioes = [(a, g) for a, g in regioes if not topo.vazia(g)]
        if not regioes:
            return
        for _per, _sup, _app, _rl, pas_arq, quadro, *_r in PERIODOS_ANTROPIZADA:
            c = self.camadas.get(pas_arq)
            if c is None or c.tipo != "P" or self._intocavel(pas_arq):
                continue
            for reg_arq, reg_g in regioes:
                ug = c.uniao(self.params)
                if topo.vazia(ug):
                    break
                try:
                    inter = topo.intersecao(ug, reg_g, self.params)
                except Exception:
                    continue
                pecas = _pecas(inter)
                if not pecas:
                    continue
                area = sum(topo.area_plana(p) for p in pecas)
                g = topo.juntar(pecas)
                tirar = True
                largas = [p for p in pecas if not self._eh_fresta(p)]
                if largas and area > REVISAR_CORTE_M2:
                    tirar = self._decidir(
                        f"P3|{pas_arq}|{reg_arq}", quadro,
                        f"{self.nome(pas_arq)}: {_texto_area(area)} dentro de {self.nome(reg_arq)}", area, g,
                        [("tirar", f"Tirar da Passível (dentro da {'APP' if reg_arq == 'APP_TOTAL' else 'RL'} vira "
                                   f"{'APP Suprimida' if reg_arq == 'APP_TOTAL' else 'RL Suprimida'})"),
                         ("manter", "Não mexer")], "tirar") == "tirar"
                if not tirar:
                    continue
                tirada, _s = c.tirar(g, self.params)
                if tirada > AREA_RUIDO_M2:
                    self._problema("P3", pas_arq, f"{quadro}: parte de {self.nome(pas_arq)} dentro de "
                                   f"{self.nome(reg_arq)} tirada (Passível é fora da APP e da RL)",
                                   "escolha" if (largas and area > REVISAR_CORTE_M2) else "auto",
                                   area_m2=tirada, qtd=len(pecas), geom=g)

    def _personalizadas_somadas(self, pers):
        """v0.5.0: personalizadas dos quadros que SOMAM (Passivos, Hidrográfica, Compensação). O cálculo dá a cada
        uma só a parte que ainda não está em outra linha do mesmo quadro; aqui essa parte repetida sai do desenho da
        personalizada (faixa fina sozinha; mancha larga, você escolhe), para o desenho bater com o quadro."""
        try:
            from .areas import BASE_QUADROS_SOMADOS
            from .catalogo import QUADRO_DO_LUGAR
        except Exception:
            return
        for cod in ("PASSIVOS", "HIDRO", "COMPENSACAO"):
            arqs = pers.get(cod) or []
            if not arqs:
                continue
            quadro = QUADRO_DO_LUGAR.get(cod) or cod
            base = [a for a in BASE_QUADROS_SOMADOS.get(quadro, ()) if a in self.camadas and self.camadas[a].tipo == "P"]
            ocupado = self._uniao_classes(base) if base else None
            for arq in arqs:
                c = self.camadas[arq]
                if self._intocavel(arq):
                    continue
                ug = c.uniao(self.params)
                if topo.vazia(ug):
                    continue
                if not topo.vazia(ocupado):
                    try:
                        inter = topo.intersecao(ug, ocupado, self.params)
                    except Exception:
                        inter = None
                    pecas = _pecas(inter)
                    if pecas:
                        area = sum(topo.area_plana(p) for p in pecas)
                        g = topo.juntar(pecas)
                        tirar = True
                        if area > REVISAR_CORTE_M2:
                            tirar = self._decidir(
                                f"PERS|{quadro}|{arq}", quadro,
                                f"{self.nome(arq)}: {_texto_area(area)} já contados em outra linha de {quadro}", area, g,
                                [("tirar", f"Tirar de {self.nome(arq)} (no quadro conta só na outra linha)"),
                                 ("manter", "Não mexer (o cálculo desconta do mesmo jeito)")], "tirar") == "tirar"
                        if tirar:
                            tirada, _s = c.tirar(g, self.params)
                            if tirada > AREA_RUIDO_M2:
                                self._problema("T1", arq, f"{quadro}: parte de {self.nome(arq)} que já está em outra linha "
                                               f"tirada", "escolha" if area > REVISAR_CORTE_M2 else "auto",
                                               area_m2=tirada, qtd=len(pecas), geom=g)
                ocupado = topo.uniao([g for g in (ocupado, c.uniao(self.params)) if not topo.vazia(g)], self.params)

    def _totais(self):
        """v0.4.0: camadas de total desenhadas à parte (APP Suprimida, Área Suprimida, Supressão em Área Passível)
        têm de ser exatamente antes + depois de 2019 (regras R3, R6, R9); a RL Suprimida tem de ficar dentro da
        Área Suprimida (R8). Diferença pequena é corrigida sozinha; grande vira decisão técnica."""
        for total, partes in TOTAIS_PARTES.items():
            ct = self.camadas.get(total)
            ps = [self.camadas[p] for p in partes if p in self.camadas and self.camadas[p].tipo == "P"]
            if ct is None or ct.tipo != "P" or not ps or not ct.vivas():
                continue
            alvo = topo.uniao([c.uniao(self.params) for c in ps], self.params)
            if topo.vazia(alvo):
                continue
            boas = [p for p in topo.partes_simples(alvo) if topo.area_plana(p) >= AREA_LASCA_M2]
            alvo = topo.juntar(boas) if boas else None  # lasca das partes não vira lasca no total
            if topo.vazia(alvo):
                continue
            atual = ct.uniao(self.params)
            try:
                sobra = topo.diferenca(atual, alvo, self.params)
                falta = topo.diferenca(alvo, atual, self.params) if TOTAIS_SOMA[total] else None
            except Exception:
                continue
            a_sobra = 0.0 if topo.vazia(sobra) else topo.area_plana(sobra)
            falta_pecas = [] if topo.vazia(falta) else [p for p in topo.partes_simples(falta) if topo.area_plana(p) >= AREA_LASCA_M2]
            a_falta = sum(topo.area_plana(p) for p in falta_pecas)
            falta = topo.juntar(falta_pecas) if falta_pecas else None
            if a_sobra + a_falta < AREA_PONTO_M2:
                continue
            nomes_p = " + ".join(self.nome(p) for p in partes)
            refazer = True
            if a_sobra + a_falta > REVISAR_CORTE_M2:
                refazer = self._decidir(
                    f"TOTAL|{total}", "Totais",
                    f"{self.nome(total)} difere de {nomes_p} em {_texto_area(a_sobra + a_falta)}", a_sobra + a_falta,
                    topo.juntar([g for g in (sobra, falta) if not topo.vazia(g)]),
                    [("refazer", f"Acertar {self.nome(total)} para ficar igual a {nomes_p}"),
                     ("manter", "Não mexer")], "refazer") == "refazer"
            if not refazer:
                continue
            if a_sobra >= AREA_RUIDO_M2:
                ct.tirar(sobra, self.params)
            if a_falta >= AREA_RUIDO_M2:
                for peca in topo.partes_simples(falta):
                    if topo.area_plana(peca) < AREA_LASCA_M2:
                        continue  # fiapo de borda: não vale criar lasca no total
                    fid = self._feicao_destino(ct, peca)
                    if fid is None:
                        continue
                    try:
                        ng = topo.uniao([ct.geoms.get(fid), peca], self.params)
                    except Exception:
                        ng = None
                    if ng is not None:
                        ct.definir(fid, ng)
            self._problema("R", total, f"{self.nome(total)} acertada para ficar igual a {nomes_p}",
                           "escolha" if a_sobra + a_falta > REVISAR_CORTE_M2 else "auto", area_m2=a_sobra + a_falta)

    def _quadro(self, quadro, pai, nome_pai, filhos, extras=None, absorver=True, fixos=None, sem_recorte=None,
                sem_lasca=None, sempre_ganham=None, convivem=None, pai_arq=None, definicao=None):
        fixos, sem_recorte, sem_lasca, extras = set(fixos or ()), set(sem_recorte or ()), set(sem_lasca or ()), extras or {}
        conv_a, conv_b = convivem or (set(), set())
        sempre_ganham = set(sempre_ganham or ())
        ordem = [a for a in filhos if a in self.camadas and self.camadas[a].tipo == "P"]
        if not ordem:
            return
        self._passo(f"Conferindo sobreposições: {quadro}...")
        pai = None if topo.vazia(pai) else pai
        # a) filha fora do pai (e do pai extra)
        for arq in ordem:
            if arq in sem_recorte:
                continue
            c = self.camadas[arq]
            for limite, nome_lim in ((pai, nome_pai), (extras.get(arq, (None, None))[1], extras.get(arq, (None, None))[0])):
                if limite is None or arq == "AREA_DO_IMOVEL":
                    continue
                if quadro == "Áreas Totais do Imóvel":
                    continue  # já recortado em _fora_do_imovel (hidrografia pode sair)
                fora_total, n, foras, cortes = 0.0, 0, [], []
                motor = _preparar(limite)
                for fid, g in c.vivas():
                    try:
                        if _contem(motor, limite, g):
                            continue
                        fora = topo.diferenca(g, limite, self.params)
                    except Exception:
                        continue
                    a = topo.area_plana(fora)
                    if a < AREA_PONTO_M2:
                        continue
                    dentro = topo.intersecao(g, limite, self.params)
                    cortes.append((fid, _sem_fiapos(dentro) if dentro is not None else None))
                    fora_total += a; n += 1; foras.append(fora)
                if n:
                    grande = fora_total > REVISAR_FORA_M2
                    g_fora = topo.juntar(foras)
                    recortar = True
                    if grande:  # v0.4.0: avaliação técnica
                        recortar = self._decidir(
                            f"MAE|{quadro}|{arq}|{nome_lim}", quadro,
                            f"{self.nome(arq)}: {_texto_area(fora_total)} fora de {nome_lim}",
                            fora_total, g_fora,
                            [("recortar", f"Recortar no limite de {nome_lim}"),
                             ("manter", f"Não mexer (falta desenhar {nome_lim} ali)")], "recortar") == "recortar"
                    if recortar:
                        for fid, dentro in cortes:
                            c.definir(fid, dentro)
                        self._problema("T2", arq, f"{quadro}: parte fora de {nome_lim} recortada ({n} feição(ões))",
                                       "escolha" if grande else "auto", area_m2=fora_total, qtd=n, geom=g_fora, grave=grande,
                                       detalhe=(f"recorte grande: confira também a camada {nome_lim}" if grande else ""))
                    else:
                        self._problema("T2", arq, f"{quadro}: parte fora de {nome_lim} mantida (decisão técnica)", "escolha",
                                       area_m2=fora_total, qtd=n, geom=g_fora, grave=True,
                                       detalhe=f"desenhe {nome_lim} nessa área para o quadro fechar")
        # b) sobreposição entre irmãs
        for j, arq_b in enumerate(ordem):
            for arq_a in ordem[:j]:
                if arq_a in fixos and arq_b in fixos:
                    # v0.4.0: duas classes fixas (ex.: APP Suprimida x RL Suprimida) - mancha larga pode ser
                    # verdade (RL com APP dentro); faixa fina é erro de traçado: sai da de trás (o cálculo dá à da frente)
                    ca, cb = self.camadas[arq_a], self.camadas[arq_b]
                    ua, ub = ca.uniao(self.params), cb.uniao(self.params)
                    if topo.vazia(ua) or topo.vazia(ub) or ca is cb:
                        continue
                    try:
                        finas = [p for p in _pecas(topo.intersecao(ua, ub, self.params)) if _largura_m(p) < LARGURA_FAIXA_M]
                    except Exception:
                        finas = []
                    if finas:
                        tirada, _s = cb.tirar(topo.juntar(finas), self.params)
                        if tirada > AREA_RUIDO_M2:
                            self._problema("T1", arq_b, f"{quadro}: {len(finas)} faixa(s) fina(s) de {self.nome(arq_b)} por cima "
                                           f"de {self.nome(arq_a)} (erro de traçado) tiradas", area_m2=tirada, qtd=len(finas))
                    continue
                if arq_a in sempre_ganham and arq_b in sempre_ganham:
                    continue  # água x água: resolvido no quadro Área Hidrográfica
                if (arq_a in conv_a and arq_b in conv_b) or (arq_a in conv_b and arq_b in conv_a):
                    # v0.4.0: barragem/rio feito em área suprimida - as duas coisas são verdade, nenhuma camada é
                    # cortada; no quadro a área conta como Suprimida (passivo)
                    try:
                        ua, ub = self.camadas[arq_a].uniao(self.params), self.camadas[arq_b].uniao(self.params)
                        inter = topo.intersecao(ua, ub, self.params) if not (topo.vazia(ua) or topo.vazia(ub)) else None
                        a_int = topo.area_plana(inter) if not topo.vazia(inter) else 0.0
                    except Exception:
                        a_int, inter = 0.0, None
                    if a_int >= 1.0:
                        sup_arq = arq_a if arq_a in conv_b else arq_b
                        agua_arq = arq_b if sup_arq == arq_a else arq_a
                        self._problema("T1", "", f"{quadro}: {self.nome(agua_arq)} feita em {self.nome(sup_arq)} - mantida nas "
                                       f"duas camadas (a área foi suprimida e hoje é água); no quadro conta como "
                                       f"{self.nome(sup_arq)}", "info", area_m2=a_int, geom=inter)
                    continue
                ca, cb = self.camadas[arq_a], self.camadas[arq_b]
                ua, ub = ca.uniao(self.params), cb.uniao(self.params)
                if topo.vazia(ua) or topo.vazia(ub) or ca is cb:
                    continue
                try:
                    inter = topo.intersecao(ua, ub, self.params)
                except Exception:
                    continue
                pecas = _pecas(inter)
                if not pecas:
                    continue
                finas = [p for p in pecas if _largura_m(p) < LARGURA_FAIXA_M]
                largas = [p for p in pecas if _largura_m(p) >= LARGURA_FAIXA_M]
                # quem perde pela prioridade (o de trás); se for fixo, perde o outro
                perde_padrao = arq_b if arq_b not in fixos else arq_a
                if arq_a in sempre_ganham or arq_b in sempre_ganham:
                    perde_padrao = arq_b if arq_a in sempre_ganham else arq_a
                agua_ganha = perde_padrao not in sempre_ganham and (arq_a in sempre_ganham or arq_b in sempre_ganham)
                if finas:
                    g_finas = topo.juntar(finas)
                    alvo = self.camadas[perde_padrao]
                    tirada, sumiram = alvo.tirar(g_finas, self.params)
                    if tirada > AREA_RUIDO_M2 or sumiram:
                        ganha = arq_a if perde_padrao == arq_b else arq_b
                        self._problema("T1", perde_padrao,
                                       f"{quadro}: {len(finas)} faixa(s) fina(s) por cima de {self.nome(ganha)} (erro de "
                                       f"traçado) tiradas de {self.nome(perde_padrao)}",
                                       area_m2=tirada, qtd=len(finas), geom=g_finas)
                if largas:
                    g_largas = topo.juntar(largas)
                    area = sum(topo.area_plana(p) for p in largas)
                    ident = f"{quadro}|{arq_a}|{arq_b}"
                    perguntar = arq_a not in fixos and arq_b not in fixos and not agua_ganha
                    if perguntar:
                        cede = self.escolhas.get(ident, perde_padrao)
                        cede = cede if cede in (arq_a, arq_b) else perde_padrao
                        self.conflitos.append({
                            "id": ident, "quadro": quadro, "a": arq_a, "b": arq_b, "nome_a": self.nome(arq_a),
                            "nome_b": self.nome(arq_b), "area_m2": area, "pecas": len(largas), "geom": g_largas,
                            "sugestao": perde_padrao, "cede": cede,
                        })
                    else:
                        cede = perde_padrao  # ex.: Supressão Passível nunca fica por cima da APP ou da RL
                    tirada, sumiram = self.camadas[cede].tirar(g_largas, self.params)
                    ganha = arq_a if cede == arq_b else arq_b
                    det = []
                    if sumiram:
                        det.append(f"{sumiram} feição(ões) de {self.nome(cede)} ficam inteiras dentro de "
                                   f"{self.nome(ganha)} e serão apagadas")
                    if agua_ganha:
                        self._problema("T1", cede, f"{quadro}: {self.nome(ganha)} por cima de {self.nome(cede)} - água não é "
                                       f"{self.nome(cede).lower()}: área tirada de {self.nome(cede)}; no quadro ela fica na "
                                       f"linha Hidrografia", "auto", area_m2=tirada, qtd=len(largas), geom=g_largas,
                                       grave=bool(sumiram), detalhe="; ".join(det))
                        continue
                    if area > REVISAR_CORTE_M2:
                        det.append("mancha larga: é conflito de classificação, confira qual camada está certa")
                    self._problema("T1", cede, f"{quadro}: {len(largas)} mancha(s) de {self.nome(cede)} por cima de "
                                   f"{self.nome(ganha)} tirada(s) de {self.nome(cede)}",
                                   "escolha" if perguntar else "auto", area_m2=tirada, qtd=len(largas), geom=g_largas,
                                   grave=area > REVISAR_CORTE_M2 or bool(sumiram), detalhe="; ".join(det))
        # c) frestas entre classes
        if absorver and pai is not None:
            self._frestas(quadro, pai, nome_pai, ordem, extras, sem_lasca, pai_arq, definicao)

    def _eh_fresta(self, parte):
        """v0.5.0: fresta = erro de traçado entre duas classes. Vale para qualquer comprimento: o que decide é a
        LARGURA. Além das regras do cálculo (menos de 1 m² ou largura média < 0,5 m), toda parte em que não cabe um
        círculo de LARGURA_FRESTA_M de diâmetro é fresta (faixas compridas de 1-2 m que sobram entre duas camadas
        desenhadas separadas). Antes a decisão era pela SOMA de todas as frestas do imóvel, e centenas de frestas finas
        ficavam "sem classificação"."""
        a = topo.area_plana(parte)
        if a < FRESTA_AREA_M2 or _largura_m(parte) < self.largura_fresta:
            return True
        return _diametro_interno(parte) < LARGURA_FRESTA_M

    def _frestas(self, quadro, pai, nome_pai, ordem, extras, sem_lasca, pai_arq=None, definicao=None):
        if definicao:
            return self._frestas_suprimida(quadro, pai, nome_pai, ordem, sem_lasca, pai_arq, definicao)
        ocupado = topo.uniao([self.camadas[a].uniao(self.params) for a in ordem], self.params)
        try:
            vazio = topo.diferenca(pai, ocupado, self.params) if ocupado is not None else pai
        except Exception:
            return
        somadas, total_f, sem_class, total_s, geo_s = {}, 0.0, 0, 0.0, []
        pendentes = {}
        area_somada_por = {}
        for parte in topo.partes_simples(vazio):
            a = topo.area_plana(parte)
            if a <= AREA_RUIDO_M2 or _largura_m(parte) < LARGURA_RUIDO_M:
                continue  # v0.7.0: buraco de ruído numérico (menos de 0,1 mm de largura) não é fresta
            if self._eh_fresta(parte):
                viz = self._vizinho(parte, ordem, extras, sem_lasca)
                if viz is not None:
                    c, fid = viz
                    # v0.3.0 (otimização): junta todas as frestas de uma feição de uma vez só
                    pendentes.setdefault((c.arquivo, fid), []).append(parte)
                    somadas[c.arquivo] = somadas.get(c.arquivo, 0) + 1
                    area_somada_por[c.arquivo] = area_somada_por.get(c.arquivo, 0.0) + a
                    total_f += a
                    continue
            sem_class += 1; total_s += a; geo_s.append(parte)
        # v0.5.0: fresta sem vizinha que possa recebê-la, dentro da Área Suprimida: vai pela definição
        # (dentro da RL -> RL Suprimida; fora -> Supressão em Área Passível). Antes saía da Área Suprimida e, na passada
        # seguinte, voltava para ela pelo quadro do imóvel (vai-e-volta sem fim).
        if definicao and geo_s:
            finas = [p for p in geo_s if self._eh_fresta(p)]
            if finas:
                restam = self._classificar_por_definicao(quadro, finas, definicao, pendentes)
                geo_s = [p for p in geo_s if p not in finas] + restam
                sem_class = len(geo_s); total_s = sum(topo.area_plana(p) for p in geo_s)
        # v0.4.0: área sem classificação é decisão técnica: somar à classe vizinha ou deixar para desenhar depois
        if sem_class and total_s >= 1.0:
            # v0.5.0: a sugestão olha o TAMANHO de cada parte (círculo que cabe dentro), não a soma: buraco onde cabe
            # um círculo de 10 m é área de verdade sem desenho (deixar); menor que isso é sobra de traçado (vizinha).
            maior_d = max((_diametro_interno(p) for p in geo_s), default=0.0)
            sugestao = "vizinha" if maior_d < LARGURA_BURACO_M else "deixar"
            opcoes = [("vizinha", "Somar cada parte à classe vizinha"),
                      ("deixar", "Deixar sem classificação (desenhar depois)")]
            if definicao and any(a in self.camadas for a in definicao if a):
                opcoes.insert(0, ("definicao", "Classificar pela definição (dentro da RL → RL Suprimida; fora → "
                                               "Supressão em Área Passível)"))
                sugestao = "definicao"
            mapa_cob = COBERTURA_PARA.get(quadro)
            if mapa_cob:
                cobertas = self._cobertura_conhecida(topo.juntar(geo_s), mapa_cob)
                if cobertas > 0:
                    opcoes.insert(0, ("cobertura", "Classificar pelo uso do solo embaixo (vegetação → APP Preservada, "
                                                   "consolidada → APP Consolidada, suprimida → APP Suprimida; água sai "
                                                   "da APP Total)"))
                    if cobertas >= 0.9 * total_s:
                        sugestao = "cobertura"
            escolha = self._decidir(
                f"SEMCLASSE|{quadro}", quadro,
                f"{_texto_area(total_s)} de {nome_pai} sem classificação em {sem_class} parte(s)",
                total_s, topo.juntar(geo_s), opcoes, sugestao)
            if escolha == "cobertura" and mapa_cob:
                geo_s = self._classificar_por_cobertura(quadro, geo_s, mapa_cob, pendentes)
                sem_class = len(geo_s); total_s = sum(topo.area_plana(p) for p in geo_s)
            if escolha == "definicao" and definicao:
                geo_s = self._classificar_por_definicao(quadro, geo_s, definicao, pendentes, decisao=True)
                sem_class = len(geo_s); total_s = sum(topo.area_plana(p) for p in geo_s)
            if escolha == "vizinha":
                restam, n_somadas, area_somada = [], 0, 0.0
                for parte in geo_s:
                    viz = self._vizinho(parte, ordem, extras, sem_lasca)
                    if viz is None:
                        restam.append(parte); continue
                    c, fid = viz
                    pendentes.setdefault((c.arquivo, fid), []).append(parte)
                    n_somadas += 1; area_somada += topo.area_plana(parte)
                if n_somadas:
                    self._problema("T4", "", f"{quadro}: {n_somadas} parte(s) sem classificação somada(s) à classe "
                                   f"vizinha (decisão técnica)", "escolha", area_m2=area_somada, qtd=n_somadas,
                                   geom=topo.juntar([p for p in geo_s if p not in restam]))
                geo_s = restam; sem_class = len(restam); total_s = sum(topo.area_plana(p) for p in restam)
        for (arq, fid), partes in pendentes.items():
            c = self.camadas[arq]
            g = c.geoms.get(fid)
            try:
                ng = topo.uniao([g] + partes, self.params)
            except Exception:
                ng = None
            if ng is not None:
                c.definir(fid, ng)
        for arq, n in somadas.items():
            self._problema("T3", arq, f"{quadro}: {n} fresta(s) entre classes somada(s) a {self.nome(arq)}", qtd=n,
                           area_m2=area_somada_por.get(arq))
        if sem_class and total_s >= 1.0:
            self._problema("T4", "", f"{quadro}: {_texto_area(total_s)} de {nome_pai} sem classificação em "
                           f"{sem_class} parte(s): desenhe a classe certa (não dá para adivinhar)", "info",
                           area_m2=total_s, qtd=sem_class, geom=topo.juntar(geo_s))

    def _frestas_suprimida(self, quadro, pai, nome_pai, ordem, sem_lasca, pai_arq, definicao):
        """v0.5.0: o que sobra da Área Suprimida do período fora de APP Suprimida + RL Suprimida + Passível é
        classificado pela DEFINIÇÃO do quadro (não pela vizinha, que podia jogar Passível dentro da RL - regra P3):
          * dentro da Reserva Legal                 -> RL Suprimida
          * fora da RL e fora da APP Total          -> Supressão em Área Passível
          * fora da RL e dentro da APP Total        -> é APP Suprimida que não está desenhada; como as camadas de APP não
            são alteradas, a fresta fina sai da Área Suprimida (e não volta para ela no quadro do imóvel); parte larga
            fica como aviso (desenhe a APP Suprimida ali).
        Se a camada de destino não existe no projeto, a fresta fina vai para a vizinha (como o cálculo faz)."""
        rl_arq, pas_arq = definicao
        ocupado = topo.uniao([self.camadas[a].uniao(self.params) for a in ordem], self.params)
        try:
            vazio = topo.diferenca(pai, ocupado, self.params) if ocupado is not None else pai
        except Exception:
            return
        partes = [p for p in topo.partes_simples(vazio)
                  if topo.area_plana(p) > AREA_RUIDO_M2 and _largura_m(p) >= LARGURA_RUIDO_M]  # v0.7.0: sem ruído numérico
        if not partes:
            return
        rl = self._uniao_classes(["RESERVA_LEGAL"]) if "RESERVA_LEGAL" in self.camadas else None
        app = self._uniao_classes(["APP_TOTAL"]) if "APP_TOTAL" in self.camadas else None
        tem_rl = rl_arq in self.camadas and self.camadas[rl_arq].tipo == "P" and not self._intocavel(rl_arq)
        tem_pas = pas_arq in self.camadas and self.camadas[pas_arq].tipo == "P" and not self._intocavel(pas_arq)

        def cortar(g, regiao):
            if topo.vazia(g) or topo.vazia(regiao):
                return None, g
            try:
                dentro = topo.intersecao(g, regiao, self.params)
                fora = topo.diferenca(g, regiao, self.params)
            except Exception:
                return None, g
            return dentro, fora

        destino = {}          # arq -> [pecas]
        sair_da_sup, sem_classe, vizinha = [], [], []
        _cache_vazio = []

        def vazio_im():  # v0.7.0: área sem desenho do imóvel, calculada uma vez só e só se precisar
            if not _cache_vazio:
                _cache_vazio.append(self._vazio_do_imovel())
            return _cache_vazio[0]
        largas = []
        for parte in partes:
            fina = self._eh_fresta(parte)
            if not fina:
                largas.append(parte)
                continue
            na_rl, resto = cortar(parte, rl)
            na_app, resto = cortar(resto, app)
            # v0.7.0: sem a camada de destino, a peça vai para a vizinha - mas NUNCA para a classe que a definição
            # proíbe ali (fora da RL não é RL Suprimida; dentro da RL não é Passível). Antes, sem a camada de Passível,
            # o fio fora da RL ia para a RL Suprimida, o quadro da Reserva Legal tirava de volta na passada seguinte e a
            # correção nunca terminava igual (caso real de cliente, 3 m²).
            for g, arq, tem, proibida in ((na_rl, rl_arq, tem_rl, pas_arq), (resto, pas_arq, tem_pas, rl_arq)):
                for p in topo.partes_simples(g) if not topo.vazia(g) else []:
                    if topo.area_plana(p) <= AREA_RUIDO_M2:
                        continue
                    if tem:
                        destino.setdefault(arq, []).append(p)
                    else:
                        vizinha.append((p, proibida))
            for p in topo.partes_simples(na_app) if not topo.vazia(na_app) else []:
                if topo.area_plana(p) > AREA_RUIDO_M2:
                    # v0.7.0: só sai da Área Suprimida se OUTRA classe do imóvel pode ficar com ela; cercada pela própria
                    # Suprimida, o buraco voltava para ela no cálculo e o quadro ficava diferente do desenho (caso real:
                    # imóvel de cliente, 2,7 m²). Fica na Suprimida, sem classe no quadro da Área antropizada.
                    (sair_da_sup if (self._outra_classe_recebe(pai_arq, p) and
                                     not self._encosta_no_vazio(p, vazio_im())) else sem_classe).append(p)
        # partes largas: decisão técnica (sugestão: pela definição)
        if largas:
            total = sum(topo.area_plana(p) for p in largas)
            opcoes = [("definicao", "Classificar pela definição (dentro da RL → RL Suprimida; fora da RL e da APP → "
                                    "Supressão em Área Passível; dentro da APP, sobra estreita sai da Área Suprimida e "
                                    "o resto fica para desenhar a APP Suprimida)"),
                      ("deixar", "Deixar sem classificação (desenhar depois)")]
            escolha = self._decidir(f"SEMCLASSE|{quadro}", quadro,
                                    f"{_texto_area(total)} de {nome_pai} sem classificação em {len(largas)} parte(s)",
                                    total, topo.juntar(largas), opcoes, "definicao")
            if escolha == "definicao":
                for parte in largas:
                    na_rl, resto = cortar(parte, rl)
                    na_app, resto = cortar(resto, app)
                    for g, arq, tem, proibida in ((na_rl, rl_arq, tem_rl, pas_arq), (resto, pas_arq, tem_pas, rl_arq)):
                        for p in topo.partes_simples(g) if not topo.vazia(g) else []:
                            if topo.area_plana(p) <= AREA_RUIDO_M2:
                                continue
                            if tem:
                                destino.setdefault(arq, []).append(p)
                            elif self._eh_fresta(p):
                                vizinha.append((p, proibida))
                            else:
                                sem_classe.append(p)
                    for p in topo.partes_simples(na_app) if not topo.vazia(na_app) else []:
                        if topo.area_plana(p) > AREA_RUIDO_M2:
                            # dentro da APP sem APP Suprimida desenhada: a APP é a referência (não é alterada). Sobra de
                            # traçado da Área Suprimida (onde não cabe um círculo de 10 m) sai dela; maior que isso é
                            # APP Suprimida faltando - fica como aviso para desenhar.
                            # v0.7.0: e só sai se outra classe do imóvel pode ficar com ela (ver acima).
                            (sair_da_sup if (_diametro_interno(p) < LARGURA_BURACO_M and
                                             self._outra_classe_recebe(pai_arq, p) and
                                             not self._encosta_no_vazio(p, vazio_im())) else sem_classe).append(p)
            else:
                sem_classe.extend(largas)
        pendentes = {}
        for arq, pecas in destino.items():
            c = self.camadas[arq]
            area = 0.0
            for peca in pecas:
                fid = self._feicao_destino(c, peca)
                if fid is None:
                    sem_classe.append(peca); continue
                pendentes.setdefault((arq, fid), []).append(peca); area += topo.area_plana(peca)
            if area > 0:
                self._problema("T3", arq, f"{quadro}: {len(pecas)} parte(s) sem classe somada(s) a {self.nome(arq)} "
                               f"pela definição", "auto", area_m2=area, qtd=len(pecas))
        for peca, proibida in vizinha:
            viz = self._vizinho(peca, [a for a in ordem if a != proibida], {}, sem_lasca)
            if viz is None:
                sem_classe.append(peca); continue
            c, fid = viz
            pendentes.setdefault((c.arquivo, fid), []).append(peca)
        for (arq, fid), pecas in pendentes.items():
            c = self.camadas[arq]
            try:
                ng = topo.uniao([c.geoms.get(fid)] + pecas, self.params)
            except Exception:
                ng = None
            if ng is not None:
                c.definir(fid, ng)
        if sair_da_sup and pai_arq in self.camadas and not self._intocavel(pai_arq):
            g = topo.juntar(sair_da_sup)
            tirada, _s = self.camadas[pai_arq].tirar(g, self.params)
            self._proibir(pai_arq, g)
            if tirada > AREA_RUIDO_M2:
                self._problema("T4", pai_arq, f"{quadro}: {len(sair_da_sup)} fresta(s) dentro da APP Total sem APP "
                               f"Suprimida desenhada tirada(s) de {self.nome(pai_arq)} (as camadas de APP não são "
                               f"alteradas)", "auto", area_m2=tirada, qtd=len(sair_da_sup), geom=g)
        elif sair_da_sup:
            sem_classe.extend(sair_da_sup)
        total_s = sum(topo.area_plana(p) for p in sem_classe)
        if total_s >= 1.0:
            self._problema("T4", "", f"{quadro}: {_texto_area(total_s)} de {nome_pai} sem classificação em "
                           f"{len(sem_classe)} parte(s): desenhe a classe certa (dentro da APP: falta a APP Suprimida)",
                           "info", area_m2=total_s, qtd=len(sem_classe), geom=topo.juntar(sem_classe))

    def _classes_do_imovel(self):
        cfg = self.config
        return {str(x).upper() for x in cfg.get("fechamento", FECHAMENTO_PADRAO)} | set(AGUA_FECHAMENTO) | \
            {"AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019"} | set(self._personalizadas().get("IMOVEL", []))

    def _vazio_do_imovel(self):
        """v0.7.0: parte do imóvel que nenhuma classe do quadro do imóvel cobre agora (área sem desenho)."""
        imovel = getattr(self, "_imovel", None)
        if topo.vazia(imovel):
            ic = self.camadas.get("AREA_DO_IMOVEL")
            imovel = ic.uniao(self.params) if (ic is not None and ic.tipo == "P") else None
        if topo.vazia(imovel):
            return None
        gs = [self.camadas[a].uniao(self.params) for a in self._classes_do_imovel()
              if a in self.camadas and self.camadas[a].tipo == "P"]
        try:
            oc = topo.uniao([g for g in gs if not topo.vazia(g)], self.params)
            return topo.diferenca(imovel, oc, self.params) if oc is not None else imovel
        except Exception:
            return None

    @staticmethod
    def _encosta_no_vazio(parte, vazio):
        """v0.7.0: True se a peça encosta (divisa de verdade) numa área sem desenho do imóvel: tirar a peça só aumentaria
        essa área sem classificação - a correção nunca transforma área classificada em área sem classificação."""
        if topo.vazia(vazio):
            return False
        try:
            faixa = parte.buffer(0.02, 2)
            if not faixa.boundingBox().intersects(vazio.boundingBox()):
                return False
            return topo.area_plana(faixa.intersection(vazio)) >= DIVISA_MIN_M2
        except Exception:
            return False

    def _outra_classe_recebe(self, arq, parte):
        """v0.7.0: True se alguma OUTRA classe do mesmo quadro (sem ser `arq`) tem divisa de verdade com a peça e pode
        recebê-la. Usado antes de tirar uma peça de `arq`: se ninguém recebe, o buraco voltaria para `arq` no cálculo."""
        irmas = self._classes_irmas(arq)
        if irmas is None:
            return True
        try:
            faixa = parte.buffer(0.02, 2)
        except Exception:
            return True
        caixa = faixa.boundingBox()
        for outra in irmas:
            c = self.camadas.get(outra)
            if c is None or c.tipo != "P" or self._intocavel(outra) or not self._pode_receber(outra, parte):
                continue
            for _fid, g in c.perto(caixa):
                try:
                    if topo.area_plana(faixa.intersection(g)) >= DIVISA_MIN_M2:
                        return True
                except Exception:
                    continue
        return False

    def _classes_irmas(self, arq):
        """Classes que dividem o mesmo "todo" com `arq` (para saber quem pode receber uma lasca dela)."""
        arq = str(arq).upper()
        cfg = self.config
        quadro_a = {str(x).upper() for x in cfg.get("fechamento", FECHAMENTO_PADRAO)} | set(AGUA_FECHAMENTO) | \
            {"AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019"} | set(self._personalizadas().get("IMOVEL", []))
        if arq in quadro_a:
            return [a for a in quadro_a if a != arq]
        for _per, _sup, _app, rl_direto, pas_arq, *_r in PERIODOS_ANTROPIZADA:
            rl_arq = rl_direto if rl_direto in self.camadas else "RESERVA_SUPRIMIDA"
            if arq in (rl_arq, pas_arq):
                return [a for a in (rl_arq, pas_arq) if a != arq]
        return None

    def _tem_vizinha_real(self, arq, parte):
        """True se, tirando a lasca, a fresta que fica iria para OUTRA classe (divisa real e maior que a divisa com o
        resto da própria camada). Senão a lasca voltaria para a mesma camada: não vale tirar."""
        irmas = self._classes_irmas(arq)
        if irmas is None:
            return True  # fora dos quadros: lasca sai como antes
        try:
            faixa = parte.buffer(0.02, 2)
        except Exception:
            return True
        caixa = faixa.boundingBox()
        a_parte = topo.area_plana(parte)
        maior_outra = 0.0
        for outra in irmas:
            c = self.camadas.get(outra)
            if c is None or c.tipo != "P" or self._intocavel(outra) or not self._pode_receber(outra, parte):
                continue
            for _fid, g in c.perto(caixa):
                try:
                    maior_outra = max(maior_outra, topo.area_plana(faixa.intersection(g)))
                except Exception:
                    continue
        if maior_outra < DIVISA_MIN_M2:
            return False
        propria = self.camadas.get(arq)
        maior_propria = 0.0
        if propria is not None:
            for _fid, g in propria.perto(caixa):
                try:
                    comum = topo.area_plana(faixa.intersection(g))
                    if g.intersects(parte) and topo.area_plana(g.intersection(parte)) > 0.5 * a_parte:
                        comum -= a_parte  # a feição que contém a lasca: só conta a divisa com o resto dela
                    maior_propria = max(maior_propria, comum)
                except Exception:
                    continue
        return maior_outra > maior_propria + 1e-9

    def _regiao_app_sem_suprimida(self, sup_arq):
        """APP Total fora da APP Suprimida do período: por definição a Área Suprimida do período não entra aí (as
        camadas de APP são a referência e não mudam). Calculado uma vez."""
        cache = getattr(self, "_cache_app_sem_sup", None)
        if cache is None:
            cache = self._cache_app_sem_sup = {}
        if sup_arq in cache:
            return cache[sup_arq]
        reg = None
        app_arq = next((x[2] for x in PERIODOS_ANTROPIZADA if x[1] == sup_arq), None)
        if app_arq and "APP_TOTAL" in self.camadas and app_arq in self.camadas:
            try:
                tot = self._uniao_classes(["APP_TOTAL"])
                ant = self._uniao_classes([app_arq])
                reg = topo.diferenca(tot, ant, self.params) if not topo.vazia(ant) else tot
            except Exception:
                reg = None
        cache[sup_arq] = reg
        return reg

    def _pode_receber(self, arq, parte):
        if self._proibido(arq, parte):
            return False
        if arq in ("AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019"):
            reg = self._regiao_app_sem_suprimida(arq)
            if not topo.vazia(reg):
                try:
                    a = topo.area_plana(parte)
                    if a > 0 and topo.area_plana(topo.intersecao(parte, reg, self.params)) >= 0.5 * a:
                        return False
                except Exception:
                    pass
        return True

    def _proibir(self, arq, g):
        """Pedaço que não pode voltar para `arq` pelas frestas do quadro do imóvel (evita vai-e-volta)."""
        if topo.vazia(g):
            return
        self._proibidos = getattr(self, "_proibidos", {})
        self._proibidos.setdefault(arq, []).append(QgsGeometry(g))

    def _proibido(self, arq, parte):
        gs = getattr(self, "_proibidos", {}).get(arq)
        if not gs:
            return False
        try:
            a = topo.area_plana(parte)
            dentro = sum(topo.area_plana(topo.intersecao(parte, g, self.params)) for g in gs
                         if g.boundingBox().intersects(parte.boundingBox()))
            return a > 0 and dentro >= 0.5 * a
        except Exception:
            return False

    def _classificar_por_definicao(self, quadro, partes, definicao, pendentes, decisao=False):
        """v0.5.0: parte da Área Suprimida sem classe recebe a classe pela definição do quadro da Área antropizada:
        dentro da Reserva Legal -> RL Suprimida; fora da RL e fora da APP -> Supressão em Área Passível. O que está
        dentro da APP Total fica (a APP não é alterada: falta desenhar a APP Suprimida ali). Devolve o que ficou."""
        rl_arq, pas_arq = definicao
        rl = self._uniao_classes(["RESERVA_LEGAL"]) if "RESERVA_LEGAL" in self.camadas else None
        app = self._uniao_classes(["APP_TOTAL"]) if "APP_TOTAL" in self.camadas else None
        restam, somadas, area_som = [], {}, 0.0
        for parte in partes:
            resto = parte
            destinos = []
            if not topo.vazia(app):
                try:
                    na_app = topo.intersecao(resto, app, self.params)
                    if not topo.vazia(na_app) and topo.area_plana(na_app) > AREA_RUIDO_M2:
                        restam.extend(p for p in topo.partes_simples(na_app) if topo.area_plana(p) > AREA_RUIDO_M2)
                        resto = topo.diferenca(resto, na_app, self.params)
                except Exception:
                    pass
            if topo.vazia(resto):
                continue
            if not topo.vazia(rl) and rl_arq in self.camadas:
                try:
                    na_rl = topo.intersecao(resto, rl, self.params)
                    if not topo.vazia(na_rl) and topo.area_plana(na_rl) > AREA_RUIDO_M2:
                        destinos.append((rl_arq, na_rl))
                        resto = topo.diferenca(resto, na_rl, self.params)
                except Exception:
                    pass
            if not topo.vazia(resto):
                if pas_arq in self.camadas:
                    destinos.append((pas_arq, resto))
                else:
                    restam.extend(p for p in topo.partes_simples(resto) if topo.area_plana(p) > AREA_RUIDO_M2)
            for arq, g in destinos:
                c = self.camadas[arq]
                if c.tipo != "P" or self._intocavel(arq):
                    restam.extend(topo.partes_simples(g)); continue
                for peca in topo.partes_simples(g):
                    if topo.area_plana(peca) <= AREA_RUIDO_M2:
                        continue
                    fid = self._feicao_destino(c, peca)
                    if fid is None:
                        restam.append(peca); continue
                    pendentes.setdefault((arq, fid), []).append(peca)
                    somadas[arq] = somadas.get(arq, 0.0) + topo.area_plana(peca)
                    area_som += topo.area_plana(peca)
        for arq, m2 in somadas.items():
            self._problema("T4", arq, f"{quadro}: parte sem classe somada a {self.nome(arq)} pela definição "
                           f"(dentro da RL → RL Suprimida; fora → Passível)", "escolha" if decisao else "auto", area_m2=m2)
        return restam

    def _uniao_classes(self, arqs):
        gs = [self.camadas[a].uniao(self.params) for a in arqs if a in self.camadas and self.camadas[a].tipo == "P"]
        gs = [g for g in gs if not topo.vazia(g)]
        return topo.uniao(gs, self.params) if gs else None

    def _cobertura_conhecida(self, geom, mapa_cob):
        """m² de `geom` que caem em alguma classe do uso do solo (vegetação, consolidada, suprimidas, água)."""
        cob = self._uniao_classes(list(mapa_cob) + list(AGUA_FECHAMENTO))
        if cob is None or topo.vazia(geom):
            return 0.0
        try:
            return topo.area_plana(topo.intersecao(geom, cob, self.params))
        except Exception:
            return 0.0

    def _feicao_destino(self, c, parte):
        """Feição de `c` que recebe `parte`: a de maior divisa comum; sem divisa, a maior feição."""
        try:
            faixa = parte.buffer(0.02, 2)
        except Exception:
            faixa = parte
        melhor, maior = None, 0.0
        for fid, g in c.perto(faixa.boundingBox()):
            try:
                comum = topo.area_plana(faixa.intersection(g))
            except Exception:
                continue
            if comum > maior:
                melhor, maior = fid, comum
        if melhor is None:
            vivas = c.vivas()
            if vivas:
                melhor = max(vivas, key=lambda x: topo.area_plana(x[1]))[0]
        return melhor

    def _classificar_por_cobertura(self, quadro, partes, mapa_cob, pendentes):
        """APP sem classe recebe a classe do uso do solo que está embaixo (regra fixa, não é adivinhação):
        vegetação → APP Preservada, consolidada → APP Consolidada, suprimida antes/depois → APP Suprimida
        antes/depois. A água (rio, barragem...) não é APP: sai da APP Total. Devolve o que ficou sem classe."""
        restam, somadas, area_som, agua_m2, geo_ok = [], {}, 0.0, 0.0, []
        agua = self._uniao_classes(AGUA_FECHAMENTO)
        coberturas = [(cob, self._uniao_classes([cob])) for cob in mapa_cob]
        tirar_agua = []
        for parte in partes:
            resto = parte
            for cob, ucob in coberturas:
                if topo.vazia(resto) or ucob is None:
                    break
                destino = mapa_cob[cob]
                if destino not in self.camadas or self.camadas[destino].tipo != "P":
                    continue
                try:
                    peca = topo.intersecao(resto, ucob, self.params)
                except Exception:
                    continue
                if topo.vazia(peca) or topo.area_plana(peca) <= AREA_RUIDO_M2:
                    continue
                c = self.camadas[destino]
                fid = self._feicao_destino(c, peca)
                if fid is None:
                    continue
                pendentes.setdefault((destino, fid), []).append(peca)
                somadas[destino] = somadas.get(destino, 0.0) + topo.area_plana(peca)
                area_som += topo.area_plana(peca); geo_ok.append(peca)
                resto = topo.diferenca(resto, peca, self.params)
            if agua is not None and not topo.vazia(resto):
                try:
                    na_agua = topo.intersecao(resto, agua, self.params)
                except Exception:
                    na_agua = None
                if not topo.vazia(na_agua) and topo.area_plana(na_agua) > AREA_RUIDO_M2:
                    tirar_agua.append(na_agua); agua_m2 += topo.area_plana(na_agua); geo_ok.append(na_agua)
                    resto = topo.diferenca(resto, na_agua, self.params)
            if not topo.vazia(resto):
                for r in topo.partes_simples(resto):
                    if topo.area_plana(r) > AREA_RUIDO_M2:
                        restam.append(r)
        if tirar_agua and "APP_TOTAL" in self.camadas:
            self.camadas["APP_TOTAL"].tirar(topo.juntar(tirar_agua), self.params)
            self._problema("T4", "APP_TOTAL", f"{quadro}: água (rio, barragem...) dentro da APP Total tirada da APP - "
                           f"a superfície da água não é APP", "escolha", area_m2=agua_m2, geom=topo.juntar(tirar_agua))
        for destino, m2 in somadas.items():
            self._problema("T4", destino, f"{quadro}: área sem classe somada a {self.nome(destino)} pelo uso do solo "
                           f"embaixo", "escolha", area_m2=m2)
        return restam

    def _vizinho(self, parte, ordem, extras, sem_lasca):
        """Feição (de qualquer classe do quadro) com a maior divisa comum com a fresta (faixa de 2 cm)."""
        try:
            faixa = parte.buffer(0.02, 2)
        except Exception:
            return None
        caixa = faixa.boundingBox()
        melhor, maior = None, 0.0
        for arq in ordem:
            if arq in sem_lasca:
                continue
            extra = extras.get(arq)
            if extra is not None and extra[1] is not None:
                try:
                    if topo.area_plana(parte.intersection(extra[1])) < 0.99 * topo.area_plana(parte):
                        continue
                except Exception:
                    continue
            if not self._pode_receber(arq, parte):
                continue
            c = self.camadas[arq]
            for fid, g in c.perto(caixa):
                try:
                    comum = topo.area_plana(faixa.intersection(g))
                except Exception:
                    continue
                if comum > maior + 1e-9:
                    melhor, maior = (c, fid), comum
        # v0.4.0: encostar só num ponto não é divisa - somar ali criaria uma lasca solta (e a próxima passada a
        # apagaria de novo, sem fim). Exige ao menos ~25 cm de divisa comum.
        # v0.5.0: se NENHUMA vizinha tem essa divisa, fica a que mais encosta (o cálculo faria o mesmo, e assim não
        # sobra fresta para ele); a lasca criada assim não é mais apagada nas passadas seguintes.
        if melhor is not None and maior < DIVISA_MIN_M2 and not getattr(self, "_aceitar_toque", True):
            return None
        return melhor if maior > 0.0 else None

    # ---------------------------------------------------------------- gravação
    def gravar(self):
        """Grava as correções nas camadas (com cópia de segurança). Devolve (gravadas, erros, backups)."""
        gravadas, erros, backups = [], [], []
        for arq, c in self.camadas.items():
            if not c.alterada():
                continue
            if not c.editavel:
                continue
            self._passo(f"Gravando {c.nome}...")
            try:
                b = _backup(c.layer)
                if b:
                    backups.append(b)
            except Exception as exc:
                erros.append(f"{c.nome}: não foi possível guardar a cópia de segurança ({exc}); a camada NÃO foi alterada.")
                continue
            ok, msg = _aplicar_na_camada(c)
            (gravadas.append(c.nome) if ok else erros.append(f"{c.nome}: {msg}"))
        return gravadas, erros, backups


def _backup(layer):
    prov = str(layer.providerType() or "").lower()
    if prov == "memory":
        return ""
    fonte = _arquivo_da_camada(layer)
    ext = os.path.splitext(fonte)[1].lower()
    if ext == ".shp":
        from .operacoes import backup_shapefile
        return backup_shapefile(layer)
    if ext == ".gpkg" and os.path.isfile(fonte):
        destino = os.path.join(os.path.dirname(fonte), "_backup", datetime.now().strftime("%Y-%m-%d_%H%M%S"))
        n = 2
        base = destino
        while os.path.exists(destino):
            destino = f"{base}_{n}"; n += 1
        os.makedirs(destino, exist_ok=True)
        shutil.copy2(fonte, os.path.join(destino, os.path.basename(fonte)))
        return destino
    raise RuntimeError("formato sem cópia de segurança")


def _para_camada(c, g):
    """Geometria de trabalho -> SRC e tipo da camada. Devolve lista de partes (1 se a camada aceita multi)."""
    g = QgsGeometry(g)
    if c.volta is not None:
        g.transform(c.volta)
        # v0.5.0: voltar para o SRC da camada (ex.: SIRGAS 2000 geográfico) pode deixar um anel encostando nele mesmo
        # por 1e-9 grau; o cálculo então acusava "geometria corrigida". Corrige aqui, no SRC da camada.
        try:
            if c.tipo == "P" and not g.isGeosValid():
                v = topo.so_poligonos(g)
                if v is not None and abs(topo.area_plana(v) - topo.area_plana(g)) <= 1e-6 * max(1.0, topo.area_plana(g)):
                    g = v
        except Exception:
            pass
    tipo = c.layer.wkbType()
    try:
        if QgsWkbTypes.hasZ(tipo) and not g.constGet().is3D():
            g.get().addZValue(0.0)
        if QgsWkbTypes.hasM(tipo) and not g.constGet().isMeasure():
            g.get().addMValue(0.0)
    except Exception:
        pass
    if QgsWkbTypes.isMultiType(tipo):
        g.convertToMultiType()
        return [g]
    if g.isMultipart():
        partes = [QgsGeometry(p) for p in g.asGeometryCollection() if not topo.vazia(p)]
        for p in partes:
            p.convertToSingleType()
        return partes or [g]
    return [g]


def _aplicar_na_camada(c):
    lay = c.layer
    estava_em_edicao = lay.isEditable()
    if estava_em_edicao:
        if lay.isModified():
            return False, "a camada tem edição não salva: salve ou descarte a edição dela e corrija de novo"
        lay.rollBack()  # v0.7.0: edição aberta sem mudança - fecha, grava a correção e abre de novo no fim
    if not lay.startEditing():
        return False, "não foi possível abrir a edição da camada"
    try:
        apagar = set(c.apagar) | set(getattr(c, "apagar_acum", set()))
        for fid in sorted(apagar):
            lay.deleteFeature(fid)
        for fid in sorted((set(c.mudou) | set(getattr(c, "mudou_acum", set()))) - apagar):
            g = c.geoms.get(fid)
            if topo.vazia(g):
                lay.deleteFeature(fid)
                continue
            partes = _para_camada(c, g)
            lay.changeGeometry(fid, partes[0])
            if len(partes) > 1:
                orig = lay.getFeature(fid)
                for p in partes[1:]:
                    nova = QgsFeature(lay.fields())
                    nova.setAttributes(orig.attributes())
                    # chave única (ex.: fid do GeoPackage) é gerada pelo provedor
                    try:
                        for i in lay.dataProvider().pkAttributeIndexes():
                            nova.setAttribute(i, None)
                    except Exception:
                        pass
                    nova.setGeometry(p)
                    lay.addFeature(nova)
        if not lay.commitChanges():
            erros = "; ".join(lay.commitErrors()[:3])
            lay.rollBack()
            return False, f"o QGIS recusou a gravação ({erros})"
    except Exception as exc:
        try:
            lay.rollBack()
        except Exception:
            pass
        return False, str(exc)
    if estava_em_edicao:
        try:
            lay.startEditing()
        except Exception:
            pass
    lay.triggerRepaint()
    return True, ""


# ---------------------------------------------------------------- conferência depois do cálculo
def conferir_resultado(resultado, livres=None, indice=None):
    """Depois de corrigir e calcular: cada camada de polígono deve ter área do desenho (dentro do imóvel) igual à
    área do quadro. Devolve lista de textos com o que ainda não bate (vazia = tudo bate)."""
    livres = set(livres or LIVRES_DO_IMOVEL)
    saida = []
    for reg in (resultado or {}).get("todas", []):
        if reg.get("tipo") != "Polígono" or reg.get("area_quadro") is None:
            continue
        arq = str(reg.get("reconhecida") or "")
        if "duplicada" in str(reg.get("reconhecida_texto") or ""):
            continue
        if arq.upper() in APP_INTOCAVEIS:
            continue  # v0.4.0: camadas que a correção não altera (o cálculo usa só a parte dentro do imóvel)
        # v0.5.0: desconta a diferença esperada pela regra do quadro (RL Suprimida dentro da APP Suprimida conta na APP)
        ajuste = abs(float(reg.get("ajuste_topologico") or 0.0) - float(reg.get("ajuste_esperado") or 0.0))
        if arq in AGUA_FECHAMENTO:
            ajuste = 0.0  # v0.4.0: barragem/rio sobre área suprimida conta como suprimida, de propósito
        fora = float(reg.get("fora_imovel") or 0.0) if (arq not in livres and not pode_sair_do_imovel(arq, indice)) else 0.0
        if ajuste >= 0.0001 or fora >= 0.0001:
            partes = []
            if fora >= 0.0001:
                partes.append(f"{fora:.4f} ha fora do imóvel")
            if ajuste >= 0.0001:
                partes.append(f"{ajuste:.4f} ha ajustados no quadro")
            saida.append(f"{reg.get('nome')}: " + ", ".join(partes))
    return saida
