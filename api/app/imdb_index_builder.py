"""Constrói (1 vez só, não a cada classificação) um índice SQLite local a
partir do dataset do IMDb (title.basics.tsv.gz + title.akas.tsv.gz).

Por quê: a v1 do imdb_classifier.py reprocessava os dois arquivos .gz
inteiros (~62M linhas somadas) do zero TODA VEZ que o botão "Classificar
gêneros" era clicado — minutos de CPU por clique, sempre. Isso constrói o
índice uma vez (ou quando o dataset for atualizado) e grava num arquivo
SQLite dentro de IMDB_DATA_DIR; depois disso, classificar um título vira 1
SELECT indexado, não uma varredura do arquivo inteiro.

Estratégia: em vez de fazer 1 SELECT por linha do title.basics pra achar o
título em PT-BR correspondente (lento — 12M round-trips), faz 2 inserções em
massa (bulk insert, sem parar pra consultar nada) e deixa o SQLite resolver o
JOIN + agregação em SQL puro no final — é ordens de magnitude mais rápido que
fazer isso em loop Python."""

import csv
import gzip
import os
import sqlite3
import threading
import time

from .config import IMDB_DATA_DIR

# evita 2 builds simultâneos pisando no mesmo arquivo temporário (aconteceu
# na prática: 2 cliques em "Classificar gêneros" quase ao mesmo tempo, antes
# do índice existir, corromperam o .building de um deles)
_build_lock = threading.Lock()

AKAS_PATH = os.path.join(IMDB_DATA_DIR, "title.akas.tsv.gz")
BASICS_PATH = os.path.join(IMDB_DATA_DIR, "title.basics.tsv.gz")
INDEX_PATH = os.path.join(IMDB_DATA_DIR, "imdb_genre_index.sqlite3")

# só pra estimar % de progresso na barra — não precisa ser exato
_AKAS_APPROX_LINES = 50_000_000
_BASICS_APPROX_LINES = 12_000_000

MOVIE_TYPES = {"movie", "tvMovie"}
SERIES_TYPES = {"tvSeries", "tvMiniSeries"}

# mapeia o gênero em inglês do IMDb pra nossa taxonomia (mesmas chaves de
# genre_classifier.DEFAULT_KEYWORDS) — em ordem de prioridade: quando um
# título tem vários gêneros no IMDb, o mais específico vence
IMDB_GENRE_PRIORITY = [
    ("Documentary", "Documentário"), ("Biography", "Biografia"), ("Animation", "Animação"),
    ("Musical", "Musical"), ("Music", "Musical"), ("Western", "Western"), ("War", "Guerra"),
    ("History", "Época"), ("Sci-Fi", "Ficção científica"), ("Fantasy", "Fantasia"),
    ("Horror", "Terror"), ("Thriller", "Suspense/Thriller"), ("Film-Noir", "Suspense/Thriller"),
    ("Crime", "Crime"), ("Mystery", "Mistério"), ("Sport", "Esporte"), ("Family", "Família"),
    ("Romance", "Romance"), ("Comedy", "Comédia"), ("Adventure", "Aventura"), ("Action", "Ação"),
    ("Drama", "Drama"),
]
IMDB_TO_OUR_GENRE = dict(IMDB_GENRE_PRIORITY)
PRIORITY_ORDER = [our for _, our in IMDB_GENRE_PRIORITY]


def _normalize(text: str) -> str:
    import unicodedata
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower().strip()


def _pick_genre(imdb_genres_csv: str) -> str | None:
    genres = [g for g in imdb_genres_csv.split(",") if g in IMDB_TO_OUR_GENRE]
    if not genres:
        return None
    mapped = {IMDB_TO_OUR_GENRE[g] for g in genres}
    for our_genre in PRIORITY_ORDER:
        if our_genre in mapped:
            return our_genre
    return None


def dataset_files_available() -> bool:
    return os.path.isfile(AKAS_PATH) and os.path.isfile(BASICS_PATH)


def index_exists() -> bool:
    return os.path.isfile(INDEX_PATH)


def index_age_seconds() -> float | None:
    if not index_exists():
        return None
    return time.time() - os.path.getmtime(INDEX_PATH)


def build_index(progress_cb=None):
    """progress_cb(phase: str, processed: int, total: int), chamado
    periodicamente — opcional. Constrói num arquivo temporário e só substitui
    o índice final no fim (build interrompida não deixa um índice corrompido
    pra trás). Serializado por _build_lock — 2 chamadas concorrentes esperam
    a 1ª terminar e a 2ª aproveita o índice recém-criado em vez de reconstruir."""
    with _build_lock:
        if index_exists():
            # outra chamada concorrente já construiu enquanto esperávamos o lock
            return
        _build_index_locked(progress_cb)


