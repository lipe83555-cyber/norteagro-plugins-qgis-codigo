# -*- coding: utf-8 -*-
"""Resolução topológica em memória para o Quadro de Áreas (v3.9.0).

Nada neste módulo altera camadas ou arquivos: as funções recebem QgsGeometry
e devolvem cópias. Todas as operações de sobreposição usam snap-rounding de
1 mm (QgsGeometryParameters.setGridSize), o que elimina microlascas e falhas
"TopologyException" do GEOS em bordas quase coincidentes.
"""
from . import compat
import math

from qgis.core import Qgis, QgsGeometry, QgsWkbTypes

TOL_HA = 0.0001
LASCA_AREA_M2 = 1.0
LARGURA_LASCA_M = 0.5
DENSIFICACAO_M = 10.0
_AREA_MINIMA = 1e-6


# ---------------------------------------------------------------- utilitários

def parametros_geometria(crs=None):
    """Snap-rounding de 1 mm (QGIS 3.28+). Em versões antigas devolve None: as operações rodam sem grade."""
    geografico = False
    try:
        geografico = bool(crs is not None and crs.isValid() and crs.isGeographic())
    except Exception:
        geografico = False
    return compat.parametros_grade(1e-8 if geografico else 0.001)


def vazia(geom):
    try:
        return geom is None or geom.isNull() or geom.isEmpty()
    except Exception:
        return True


def so_poligonos(geom):
    """Torna válida (método Structure) e mantém só as partes poligonais."""
    if vazia(geom):
        return None
    g = QgsGeometry(geom)
    try:
        if not g.isGeosValid():
            v = compat.tornar_valida(g)
            if not vazia(v):
                g = v
    except Exception:
        pass
    try:
        tipo = QgsWkbTypes.geometryType(g.wkbType())
        flat = QgsWkbTypes.flatType(g.wkbType())
        if tipo == compat.GEOM_POLIGONO and flat != compat.WKB_COLECAO:
            return None if vazia(g) else g
        partes = []
        for parte in g.asGeometryCollection():
            if vazia(parte):
                continue
            if QgsWkbTypes.geometryType(parte.wkbType()) == compat.GEOM_POLIGONO:
                partes.append(QgsGeometry(parte))
    except Exception:
        return None
    if not partes:
        return None
    if len(partes) == 1:
        return partes[0]
    return QgsGeometry.collectGeometry(partes)


def partes_simples(geom):
    g = so_poligonos(geom)
    if g is None:
        return []
    try:
        if g.isMultipart():
            return [QgsGeometry(x) for x in g.asGeometryCollection() if not vazia(x)]
    except Exception:
        pass
    return [g]


def juntar(partes):
    partes = [QgsGeometry(x) for x in partes if not vazia(x)]
    if not partes:
        return None
    if len(partes) == 1:
        return partes[0]
    return QgsGeometry.collectGeometry(partes)


def area_plana(geom):
    try:
        return 0.0 if vazia(geom) else float(geom.area())
    except Exception:
        return 0.0


def ponto_interno(geom):
    try:
        pt = geom.pointOnSurface().asPoint()
        return float(pt.x()), float(pt.y())
    except Exception:
        try:
            pt = geom.centroid().asPoint()
            return float(pt.x()), float(pt.y())
        except Exception:
            return 0.0, 0.0


# ---------------------------------------------------------------- medição

def area_ha(d, geom, densificar=False):
    """Área em ha, parte por parte; densifica só polígonos simples (nunca coleções)."""
    total = 0.0
    for parte in partes_simples(geom):
        medir = parte
        if densificar:
            try:
                dd = parte.densifyByDistance(DENSIFICACAO_M)
                if not vazia(dd):
                    medir = dd
            except Exception:
                medir = parte
        try:
            total += float(d.convertAreaMeasurement(d.measureArea(medir), compat.UNID_HECTARES))
        except Exception:
            pass
    return total


# ---------------------------------------------------------------- operações

def _so_partes_poligonais(g):
    """Igual a so_poligonos, sem refazer a checagem de validade (v3.9.12): o resultado de uma
    operação do GEOS já sai válido; se algo vier inválido, a operação seguinte cai na tentativa
    que corrige as entradas (ver _executar)."""
    if vazia(g):
        return None
    try:
        tipo = QgsWkbTypes.geometryType(g.wkbType())
        flat = QgsWkbTypes.flatType(g.wkbType())
        if tipo == compat.GEOM_POLIGONO and flat != compat.WKB_COLECAO:
            return g
        partes = [QgsGeometry(p) for p in g.asGeometryCollection()
                  if not vazia(p) and QgsWkbTypes.geometryType(p.wkbType()) == compat.GEOM_POLIGONO]
    except Exception:
        return so_poligonos(g)
    if not partes:
        return None
    return partes[0] if len(partes) == 1 else QgsGeometry.collectGeometry(partes)


