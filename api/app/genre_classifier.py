"""Classificação automática de gênero por palavra-chave no título — usada pelo
botão "Classificar gêneros" no dashboard. As palavras (EN+PT) ficam na tabela
`genre_keywords`, editáveis em /genres.html; a ordem de prioridade é pelo `id`
mais antigo de cada gênero (o gênero cujo primeiro registro é mais antigo é
checado primeiro — favorece gêneros mais específicos sobre os mais genéricos,
desde que a lista padrão seja semeada nessa ordem).

Isso NUNCA sobrescreve um gênero já preenchido — só age em títulos com
`genre IS NULL`. Limite conhecido: título sem nenhuma palavra-chave (ex: nomes
próprios) continua sem classificar — só um fallback contra uma base externa
(TMDB) resolveria isso de fato."""

import re
import threading
import unicodedata
import uuid
from datetime import datetime, timezone

from sqlalchemy import func

from .db import SessionLocal
from .job_registry import is_cancelled, register
from .models import GenreKeyword, VodTitle

# ordem de prioridade da semente padrão: gêneros mais específicos primeiro,
# os mais genéricos (Ação, Drama) por último — evita que "guerra"/"soldado"
# vire Ação quando devia ser Guerra, por exemplo
DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "Documentário": [
        "documentary", "docuseries", "true story footage", "real footage", "nature documentary",
        "biopic documentary", "documentário", "história real filmada", "natureza selvagem", "vida real", "bastidores",
    ],
    "Biografia": [
        "biography", "biopic", "based on true story", "based on real events", "life story of",
        "biografia", "baseado em fatos reais", "história de vida", "a vida real de",
    ],
    # Anime vem ANTES de Animação na ordem de prioridade — quando o título tem
    # sinal claro de anime japonês, ganha "Anime"; senão cai em "Animação"
    "Anime": [
        "anime", "mangá", "manga", "otaku", "shounen", "shonen", "shoujo", "shojo",
        "seinen", "isekai", "mecha", "studio ghibli", "toei animation", "crunchyroll",
        "naruto", "one piece", "dragon ball", "bleach", "boruto", "demon slayer",
        "kimetsu", "jujutsu kaisen", "attack on titan", "shingeki", "pokémon", "pokemon",
        "digimon", "yu-gi-oh", "sailor moon", "cavaleiros do zodíaco", "saint seiya",
        "hunter x hunter", "my hero academia", "boku no hero", "death note",
        "fullmetal alchemist", "evangelion", "gundam", "one punch man", "chainsaw man",
        "spy x family", "tokyo revengers", "haikyuu", "black clover", "fairy tail",
        "dublado anime", "anime legendado",
    ],
    "Animação": [
        "animation", "animated", "cartoon", "pixar", "dreamworks", "illumination",
        "stop motion", "claymation", "desenho animado", "animação", "desenhos", "infantil animado", "longa animado",
    ],
    "Musical": [
        "musical", "singer", "singing", "concert", "musician", "song and dance", "broadway", "rock band",
        "música ao vivo", "banda", "show musical", "cantor", "cantora",
    ],
    "Dança": [
        "dance", "dancer", "ballet", "choreography", "dance competition",
        "dançarino", "dançarina", "balé", "coreografia", "competição de dança", "dança de salão",
    ],
    "Western": [
        "western", "cowboy", "wild west", "gunslinger", "saloon", "outlaw", "frontier town",
        "velho oeste", "pistoleiro", "xerife", "cidade fronteiriça", "forasteiro", "duelo",
    ],
    "Guerra": [
        "war film", "world war", "battlefield", "invasion", "occupation", "trench warfare",
        "resistance fighters", "prisoner of war", "guerra", "invasão", "trincheira", "resistência",
        "prisioneiro de guerra", "soldado", "batalha final", "front de guerra", "filme de guerra",
    ],
    "Época": [
        "period drama", "victorian era", "renaissance", "19th century", "belle époque",
        "século xix", "era vitoriana", "antigamente", "outra época",
    ],
    "Apocalipse": [
        "apocalypse", "doomsday", "extinction event", "pandemic outbreak", "post-apocalyptic", "nuclear fallout",
        "fim do mundo", "pandemia", "pós-apocalíptico", "catástrofe nuclear", "extinção", "apocalipse zumbi",
    ],
    "Sobrenatural": [
        "supernatural power", "psychic", "medium", "clairvoyant", "telekinesis", "aura reading",
        "poder sobrenatural", "vidente", "telecinese", "premonição", "dom especial",
    ],
    "Ficção científica": [
        "sci-fi", "science fiction", "alien", "extraterrestrial", "android", "cyborg", "robot uprising",
        "spaceship", "dystopia", "time travel", "parallel universe", "artificial intelligence", "cloning",
        "alienígena", "androide", "nave espacial", "distopia", "viagem no tempo", "universo paralelo",
        "inteligência artificial", "clone", "robô", "extraterrestre", "invasão alienígena",
    ],
    "Fantasia": [
        "fantasy", "wizard", "dragon", "elf", "enchanted", "mythical creature", "spell", "sorcerer",
        "kingdom quest", "magical realm", "mago", "maga", "dragão", "elfo", "encantado", "feitiço",
        "feiticeiro", "feiticeira", "reino mágico", "magia", "criatura mágica", "poderes mágicos", "portal mágico",
    ],
    "Terror": [
        "horror", "haunted", "exorcism", "possession", "vampire", "zombie", "undead", "curse", "nightmare",
        "slasher", "massacre", "haunted house", "demon", "evil spirit", "cult horror", "found footage",
        "terror", "fantasma", "demônio", "possessão", "exorcismo", "vampiro", "zumbi", "maldição", "pesadelo",
        "casa mal-assombrada", "espírito maligno", "assombrado", "criatura", "monstro", "macabro",
    ],
    "Suspense/Thriller": [
        "thriller", "suspense", "psychological thriller", "stalker", "kidnapping", "hostage", "conspiracy",
        "serial killer", "cat and mouse", "whodunit thriller", "perseguição", "sequestro", "refém",
        "conspiração", "jogo psicológico", "armadilha", "traição", "segredo mortal", "jogo mortal", "tensão",
    ],
    "Policial": [
        "detective", "police officer", "cop", "fbi", "cia", "swat", "sheriff", "homicide unit", "undercover",
        "precinct", "manhunt", "delegado", "investigação policial", "esquadrão", "disfarçado",
        "caça ao criminoso", "polícia federal", "detetive", "inspetor",
    ],
    "Crime": [
        "gangster", "mafia", "cartel", "heist", "robbery", "organized crime", "drug trafficking", "smuggling",
        "underworld", "gang war", "máfia", "cartel", "tráfico", "assalto", "roubo", "quadrilha",
        "crime organizado", "contrabando", "gângster", "submundo do crime",
    ],
    "Mistério": [
        "mystery", "disappearance", "missing person", "clue", "whodunit", "cold case", "enigma", "unsolved",
        "segredo", "desaparecimento", "pista", "caso arquivado", "mistério sombrio", "quebra-cabeça",
    ],
    "Esporte": [
        "sports film", "championship", "athlete", "boxing match", "racing team", "underdog story", "olympic",
        "atleta", "luta de boxe", "superação esportiva", "olimpíadas", "campeonato", "corrida", "futebol", "competição",
    ],
    "Família": [
        "family-friendly", "children's film", "kids movie", "parents", "bedtime story", "family adventure",
        "infantil", "crianças", "em família", "filme infantil", "história de ninar", "para toda família", "diversão em família",
    ],
    "Romance": [
        "romance", "romantic", "love story", "lovers", "wedding", "boyfriend", "girlfriend", "couple", "soulmate",
        "first love", "heartbreak", "amor", "apaixonado", "apaixonada", "casamento", "casal", "alma gêmea",
        "paixão", "coração partido", "romance proibido", "primeiro amor", "triângulo amoroso", "reencontro",
        "amor à primeira vista",
    ],
    "Comédia": [
        "comedy", "comedian", "hilarious", "parody", "satire", "spoof", "slapstick", "sitcom", "stand-up",
        "rom-com", "buddy comedy", "comédia", "engraçado", "paródia", "sátira", "comédia romântica", "hilário",
        "comédia de humor negro", "farsa", "gozação",
    ],
    "Aventura": [
        "adventure", "expedition", "quest", "treasure hunt", "explorer", "exploration", "jungle", "voyage",
        "journey", "survival island", "lost world", "aventura", "expedição", "caça ao tesouro", "explorador",
        "exploradora", "selva", "jornada", "mundo perdido", "ilha", "viagem perigosa", "desafio",
        "sobrevivência", "descoberta", "tesouro perdido", "mapa do tesouro",
    ],
    "Ação": [
        "action", "combat", "fighting", "fight", "battle", "warrior", "assassin", "hitman", "mercenary",
        "gunfight", "shootout", "revenge", "raid", "weapon", "explosive", "commando", "agent", "spy",
        "special ops", "ação", "combate", "batalha", "guerreiro", "guerreira", "assassino", "assassina",
        "mercenário", "vingança", "comando", "agente secreto", "espião", "perigo", "mortal", "fúria", "luta",
        "lutador", "lutadora", "atirador", "arma", "explosivo", "resgate", "missão", "inimigo", "confronto",
        "caçada", "implacável",
    ],
    "Drama": [
        "drama", "dramatic", "coming of age", "tragedy", "tearjerker", "melodrama", "tragédia", "drama familiar",
        "superação", "emocionante", "comovente", "drama social", "drama psicológico", "história de vida difícil",
    ],
}


