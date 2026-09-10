"""Classificação de gênero via dataset público do IMDb, NÃO por palavra-chave
— casa o TÍTULO EXATO (original OU a tradução em PT-BR) com uma obra real do
IMDb e herda o gênero de lá. Complementa o genre_classifier.py (que casa por
palavra-chave dentro do título).

O trabalho pesado (ler os ~62M linhas de title.basics.tsv.gz +
title.akas.tsv.gz) acontece só na CONSTRUÇÃO do índice (imdb_index_builder.py),
não a cada classificação — o índice fica salvo em SQLite dentro de
IMDB_DATA_DIR e é reaproveitado em toda chamada seguinte. Só reconstrói de
novo se você apagar o arquivo do índice ou baixar uma versão nova do dataset.

Diferente do genre_classifier.py sozinho, este SOBRESCREVE gênero já
preenchido quando acha um match no IMDb — de propósito: o gênero real do
IMDb é mais confiável que um palpite por palavra-chave no título, então
corrige classificações antigas erradas, não só preenche o que está NULL.

Esse módulo é o botão único "Classificar gêneros" do dashboard: constrói o
índice na 1ª vez (só demora nessa), casa cada título pelo índice, e só
DEPOIS usa a palavra-chave (genre_classifier.py) como último recurso pro que
ainda ficou sem gênero — a palavra-chave nunca sobrescreve nada, só preenche
vazio, então rodar ela depois é seguro."""

import re
import threading
import unicodedata
import uuid
from datetime import datetime, timezone

from .db import SessionLocal
from .genre_classifier import _load_ordered_patterns, classify_title
from .job_registry import is_cancelled, register
from .imdb_index_builder import (
    build_index,
    dataset_files_available,
    index_exists,
    lookup_genre,
    open_index_readonly,
)
from .models import VodTitle


def is_dataset_available() -> bool:
    """Índice já construído OU dataset bruto presente (constrói na hora)."""
    return index_exists() or dataset_files_available()


def _normalize(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower().strip()


# "(2009)" no fim do título -> tira. Seguro: o índice quase sempre guarda sem.
_RE_YEAR_SUFFIX = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")
# "007: " no começo -> tira (série do Bond). Exige 2+ dígitos de propósito:
# "4: Apocalipse" / "3: Gênesis" são sequências e um dígito solto casa lixo.
_RE_NUM_PREFIX = re.compile(r"^\s*\d{2,4}\s*[:\-–]\s*")
_RE_MULTISPACE = re.compile(r"\s+")


def _normalize_variants(text: str) -> list[str]:
    """Formas normalizadas pra tentar no índice, da mais fiel à mais 'limpa'.
    O índice guarda os títulos com pontuação e às vezes com '(ano)', então
    quando o match exato falha vale tentar sem o ano no fim, sem prefixo
    numérico ('007: ...' -> '...'), etc. Primeiro acerto vence."""
    base = _normalize(text)
    seen = []

    def add(s):
        s = _RE_MULTISPACE.sub(" ", s).strip()
        if s and s not in seen:
            seen.append(s)

    add(base)
    no_year = _RE_YEAR_SUFFIX.sub("", base)
    add(no_year)
    add(_RE_NUM_PREFIX.sub("", base))
    add(_RE_NUM_PREFIX.sub("", no_year))
    return seen


def _lookup_any(index_conn, text: str, ttype_group: str):
    for variant in _normalize_variants(text):
        genre = lookup_genre(index_conn, variant, ttype_group)
        if genre:
            return genre
    return None


# --- job em background com progresso (mesmo padrão do genre_classifier.py) ---

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _set_progress(job_id: str, **kwargs):
    with _jobs_lock:
        _jobs[job_id].update(kwargs)


def start_imdb_classify_job() -> str:
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "phase": "iniciando",
            "processed": 0,
            "total": 1,
            "classified": 0,
            "newly_classified": 0,
            "corrected": 0,
            "keyword_classified": 0,
            "error": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    register("Classificar gêneros", job_id, get_imdb_classify_job)

    def _worker():
        # expire_on_commit=False: sem isso, o db.commit() no meio expira os
        # ~26k objetos já carregados e a fase de palavra-chave dispara um
        # SELECT por título (lentidão de minutos). Job em lote pode manter o
        # estado em memória tranquilo.
        db = SessionLocal(expire_on_commit=False)
        try:
            # constrói o índice só se ainda não existir — isso é o único
            # ponto lento (1ª vez ou depois de apagar/atualizar o dataset)
            if not index_exists():
                if not dataset_files_available():
                    raise RuntimeError(
                        "Dataset do IMDb não encontrado no servidor "
                        "(title.basics.tsv.gz / title.akas.tsv.gz)."
                    )

                def _progress_cb(phase, processed, total):
                    _set_progress(job_id, phase=f"construindo índice (só na 1ª vez): {phase}", processed=processed, total=total)

                build_index(progress_cb=_progress_cb)

            # ao contrário do genre_classifier.py, aqui pega TODO título (não
            # só genre IS NULL) — corrige palpites errados da classificação
            # por palavra-chave também, não só preenche vazio
            _set_progress(job_id, phase="classificando pelo índice do IMDb", processed=0)
            titles = db.query(VodTitle).all()
            _set_progress(job_id, total=len(titles))

            index_conn = open_index_readonly()
            newly_classified = 0
            corrected = 0
            try:
                for i, title in enumerate(titles, start=1):
                    ttype_group = "movie" if title.type == "movie" else "series"
                    genre = _lookup_any(index_conn, title.title, ttype_group)
                    if genre and genre != title.genre:
                        if title.genre is None:
                            newly_classified += 1
                        else:
                            corrected += 1
                        title.genre = genre
                    if i % 500 == 0:
                        _set_progress(job_id, processed=i)
                        if is_cancelled(job_id):
                            db.commit()
                            _set_progress(job_id, status="cancelled", phase=f"cancelado em {i} de {len(titles)}")
                            return
            finally:
                index_conn.close()

            db.commit()

            # passo final: o que o IMDb não conseguiu bater, tenta por
            # palavra-chave como ultimo recurso — nunca sobrescreve nada, so
            # preenche genre ainda NULL, entao rodar depois do IMDb e seguro
            _set_progress(job_id, phase="preenchendo o resto por palavra-chave", processed=0)
            patterns = _load_ordered_patterns(db)
            keyword_classified = 0
            total = len(titles)
            for i, title in enumerate(titles, start=1):
                if title.genre is None:
                    genre = classify_title(title.title, patterns)
                    if genre:
                        title.genre = genre
                        keyword_classified += 1
                # refino Animação -> Anime no mesmo passo
                if title.genre == "Animação" and classify_title(title.title, patterns) == "Anime":
                    title.genre = "Anime"
                    corrected += 1
                if i % 1000 == 0:
                    _set_progress(job_id, processed=i)

            db.commit()
            _set_progress(
                job_id,
                status="done",
                phase="concluído",
                processed=len(titles),
                classified=newly_classified + corrected + keyword_classified,
                newly_classified=newly_classified,
                corrected=corrected,
                keyword_classified=keyword_classified,
            )
        except Exception as e:
            db.rollback()
            _set_progress(job_id, status="error", error=str(e))
        finally:
            db.close()

    threading.Thread(target=_worker, daemon=True, name=f"imdb-classify-{job_id[:8]}").start()
    return job_id


def get_imdb_classify_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None
