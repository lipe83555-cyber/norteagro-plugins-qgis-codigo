# -*- coding: utf-8 -*-
"""Extração de texto de PDF.

1. Usa a biblioteca pypdf quando ela existe no Python do QGIS.
2. Se não existir, usa o leitor mínimo deste arquivo (só biblioteca padrão):
   objetos, fluxos FlateDecode, fluxos de objetos, fontes WinAnsi e fontes Type0
   com tabela ToUnicode. Cobre os PDFs gerados por sistema (recibo do SIGCAR/SICAR,
   certidões digitais de cartório). PDFs digitalizados (só imagem) não têm texto:
   para eles é preciso OCR.
"""

import re
import zlib

# WinAnsiEncoding (cp1252) cobre os acentos do português
_WINANSI = "cp1252"


def extrair(caminho, max_paginas=8):
    """Retorna (texto_por_pagina: list[str], metodo: str)."""
    try:
        import pypdf  # noqa: F401
        return _com_pypdf(caminho, max_paginas), "pypdf"
    except ImportError:
        pass
    except Exception:
        # pypdf falhou neste arquivo: tenta o leitor próprio
        pass
    return LeitorPdf(caminho).paginas(max_paginas), "leitor interno"


def _com_pypdf(caminho, max_paginas):
    import pypdf
    leitor = pypdf.PdfReader(caminho, strict=False)
    if leitor.is_encrypted:
        try:
            leitor.decrypt("")
        except Exception:
            pass
    saida = []
    for i, pagina in enumerate(leitor.pages):
        if i >= max_paginas:
            break
        try:
            saida.append(pagina.extract_text() or "")
        except Exception:
            saida.append("")
    return saida


# ---------------------------------------------------------------- leitor mínimo
_RE_OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj", re.S)
_RE_REF = re.compile(rb"(\d+)\s+(\d+)\s+R")


def _dict_e_fluxo(corpo):
    """Separa o dicionário e o fluxo (bytes) de um objeto."""
    m = re.search(rb"stream\r?\n", corpo)
    if not m:
        return corpo, None
    dic = corpo[:m.start()]
    fim = corpo.rfind(b"endstream")
    dados = corpo[m.end():fim if fim > 0 else len(corpo)]
    if dados.endswith(b"\r\n"):
        dados = dados[:-2]
    elif dados.endswith(b"\n") or dados.endswith(b"\r"):
        dados = dados[:-1]
    return dic, dados


def _decodificar(dic, dados):
    if dados is None:
        return None
    if b"/FlateDecode" in dic or b"/Fl " in dic or b"/Fl]" in dic:
        try:
            return zlib.decompress(dados)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(dados)
            except zlib.error:
                return b""
    if b"/Filter" in dic:
        return b""  # outros filtros (imagens, LZW...) não interessam ao texto
    return dados


def _ler_string_literal(b, i):
    """b[i] == '(' -> (bytes, novo_indice)."""
    nivel = 1
    i += 1
    out = bytearray()
    while i < len(b) and nivel:
        c = b[i]
        if c == 0x5C:  # barra invertida
            i += 1
            if i >= len(b):
                break
            e = b[i]
            mapa = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12,
                    ord("("): 40, ord(")"): 41, 0x5C: 0x5C}
            if e in mapa:
                out.append(mapa[e])
            elif 48 <= e <= 55:
                oct_ = bytes([e])
                for _ in range(2):
                    if i + 1 < len(b) and 48 <= b[i + 1] <= 55:
                        i += 1
                        oct_ += bytes([b[i]])
                out.append(int(oct_, 8) & 0xFF)
            elif e in (10, 13):
                if e == 13 and i + 1 < len(b) and b[i + 1] == 10:
                    i += 1
            else:
                out.append(e)
        elif c == 0x28:
            nivel += 1
            out.append(c)
        elif c == 0x29:
            nivel -= 1
            if nivel:
                out.append(c)
        else:
            out.append(c)
        i += 1
    return bytes(out), i