def _normalize(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def seed_default_keywords_if_empty(db) -> int:
    """Só semeia se a tabela estiver vazia — depois disso o usuário é dono dos
    dados (editáveis em /genres.html), não sobrescrevemos nada."""
    existing = db.query(func.count(GenreKeyword.id)).scalar() or 0
    if existing > 0:
        return 0

    count = 0
    for genre, keywords in DEFAULT_KEYWORDS.items():
        for kw in keywords:
            db.add(GenreKeyword(genre=genre, keyword=kw))
            count += 1
    db.commit()
    return count


def sync_new_default_keywords(db) -> int:
    """Insere pares (gênero, palavra) do DEFAULT_KEYWORDS que ainda não existem
    na tabela — pra quando a gente adiciona um gênero novo no código (ex:
    "Anime") sem querer re-semear tudo nem apagar o que o usuário editou.
    Idempotente. Não roda se a tabela estiver vazia (aí o seed cuida)."""
    existing = {
        (g, k)
        for g, k in db.query(GenreKeyword.genre, GenreKeyword.keyword).all()
    }
    if not existing:
        return 0
    added = 0
    for genre, keywords in DEFAULT_KEYWORDS.items():
        for kw in keywords:
            if (genre, kw) not in existing:
                db.add(GenreKeyword(genre=genre, keyword=kw))
                added += 1
    if added:
        db.commit()
    return added


def _load_ordered_patterns(db) -> list[tuple[str, re.Pattern]]:
    """Devolve [(genre, pattern), ...] na ordem de prioridade: a ordem do
    DEFAULT_KEYWORDS (mais específico primeiro) manda pros gêneros conhecidos;
    gêneros criados só pelo usuário vêm depois, na ordem do id mais antigo."""
    rows = db.query(GenreKeyword).order_by(GenreKeyword.id).all()
    by_genre: dict[str, list[str]] = {}
    first_id: dict[str, int] = {}
    for row in rows:
        by_genre.setdefault(row.genre, []).append(row.keyword)
        first_id.setdefault(row.genre, row.id)

    default_order = {g: i for i, g in enumerate(DEFAULT_KEYWORDS)}
    big = len(default_order)
    ordered_genres = sorted(
        by_genre.keys(),
        key=lambda g: (default_order.get(g, big), first_id[g]),
    )
    patterns = []
    for genre in ordered_genres:
        escaped = sorted({re.escape(_normalize(kw)) for kw in by_genre[genre] if kw.strip()}, key=len, reverse=True)
        if not escaped:
            continue
        pattern = re.compile(r"\b(" + "|".join(escaped) + r")\b")
        patterns.append((genre, pattern))
    return patterns


def classify_title(title: str, patterns: list[tuple[str, re.Pattern]]) -> str | None:
    normalized = _normalize(title)
    for genre, pattern in patterns:
        if pattern.search(normalized):
            return genre
    return None


# --- job em background com progresso (mesmo padrão do import_vod.py) ---

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_classify_job() -> str:
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "total": 0,
            "processed": 0,
            "classified": 0,
            "error": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    register("Classificar gêneros (palavra-chave)", job_id, get_classify_job)

    def _worker():
        db = SessionLocal()
        try:
            patterns = _load_ordered_patterns(db)
            titles = db.query(VodTitle).filter(VodTitle.genre.is_(None)).all()
            with _jobs_lock:
                _jobs[job_id]["total"] = len(titles)

            classified = 0
            for i, title in enumerate(titles, start=1):
                genre = classify_title(title.title, patterns)
                if genre:
                    title.genre = genre
                    classified += 1
                if i % 25 == 0:
                    with _jobs_lock:
                        _jobs[job_id]["processed"] = i
                        _jobs[job_id]["classified"] = classified
                    if is_cancelled(job_id):
                        db.commit()
                        with _jobs_lock:
                            _jobs[job_id]["status"] = "cancelled"
                        return

            db.commit()
            with _jobs_lock:
                _jobs[job_id]["processed"] = len(titles)
                _jobs[job_id]["classified"] = classified
                _jobs[job_id]["status"] = "done"
        except Exception as e:
            db.rollback()
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(e)
        finally:
            db.close()

    threading.Thread(target=_worker, daemon=True, name=f"classify-genres-{job_id[:8]}").start()
    return job_id


def get_classify_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None