def _build_index_locked(progress_cb=None):
    if not dataset_files_available():
        raise RuntimeError(
            f"Dataset do IMDb não encontrado em {IMDB_DATA_DIR} — baixe "
            "title.basics.tsv.gz e title.akas.tsv.gz de datasets.imdbws.com."
        )

    def report(phase, processed, total):
        if progress_cb:
            progress_cb(phase, processed, total)

    # pid no nome evita colisão até com processos concorrentes de outras
    # replicas/reinicios que por algum motivo não peguem o mesmo _build_lock
    tmp_path = f"{INDEX_PATH}.building.{os.getpid()}"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    conn = sqlite3.connect(tmp_path)
    try:
        # trade-offs seguros pra um índice que é só cache reconstruível —
        # não precisa da durabilidade normal do SQLite (WAL/fsync)
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA journal_mode=MEMORY")
        conn.execute("PRAGMA temp_store=MEMORY")

        conn.execute("CREATE TABLE br_titles (tconst TEXT, norm_title TEXT)")
        conn.execute("CREATE TABLE title_genre (tconst TEXT, ttype_group TEXT, genre TEXT)")
        conn.execute("CREATE TABLE raw_votes (norm_title TEXT, ttype_group TEXT, genre TEXT)")

        # passo 1: title.akas.tsv.gz, só region=='BR' -> (tconst, titulo normalizado)
        report("lendo títulos em português (title.akas)", 0, _AKAS_APPROX_LINES)
        batch = []
        with gzip.open(AKAS_PATH, mode="rt", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
            next(reader, None)
            for i, row in enumerate(reader):
                if i % 500_000 == 0:
                    report("lendo títulos em português (title.akas)", i, _AKAS_APPROX_LINES)
                if len(row) < 4:
                    continue
                tconst, title, region = row[0], row[2], row[3]
                if region != "BR":
                    continue
                batch.append((tconst, _normalize(title)))
                if len(batch) >= 20_000:
                    conn.executemany("INSERT INTO br_titles VALUES (?, ?)", batch)
                    batch.clear()
        if batch:
            conn.executemany("INSERT INTO br_titles VALUES (?, ?)", batch)
        conn.commit()

        # passo 2: title.basics.tsv.gz -> vota titulo original/traduzido direto
        # (sem consultar nada — é so bulk insert, rapido) + guarda o genero por
        # tconst pra juntar com os titulos BR depois via SQL
        report("lendo gêneros (title.basics)", 0, _BASICS_APPROX_LINES)
        genre_batch = []
        vote_batch = []
        with gzip.open(BASICS_PATH, mode="rt", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
            next(reader, None)
            for i, row in enumerate(reader):
                if i % 500_000 == 0:
                    report("lendo gêneros (title.basics)", i, _BASICS_APPROX_LINES)
                if len(row) < 9:
                    continue
                tconst, ttype, primary, original, _adult, _sy, _ey, _rt, genres = row
                if genres == "\\N":
                    continue
                if ttype in MOVIE_TYPES:
                    ttype_group = "movie"
                elif ttype in SERIES_TYPES:
                    ttype_group = "series"
                else:
                    continue

                our_genre = _pick_genre(genres)
                if our_genre is None:
                    continue

                genre_batch.append((tconst, ttype_group, our_genre))
                vote_batch.append((_normalize(primary), ttype_group, our_genre))
                norm_original = _normalize(original)
                if norm_original != _normalize(primary):
                    vote_batch.append((norm_original, ttype_group, our_genre))

                if len(genre_batch) >= 20_000:
                    conn.executemany("INSERT INTO title_genre VALUES (?, ?, ?)", genre_batch)
                    conn.executemany("INSERT INTO raw_votes VALUES (?, ?, ?)", vote_batch)
                    genre_batch.clear()
                    vote_batch.clear()
        if genre_batch:
            conn.executemany("INSERT INTO title_genre VALUES (?, ?, ?)", genre_batch)
            conn.executemany("INSERT INTO raw_votes VALUES (?, ?, ?)", vote_batch)
        conn.commit()

        # passo 3: SQL puro faz o resto — junta titulo BR com genero (via
        # tconst) e agrega tudo em votos por (titulo, tipo, genero). Isso e
        # ORDENS DE MAGNITUDE mais rapido que 12M SELECTs individuais em loop.
        report("cruzando título em português com gênero (SQL)", 0, 1)
        conn.execute("CREATE INDEX idx_br_tconst ON br_titles(tconst)")
        conn.execute("CREATE INDEX idx_tg_tconst ON title_genre(tconst)")
        conn.execute(
            """
            INSERT INTO raw_votes (norm_title, ttype_group, genre)
            SELECT br.norm_title, tg.ttype_group, tg.genre
            FROM br_titles br JOIN title_genre tg ON br.tconst = tg.tconst
            """
        )
        conn.commit()

        report("agregando votos (SQL)", 0, 1)
        conn.execute(
            """
            CREATE TABLE genre_votes AS
            SELECT norm_title, ttype_group, genre, COUNT(*) AS votes
            FROM raw_votes
            WHERE norm_title != ''
            GROUP BY norm_title, ttype_group, genre
            """
        )
        conn.execute("CREATE INDEX idx_votes_lookup ON genre_votes(norm_title, ttype_group)")
        conn.execute("DROP TABLE raw_votes")
        conn.execute("DROP TABLE title_genre")
        conn.execute("DROP TABLE br_titles")
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()

    os.replace(tmp_path, INDEX_PATH)
    report("índice construído", 1, 1)


def lookup_genre(conn: sqlite3.Connection, norm_title: str, ttype_group: str) -> str | None:
    row = conn.execute(
        "SELECT genre FROM genre_votes WHERE norm_title=? AND ttype_group=? ORDER BY votes DESC LIMIT 1",
        (norm_title, ttype_group),
    ).fetchone()
    return row[0] if row else None


def open_index_readonly() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{INDEX_PATH}?mode=ro", uri=True)