def _executar(nome, a, b, params):
    # v0.5.0: conta EXATA primeiro; a grade de 1 mm fica só de reserva (quando o GEOS falha). A grade arredondava cada
    # vértice e, numa borda reta comprida, mudava a área (até ~1 m² num lado de 2 km): o quadro não batia com o $area
    # da camada e a borda corrigida ficava fora do imóvel por frações de milímetro.
    tentativas = [(a, b, None)]
    if params is not None:
        tentativas.append((a, b, params))
    tentativas.append((so_poligonos(a), so_poligonos(b), None))
    if params is not None:
        tentativas.append((so_poligonos(a), so_poligonos(b), params))
    ultimo = ""
    for x, y, p in tentativas:
        if x is None or y is None:
            continue
        try:
            r = getattr(x, nome)(y, p) if p is not None else getattr(x, nome)(y)
        except Exception as exc:
            ultimo = str(exc)
            continue
        erro = ""
        try:
            erro = x.lastError()
        except Exception:
            erro = ""
        if r is None or (r.isNull() and erro):
            ultimo = erro or "resultado nulo"
            continue
        return _so_partes_poligonais(r)
    raise RuntimeError(f"Falha de geometria em {nome}: {ultimo}")


def intersecao(a, b, params=None):
    if vazia(a) or vazia(b):
        return None
    try:
        if not a.boundingBox().intersects(b.boundingBox()):
            return None
    except Exception:
        pass
    return _executar("intersection", a, b, params)


def diferenca(a, b, params=None):
    if vazia(a):
        return None
    if vazia(b):
        return so_poligonos(a)
    try:
        if not a.boundingBox().intersects(b.boundingBox()):
            return so_poligonos(a)
    except Exception:
        pass
    return _executar("difference", a, b, params)


def combinar(a, b, params=None):
    if vazia(a):
        return so_poligonos(b)
    if vazia(b):
        return so_poligonos(a)
    return _executar("combine", a, b, params)


def uniao(geoms, params=None):
    gs = [so_poligonos(g) for g in geoms]
    gs = [g for g in gs if g is not None]
    if not gs:
        return None
    if len(gs) == 1:
        return gs[0]
    for p in (None, params):  # v0.5.0: exata primeiro, grade só de reserva
        try:
            r = QgsGeometry.unaryUnion(gs, p) if p is not None else QgsGeometry.unaryUnion(gs)
            if not vazia(r):
                return so_poligonos(r)
        except Exception:
            pass
        if p is None and params is None:
            break
    atual = gs[0]
    for g in gs[1:]:
        atual = combinar(atual, g, params)
    return atual


# ---------------------------------------------------------------- partição

def _vizinho(lasca, resolvidos, params, pais_extras=None, sem_lasca=None, pendentes=None, permitidos=None):
    """Classe com maior fronteira comum com a lasca (faixa de 2 cm em volta).

    A lasca só vai para uma classe se estiver dentro do pai extra dela (ex.: APP
    Suprimida antes só recebe lasca que esteja dentro da Área Suprimida antes).
    v0.7.0 - permitidos: {chave: (dentro, fora)} - a classe só recebe a lasca que está (na maior parte) DENTRO de
    `dentro` e FORA de `fora` (ex.: Passível não recebe lasca dentro da RL ou da APP; RL Suprimida não recebe lasca
    fora da RL). É a mesma regra da correção (correcao._frestas_suprimida): uma régua só.
    """
    try:
        faixa = lasca.buffer(0.02, 2)
    except Exception:
        return None
    melhor, maior = None, 0.0
    pendentes = pendentes or {}
    caixa = faixa.boundingBox()
    for chave, geom in resolvidos.items():
        if vazia(geom) or (sem_lasca and chave in sem_lasca):
            continue
        try:
            extras_pend = [p for p in pendentes.get(chave, []) if caixa.intersects(p.boundingBox())]
            if not caixa.intersects(geom.boundingBox()) and not extras_pend:
                continue
            extra = (pais_extras or {}).get(chave)
            if extra is not None and extra[1] is not None:
                if area_plana(lasca.intersection(extra[1])) < 0.99 * area_plana(lasca):
                    continue
            perm = (permitidos or {}).get(chave)
            if perm is not None:
                dentro, fora_g = perm
                a_l = area_plana(lasca)
                if dentro is not None and area_plana(lasca.intersection(dentro)) < 0.5 * a_l:
                    continue
                if fora_g is not None and area_plana(lasca.intersection(fora_g)) > 0.5 * a_l:
                    continue
            comum = area_plana(faixa.intersection(geom)) if caixa.intersects(geom.boundingBox()) else 0.0
            for p in extras_pend:  # frestas já destinadas a esta classe (são disjuntas da classe)
                comum += area_plana(faixa.intersection(p))
        except Exception:
            continue
        if comum > maior + 1e-9:
            melhor, maior = chave, comum
    return melhor


