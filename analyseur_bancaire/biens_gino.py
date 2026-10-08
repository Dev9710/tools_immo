"""Biens relevés par Gino (projet agence-immo) : lecture et financement, bien par bien.

Contrat : tools_immo LIT seulement les `<ville>/_gino_<agence>.json` (et `_stan.json`
pour les noms d'agences). Aucun code partagé avec Gino, projet séparé (futur SaaS).
Tout ce qui dépend de leur format vit ici. Module sans Django : testable seul.

Les `_gino_*.json` contiennent TOUS les biens de l'agence ; les onglets Excel de Gino,
eux, sont déjà filtrés par criteres.json — on ne les lit pas.
"""
import json
import os
import re
import statistics
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

HORS_HABITATION = ("terrain", "parking", "garage", "local", "commerce", "immeuble", "fonds")
STATUTS_MASQUES = ("vendu", "compromis", "erreur", "retire")   # « retire » : fiche supprimée (moteur de vérification)
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


def _nom_ville_stan(dossier):
    """Nom accentué de la ville (« Créteil »), lu dans les adresses de Stan
    (« …, 94000 Créteil ») dont le nom correspond au dossier ; None sinon."""
    try:
        data = json.loads((dossier / "_stan.json").read_text(encoding="utf-8"))
        adresses = [a.get("adresse") or "" for a in data if isinstance(a, dict)]
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    noms = [m.group(1) for m in (re.search(r"\b\d{5}\s+(.+?)\s*$", str(a)) for a in adresses)
            if m and _slug(m.group(1)) == dossier.name]
    return max(set(noms), key=noms.count) if noms else None


