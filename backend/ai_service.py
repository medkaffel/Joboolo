"""IA (Claude Sonnet 4.6 via emergentintegrations) : matching CV/offre + recommandations."""
import os
import re
import json
import uuid
import logging

from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")
PROVIDER = "anthropic"
MODEL = "claude-sonnet-4-6"


def _new_chat(system_message: str) -> LlmChat:
    return LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"joboolo-{uuid.uuid4()}",
        system_message=system_message,
    ).with_model(PROVIDER, MODEL)


def _extract_json(text: str):
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                continue
    return None


async def _ask(system: str, prompt: str) -> str:
    if not EMERGENT_LLM_KEY:
        raise RuntimeError("EMERGENT_LLM_KEY manquante")
    chat = _new_chat(system)
    resp = await chat.send_message(UserMessage(text=prompt))
    if isinstance(resp, str):
        return resp
    return getattr(resp, "content", None) or str(resp)


def build_profile(user: dict, applications=None) -> dict:
    """Construit un profil candidat structuré depuis le document user (CV/profil)."""
    return {
        "prenom": user.get("first_name", ""),
        "competences": user.get("skills", []) or [],
        "bio": (user.get("bio") or "")[:1500],
        "annees_experience": user.get("experience_years"),
        "localisation": user.get("location") or "",
        "candidatures_recentes": applications or [],
    }


def _verdict_from_score(score: int) -> str:
    if score >= 80:
        return "Excellent match"
    if score >= 60:
        return "Bon match"
    if score >= 40:
        return "Match moyen"
    return "Match faible"


async def analyze_match(profile: dict, job: dict) -> dict:
    """Score de correspondance profil/CV <-> offre, avec explication."""
    system = (
        "Tu es un expert RH français. Tu évalues objectivement l'adéquation entre le profil "
        "d'un candidat (CV) et une offre d'emploi. Réponds STRICTEMENT en JSON valide, sans aucun texte autour."
    )
    prompt = f"""PROFIL du candidat (JSON):
{json.dumps(profile, ensure_ascii=False)}

OFFRE d'emploi (JSON):
{json.dumps(job, ensure_ascii=False)}

Analyse l'adéquation et renvoie un JSON avec EXACTEMENT ces clés:
{{
  "score": <entier 0-100 de compatibilité globale>,
  "verdict": "<Excellent match | Bon match | Match moyen | Match faible>",
  "summary": "<2 à 3 phrases en français expliquant le score>",
  "strengths": ["<point fort concret>", "..."],
  "gaps": ["<compétence/expérience manquante ou à renforcer>", "..."]
}}
Sois honnête, concret et concis. Base-toi sur les compétences, l'expérience, la localisation et la description."""
    text = await _ask(system, prompt)
    data = _extract_json(text) or {}
    try:
        score = max(0, min(100, int(round(float(data.get("score", 0))))))
    except (TypeError, ValueError):
        score = 0
    strengths = data.get("strengths") or []
    gaps = data.get("gaps") or []
    return {
        "score": score,
        "verdict": data.get("verdict") or _verdict_from_score(score),
        "summary": data.get("summary") or "Analyse indisponible pour le moment.",
        "strengths": strengths if isinstance(strengths, list) else [str(strengths)],
        "gaps": gaps if isinstance(gaps, list) else [str(gaps)],
    }


async def rank_jobs(profile: dict, jobs: list) -> list:
    """Classe une liste d'offres par pertinence pour le candidat (1 seul appel LLM)."""
    system = (
        "Tu es un moteur de recommandation d'emploi français. Tu classes des offres par pertinence "
        "pour un candidat donné. Réponds STRICTEMENT en JSON valide, sans aucun texte autour."
    )
    slim = [{
        "id": j.get("id"),
        "titre": j.get("title", ""),
        "localisation": j.get("location", ""),
        "type": j.get("job_type", ""),
        "competences_requises": (j.get("requirements", []) or [])[:8],
        "description": (j.get("description", "") or "")[:400],
    } for j in jobs]
    prompt = f"""PROFIL candidat (JSON):
{json.dumps(profile, ensure_ascii=False)}

OFFRES disponibles (JSON):
{json.dumps(slim, ensure_ascii=False)}

Classe les offres de la plus pertinente à la moins pertinente pour ce candidat.
Renvoie un JSON: {{"recommendations":[{{"id":"<id de l'offre>","score":<0-100>,"reason":"<1 phrase en français>"}}]}}
N'inclus que les offres avec un score >= 40. Maximum 10 offres, triées par score décroissant."""
    text = await _ask(system, prompt)
    data = _extract_json(text) or {}
    recs = data.get("recommendations") if isinstance(data, dict) else data
    if not isinstance(recs, list):
        recs = []
    out = []
    for r in recs:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        try:
            score = max(0, min(100, int(round(float(r.get("score", 0))))))
        except (TypeError, ValueError):
            score = 0
        out.append({"id": r["id"], "score": score, "reason": r.get("reason", "")})
    return out
