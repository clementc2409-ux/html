"""Recherche dans le wiki Minecraft (fr.minecraft.wiki), gratuite : recettes, mécaniques, chiffres exacts.

La recherche Google de Gemini n'est pas incluse dans l'offre gratuite (vérifié le 16/10/2026) : le compagnon
consulte le wiki à la place quand il n'est pas sûr d'une recette ou d'un chiffre.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

AGENT = "CompagnonMinecraft/1.0 (compagnon IA personnel ; lecture seule)"
LONGUEUR_MAX = 4000


def _api(domaine: str, delai: float, **parametres) -> dict:
    parametres.update(format="json", formatversion="2")
    url = f"https://{domaine}/api.php?" + urllib.parse.urlencode(parametres)
    requete = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(requete, timeout=delai) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def nettoyer_wikitexte(texte: str) -> str:
    """Wikitexte -> texte lisible par le modèle (les modèles {{Fabrication|…}} sont gardés : ils
    contiennent les recettes)."""
    texte = re.sub(r"<!--.*?-->", "", texte, flags=re.S)
    texte = re.sub(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", "", texte, flags=re.S | re.I)
    texte = re.sub(r"\[\[(?:Fichier|File|Image|Catégorie|Category|[a-z]{2}(?:-[a-z]+)?):[^\[\]]*"
                   r"(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", "", texte, flags=re.I)
    texte = re.sub(r"\[\[[^|\]]*\|([^\]]*)\]\]", r"\1", texte)
    texte = re.sub(r"\[\[([^\]]*)\]\]", r"\1", texte)
    texte = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", texte)
    texte = re.sub(r"'{2,}", "", texte)
    texte = re.sub(r"<[^>]+>", "", texte)
    texte = re.sub(r"[ \t]+", " ", texte)
    texte = re.sub(r"\n\s*\n+", "\n", texte)
    return texte.strip()


def chercher(sujet: str, domaine: str = "fr.minecraft.wiki", delai: float = 8.0) -> dict:
    """Cherche « sujet » dans le wiki et renvoie le début de la page la plus pertinente."""
    sujet = " ".join(str(sujet or "").split())[:120]
    if not sujet:
        return {"erreur": "sujet vide"}
    try:
        trouve = _api(domaine, delai, action="query", list="search", srsearch=sujet, srlimit="4")
        titres = [r["title"] for r in trouve.get("query", {}).get("search", []) if r.get("title")]
        if not titres:
            return {"resultat": f"aucune page du wiki ne parle de « {sujet} »"}
        page = _api(domaine, delai, action="parse", page=titres[0], prop="wikitext", redirects="1")
        wikitexte = page.get("parse", {}).get("wikitext", "")
        if isinstance(wikitexte, dict):  # ancien format de réponse
            wikitexte = wikitexte.get("*", "")
    except Exception as e:  # réseau, wiki indisponible, réponse inattendue
        return {"erreur": f"wiki inaccessible ({type(e).__name__}) : réponds avec ce que tu sais, en le disant"}
    contenu = nettoyer_wikitexte(wikitexte)
    if len(contenu) > LONGUEUR_MAX:
        contenu = contenu[:LONGUEUR_MAX].rsplit("\n", 1)[0] + "\n[…]"
    return {"page": titres[0], "contenu": contenu, "autres_pages": titres[1:],
            "source": f"https://{domaine}/w/{urllib.parse.quote(titres[0].replace(' ', '_'))}"}