def villes(racine):
    """Villes relevées par Gino, ou None si le dossier racine n'existe pas."""
    racine = Path(racine)
    if not racine.is_dir():
        return None
    return [{"slug": d.name, "nom": _nom_ville_stan(d) or _nom_ville(d.name)}
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


JOURS_NOUVEAU = 7


def _date(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def baisse_prix(bien):
    """Baisse du prix actuel par rapport au plus haut prix vu par la veille, ou None."""
    hist = bien.get("historique_prix")
    points = [(str(h.get("date") or ""), nombre(h.get("prix"))) for h in hist
              if isinstance(h, dict)] if isinstance(hist, list) else []
    points = [(d, p) for d, p in points if p]
    actuel = nombre(bien.get("prix"))
    if not points or not actuel:
        return None
    haut = max(p for _, p in points)
    if actuel >= haut:
        return None
    # Date de la baisse : début de la dernière série de relevés au prix actuel.
    depuis = ""
    for d, p in points:
        depuis = (depuis or d) if p == actuel else ""
    return {"avant": haut, "apres": actuel, "pct": round((actuel / haut - 1) * 100, 1),
            "depuis": depuis}


def charger_ville(dossier, aujourdhui=None):
    """Biens d'habitation d'une ville, fichier par fichier ; un fichier illisible est ignoré.
    « nouveau » : apparu après le premier relevé de son agence, il y a JOURS_NOUVEAU jours au plus."""
    dossier = Path(dossier)
    aujourdhui = aujourdhui or date.today()
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
        # Fichier d'une agence sans recette : écrit par Gino et jamais touché depuis, sa date
        # est celle du relevé. Sert à dater les biens jamais revérifiés.
        releve_le = datetime.fromtimestamp(f.stat().st_mtime).date().isoformat()
        agence = _nom_agence(f, noms)
        vus = [d for d in (_date(b.get("vu_depuis")) for b in data if isinstance(b, dict)) if d]
        premier_releve = min(vus) if vus else None
        for b in data:
            if not isinstance(b, dict):
                continue
            url = str(b.get("url") or "").strip()
            # Une url sans schéma http(s) (ex : « javascript:… ») n'est jamais rendue
            # cliquable : le bien est écarté, comme s'il n'avait pas d'url du tout.
            if not url or not url.lower().startswith(("http://", "https://")):
                continue
            a_verifier = [str(x) for x in b.get("a_verifier") or [] if x]
            t = type_habitation(b.get("type"))
            if t is None:
                # Type vide ou inconnu : gardé seulement si le moteur de vérification l'a signalé
                # (« type illisible ») et que rien n'indique un bien hors habitation.
                if not a_verifier or any(m in _sans_accents(b.get("type")) for m in HORS_HABITATION):
                    continue
                t = "Bien"
            if est_masque(b.get("statut")):
                masques += 1
                continue
            dpe = str(b.get("dpe") or "").strip().upper()
            vu = _date(b.get("vu_depuis"))
            biens.append({
                "type": t, "type_source": str(b.get("type") or ""),
                "lieu": str(b.get("lieu") or "").strip(),
                "pieces": entier(b.get("pieces")), "chambres": entier(b.get("chambres")),
                "annee": entier(b.get("annee")),
                "dpe": dpe if dpe in tuple("ABCDEFG") else "",
                "surface": nombre(b.get("surface")), "prix": nombre(b.get("prix")),
                "url": url, "agence": agence,
                "statut": str(b.get("statut") or ""),
                "a_verifier": a_verifier,
                "verifie_le": str(b.get("verifie_le") or ""),
                "jamais_verifie": not b.get("verifie_le"),
                "releve_le": releve_le,
                "nouveau": bool(vu and premier_releve and vu > premier_releve
                                and (aujourdhui - vu).days <= JOURS_NOUVEAU),
                "baisse": baisse_prix(b),
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


# --- Vérification sans IA (veille.py d'agence-immo) : lecture seule de ses fichiers ---

ORDRE_ETAT_VEILLE = {"recette_cassee": 0, "injoignable": 1, "recette_non_validee": 2,
                     "sans_recette": 3, "ok": 4}
LIBELLES_EVENEMENTS = {"nouveau": "nouveau", "vendu": "vendu", "compromis": "sous compromis",
                       "retire": "retiré", "remis_en_vente": "remis en vente",
                       "baisse_prix": "baisse de prix", "hausse_prix": "hausse de prix",
                       "a_verifier": "à vérifier"}


def etat_veille(dossier):
    """État du dernier contrôle (`_veille_etat.json`), ou None s'il n'y en a pas."""
    try:
        data = json.loads((Path(dossier) / "_veille_etat.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _processus_vivant(pid):
    """Vrai si le processus `pid` tourne encore (pid inconnu : on le croit vivant, par prudence).
    Sous Windows, os.kill(pid, 0) TERMINERAIT le processus : on interroge Windows directement.
    (Même règle que lib/veille/ecriture.py d'agence-immo : aucun code partagé entre les projets.)"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return True
    if os.name == "nt":
        import ctypes
        noyau = ctypes.WinDLL("kernel32", use_last_error=True)
        poignee = noyau.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not poignee:
            return ctypes.get_last_error() == 5                 # accès refusé : il existe
        code = ctypes.c_ulong()
        try:
            lu = noyau.GetExitCodeProcess(poignee, ctypes.byref(code))
        finally:
            noyau.CloseHandle(poignee)
        return not lu or code.value == 259                      # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def veille_en_cours(dossier, maintenant=None):
    """Vrai si un contrôle tient le verrou depuis moins de 2 h ET que son processus vit
    encore : un contrôle tué (PC en veille, fenêtre fermée) n'affiche plus « en cours »."""
    try:
        verrou = json.loads((Path(dossier) / "_veille.lock").read_text(encoding="utf-8"))
        debut = float(verrou.get("debut", 0))
    except (OSError, ValueError, AttributeError, TypeError):
        return False
    if (maintenant or time.time()) - debut >= 2 * 3600:
        return False
    return _processus_vivant(verrou.get("pid"))


def agences_veille(dossier):
    """État de chaque agence au dernier contrôle, les problèmes d'abord."""
    etat = etat_veille(dossier) or {}
    noms = _noms_stan(Path(dossier))
    lignes = []
    for slug, a in (etat.get("agences") or {}).items():
        if not isinstance(a, dict):
            continue
        evenements = a.get("evenements") if isinstance(a.get("evenements"), dict) else {}
        lignes.append({"nom": _nom_agence(Path(f"_gino_{slug}.json"), noms),
                       "etat": str(a.get("etat") or ""), "raison": str(a.get("raison") or ""),
                       "verifie_le": str(a.get("verifie_le") or ""), "evenements": evenements,
                       "avertissement": str(a.get("avertissement") or ""),
                       "resume": ", ".join(f"{n} {LIBELLES_EVENEMENTS.get(k, k)}" for k, n in evenements.items())})
    lignes.sort(key=lambda x: (ORDRE_ETAT_VEILLE.get(x["etat"], 9), x["nom"]))
    return lignes
