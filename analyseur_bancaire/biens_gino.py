"""Biens relevés par Gino (projet agence-immo) : lecture et financement, bien par bien.

Contrat : tools_immo LIT seulement les `<ville>/_gino_<agence>.json` (et `_stan.json`
pour les noms d'agences). Aucun code partagé avec Gino, projet séparé (futur SaaS).
Tout ce qui dépend de leur format vit ici. Module sans Django : testable seul.

Les `_gino_*.json` contiennent TOUS les biens de l'agence ; les onglets Excel de Gino,
eux, sont déjà filtrés par criteres.json — on ne les lit pas.
"""
import json
import re
import statistics
import unicodedata
from datetime import datetime
from pathlib import Path

HORS_HABITATION = ("terrain", "parking", "garage", "local", "commerce", "immeuble", "fonds")
STATUTS_MASQUES = ("vendu", "compromis", "erreur")   # « Fiche annonce en erreur » = annonce morte
PETITS_MOTS = ("sur", "sous", "les", "le", "la", "de", "du", "des", "en")


def nombre(v):
    """'254 000 €' → 254000.0 ; '104,23 m²' → 104.23 ; 'Entre 222 m² et 245 m²' → 222.0."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(" ", " ").replace("\xa0", " ")
    s = re.sub(r"(?<=\d)[ .](?=\d{3}\b)", "", s)      # séparateurs de milliers
    m = re.search(r"\d+(?:[.,]\d+)?", s)
    return float(m.group().replace(",", ".")) if m else None


def entier(v):
    n = nombre(v)
    return int(n) if n is not None else None


def _sans_accents(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", _sans_accents(s)).strip("-")


def type_habitation(t):
    """Range un type de Gino en « Appartement » ou « Maison » ; None hors habitation."""
    s = _sans_accents(t)
    if not s or any(m in s for m in HORS_HABITATION):
        return None
    if any(m in s for m in ("maison", "villa", "propriete")):
        return "Maison"
    if any(m in s for m in ("appartement", "studio", "duplex", "loft")):
        return "Appartement"
    return None


def est_masque(statut):
    s = _sans_accents(str(statut or ""))
    return any(m in s for m in STATUTS_MASQUES)


def _nom_ville(slug):
    mots = slug.split("-")
    return "-".join(m if (i and m in PETITS_MOTS) else m.capitalize() for i, m in enumerate(mots))


def villes(racine):
    """Villes relevées par Gino, ou None si le dossier racine n'existe pas."""
    racine = Path(racine)
    if not racine.is_dir():
        return None
    return [{"slug": d.name, "nom": _nom_ville(d.name)}
            for d in sorted(p for p in racine.iterdir() if p.is_dir())
            if any(d.glob("_gino_*.json"))]


def _noms_stan(dossier):
    try:
        data = json.loads((dossier / "_stan.json").read_text(encoding="utf-8"))
        return [a.get("nom", "") for a in data if isinstance(a, dict)]
    except (OSError, ValueError, TypeError):
        return []


def _nom_agence(fichier, noms):
    slug = fichier.stem[len("_gino_"):]
    for n in noms:
        if n and (_slug(n) == slug or _slug(n).startswith(slug)):
            return n
    return " ".join(m.capitalize() for m in slug.split("-"))


def charger_ville(dossier):
    """Biens d'habitation d'une ville, fichier par fichier ; un fichier illisible est ignoré."""
    dossier = Path(dossier)
    noms = _noms_stan(dossier)
    biens, ignores, masques, dates = [], [], 0, []
    for f in sorted(dossier.glob("_gino_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("liste attendue")
        except (OSError, ValueError):
            ignores.append(f.name)
            continue
        dates.append(f.stat().st_mtime)
        agence = _nom_agence(f, noms)
        for b in data:
            if not isinstance(b, dict) or not b.get("url"):
                continue
            t = type_habitation(b.get("type"))
            if t is None:
                continue
            if est_masque(b.get("statut")):
                masques += 1
                continue
            dpe = str(b.get("dpe") or "").strip().upper()
            biens.append({
                "type": t, "type_source": str(b.get("type") or ""),
                "lieu": str(b.get("lieu") or "").strip(),
                "pieces": entier(b.get("pieces")), "chambres": entier(b.get("chambres")),
                "annee": entier(b.get("annee")),
                "dpe": dpe if dpe in tuple("ABCDEFG") else "",
                "surface": nombre(b.get("surface")), "prix": nombre(b.get("prix")),
                "url": str(b["url"]).strip(), "agence": agence,
                "statut": str(b.get("statut") or ""),
            })
    return {"biens": biens, "ignores": ignores, "masques": masques,
            "date_releve": datetime.fromtimestamp(max(dates)).date() if dates else None}
