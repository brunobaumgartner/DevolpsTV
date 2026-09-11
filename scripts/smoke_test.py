#!/usr/bin/env python3
"""Teste de fumaça do DevolpsTV — roda contra o site JÁ NO AR (não é teste de
unidade, é ponta-a-ponta pela API real) pra pegar regressão depois de um
deploy: login, papéis, conteúdo, proxy HLS, console do banco, upload de CSV,
"continuar assistindo".

Uso:
    pip install requests
    set DEVOLPSTV_ADMIN_PASS=...          (Windows)
    export DEVOLPSTV_ADMIN_PASS=...       (Linux/Mac)
    python scripts/smoke_test.py

Variáveis de ambiente:
    DEVOLPSTV_BASE_URL    default: http://exposite.com.br/iptv
    DEVOLPSTV_ADMIN_USER  default: admin
    DEVOLPSTV_ADMIN_PASS  obrigatória (não tem default de propósito)

Cada checagem é isolada: cria o que precisa e apaga no final (título de
teste, usuário de teste, progresso de teste) — não deixa lixo no banco real
mesmo se um teste no meio falhar (try/finally em cada um).

Sai com código 0 se tudo passou, 1 se algo falhou — dá pra plugar num
`&& echo ok` depois de um deploy.
"""

import os
import sys
import time
import uuid

import requests