class LeitorPdf:
    def __init__(self, caminho):
        with open(caminho, "rb") as fh:
            self.bruto = fh.read()
        self.objetos = {}
        for m in _RE_OBJ.finditer(self.bruto):
            self.objetos[int(m.group(1))] = m.group(3)
        self._expandir_fluxos_de_objetos()
        self._cache_cmap = {}

    def _expandir_fluxos_de_objetos(self):
        for num, corpo in list(self.objetos.items()):
            if b"/ObjStm" not in corpo[:400]:
                continue
            dic, dados = _dict_e_fluxo(corpo)
            dados = _decodificar(dic, dados)
            if not dados:
                continue
            n = re.search(rb"/N\s+(\d+)", dic)
            first = re.search(rb"/First\s+(\d+)", dic)
            if not n or not first:
                continue
            n, first = int(n.group(1)), int(first.group(1))
            cab = dados[:first].split()
            pares = [(int(cab[k]), int(cab[k + 1])) for k in range(0, min(len(cab), 2 * n) - 1, 2)]
            for idx, (onum, desloc) in enumerate(pares):
                ini = first + desloc
                fim = first + pares[idx + 1][1] if idx + 1 < len(pares) else len(dados)
                self.objetos.setdefault(onum, dados[ini:fim])

    def obj(self, ref):
        if isinstance(ref, bytes):
            m = _RE_REF.match(ref.strip())
            if not m:
                return None
            ref = int(m.group(1))
        return self.objetos.get(ref)

    def _valor(self, dic, chave):
        """Valor bruto de /Chave num dicionário (referência, nome, array ou dicionário)."""
        m = re.search(rb"/" + chave + rb"\s*", dic)
        if not m:
            return None
        i = m.end()
        if dic[i:i + 2] == b"<<":
            nivel, j = 0, i
            while j < len(dic):
                if dic[j:j + 2] == b"<<":
                    nivel += 1
                    j += 2
                    continue
                if dic[j:j + 2] == b">>":
                    nivel -= 1
                    j += 2
                    if nivel == 0:
                        return dic[i:j]
                    continue
                j += 1
            return dic[i:]
        if dic[i:i + 1] == b"[":
            j = dic.find(b"]", i)
            return dic[i:j + 1]
        m2 = _RE_REF.match(dic, i)
        if m2:
            return m2.group(0)
        m3 = re.match(rb"/?[^\s/<>\[\]()]+", dic[i:])
        return m3.group(0) if m3 else None

    def _resolver(self, v):
        if v is not None and _RE_REF.fullmatch(v.strip()):
            return self.obj(v)
        return v

    def _paginas_ordenadas(self):
        raiz = None
        for num, corpo in self.objetos.items():
            if re.search(rb"/Type\s*/Catalog", corpo):
                raiz = corpo
                break
        if raiz is None:
            return [c for _, c in sorted(self.objetos.items()) if re.search(rb"/Type\s*/Page\b", c)]
        ordem = []

        def visitar(no, herdado, profundidade=0):
            if no is None or profundidade > 50:
                return
            if re.search(rb"/Type\s*/Pages\b", no):
                rec = self._valor(no, b"Resources") or herdado
                kids = self._valor(no, b"Kids") or b"[]"
                for r in _RE_REF.finditer(kids):
                    visitar(self.obj(int(r.group(1))), rec, profundidade + 1)
            elif re.search(rb"/Type\s*/Page\b", no):
                ordem.append((no, herdado))

        visitar(self._resolver(self._valor(raiz, b"Pages")), None)
        return ordem

    def _fontes(self, pagina, herdado):
        rec = self._resolver(self._valor(pagina, b"Resources") or herdado)
        if not rec:
            return {}
        fontes = self._resolver(self._valor(rec, b"Font"))
        if not fontes:
            return {}
        saida = {}
        for m in re.finditer(rb"/([^\s/<>\[\]()]+)\s+(\d+\s+\d+\s+R)", fontes):
            saida[m.group(1)] = self._info_fonte(self.obj(m.group(2)) or b"")
        return saida

    def _info_fonte(self, fonte):
        tipo0 = b"/Type0" in fonte
        cmap = {}
        tu = self._valor(fonte, b"ToUnicode")
        if tu and _RE_REF.fullmatch(tu.strip()):
            num = int(_RE_REF.match(tu.strip()).group(1))
            if num not in self._cache_cmap:
                dic, dados = _dict_e_fluxo(self.obj(num) or b"")
                self._cache_cmap[num] = _ler_cmap(_decodificar(dic, dados) or b"")
            cmap = self._cache_cmap[num]
        largura = 2 if tipo0 else 1
        if cmap:
            largura = max(len(k) for k in cmap) if cmap else largura
        return {"cmap": cmap, "bytes": largura}

    def _conteudo(self, pagina):
        cont = self._valor(pagina, b"Contents")
        if not cont:
            return b""
        refs = [int(r.group(1)) for r in _RE_REF.finditer(cont)]
        partes = []
        for r in refs:
            dic, dados = _dict_e_fluxo(self.obj(r) or b"")
            partes.append(_decodificar(dic, dados) or b"")
        return b"\n".join(partes)

    def paginas(self, max_paginas=8):
        saida = []
        for pagina, herdado in self._paginas_ordenadas()[:max_paginas]:
            fontes = self._fontes(pagina, herdado)
            saida.append(_texto_do_conteudo(self._conteudo(pagina), fontes))
        return saida


