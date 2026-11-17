# -*- coding: utf-8 -*-
"""Leituras GDAL pela internet (nuvens das cenas Sentinel-2 e recorte da imagem) em um processo separado.

Por quê: as funções do GDAL seguram o Python do QGIS enquanto esperam a internet. Feitas dentro do
QGIS, uma conexão lenta congela o programa. Aqui elas rodam em outro processo Python (o mesmo do QGIS,
com o mesmo GDAL): o QGIS só lê as respostas, linha a linha, e pode encerrar o processo se demorar.

Este arquivo também é o próprio programa do processo filho (python gdal_processo.py < pedido.json).
"""

import json
import os
import subprocess
import sys
import threading
import time

TEMPO_MAXIMO_S = 120


# ================================================================ lado do QGIS
def _python():
    """Executável Python que acompanha o QGIS (no Windows o sys.executable é o qgis-bin.exe)."""
    candidatos = []
    exe = sys.executable or ""
    if os.path.basename(exe).lower().startswith("python"):
        candidatos.append(exe)
    for base in (sys.prefix, sys.exec_prefix, getattr(sys, "base_prefix", ""), os.path.dirname(exe)):
        if base:
            candidatos += [os.path.join(base, "python.exe"), os.path.join(base, "python3.exe"),
                           os.path.join(base, "bin", "python3"), os.path.join(base, "bin", "python")]
    for c in candidatos:
        if c and os.path.isfile(c):
            return c
    import shutil
    return shutil.which("python3") or shutil.which("python")


def executar(pedido, ao_resultado=None, feedback=None, tempo_maximo=TEMPO_MAXIMO_S):
    """Roda o pedido no processo filho. ao_resultado(dict) é chamado a cada item pronto.
    Retorna a lista de resultados. Cancela (encerra o processo) se o feedback for cancelado ou estourar o tempo."""
    py = _python()
    if not py:
        raise IOError("não encontrei o Python do QGIS para ler as imagens")
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: sem janela preta piscando
    proc = subprocess.Popen([py, "-u", os.path.abspath(__file__)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, creationflags=flags)
    proc.stdin.write(json.dumps(pedido).encode("utf-8"))
    proc.stdin.close()
    esperados = len(pedido.get("itens") or [])
    resultados, erros = [], []

    def ler_erros():
        erros.append(proc.stderr.read().decode("utf-8", "replace"))

    threading.Thread(target=ler_erros, daemon=True).start()
    inicio = time.time()

    def vigia():
        while proc.poll() is None:
            if (feedback is not None and feedback.isCanceled()) or time.time() - inicio > tempo_maximo:
                _encerrar(proc)
                return
            time.sleep(0.2)

    threading.Thread(target=vigia, daemon=True).start()
    for linha in proc.stdout:
        linha = linha.decode("utf-8", "replace").strip()
        if not linha.startswith("{"):
            continue
        try:
            r = json.loads(linha)
        except ValueError:
            continue
        resultados.append(r)
        if ao_resultado:
            ao_resultado(r)
        if esperados and len(resultados) >= esperados:
            break  # tudo respondido: não espera o processo terminar sozinho
    _encerrar(proc)
    if feedback is not None and feedback.isCanceled():
        from .imagens import Cancelado
        raise Cancelado()
    if time.time() - inicio > tempo_maximo:
        raise IOError("a leitura das imagens demorou demais (internet lenta?)")
    if len(resultados) < esperados and proc.returncode not in (0, None) and not resultados:
        raise IOError("falha ao ler as imagens: " + ("".join(erros).strip().splitlines() or ["?"])[-1])
    return resultados


def _encerrar(proc):
    """Fecha o processo filho e os que ele abriu (no Windows o GDAL às vezes não deixa o Python sair)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=0x08000000, timeout=10)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def limpar_orfaos():
    """Encerra processos deste arquivo que ficaram para trás (versões antigas não fechavam o processo)."""
    if os.name != "nt":
        return 0
    ps = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0",
                      "powershell.exe")
    comando = [ps if os.path.isfile(ps) else "powershell", "-NoProfile", "-Command",
               "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
               "Where-Object { $_.CommandLine -like '*gdal_processo.py*' } | ForEach-Object { $_.ProcessId }"]
    try:
        r = subprocess.run(comando, capture_output=True, creationflags=0x08000000, timeout=20)
        pids = [x.strip() for x in r.stdout.decode("cp850", "replace").split() if x.strip().isdigit()]
    except Exception:
        return 0
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, creationflags=0x08000000)
    return len(pids)


# ================================================================ lado do processo filho
def _configurar(gdal):
    for k, v in {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_MAX_RETRY": "2",
                 "GDAL_HTTP_RETRY_DELAY": "1", "GDAL_HTTP_TIMEOUT": "30", "GDAL_HTTP_CONNECTTIMEOUT": "15",
                 "AWS_NO_SIGN_REQUEST": "YES", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF"}.items():
        gdal.SetConfigOption(k, v)


def _nuvens(gdal, item):
    import numpy
    x0, y0, x1, y1 = item["bbox"]
    destino = f"/vsimem/scl_{item['id']}.tif"
    ds = gdal.Warp(destino, "/vsicurl/" + item["href"], format="GTiff", resampleAlg="near",
                   outputBounds=(x0, y0, x1, y1), outputBoundsSRS="EPSG:4326")
    a = ds.ReadAsArray()
    ds = None
    gdal.Unlink(destino)
    total = float(a.size or 1)
    return {"id": item["id"], "nuvens": round(float(numpy.isin(a, (3, 8, 9, 10)).sum()) * 100 / total, 1),
            "sem_dados": round(float((a == 0).sum()) * 100 / total, 1)}


def _recorte(gdal, item):
    x0, y0, x1, y1 = item["bbox"]
    ds = gdal.Warp(item["destino"], "/vsicurl/" + item["href"], format="GTiff",
                   outputBounds=(x0, y0, x1, y1), outputBoundsSRS="EPSG:4326",
                   creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
    ds = None
    return {"id": item["id"], "arquivo": item["destino"]}


def _principal():
    pedido = json.loads(sys.stdin.read())
    from osgeo import gdal
    gdal.UseExceptions()
    _configurar(gdal)
    funcao = _nuvens if pedido.get("acao") == "nuvens" else _recorte
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def um(item):
        try:
            return funcao(gdal, item)
        except Exception as e:
            return {"id": item.get("id"), "erro": str(e)}

    ex = ThreadPoolExecutor(max(1, min(8, len(pedido.get("itens") or [1]))))
    for f in as_completed([ex.submit(um, it) for it in pedido.get("itens") or []]):
        sys.stdout.write(json.dumps(f.result()) + "\n")
        sys.stdout.flush()
    # sai na hora: no Windows o GDAL (leitura pela internet) pode travar a saída normal do Python
    os._exit(0)


if __name__ == "__main__":
    _principal()
