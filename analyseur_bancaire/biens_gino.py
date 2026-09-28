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
from dataclasses import dataclass
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
    s = str(v).replace("\N{NARROW NO-BREAK SPACE}", " ").replace("\N{NO-BREAK SPACE}", " ")
    s = re.sub(r"(?<=\d)[ .](?=\d{3}\b)", "", s)      # séparateurs de milliers
    m = re.search(r"\d+(?:[.,]\d+)?", s)
    return float(m.group().replace(",", ".")) if m else None


def entier(v):
    n = nombre(v)
    return int(n) if n is not None else None


def _sans_accents(s):
    s = unicodedata.normalize("NFKD", str(s if s is not None else "").lower())
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
            if not isinstance(b, dict):
                continue
            url = str(b.get("url") or "").strip()
            # Une url sans schéma http(s) (ex : « javascript:… ») n'est jamais rendue
            # cliquable : le bien est écarté, comme s'il n'avait pas d'url du tout.
            if not url or not url.lower().startswith(("http://", "https://")):
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
                "url": url, "agence": agence,
                "statut": str(b.get("statut") or ""),
            })
    return {"biens": biens, "ignores": ignores, "masques": masques,
            "date_releve": datetime.fromtimestamp(max(dates)).date() if dates else None}


def meme_bien(a, b):
    """Même bien confié à deux agences : type, ville, prix à 1 %, surface à 1 m²."""
    if a["type"] != b["type"] or a["lieu"].lower() != b["lieu"].lower():
        return False
    if not (a["prix"] and b["prix"]) or abs(a["prix"] - b["prix"]) > 0.01 * max(a["prix"], b["prix"]):
        return False
    if a["surface"] is None or b["surface"] is None:
        return False
    return abs(a["surface"] - b["surface"]) <= 1.0


def regrouper_doublons(biens):
    groupes = []
    for b in biens:
        for g in groupes:
            if b["agence"] not in g["agences"] and meme_bien(g, b):
                g["agences"].append(b["agence"])
                g["annonces"].append({"agence": b["agence"], "url": b["url"]})
                for k in ("annee", "dpe", "pieces", "chambres"):
                    if g[k] in (None, "") and b[k] not in (None, ""):
                        g[k] = b[k]
                break
        else:
            groupes.append({**b, "agences": [b["agence"]],
                            "annonces": [{"agence": b["agence"], "url": b["url"]}]})
    return groupes


def mediane_prix_m2(biens):
    vals = [b["prix"] / b["surface"] for b in biens if b["prix"] and b["surface"]]
    return statistics.median(vals) if vals else None


SEUIL_FINANCABLE = 35.0     # règle HCSF, assurance comprise
SEUIL_LIMITE = 40.0         # au-delà, même une dérogation est improbable
ANNEE_NEUF = 2025
MOTS_NEUF = ("neuf", "vefa", "livraison")
ORDRE_VERDICT = {"financable": 0, "limite": 1, "hors_budget": 2, None: 3}


@dataclass
class Profil:
    revenus: float = 0.0
    charges: float = 0.0
    apport: float = 0.0
    duree: int = 20
    taux_nominal: float = 0.0
    taux_assurance: float = 0.0
    primo: bool = False
    nb_adultes: int = 2
    nb_enfants: int = 0


def est_neuf(bien):
    if bien.get("annee") and bien["annee"] >= ANNEE_NEUF:
        return True
    return any(m in _sans_accents(bien.get("type_source", "")) for m in MOTS_NEUF)


def verdict(endettement, statut_reste_a_vivre="OK"):
    if statut_reste_a_vivre == "danger" or endettement > SEUIL_LIMITE:
        return "hors_budget"
    if endettement > SEUIL_FINANCABLE:
        return "limite"
    return "financable"


def _cle_notaire(neuf, profil):
    return "neuf" if neuf else ("ancien_primo" if profil.primo else "ancien")


def evaluer(bien, profil, mediane, sim):
    r = dict(bien)
    r["neuf"] = est_neuf(bien)
    r["alerte_dpe"] = bien["dpe"] in ("F", "G")
    r["ecart_m2"] = (round(bien["prix"] / bien["surface"] / mediane - 1, 3)
                     if bien["prix"] and bien["surface"] and mediane else None)
    r.update(frais_notaire=None, emprunt=None, mensualite=None, endettement=None, verdict=None)
    if not bien["prix"] or profil.revenus <= 0:
        return r
    frais = sim.calculer_frais_notaire(bien["prix"], _cle_notaire(r["neuf"], profil))
    emprunt = max(0.0, bien["prix"] + frais - profil.apport)
    mens = (sim.calculer_mensualites(emprunt, profil.duree, profil.taux_nominal,
                                     profil.taux_assurance)["mensualite"] if emprunt > 0 else 0.0)
    endettement = round((profil.charges + mens) / profil.revenus * 100, 1)
    rav = sim.calculer_reste_a_vivre(profil.revenus, profil.charges + mens,
                                     profil.nb_adultes, profil.nb_enfants)
    r.update(frais_notaire=frais, emprunt=round(emprunt, 2), mensualite=mens,
             endettement=endettement, verdict=verdict(endettement, rav["statut"]))
    return r


def prix_max_financable(profil, sim):
    """Prix d'un bien ancien au-delà duquel l'endettement dépasserait 35 %."""
    if profil.revenus <= 0:
        return None
    mens_max = max(0.0, profil.revenus * SEUIL_FINANCABLE / 100 - profil.charges)
    n = profil.duree * 12
    t = (profil.taux_nominal + profil.taux_assurance) / 100 / 12
    emprunt = mens_max * n if t == 0 else mens_max * (1 - (1 + t) ** -n) / t
    taux_notaire = sim.calculer_frais_notaire(1_000_000.0, _cle_notaire(False, profil)) / 1_000_000.0
    return round((emprunt + profil.apport) / (1 + taux_notaire), -2)


def analyser_ville(dossier, profil, sim):
    lu = charger_ville(dossier)
    biens = regrouper_doublons(lu["biens"])
    mediane = mediane_prix_m2(biens)
    ev = [evaluer(b, profil, mediane, sim) for b in biens]
    ev.sort(key=lambda b: (ORDRE_VERDICT[b["verdict"]],
                           b["ecart_m2"] if b["ecart_m2"] is not None else 9.0,
                           b["prix"] or 0))
    resume = {k: sum(1 for b in ev if b["verdict"] == k)
              for k in ("financable", "limite", "hors_budget")}
    resume.update(total=len(ev), prix_max=prix_max_financable(profil, sim))
    return {"biens": ev, "resume": resume, "ignores": lu["ignores"], "masques": lu["masques"],
            "date_releve": lu["date_releve"], "mediane": mediane}