def _ler_cmap(dados):
    cmap = {}

    def hex_para_texto(h):
        bts = bytes.fromhex(h.decode())
        try:
            return bts.decode("utf-16-be")
        except UnicodeDecodeError:
            return ""

    for bloco in re.findall(rb"beginbfchar(.*?)endbfchar", dados, re.S):
        for a, b in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", bloco):
            cmap[bytes.fromhex(a.decode())] = hex_para_texto(b)
    for bloco in re.findall(rb"beginbfrange(.*?)endbfrange", dados, re.S):
        for m in re.finditer(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", bloco):
            ini, fim = int(m.group(1), 16), int(m.group(2), 16)
            larg = len(m.group(1)) // 2
            if fim - ini > 5000:
                continue
            alvo = m.group(3)
            if alvo.startswith(b"["):
                itens = re.findall(rb"<([0-9A-Fa-f]+)>", alvo)
                for k, h in enumerate(itens):
                    cmap[(ini + k).to_bytes(larg, "big")] = hex_para_texto(h)
            else:
                base = int(alvo[1:-1], 16)
                nbytes = (len(alvo) - 2) // 2
                for k in range(fim - ini + 1):
                    try:
                        cmap[(ini + k).to_bytes(larg, "big")] = (base + k).to_bytes(nbytes, "big").decode("utf-16-be")
                    except (UnicodeDecodeError, OverflowError):
                        pass
    return cmap


def _decodificar_texto(bts, fonte):
    if not fonte or not fonte.get("cmap"):
        return bts.decode(_WINANSI, errors="replace")
    cmap, larg = fonte["cmap"], fonte.get("bytes", 1)
    out = []
    i = 0
    while i < len(bts):
        pedaco = bts[i:i + larg]
        if pedaco in cmap:
            out.append(cmap[pedaco])
        elif larg == 1:
            out.append(bytes([bts[i]]).decode(_WINANSI, errors="replace"))
        i += larg
    return "".join(out)


_RE_TOKEN = re.compile(rb"\s*(\((?:\\.|[^\\])*?\)|<[0-9A-Fa-f\s]*>|\[|\]|/[^\s/<>\[\]()]+|[-+]?\d*\.?\d+|[A-Za-z'\"*]+)",
                       re.S)


def _texto_do_conteudo(dados, fontes):
    """Interpreta os operadores de texto e monta linhas (ordem do fluxo, com quebra quando y muda)."""
    linhas = []
    atual = []
    pilha = []
    fonte = None
    y_atual = None
    i = 0
    n = len(dados)

    def quebrar():
        if atual:
            linhas.append("".join(atual))
            atual.clear()

    while i < n:
        c = dados[i:i + 1]
        if c in b" \t\r\n":
            i += 1
            continue
        if c == b"(":
            s, i = _ler_string_literal(dados, i)
            pilha.append(("str", s))
            continue
        if c == b"<" and dados[i:i + 2] != b"<<":
            j = dados.find(b">", i)
            h = re.sub(rb"\s", b"", dados[i + 1:j])
            if len(h) % 2:
                h += b"0"
            try:
                pilha.append(("str", bytes.fromhex(h.decode())))
            except ValueError:
                pass
            i = j + 1
            continue
        if dados[i:i + 2] in (b"<<", b">>"):
            i += 2
            continue
        if c == b"[":
            pilha.append(("[", None))
            i += 1
            continue
        if c == b"]":
            arr = []
            while pilha and pilha[-1][0] != "[":
                arr.insert(0, pilha.pop())
            if pilha:
                pilha.pop()
            pilha.append(("arr", arr))
            i += 1
            continue
        if c == b"/":
            m = re.match(rb"/[^\s/<>\[\]()]+", dados[i:])
            pilha.append(("nome", m.group(0)[1:]))
            i += len(m.group(0))
            continue
        m = re.match(rb"[-+]?\d*\.?\d+", dados[i:])
        if m and m.group(0) not in (b"", b"+", b"-"):
            try:
                pilha.append(("num", float(m.group(0))))
            except ValueError:
                pass
            i += len(m.group(0))
            continue
        m = re.match(rb"[A-Za-z'\"*][A-Za-z0-9*]*", dados[i:])
        if not m:
            i += 1
            continue
        op = m.group(0)
        i += len(op)
        if op == b"BI":  # imagem embutida: pula até EI
            j = dados.find(b"EI", i)
            i = j + 2 if j > 0 else n
            pilha.clear()
            continue
        if op == b"Tf":
            nomes = [v for t, v in pilha if t == "nome"]
            if nomes:
                fonte = fontes.get(nomes[-1])
        elif op in (b"Td", b"TD", b"Tm"):
            nums = [v for t, v in pilha if t == "num"]
            if op == b"Tm" and len(nums) >= 6:
                y = nums[5]
                if y_atual is not None and abs(y - y_atual) > 1:
                    quebrar()
                elif atual:
                    atual.append(" ")
                y_atual = y
            elif len(nums) >= 2:
                if abs(nums[1]) > 1:
                    quebrar()
                    y_atual = (y_atual or 0) + nums[1]
                elif nums[0] > 1 and atual:
                    atual.append(" ")
        elif op in (b"T*", b"'", b'"'):
            quebrar()
            if op != b"T*":
                strs = [v for t, v in pilha if t == "str"]
                if strs:
                    atual.append(_decodificar_texto(strs[-1], fonte))
        elif op == b"Tj":
            strs = [v for t, v in pilha if t == "str"]
            if strs:
                atual.append(_decodificar_texto(strs[-1], fonte))
        elif op == b"TJ":
            arrs = [v for t, v in pilha if t == "arr"]
            if arrs:
                for t, v in arrs[-1]:
                    if t == "str":
                        atual.append(_decodificar_texto(v, fonte))
                    elif t == "num" and v < -200:
                        atual.append(" ")
        elif op == b"ET":
            pass
        pilha.clear()
    quebrar()
    texto = "\n".join(l.rstrip() for l in linhas)
    return re.sub(r"[ \t]{2,}", " ", texto)