def particionar(pai, filhos, params=None, largura_lasca=LARGURA_LASCA_M,
                area_lasca_m2=LASCA_AREA_M2, absorver=True, pais_extras=None, sem_lasca=None, permitidos=None):
    """Divide o pai entre os filhos pela ordem de prioridade.

    filhos: lista [(chave, geom|None)], o primeiro ganha a área sobreposta.
    pais_extras: {chave: (nome_do_pai, geom)} recorte adicional de um filho.
    Retorna dict com resolvidos, sobreposicoes [(ganhou, perdeu, geom)],
    fora [(chave, nome_pai, geom)], lascas [(chave, geom)] e vazio.
    """
    pai_g = so_poligonos(pai) if pai is not None else None
    pais_extras = pais_extras or {}
    resolvidos, sobreposicoes, fora, lascas = {}, [], [], []
    ocupado = None
    for chave, geom in filhos:
        g = so_poligonos(geom)
        if g is None:
            resolvidos[chave] = None
            continue
        if pai_g is not None:
            f = diferenca(g, pai_g, params)
            if area_plana(f) > _AREA_MINIMA:
                fora.append((chave, None, f))
            g = intersecao(g, pai_g, params)
        extra = pais_extras.get(chave)
        if g is not None and extra is not None and extra[1] is not None:
            f = diferenca(g, extra[1], params)
            if area_plana(f) > _AREA_MINIMA:
                fora.append((chave, extra[0], f))
            g = intersecao(g, extra[1], params)
        if g is not None and ocupado is not None:
            for outra, go in resolvidos.items():
                if vazia(go):
                    continue
                inter = intersecao(g, go, params)
                if area_plana(inter) > _AREA_MINIMA:
                    sobreposicoes.append((outra, chave, inter))
            g = diferenca(g, ocupado, params)
        resolvidos[chave] = g
        if g is not None:
            ocupado = combinar(ocupado, g, params)
    vazio = None
    if pai_g is not None:
        vazio = diferenca(pai_g, ocupado, params) if ocupado is not None else pai_g
        if absorver and vazio is not None:
            restantes = []; pendentes = {}
            for parte in partes_simples(vazio):
                a = area_plana(parte)
                try:
                    perimetro = float(parte.length())
                except Exception:
                    perimetro = 0.0
                largura = (2.0 * a / perimetro) if perimetro > 0 else 0.0
                if a < area_lasca_m2 or largura < largura_lasca:
                    viz = _vizinho(parte, resolvidos, params, pais_extras, sem_lasca, pendentes, permitidos)
                    if viz is not None:
                        # v3.9.12: antes cada fresta era unida na hora à classe inteira (lento com
                        # muitas frestas). Agora acumula e une uma vez só; a escolha do vizinho soma a
                        # divisa com as frestas pendentes, então o resultado é o mesmo.
                        pendentes.setdefault(viz, []).append(parte)
                        lascas.append((viz, parte))
                        continue
                restantes.append(parte)
            for viz, partes in pendentes.items():
                resolvidos[viz] = uniao([resolvidos[viz]] + partes, params)
            vazio = juntar(restantes)
    return {"resolvidos": resolvidos, "sobreposicoes": sobreposicoes, "fora": fora,
            "lascas": lascas, "vazio": vazio}


# ---------------------------------------------------------------- arredondamento

def _unidades(valor, fator):
    return int(math.floor(float(valor) * fator + 0.5))


def arredondar_fechando(itens, alvo, casas=4, fixos=None, tolerancia=TOL_HA):
    """Arredonda valores para que a soma exibida feche exatamente com o alvo.

    itens: {chave: valor}; fixos: {chave: valor já arredondado}. Se a soma real
    não estiver a menos de `tolerancia` do alvo (dado incompleto), faz
    arredondamento simples sem forçar o fechamento.
    """
    fator = 10 ** casas
    fixos = dict(fixos or {})
    saida = {k: round(float(v), casas) for k, v in fixos.items()}
    livres = {k: max(0.0, float(v or 0.0)) for k, v in itens.items() if k not in fixos}
    if alvo is None or not livres:
        saida.update({k: round(v, casas) for k, v in livres.items()})
        return saida
    soma_real = sum(livres.values()) + sum(float(v) for v in fixos.values())
    if abs(soma_real - float(alvo)) > tolerancia:
        saida.update({k: round(v, casas) for k, v in livres.items()})
        return saida
    alvo_u = _unidades(alvo, fator) - sum(_unidades(v, fator) for v in fixos.values())
    base = {k: int(math.floor(v * fator + 1e-9)) for k, v in livres.items()}
    resto = alvo_u - sum(base.values())
    restos = sorted(livres, key=lambda k: (livres[k] * fator - base[k], livres[k]), reverse=True)
    if resto > 0:
        i = 0
        while resto > 0 and restos:
            base[restos[i % len(restos)]] += 1
            resto -= 1
            i += 1
    elif resto < 0:
        for k in reversed(restos):
            if resto == 0:
                break
            if base[k] > 0:
                base[k] -= 1
                resto += 1
    saida.update({k: base[k] / float(fator) for k in livres})
    return saida
