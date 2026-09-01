"""P0-008 — validation fail-safe des destinations de redirection du tracker.

Le tracker d'alertes (`GET /api/alerts/track/{alert_id}`) ne doit jamais
rediriger vers une origine externe arbitraire (open redirect). Ce module
expose un validateur PUR : il ne lit aucune configuration, ne fait jamais
confiance au `Host` de la requête et n'a aucune dépendance externe.

Invariants :
- Relatif autorisé uniquement s'il commence par UN SEUL `/` (`/`, `/jobs/x`,
  query/fragment permis). Toute forme scheme-relative ou ambiguë est refusée :
  `//`, `///`, backslashes, contrôles, blanc de tête trompeur.
- Absolu autorisé uniquement HTTP(S) avec une origine (scheme + hostname
  normalisé + port effectif 80/443 par défaut) EXACTEMENT égale à celle de
  l'APP_URL canonique : pas de startswith/suffix matching, refus des ports
  différents, faux sous-domaines, point final trompeur, userinfo, schémas
  non HTTP(S), encodages/normalisations de contournement.
- Parsing FAIL-SAFE : tout accès (`urlsplit`, `.hostname`, `.port`, IDNA, ...)
  est entouré de gestion d'erreur ; aucune entrée malformée ne produit
  d'exception ni de `Location` externe.
- Le paramètre est déjà décodé une fois par FastAPI. On inspecte de façon
  récursive et bornée les décodages percent pour détecter `//`, backslash et
  contrôles cachés ; sans convergence dans la borne => refus.
- On ne retourne JAMAIS une version décodée de l'entrée : l'entrée d'origine
  est retournée uniquement si elle est jugée sûre, sinon le fallback `/`.
"""

from urllib.parse import unquote, urlsplit

DEFAULT_DESTINATION = "/"
ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_DECODE_DEPTH = 3
BACKSLASH = "\\"
DEFAULT_HTTP_PORT = 80
DEFAULT_HTTPS_PORT = 443


def _has_control_chars(value: str) -> bool:
    # C0 (0x00-0x1F), DEL (0x7F) et contrôles C1/NEL (0x80-0x9F) : jamais
    # légitimes dans une destination de redirection (injection d'en-tête).
    return any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in value)


def _leading_whitespace(value: str) -> bool:
    return bool(value) and value[0].isspace()


def _starts_netloc(value: str) -> bool:
    """Forme scheme-relative `//...` après blanc de tête (les navigateurs
    trimment le blanc avant de résoudre l'URL)."""
    return value.lstrip().startswith("//")


def _split_safe(value: str):
    """urlsplit fail-safe : renvoie None (au lieu de lever) si mal formé."""
    try:
        return urlsplit(value)
    except ValueError:
        return None


def _decoded_variants(value: str):
    """Suite bornée des décodages percent successifs de `value`.

    Retourne la liste (jamais vide) des variantes si la normalisation converge
    dans la borne MAX_DECODE_DEPTH, sinon None (refus).
    """
    variants = [value]
    current = value
    for _ in range(MAX_DECODE_DEPTH):
        next_value = unquote(current)
        if next_value == current:
            return variants
        variants.append(next_value)
        current = next_value
    return None


def _origin(url: str):
    """Origine structurée d'une URL absolue HTTP(S), ou None si invalide.

    Normalisation : schéma en minuscules, hostname en minuscules sans point
    final, port effectif (80 pour http, 443 pour https si absent).
    Refuse userinfo et tout hôte/port mal formé.
    """
    parts = _split_safe(url)
    if parts is None:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        return None
    try:
        if parts.username is not None or parts.password is not None:
            return None
        hostname = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except (ValueError, IndexError):
        return None
    if not hostname:
        return None
    if port is None:
        port = DEFAULT_HTTPS_PORT if scheme == "https" else DEFAULT_HTTP_PORT
    return (scheme, hostname, port)


def safe_redirect(target, app_url: str) -> str:
    """Retourne `target` s'il est jugé sûr, sinon le fallback sûr '/'."""
    if not isinstance(target, str):
        return DEFAULT_DESTINATION
    if target == "":
        return DEFAULT_DESTINATION
    if _has_control_chars(target) or _leading_whitespace(target) or BACKSLASH in target:
        return DEFAULT_DESTINATION

    variants = _decoded_variants(target)
    if variants is None:
        return DEFAULT_DESTINATION

    for variant in variants:
        if _has_control_chars(variant) or BACKSLASH in variant or _starts_netloc(variant):
            return DEFAULT_DESTINATION

    parts = _split_safe(target)
    if parts is None:
        return DEFAULT_DESTINATION

    if not parts.scheme:
        # Relatif : autorisé uniquement s'il commence par un seul '/'.
        if not target.startswith("/"):
            return DEFAULT_DESTINATION
        if parts.netloc:
            return DEFAULT_DESTINATION
        return target

    origin = _origin(target)
    allowed = _origin(app_url)
    if origin is None or allowed is None:
        return DEFAULT_DESTINATION
    if origin == allowed:
        return target
    return DEFAULT_DESTINATION