# Windows/cmd às vezes usa uma codepage que não é UTF-8 -> acentos saem
# corrompidos no terminal. Força UTF-8 na saída quando o Python permite.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.environ.get("DEVOLPSTV_BASE_URL", "http://exposite.com.br/iptv").rstrip("/")
ADMIN_USER = os.environ.get("DEVOLPSTV_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("DEVOLPSTV_ADMIN_PASS")

_results = []  # (nome, ok, detalhe)


def check(name):
    """Decorator: roda a função, registra PASS/FAIL, nunca deixa uma
    checagem quebrar as outras (uma exceção conta como FAIL, não aborta)."""

    def wrap(fn):
        try:
            fn()
            _results.append((name, True, ""))
        except AssertionError as e:
            _results.append((name, False, str(e)))
        except Exception as e:  # rede, timeout, etc.
            _results.append((name, False, f"{type(e).__name__}: {e}"))
        return fn

    return wrap


def main():
    if not ADMIN_PASS:
        print("Defina DEVOLPSTV_ADMIN_PASS (senha do admin) antes de rodar.")
        sys.exit(2)

    admin = requests.Session()
    ctx = {}  # dados passados entre checagens (token, etc.)

    # ---------- site no ar ----------
    @check("frontend v2 carrega (200 + HTML)")
    def _():
        r = requests.get(f"{BASE}/v2/", timeout=10)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        assert "devolpstv" in r.text.lower() or "DevolpsTV" in r.text, "HTML não parece o app"

    @check("login com senha errada é rejeitado (401)")
    def _():
        r = requests.post(f"{BASE}/admin/login", json={"username": ADMIN_USER, "password": "senha-errada-de-proposito"}, timeout=10)
        assert r.status_code == 401, f"HTTP {r.status_code} (esperava 401)"

    @check("login admin funciona")
    def _():
        r = admin.post(f"{BASE}/admin/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}, timeout=10)
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"

    @check("/admin/me devolve role=admin + token")
    def _():
        r = admin.get(f"{BASE}/admin/me", timeout=10)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        me = r.json()
        assert me.get("role") == "admin", f"role={me.get('role')!r}"
        assert me.get("token"), "sem token de conteúdo"
        ctx["token"] = me["token"]

    # ---------- conteúdo (token) ----------
    @check("lista de canais carrega")
    def _():
        r = requests.get(f"{BASE}/p/{ctx['token']}/channels.json", timeout=15)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        chs = r.json().get("channels") or []
        assert len(chs) > 0, "0 canais"
        ctx["channels"] = chs

    @check("catálogo VOD carrega")
    def _():
        r = requests.get(f"{BASE}/p/{ctx['token']}/vod", params={"limit": 1}, timeout=15)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        assert "titles" in r.json()

    @check("gêneros VOD carregam")
    def _():
        r = requests.get(f"{BASE}/p/{ctx['token']}/vod/genres", timeout=15)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        assert len(r.json().get("genres") or []) > 0, "0 gêneros"

    @check("proxy do manifesto HLS reescreve pro Pluto (CORS)")
    def _():
        # acha um canal Pluto (jmp2.uk) de verdade na lista pra testar o proxy real
        cand = next((c for c in ctx.get("channels", []) for u in (c.get("stream_urls") or [c.get("stream_url")]) if u and "jmp2.uk" in u), None)
        if cand is None:
            raise AssertionError("nenhum canal Pluto (jmp2.uk) encontrado pra testar — pulei de verdade")
        url = next(u for u in (cand.get("stream_urls") or [cand.get("stream_url")]) if u and "jmp2.uk" in u)
        r = requests.get(f"{BASE}/p/{ctx['token']}/hls", params={"url": url}, timeout=15)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        assert r.text.lstrip().startswith("#EXTM3U"), "resposta não é um manifesto m3u8"

    # ---------- console do banco (admin) ----------
    @check("console do banco: SELECT funciona")
    def _():
        r = admin.post(f"{BASE}/admin/db/query", json={"sql": "SELECT 1 AS ok"}, timeout=10)
        assert r.status_code == 200, f"HTTP {r.status_code}"

    @check("console do banco: escrita é bloqueada")
    def _():
        for sql in ["DELETE FROM vod_titles WHERE id=0", "DROP TABLE vod_titles", "UPDATE vod_titles SET genre=NULL"]:
            r = admin.post(f"{BASE}/admin/db/query", json={"sql": sql}, timeout=10)
            assert r.status_code == 400, f"{sql!r} -> HTTP {r.status_code} (deveria ser 400)"

    # ---------- sistema (admin) ----------
    @check("tela Sistema: consumo do servidor responde")
    def _():
        r = admin.get(f"{BASE}/admin/system/resources", timeout=10)
        assert r.status_code == 200 and "cpu_percent" in r.json()

    @check("tela Sistema: lista de processos responde")
    def _():
        r = admin.get(f"{BASE}/admin/system/jobs", timeout=10)
        assert r.status_code == 200 and "in_process" in r.json()

    # ---------- papel "user" não acessa admin ----------
    @check("conta role=user não acessa endpoint admin (403) — cria e apaga sozinha")
    def _():
        uname = f"_smoketest_{uuid.uuid4().hex[:8]}"
        r = admin.post(f"{BASE}/admin/users", json={"username": uname, "password": "x", "role": "user"}, timeout=10)
        assert r.status_code == 200, f"criar usuário: HTTP {r.status_code}"
        uid = r.json()["id"]
        try:
            u = requests.Session()
            r2 = u.post(f"{BASE}/admin/login", json={"username": uname, "password": "x"}, timeout=10)
            assert r2.status_code == 200, f"login do usuário de teste: HTTP {r2.status_code}"
            r3 = u.get(f"{BASE}/admin/dashboard", timeout=10)
            assert r3.status_code == 403, f"esperava 403, veio {r3.status_code}"
        finally:
            admin.delete(f"{BASE}/admin/users/{uid}", timeout=10)

    # ---------- upload de CSV grande (413) ----------
    @check("upload de CSV > 1MB não dá 413 (limite do nginx)")
    def _():
        title = f"_smoketest_{uuid.uuid4().hex[:8]}"
        row = f"movie,{title},,,,,,,,\n"
        header = "type,title,description,poster_url,genre,year,season_number,episode_number,episode_title,stream_url\n"
        csv = header + row * (int(1.5 * 1024 * 1024) // len(row.encode()))  # ~1.5MB
        assert len(csv.encode()) > 1024 * 1024, "csv de teste não passou de 1MB"
        files = {"file": ("smoketest.csv", csv.encode(), "text/csv")}
        r = admin.post(f"{BASE}/admin/vod/import-csv", files=files, timeout=30)
        assert r.status_code != 413, "HTTP 413 — client_max_body_size caiu de novo"
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        job_id = r.json()["job_id"]
        for _ in range(30):
            time.sleep(1)
            st = admin.get(f"{BASE}/admin/vod/import-csv/{job_id}/status", timeout=10).json()
            if st.get("status") in ("done", "error"):
                break
        # limpa o título criado pelo teste, se criou
        rq = admin.post(f"{BASE}/admin/db/query", json={"sql": f"SELECT id FROM vod_titles WHERE title='{title}'"}, timeout=10)
        for row in rq.json().get("rows", []):
            admin.delete(f"{BASE}/admin/vod/titles/{row[0]}", timeout=10)

    # ---------- "continuar assistindo" ----------
    @check('"continuar assistindo": salva, aparece, some ao terminar')
    def _():
        rq = admin.post(f"{BASE}/admin/db/query", json={"sql": "SELECT id FROM vod_titles WHERE type='movie' LIMIT 1"}, timeout=10)
        rows = rq.json().get("rows", [])
        if not rows:
            raise AssertionError("nenhum filme no catálogo pra testar com")
        title_id = rows[0][0]
        try:
            r = requests.post(f"{BASE}/p/{ctx['token']}/progress", json={"title_id": title_id, "position": 30, "duration": 300}, timeout=10)
            assert r.status_code == 200 and r.json().get("removed") is False

            r2 = requests.get(f"{BASE}/p/{ctx['token']}/continue-watching", timeout=10)
            ids = [it["title_id"] for it in r2.json().get("items", [])]
            assert title_id in ids, "não apareceu em continue-watching"

            r3 = requests.post(f"{BASE}/p/{ctx['token']}/progress", json={"title_id": title_id, "position": 290, "duration": 300}, timeout=10)
            assert r3.status_code == 200 and r3.json().get("removed") is True, "não saiu da lista ao 'terminar'"
        finally:
            requests.delete(f"{BASE}/p/{ctx['token']}/progress/{title_id}", timeout=10)

    # ---------- logout ----------
    @check("logout invalida a sessão")
    def _():
        r = admin.post(f"{BASE}/admin/logout", timeout=10)
        assert r.status_code == 200
        r2 = admin.get(f"{BASE}/admin/me", timeout=10)
        assert r2.status_code == 401, f"sessão ainda válida depois do logout (HTTP {r2.status_code})"

    # ---------- relatório ----------
    width = max(len(n) for n, _, _ in _results) + 2
    failed = 0
    for name, ok, detail in _results:
        tag = "OK  " if ok else "FAIL"
        print(f"[{tag}] {name.ljust(width)} {'' if ok else '— ' + detail}")
        if not ok:
            failed += 1
    print(f"\n{len(_results) - failed}/{len(_results)} passaram.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
