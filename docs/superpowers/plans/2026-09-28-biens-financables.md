# Biens finançables — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** une page de tools_immo qui lit les biens relevés par Gino pour une ville et dit, bien par bien, ce qu'il coûterait par mois et s'il est finançable.

**Architecture:** un module sans Django, `analyseur_bancaire/biens_gino.py`, porte tout ce qui dépend du format de Gino (lecture, normalisation, doublons, médiane) et le calcul par bien (en recevant le `SimulateurPretImmobilier` existant). Une vue Django `biens_financables` assemble le profil (session du simulateur, saisie, ou défauts) et rend un gabarit Bootstrap 5 ; filtres et tri en JavaScript léger, côté navigateur.

**Tech Stack:** Python 3.12, Django 4.2.7 (sans base de données, sessions en cookies signés), Bootstrap 5.1.3 + Bootstrap Icons 1.7.2 (déjà chargés par `base.html`).

**Spec:** `docs/superpowers/specs/2026-09-28-biens-financables-design.md`

## Global Constraints

- Aucun code partagé avec Gino : tools_immo **lit seulement** `<ville>/_gino_*.json` (et `_stan.json` pour les noms d'agences). Jamais les onglets Excel (déjà filtrés).
- `criteres.json` n'est **pas** utilisé. Tous les biens d'habitation s'affichent ; **filtres vides à l'ouverture** ; le verdict fait la distinction.
- Verdict : endettement ≤ 35 % → `financable` ; 35 % < e ≤ 40 % → `limite` ; > 40 % ou reste à vivre `danger` → `hors_budget` ; sans prix ou sans revenus → `None`.
- Frais de notaire : `ancien` 0.08 ; `ancien_primo` 0.075 ; `neuf` 0.03.
- Neuf si `annee` ≥ 2025 ou si le type contient « neuf », « vefa » ou « livraison » (les JSON de Gino n'ont pas de titre).
- Doublons : même type normalisé, même ville (casse ignorée), prix à 1 % près, surface à 1 m² près, **agences différentes**.
- Masqués (et comptés) : statut contenant « vendu », « compromis » ou « erreur » (annonce morte). « Sous offre » reste affiché.
- Hors habitation exclus : terrain, parking, garage, local, commerce, immeuble, fonds.
- Rien n'est écrit sur disque ; aucun modèle ; `models.py` reste vide.
- Textes affichés : puces, phrases simples, peu de texte ; l'utilisateur est guidé (chaque état dit quoi faire).
- Icônes Bootstrap Icons uniquement, pas d'émojis ; verdict = couleur **+ icône + mot**.
- Commandes : `venv/Scripts/python.exe manage.py test analyseur_bancaire -v 2` (depuis `tools_immo/`).
- Commits au nom de l'utilisateur, **sans** ligne Co-Authored-By ; **ne jamais pousser** sans demande.

## Review Focus

- **Nombres au format variable** (« 104.85 m² », « 104,23 m² », « 254 000 € » avec espaces insécables, pièces « 5 » ou 5) : même valeur lue → testé en tâche 2.
- **Surface en fourchette** (« Entre 222 m² et 245 m² ») : borne basse, pas de plantage → tâche 2.
- **Dossier Gino absent ou ville inconnue passée dans l'URL** (`?ville=../../etc`) : message guidé, aucune lecture hors du dossier racine → tâche 5.
- **Revenus à 0 ou profil jamais rempli** : liste affichée sans verdict, invitation à compléter → tâches 4 et 5.
- **Apport supérieur au prix + frais** : emprunt 0, mensualité 0, verdict financable (pas de division par zéro ni de montant négatif) → tâche 4.

---

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `analyseur_bancaire/views.py` (modifié) | barèmes sept. 2026, `FRAIS_NOTAIRE['ancien_primo']`, simulateur qui mémorise taux/assurance/foyer/primo, nouvelle vue `biens_financables` |
| `analyseur_bancaire/biens_gino.py` (créé) | lecture Gino, normalisation, doublons, médiane, financement par bien — **sans Django** |
| `analyseur_bancaire/tests.py` (remplacé) | tests du simulateur et des barèmes |
| `analyseur_bancaire/test_biens_gino.py` (créé) | tests du module |
| `analyseur_bancaire/test_vue_biens.py` (créé) | tests de la page |
| `analyseur_bancaire/urls.py` (modifié) | route `biens-financables/` |
| `tools_immo/settings.py` (modifié) | `AGENCE_IMMO_DIR` |
| `templates/analyseur/biens_financables.html` (créé) | la page |
| `templates/analyseur/simulateur_pret.html` (modifié) | case primo-accédant |
| `templates/analyseur/base.html` (modifié) | lien de navigation |
| `CLAUDE.md` (modifié) | documentation |

---

### Task 1: Barèmes septembre 2026 et simulateur qui mémorise tout le profil

**Files:**
- Modify: `analyseur_bancaire/views.py` (constantes en tête ; `simulateur_pret`)
- Modify: `templates/analyseur/simulateur_pret.html` (après le select `type_bien`)
- Replace: `analyseur_bancaire/tests.py`

**Interfaces:**
- Produces: `TAUX_ACTUELS` (même structure, valeurs 2026), `FRAIS_NOTAIRE = {'ancien': 0.08, 'ancien_primo': 0.075, 'neuf': 0.03}` ; clés de session ajoutées par le simulateur : `taux_nominal`, `taux_assurance`, `nb_adultes`, `nb_enfants`, `primo_accedant` ; le simulateur **supprime** `profil_biens` de la session (une nouvelle simulation fait foi).

- [ ] **Step 1: Write the failing tests** — remplacer tout `analyseur_bancaire/tests.py` par :

```python
import json

from django.test import SimpleTestCase
from django.urls import reverse

from .views import FRAIS_NOTAIRE, TAUX_ACTUELS, SimulateurPretImmobilier


class BaremesTests(SimpleTestCase):
    def test_taux_septembre_2026(self):
        self.assertEqual(TAUX_ACTUELS['regions']['autre']['20'], 3.41)
        self.assertEqual(TAUX_ACTUELS['regions']['ile_de_france']['20'], 3.33)
        self.assertEqual(TAUX_ACTUELS['regions']['ile_de_france']['25'], 3.42)
        self.assertEqual(TAUX_ACTUELS['assurance']['30_45'], 0.20)

    def test_frais_de_notaire(self):
        s = SimulateurPretImmobilier()
        self.assertEqual(s.calculer_frais_notaire(200000, 'ancien'), 16000.0)
        self.assertEqual(s.calculer_frais_notaire(200000, 'ancien_primo'), 15000.0)
        self.assertEqual(s.calculer_frais_notaire(200000, 'neuf'), 6000.0)

    def test_mensualite_valeur_de_controle_officielle(self):
        # Calculateur La finance pour tous (Service-Public) : taux « tout compris »,
        # méthode proportionnelle. 200 000 € · 20 ans · 3,53 % → ≈ 1 163 €.
        r = SimulateurPretImmobilier().calculer_mensualites(200000, 20, 3.33, 0.20)
        self.assertAlmostEqual(r['mensualite'], 1163.0, delta=1)


class SimulateurSessionTests(SimpleTestCase):
    def _simuler(self, **extra):
        data = {'mode': 'capacite', 'revenus_nets': '4000', 'charges_mensuelles': '300',
                'duree': '20', 'region': 'ile_de_france', 'profil': 'moyen', 'age': '35',
                'nb_adultes': '2', 'nb_enfants': '1', 'apport': '20000', 'type_bien': 'ancien'}
        data.update(extra)
        return self.client.post(reverse('simulateur_pret'), json.dumps(data),
                                content_type='application/json')

    def test_memorise_taux_foyer_et_primo(self):
        self.assertTrue(self._simuler(primo_accedant='on').json()['success'])
        s = self.client.session
        self.assertEqual(s['taux_nominal'], 3.33)
        self.assertEqual(s['taux_assurance'], 0.20)
        self.assertEqual(s['nb_enfants'], 1)
        self.assertIs(s['primo_accedant'], True)

    def test_primo_baisse_les_frais_de_notaire(self):
        sans = self._simuler().json()['data']['frais_notaire']
        avec = self._simuler(primo_accedant='on').json()['data']['frais_notaire']
        self.assertLess(avec, sans)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/Scripts/python.exe manage.py test analyseur_bancaire -v 2`
Expected: FAIL (taux 2025 ; `KeyError: 'ancien_primo'` ; clé de session `taux_nominal` absente).

- [ ] **Step 3: Implement** — dans `views.py`, remplacer `TAUX_ACTUELS` et `FRAIS_NOTAIRE` par :

```python
# Taux nominaux hors assurance, profil « moyen » — septembre 2026.
# Moyenne Meilleurtaux (01/09/2026 : 3,28 / 3,40 / 3,50 sur 15/20/25 ans) et Pretto
# (20/09/2026, taux obtenus : 3,35 / 3,41 / 3,50). Écarts régionaux conservés
# (IDF −0,08 ; Provence −0,03 ; Rhône-Alpes −0,06 par rapport au national).
TAUX_ACTUELS = {
    'regions': {
        'ile_de_france': {'7': 3.17, '10': 3.22, '15': 3.24, '20': 3.33, '25': 3.42},
        'provence': {'7': 3.22, '10': 3.27, '15': 3.29, '20': 3.38, '25': 3.47},
        'rhone_alpes': {'7': 3.19, '10': 3.24, '15': 3.26, '20': 3.35, '25': 3.44},
        'autre': {'7': 3.25, '10': 3.30, '15': 3.32, '20': 3.41, '25': 3.50}
    },
    'profils': {
        'excellent': -0.30,    # CDI, >10% apport, épargne
        'bon': -0.15,          # CDI, 10% apport
        'moyen': 0.00,         # CDD, apport minimal
        'risque': 0.25         # Profil difficile
    },
    # Assurance emprunteur en délégation, non-fumeur (barèmes 2026).
    'assurance': {
        'moins_30': 0.10,
        '30_45': 0.20,
        '45_plus': 0.40
    }
}

# Frais de notaire 2026. Toute l'Île-de-France a relevé les droits de mutation à
# 5 % au 01/01/2026 (Val-de-Marne : 6,32 % de DMTO) → ~8 % dans l'ancien. Les
# primo-accédants sont exonérés de la hausse → ~7,5 %.
FRAIS_NOTAIRE = {
    'ancien': 0.08,
    'ancien_primo': 0.075,
    'neuf': 0.03
}
```

Dans `simulateur_pret`, branche `mode == 'capacite'` : remplacer le calcul de `taux_notaire` par

```python
                apport = float(data.get('apport', 0))
                type_bien = data.get('type_bien', 'ancien')
                primo = data.get('primo_accedant') in ('on', 'true', '1', True)
                cle_notaire = 'ancien_primo' if (primo and type_bien == 'ancien') else type_bien
                taux_notaire = FRAIS_NOTAIRE.get(cle_notaire, FRAIS_NOTAIRE['ancien'])
```

remplacer `frais_notaire = simulateur.calculer_frais_notaire(prix_max, type_bien)` par
`frais_notaire = simulateur.calculer_frais_notaire(prix_max, cle_notaire)`, et compléter la sauvegarde en session :

```python
                request.session['taux_nominal'] = resultat['taux_nominal']
                request.session['taux_assurance'] = resultat['taux_assurance']
                request.session['nb_adultes'] = nb_adultes
                request.session['nb_enfants'] = nb_enfants
                request.session['primo_accedant'] = primo
                # Une nouvelle simulation fait foi sur la page « Biens finançables ».
                request.session.pop('profil_biens', None)
```

Dans `simulateur_pret.html`, juste après la `</div>` qui ferme la colonne du select `type_bien` (fin de la `row` apport/type), ajouter une ligne :

```html
                        <div class="form-check mb-3">
                            <input class="form-check-input" type="checkbox" name="primo_accedant" id="primo_accedant">
                            <label class="form-check-label fw-bold" for="primo_accedant">
                                Je suis primo-accédant
                            </label>
                            <div class="form-text">Premier achat de résidence principale : frais de notaire réduits (~7,5 % dans l'ancien).</div>
                        </div>
```

et remplacer l'option `Ancien (8% frais)` par `Ancien (8 % de frais, 7,5 % si primo-accédant)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test analyseur_bancaire -v 2`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add analyseur_bancaire/views.py analyseur_bancaire/tests.py templates/analyseur/simulateur_pret.html
git commit -m "Barèmes septembre 2026, frais primo-accédant, simulateur qui mémorise tout le profil"
```

---

### Task 2: Lire les biens de Gino (module sans Django)

**Files:**
- Create: `analyseur_bancaire/biens_gino.py`
- Create: `analyseur_bancaire/test_biens_gino.py`

**Interfaces:**
- Produces:
  - `nombre(v) -> float | None`, `entier(v) -> int | None`
  - `type_habitation(t: str) -> "Appartement" | "Maison" | None`
  - `est_masque(statut) -> bool`
  - `villes(racine: Path) -> list[dict] | None` — `None` si le dossier n'existe pas ; sinon `[{"slug", "nom"}]` pour chaque sous-dossier contenant au moins un `_gino_*.json`.
  - `charger_ville(dossier: Path) -> {"biens": list[dict], "ignores": list[str], "masques": int, "date_releve": date | None}` ; chaque bien : `type`, `type_source`, `lieu`, `pieces`, `chambres`, `annee`, `dpe` (lettre A–G ou ""), `surface`, `prix`, `url`, `agence`, `statut`.

- [ ] **Step 1: Write the failing tests** — `analyseur_bancaire/test_biens_gino.py` :

```python
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from . import biens_gino as bg


def ville(dossier, fichiers, stan=None):
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, contenu in fichiers.items():
        (dossier / nom).write_text(contenu if isinstance(contenu, str) else json.dumps(contenu),
                                   encoding="utf-8")
    if stan is not None:
        (dossier / "_stan.json").write_text(json.dumps(stan), encoding="utf-8")
    return dossier


class LectureNombresTests(SimpleTestCase):
    def test_formats_reels_de_gino(self):
        self.assertEqual(bg.nombre("254 000 €"), 254000.0)
        self.assertEqual(bg.nombre("254 000\xa0€"), 254000.0)
        self.assertEqual(bg.nombre("104,23 m²"), 104.23)
        self.assertEqual(bg.nombre("104.85 m²"), 104.85)
        self.assertEqual(bg.nombre("Entre 222 m² et 245 m²"), 222.0)
        self.assertEqual(bg.nombre(5), 5.0)
        self.assertIsNone(bg.nombre(""))
        self.assertIsNone(bg.nombre(None))
        self.assertIsNone(bg.nombre("prix sur demande"))
        self.assertEqual(bg.entier("5"), 5)

    def test_types(self):
        self.assertEqual(bg.type_habitation("Appartement"), "Appartement")
        self.assertEqual(bg.type_habitation("Studio"), "Appartement")
        self.assertEqual(bg.type_habitation("Maison (mas)"), "Maison")
        self.assertEqual(bg.type_habitation("Villa"), "Maison")
        self.assertEqual(bg.type_habitation("Propriété"), "Maison")
        for t in ("Terrain", "Parking", "Garage-parking", "Local commercial", "Immeuble",
                  "Fonds de commerce (Restaurant, bar)", "", None):
            self.assertIsNone(bg.type_habitation(t), t)

    def test_statuts_masques(self):
        for s in ("vendu", "Sous compromis", "sous compromis",
                  "Fiche annonce en erreur sur le site (page « Whoops »)"):
            self.assertTrue(bg.est_masque(s), s)
        for s in ("", None, "disponible", "Sous offre"):
            self.assertFalse(bg.est_masque(s), s)


class ChargerVilleTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_lit_filtre_et_compte(self):
        d = ville(self.tmp / "fresnes", {
            "_gino_primo-fresnes.json": [
                {"type": "Appartement", "lieu": "Fresnes", "pieces": 5, "chambres": 3,
                 "surface": "104.85 m²", "prix": "273 000 €", "dpe": "d", "annee": 1970,
                 "url": "https://ex/1"},
                {"type": "Parking", "lieu": "Fresnes", "prix": "15 000 €", "url": "https://ex/2"},
                {"type": "Maison", "lieu": "Fresnes", "prix": "400 000 €", "statut": "vendu",
                 "url": "https://ex/3"},
                {"type": "Maison", "lieu": "Fresnes", "prix": "", "url": "https://ex/4"},
                {"type": "Maison", "lieu": "Fresnes", "prix": "300 000 €"},
            ],
            "_gino_casse.json": "{pas du json",
        }, stan=[{"nom": "Les Agences Primo - Favreau Fresnes"}])
        r = bg.charger_ville(d)
        self.assertEqual([b["url"] for b in r["biens"]], ["https://ex/1", "https://ex/4"])
        self.assertEqual(r["masques"], 1)
        self.assertEqual(r["ignores"], ["_gino_casse.json"])
        b = r["biens"][0]
        self.assertEqual((b["type"], b["surface"], b["prix"], b["dpe"], b["pieces"]),
                         ("Appartement", 104.85, 273000.0, "D", 5))
        self.assertIsNone(r["biens"][1]["prix"])       # sans prix : gardé, sans verdict plus tard
        self.assertIsNotNone(r["date_releve"])

    def test_nom_agence_depuis_stan_sinon_fichier(self):
        d = ville(self.tmp / "champigny-sur-marne", {
            "_gino_nestenn.json": [{"type": "Maison", "prix": 1, "url": "u1"}],
            "_gino_primo-fresnes.json": [{"type": "Maison", "prix": 1, "url": "u2"}],
        }, stan=[{"nom": "Nestenn Champigny-sur-Marne"}])
        agences = sorted(b["agence"] for b in bg.charger_ville(d)["biens"])
        self.assertEqual(agences, ["Nestenn Champigny-sur-Marne", "Primo Fresnes"])

    def test_villes(self):
        self.assertIsNone(bg.villes(self.tmp / "absent"))
        ville(self.tmp / "champigny-sur-marne", {"_gino_a.json": []})
        ville(self.tmp / "l-hay-les-roses", {"agences_immo.xlsx": "x"})   # pas de Gino
        self.assertEqual(bg.villes(self.tmp),
                         [{"slug": "champigny-sur-marne", "nom": "Champigny-sur-Marne"}])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/Scripts/python.exe manage.py test analyseur_bancaire.test_biens_gino -v 2`
Expected: FAIL with `ImportError: cannot import name 'biens_gino'`.

- [ ] **Step 3: Implement** — `analyseur_bancaire/biens_gino.py` :

```python
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
    s = str(v).replace(" ", " ").replace("\xa0", " ")
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test analyseur_bancaire.test_biens_gino -v 2`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add analyseur_bancaire/biens_gino.py analyseur_bancaire/test_biens_gino.py
git commit -m "biens_gino : lecture des biens de Gino (formats réels, statuts, fichiers abîmés)"
```

---

### Task 3: Doublons entre agences et médiane du prix au m²

**Files:**
- Modify: `analyseur_bancaire/biens_gino.py` (ajout en fin de fichier)
- Modify: `analyseur_bancaire/test_biens_gino.py` (ajout d'une classe)

**Interfaces:**
- Consumes: biens de `charger_ville`.
- Produces:
  - `regrouper_doublons(biens) -> list[dict]` — chaque groupe = le premier bien + `agences: list[str]` + `annonces: list[{"agence", "url"}]` ; `annee`, `dpe`, `pieces`, `chambres` vides complétés par les doublons.
  - `mediane_prix_m2(biens) -> float | None`.

- [ ] **Step 1: Write the failing tests** — ajouter à `test_biens_gino.py` :

```python
def bien(**k):
    base = {"type": "Appartement", "type_source": "Appartement", "lieu": "Fresnes",
            "pieces": 4, "chambres": 3, "annee": None, "dpe": "", "surface": 80.0,
            "prix": 250000.0, "url": "u", "agence": "A", "statut": ""}
    base.update(k)
    return base


class DoublonsTests(SimpleTestCase):
    def test_cas_reels_regroupes(self):
        # Champigny : même T4 chez Orpi Mairie (80,5 m²) et Nestenn (80 m²) à 254 000 €.
        # Fresnes : même 5 pièces chez Primo (104,85 m²) et L'Adresse (104,23 m²) à 273 000 €.
        g = bg.regrouper_doublons([
            bien(lieu="Champigny-sur-Marne", surface=80.5, prix=254000.0, agence="Orpi Mairie", url="o"),
            bien(lieu="Champigny-sur-Marne", surface=80.0, prix=254000.0, agence="Nestenn",
                 url="n", annee=1970, dpe="D"),
            bien(surface=104.85, prix=273000.0, agence="Primo", url="p"),
            bien(surface=104.23, prix=273000.0, agence="L'Adresse", url="a"),
        ])
        self.assertEqual(len(g), 2)
        self.assertEqual(g[0]["agences"], ["Orpi Mairie", "Nestenn"])
        self.assertEqual([a["url"] for a in g[0]["annonces"]], ["o", "n"])
        self.assertEqual((g[0]["annee"], g[0]["dpe"]), (1970, "D"))   # complétés

    def test_pas_regroupes(self):
        g = bg.regrouper_doublons([
            bien(agence="A", url="1"),
            bien(agence="A", url="2"),                    # même agence : deux annonces distinctes
            bien(agence="B", url="3", prix=260000.0),     # prix à 4 % d'écart
            bien(agence="C", url="4", surface=85.0),      # 5 m² d'écart
            bien(agence="D", url="5", type="Maison"),
            bien(agence="E", url="6", surface=None),      # surface inconnue : on ne devine pas
        ])
        self.assertEqual(len(g), 6)

    def test_mediane(self):
        self.assertEqual(bg.mediane_prix_m2([bien(prix=200000.0, surface=100.0),
                                             bien(prix=300000.0, surface=100.0),
                                             bien(prix=None), bien(surface=None)]), 2500.0)
        self.assertIsNone(bg.mediane_prix_m2([bien(prix=None)]))
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/Scripts/python.exe manage.py test analyseur_bancaire.test_biens_gino -v 2`
Expected: FAIL with `AttributeError: module ... has no attribute 'regrouper_doublons'`.

- [ ] **Step 3: Implement** — ajouter à `biens_gino.py` :

```python
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
                    if not g[k] and b[k]:
                        g[k] = b[k]
                break
        else:
            groupes.append({**b, "agences": [b["agence"]],
                            "annonces": [{"agence": b["agence"], "url": b["url"]}]})
    return groupes


def mediane_prix_m2(biens):
    vals = [b["prix"] / b["surface"] for b in biens if b["prix"] and b["surface"]]
    return statistics.median(vals) if vals else None
```

- [ ] **Step 4: Run to verify they pass**

Run: `venv/Scripts/python.exe manage.py test analyseur_bancaire.test_biens_gino -v 2`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add analyseur_bancaire/biens_gino.py analyseur_bancaire/test_biens_gino.py
git commit -m "biens_gino : doublons entre agences et médiane du prix au m²"
```

---

### Task 4: Financement bien par bien, verdict et prix maximum

**Files:**
- Modify: `analyseur_bancaire/biens_gino.py`
- Modify: `analyseur_bancaire/test_biens_gino.py`

**Interfaces:**
- Consumes: `SimulateurPretImmobilier` (tâche 1) passé en paramètre `sim` — méthodes `calculer_frais_notaire(prix, cle)`, `calculer_mensualites(montant, duree, taux_nominal, taux_assurance) -> {"mensualite", ...}`, `calculer_reste_a_vivre(revenus, charges_totales, nb_adultes, nb_enfants) -> {"statut": "OK"|"warning"|"danger", ...}`.
- Produces:
  - `Profil` (dataclass) : `revenus`, `charges`, `apport` (float), `duree` (int), `taux_nominal`, `taux_assurance` (float), `primo` (bool), `nb_adultes`, `nb_enfants` (int).
  - `est_neuf(bien) -> bool` ; `verdict(endettement, statut_reste_a_vivre="OK") -> str`.
  - `evaluer(bien, profil, mediane, sim) -> dict` : le bien + `neuf`, `alerte_dpe`, `ecart_m2` (ratio, ex. −0.18), `frais_notaire`, `emprunt`, `mensualite`, `endettement` (%), `verdict` (`"financable"`, `"limite"`, `"hors_budget"` ou `None`).
  - `prix_max_financable(profil, sim) -> float | None`.
  - `analyser_ville(dossier, profil, sim) -> {"biens", "resume": {"financable", "limite", "hors_budget", "total", "prix_max"}, "ignores", "masques", "date_releve", "mediane"}`.

- [ ] **Step 1: Write the failing tests** — ajouter à `test_biens_gino.py` :

```python
from .views import SimulateurPretImmobilier

SIM = SimulateurPretImmobilier()


def profil(**k):
    p = dict(revenus=4000.0, charges=300.0, apport=0.0, duree=20, taux_nominal=3.33,
             taux_assurance=0.20, primo=False, nb_adultes=2, nb_enfants=0)
    p.update(k)
    return bg.Profil(**p)


class FinancementTests(SimpleTestCase):
    def test_verdicts_aux_seuils(self):
        self.assertEqual(bg.verdict(35.0), "financable")
        self.assertEqual(bg.verdict(35.1), "limite")
        self.assertEqual(bg.verdict(40.0), "limite")
        self.assertEqual(bg.verdict(40.1), "hors_budget")
        self.assertEqual(bg.verdict(20.0, "danger"), "hors_budget")

    def test_neuf(self):
        self.assertTrue(bg.est_neuf(bien(annee=2026)))
        self.assertTrue(bg.est_neuf(bien(type_source="Appartement neuf (VEFA)")))
        self.assertFalse(bg.est_neuf(bien(annee=1970)))
        self.assertFalse(bg.est_neuf(bien(annee=None)))

    def test_evaluer_ancien_primo(self):
        r = bg.evaluer(bien(prix=200000.0, surface=80.0, dpe="G"), profil(primo=True), 2000.0, SIM)
        self.assertEqual(r["frais_notaire"], 15000.0)                  # 7,5 %
        self.assertEqual(r["emprunt"], 215000.0)
        self.assertAlmostEqual(r["mensualite"], 1250.2, delta=1)
        self.assertAlmostEqual(r["endettement"], 38.8, delta=0.2)      # (300 + 1250) / 4000
        self.assertEqual(r["verdict"], "limite")
        self.assertTrue(r["alerte_dpe"])
        self.assertAlmostEqual(r["ecart_m2"], 0.25)                    # 2 500 €/m² vs 2 000

    def test_apport_superieur_au_cout(self):
        r = bg.evaluer(bien(prix=100000.0), profil(apport=200000.0), None, SIM)
        self.assertEqual((r["emprunt"], r["mensualite"]), (0.0, 0.0))
        self.assertEqual(r["verdict"], "financable")
        self.assertIsNone(r["ecart_m2"])

    def test_sans_prix_ou_sans_revenus(self):
        self.assertIsNone(bg.evaluer(bien(prix=None), profil(), 2000.0, SIM)["verdict"])
        r = bg.evaluer(bien(), profil(revenus=0.0), 2000.0, SIM)
        self.assertIsNone(r["verdict"])
        self.assertIsNone(r["mensualite"])

    def test_prix_max(self):
        p = bg.prix_max_financable(profil(apport=20000.0), SIM)
        # mensualité max 1 100 € → ~189 000 € empruntables + 20 000 d'apport, ÷ 1,08
        self.assertTrue(190000 < p < 196000, p)
        self.assertIsNone(bg.prix_max_financable(profil(revenus=0.0), SIM))

    def test_analyser_ville_trie_et_resume(self):
        d = ville(Path(tempfile.mkdtemp()) / "fresnes", {"_gino_a.json": [
            {"type": "Maison", "lieu": "Fresnes", "surface": "100 m²", "prix": "600 000 €", "url": "cher"},
            {"type": "Appartement", "lieu": "Fresnes", "surface": "80 m²", "prix": "180 000 €", "url": "ok"},
            {"type": "Appartement", "lieu": "Fresnes", "surface": "70 m²", "prix": "", "url": "sans-prix"},
        ]})
        # apport 50 000 € : le 180 000 € ressort à ~28 % (sans apport il serait « limite », ~36 %)
        r = bg.analyser_ville(d, profil(apport=50000.0), SIM)
        self.assertEqual([b["url"] for b in r["biens"]], ["ok", "cher", "sans-prix"])
        self.assertEqual((r["resume"]["financable"], r["resume"]["hors_budget"], r["resume"]["total"]),
                         (1, 1, 3))
        self.assertIsNotNone(r["resume"]["prix_max"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/Scripts/python.exe manage.py test analyseur_bancaire.test_biens_gino -v 2`
Expected: FAIL with `AttributeError: ... has no attribute 'Profil'`.

- [ ] **Step 3: Implement** — ajouter à `biens_gino.py` (et `from dataclasses import dataclass` en tête) :

```python
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
    taux_notaire = sim.calculer_frais_notaire(1.0, _cle_notaire(False, profil))
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `venv/Scripts/python.exe manage.py test analyseur_bancaire.test_biens_gino -v 2`
Expected: PASS (16 tests). Si `test_evaluer_ancien_primo` échoue sur la mensualité, recalculer l'attendu avec `SIM.calculer_mensualites(215000, 20, 3.33, 0.20)` et vérifier que c'est bien la formule, pas le test, qui est en cause avant de toucher au chiffre.

- [ ] **Step 5: Commit**

```bash
git add analyseur_bancaire/biens_gino.py analyseur_bancaire/test_biens_gino.py
git commit -m "biens_gino : financement par bien, verdict, prix maximum finançable"
```

---

### Task 5: La page « Biens finançables »

**Files:**
- Modify: `tools_immo/settings.py` (fin du fichier)
- Modify: `analyseur_bancaire/views.py` (imports ; nouvelle vue en fin de fichier)
- Modify: `analyseur_bancaire/urls.py`
- Create: `templates/analyseur/biens_financables.html`
- Modify: `templates/analyseur/base.html` (bloc `nav_buttons`)
- Create: `analyseur_bancaire/test_vue_biens.py`

**Interfaces:**
- Consumes: `biens_gino.villes`, `biens_gino.analyser_ville`, `biens_gino.Profil`, `SimulateurPretImmobilier`, `TAUX_ACTUELS`.
- Produces: route nommée `biens_financables` (`biens-financables/`) ; setting `AGENCE_IMMO_DIR` ; clé de session `profil_biens` (dict des champs de `Profil`).

- [ ] **Step 1: Write the failing tests** — `analyseur_bancaire/test_vue_biens.py` :

```python
import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

TMP = Path(tempfile.mkdtemp())
FRESNES = TMP / "fresnes"
FRESNES.mkdir()
(FRESNES / "_gino_primo-fresnes.json").write_text(json.dumps([
    {"type": "Appartement", "lieu": "Fresnes", "pieces": 4, "chambres": 3, "surface": "82 m²",
     "prix": "209 000 €", "dpe": "D", "url": "https://ex/209"},
    {"type": "Maison", "lieu": "Fresnes", "pieces": 6, "surface": "150 m²",
     "prix": "700 000 €", "dpe": "G", "url": "https://ex/700"},
]), encoding="utf-8")
# apport 50 000 € : le 209 000 € ressort à ~33 % → « Finançable » (avec 20 000 €, ~37 % : « Limite »)
PROFIL = {"revenus": "4000", "charges": "300", "apport": "50000", "duree": "20",
          "taux_nominal": "3,33", "taux_assurance": "0.20", "nb_adultes": "2",
          "nb_enfants": "0", "primo": "on", "ville": "fresnes"}


@override_settings(AGENCE_IMMO_DIR=TMP)
class PageBiensTests(SimpleTestCase):
    def test_sans_profil_liste_sans_verdict_et_invitation(self):
        r = self.client.get(reverse("biens_financables"), {"ville": "fresnes"})
        self.assertContains(r, "https://ex/209")
        self.assertContains(r, "Complète ton profil")
        self.assertContains(r, "valeurs par défaut")

    def test_profil_saisi_donne_les_verdicts(self):
        r = self.client.post(reverse("biens_financables"), PROFIL, follow=True)
        self.assertContains(r, "Finançable")
        self.assertContains(r, "Hors budget")
        self.assertContains(r, "ta saisie")
        self.assertEqual(self.client.session["profil_biens"]["taux_nominal"], 3.33)

    def test_ville_inconnue_ou_malveillante(self):
        r = self.client.get(reverse("biens_financables"), {"ville": "../../etc"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("analyse", r.context)

    @override_settings(AGENCE_IMMO_DIR=TMP / "absent")
    def test_dossier_gino_introuvable(self):
        r = self.client.get(reverse("biens_financables"))
        self.assertContains(r, "AGENCE_IMMO_DIR")


class VraiesDonneesTests(SimpleTestCase):
    """Bout en bout sur les vrais fichiers de Gino, s'ils sont présents sur ce poste."""

    def test_fresnes_reel(self):
        if not (Path(settings.AGENCE_IMMO_DIR) / "fresnes").is_dir():
            self.skipTest("données de Gino absentes")
        r = self.client.get(reverse("biens_financables"), {"ville": "fresnes"})
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.context["analyse"]["resume"]["total"], 50)
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/Scripts/python.exe manage.py test analyseur_bancaire.test_vue_biens -v 2`
Expected: FAIL with `NoReverseMatch: Reverse for 'biens_financables' not found`.

- [ ] **Step 3: Implement the setting** — à la fin de `tools_immo/settings.py` :

```python
# Résultats de Gino (projet séparé agence-immo). tools_immo les LIT seulement.
AGENCE_IMMO_DIR = Path(os.environ.get(
    'AGENCE_IMMO_DIR', BASE_DIR.parent / 'tools' / 'scraping' / 'agence-immo'))
```

- [ ] **Step 4: Implement the view** — dans `views.py`, ajouter aux imports (vérifié le 28/09 :
`render, redirect` sont déjà importés, les autres non) :

```python
from pathlib import Path

from django.conf import settings
from django.urls import reverse

from . import biens_gino
```

puis en fin de fichier :

```python
def _nombre_saisi(valeur, defaut):
    try:
        return float(str(valeur).replace(',', '.').replace(' ', ''))
    except (TypeError, ValueError):
        return defaut


def _profil_par_defaut():
    return biens_gino.Profil(
        duree=20,
        taux_nominal=TAUX_ACTUELS['regions']['ile_de_france']['20'] + TAUX_ACTUELS['profils']['moyen'],
        taux_assurance=TAUX_ACTUELS['assurance']['30_45'])


def _profil_biens(session):
    """Profil de la page : saisie > simulation > défauts. Renvoie (profil, source)."""
    if session.get('profil_biens'):
        return biens_gino.Profil(**session['profil_biens']), 'saisie'
    d = _profil_par_defaut()
    if session.get('revenus_nets'):
        return biens_gino.Profil(
            revenus=session['revenus_nets'], charges=session.get('charges_fixes', 0),
            apport=session.get('apport', 0), duree=session.get('duree', d.duree),
            taux_nominal=session.get('taux_nominal', d.taux_nominal),
            taux_assurance=session.get('taux_assurance', d.taux_assurance),
            primo=session.get('primo_accedant', False),
            nb_adultes=session.get('nb_adultes', 2), nb_enfants=session.get('nb_enfants', 0)
        ), 'simulation'
    return d, 'defaut'


def biens_financables(request):
    """Biens relevés par Gino, avec le coût mensuel et le verdict de financement de chacun."""
    racine = Path(settings.AGENCE_IMMO_DIR)
    liste = biens_gino.villes(racine)

    if request.method == 'POST':
        if request.POST.get('action') == 'reprendre':
            request.session.pop('profil_biens', None)
        else:
            d = _profil_par_defaut()
            p = request.POST
            request.session['profil_biens'] = {
                'revenus': _nombre_saisi(p.get('revenus'), 0.0),
                'charges': _nombre_saisi(p.get('charges'), 0.0),
                'apport': _nombre_saisi(p.get('apport'), 0.0),
                'duree': int(_nombre_saisi(p.get('duree'), d.duree)),
                'taux_nominal': _nombre_saisi(p.get('taux_nominal'), d.taux_nominal),
                'taux_assurance': _nombre_saisi(p.get('taux_assurance'), d.taux_assurance),
                'primo': p.get('primo') == 'on',
                'nb_adultes': int(_nombre_saisi(p.get('nb_adultes'), 2)),
                'nb_enfants': int(_nombre_saisi(p.get('nb_enfants'), 0)),
            }
        return redirect(f"{reverse('biens_financables')}?ville={request.POST.get('ville', '')}")

    profil, source = _profil_biens(request.session)
    contexte = {'racine': racine, 'villes': liste or [], 'dossier_introuvable': liste is None,
                'profil': profil, 'source_profil': source}
    slugs = {v['slug'] for v in liste or []}
    slug = request.GET.get('ville') or (liste[0]['slug'] if liste else None)
    if slug in slugs:   # jamais de chemin construit à partir d'une valeur non listée
        contexte['ville'] = next(v for v in liste if v['slug'] == slug)
        contexte['analyse'] = biens_gino.analyser_ville(racine / slug, profil,
                                                        SimulateurPretImmobilier())
    return render(request, 'analyseur/biens_financables.html', contexte)
```

- [ ] **Step 5: Implement the route and nav** — dans `urls.py`, ajouter
`path('biens-financables/', views.biens_financables, name='biens_financables'),` ; dans `base.html`, bloc `nav_buttons`, avant le lien « Analyser un relevé » :

```html
                <a class="nav-link text-dark" href="{% url 'biens_financables' %}">
                    <i class="bi bi-house-check"></i> Biens finançables
                </a>
```

- [ ] **Step 6: Implement the template** — `templates/analyseur/biens_financables.html` :

```html
{% extends 'analyseur/base.html' %}
{% load humanize %}
{% block title %}Biens finançables{% endblock %}
{% block content %}
<div class="container py-4">

  <div class="d-flex flex-wrap align-items-center gap-3 mb-3">
    <h1 class="h3 mb-0"><i class="bi bi-house-check"></i> Biens finançables</h1>
    {% if villes %}
    <form method="get" class="d-flex align-items-center gap-2">
      <label for="ville" class="visually-hidden">Ville</label>
      <select id="ville" name="ville" class="form-select" onchange="this.form.submit()">
        {% for v in villes %}<option value="{{ v.slug }}" {% if ville.slug == v.slug %}selected{% endif %}>{{ v.nom }}</option>{% endfor %}
      </select>
    </form>
    {% endif %}
    {% if analyse.date_releve %}<span class="text-muted small">Biens relevés le {{ analyse.date_releve|date:"d/m/Y" }}</span>{% endif %}
  </div>

  {% if dossier_introuvable %}
  <div class="alert alert-warning">
    <p class="fw-bold mb-1"><i class="bi bi-folder-x"></i> Je ne trouve pas les résultats de Gino.</p>
    <ul class="mb-0">
      <li>Dossier cherché : <code>{{ racine }}</code></li>
      <li>Indique le bon dossier avec la variable <code>AGENCE_IMMO_DIR</code>, puis relance tools_immo.</li>
    </ul>
  </div>
  {% elif not villes %}
  <div class="alert alert-info">
    <p class="fw-bold mb-1"><i class="bi bi-info-circle"></i> Aucune ville relevée pour l'instant.</p>
    <ul class="mb-0"><li>Lance Gino sur une ville, puis reviens ici.</li></ul>
  </div>
  {% endif %}

  <div class="card mb-3">
    <div class="card-header d-flex justify-content-between align-items-center">
      <span class="fw-bold"><i class="bi bi-person-badge"></i> Ton profil</span>
      {% if source_profil == 'simulation' %}<span class="badge bg-success">repris de ta simulation</span>
      {% elif source_profil == 'saisie' %}<span class="badge bg-primary">ta saisie</span>
      {% else %}<span class="badge bg-secondary">valeurs par défaut, à ajuster</span>{% endif %}
    </div>
    <div class="card-body">
      {% if profil.revenus <= 0 %}
      <p class="mb-3"><i class="bi bi-arrow-right-circle"></i> Complète ton profil pour voir ce que tu peux financer.
        Tu peux aussi <a href="{% url 'simulateur_pret' %}">faire ta simulation</a> : ses chiffres seront repris ici.</p>
      {% endif %}
      <form method="post" class="row g-2 align-items-end">
        {% csrf_token %}
        <input type="hidden" name="ville" value="{{ ville.slug }}">
        <div class="col-6 col-md-2"><label class="form-label small" for="revenus">Revenus nets / mois</label>
          <input class="form-control" id="revenus" name="revenus" type="number" step="10" value="{{ profil.revenus|floatformat:0 }}"></div>
        <div class="col-6 col-md-2"><label class="form-label small" for="charges">Charges / mois</label>
          <input class="form-control" id="charges" name="charges" type="number" step="10" value="{{ profil.charges|floatformat:0 }}"></div>
        <div class="col-6 col-md-2"><label class="form-label small" for="apport">Apport</label>
          <input class="form-control" id="apport" name="apport" type="number" step="1000" value="{{ profil.apport|floatformat:0 }}"></div>
        <div class="col-6 col-md-1"><label class="form-label small" for="duree">Durée (ans)</label>
          <input class="form-control" id="duree" name="duree" type="number" min="5" max="27" value="{{ profil.duree }}"></div>
        <div class="col-6 col-md-1"><label class="form-label small" for="taux_nominal">Taux %</label>
          <input class="form-control" id="taux_nominal" name="taux_nominal" type="number" step="0.01" value="{{ profil.taux_nominal|stringformat:'.2f' }}"></div>
        <div class="col-6 col-md-1"><label class="form-label small" for="taux_assurance">Assurance %</label>
          <input class="form-control" id="taux_assurance" name="taux_assurance" type="number" step="0.01" value="{{ profil.taux_assurance|stringformat:'.2f' }}"></div>
        <input type="hidden" name="nb_adultes" value="{{ profil.nb_adultes }}">
        <input type="hidden" name="nb_enfants" value="{{ profil.nb_enfants }}">
        <div class="col-6 col-md-1 form-check ms-2">
          <input class="form-check-input" type="checkbox" id="primo" name="primo" {% if profil.primo %}checked{% endif %}>
          <label class="form-check-label small" for="primo">Primo-accédant</label></div>
        <div class="col-12 col-md-auto">
          <button class="btn btn-primary"><i class="bi bi-arrow-repeat"></i> Recalculer</button>
          {% if source_profil == 'saisie' %}<button class="btn btn-link" name="action" value="reprendre">Reprendre ma simulation</button>{% endif %}
        </div>
      </form>
    </div>
  </div>

  {% if analyse %}
  <div class="row g-2 mb-3 text-center">
    <div class="col-6 col-md-3"><div class="border rounded p-2"><div class="h4 mb-0 text-success">{{ analyse.resume.financable }}</div><div class="small">finançables</div></div></div>
    <div class="col-6 col-md-3"><div class="border rounded p-2"><div class="h4 mb-0 text-warning">{{ analyse.resume.limite }}</div><div class="small">limites</div></div></div>
    <div class="col-6 col-md-3"><div class="border rounded p-2"><div class="h4 mb-0 text-danger">{{ analyse.resume.hors_budget }}</div><div class="small">hors budget</div></div></div>
    <div class="col-6 col-md-3"><div class="border rounded p-2"><div class="h4 mb-0">{% if analyse.resume.prix_max %}{{ analyse.resume.prix_max|floatformat:0|intcomma }} €{% else %}—{% endif %}</div><div class="small">prix maximum finançable</div></div></div>
  </div>

  <ul class="small text-muted mb-3">
    <li>Coût mensuel hors charges de copropriété et taxe foncière.</li>
    {% if analyse.masques %}<li>{{ analyse.masques }} bien{{ analyse.masques|pluralize }} vendu{{ analyse.masques|pluralize }} ou sous compromis masqué{{ analyse.masques|pluralize }}.</li>{% endif %}
    {% for f in analyse.ignores %}<li>Fichier ignoré, illisible : <code>{{ f }}</code></li>{% endfor %}
  </ul>

  <form id="filtres" class="row g-2 mb-3 align-items-end" onsubmit="return false">
    <fieldset class="col-12 col-md-auto">
      <legend class="form-label small mb-1">Verdict</legend>
      <div class="btn-group" role="group">
        <input type="checkbox" class="btn-check" id="f-financable" value="financable" name="verdict"><label class="btn btn-outline-success btn-sm" for="f-financable">Finançable</label>
        <input type="checkbox" class="btn-check" id="f-limite" value="limite" name="verdict"><label class="btn btn-outline-warning btn-sm" for="f-limite">Limite</label>
        <input type="checkbox" class="btn-check" id="f-hors" value="hors_budget" name="verdict"><label class="btn btn-outline-danger btn-sm" for="f-hors">Hors budget</label>
      </div>
    </fieldset>
    <div class="col-6 col-md-2"><label class="form-label small" for="f-type">Type</label>
      <select id="f-type" class="form-select form-select-sm"><option value="">Tous</option><option>Appartement</option><option>Maison</option></select></div>
    <div class="col-6 col-md-2"><label class="form-label small" for="f-surface">Surface min (m²)</label><input id="f-surface" type="number" class="form-control form-control-sm"></div>
    <div class="col-6 col-md-2"><label class="form-label small" for="f-pieces">Pièces min</label><input id="f-pieces" type="number" class="form-control form-control-sm"></div>
    <div class="col-6 col-md-2"><label class="form-label small" for="f-chambres">Chambres min</label><input id="f-chambres" type="number" class="form-control form-control-sm"></div>
    <div class="col-12 col-md-auto"><button type="reset" class="btn btn-link btn-sm" id="f-reset">Réinitialiser les filtres</button></div>
  </form>

  <p id="aucun" class="alert alert-light d-none"><i class="bi bi-search"></i> Aucun bien ne correspond. Élargis la surface ou les pièces, ou réinitialise les filtres.</p>

  <div class="table-responsive d-none d-md-block">
    <table class="table table-hover align-middle" id="table-biens">
      <thead class="table-light sticky-top"><tr>
        <th data-tri="verdict" aria-sort="ascending" role="button">Verdict</th>
        <th>Bien</th>
        <th class="text-end" data-tri="prix" role="button">Prix</th>
        <th class="text-end" data-tri="mensualite" role="button">Mensualité</th>
        <th class="text-end" data-tri="endettement" role="button">Endettement</th>
        <th class="text-end" data-tri="ecart" role="button">Prix/m² vs ville</th>
        <th>DPE</th><th>Agences</th><th>Annonce</th>
      </tr></thead>
      <tbody>
      {% for b in analyse.biens %}
      <tr class="bien" data-verdict="{{ b.verdict|default:'' }}" data-type="{{ b.type }}" data-surface="{{ b.surface|default:0 }}" data-pieces="{{ b.pieces|default:0 }}" data-chambres="{{ b.chambres|default:0 }}" data-prix="{{ b.prix|default:0 }}" data-mensualite="{{ b.mensualite|default:0 }}" data-endettement="{{ b.endettement|default:0 }}" data-ecart="{{ b.ecart_m2|default_if_none:9 }}" data-ordre="{{ forloop.counter }}">
        <td>{% include 'analyseur/_verdict.html' %}</td>
        <td>{{ b.type }}{% if b.pieces %} {{ b.pieces }} p.{% endif %} · {{ b.lieu }}{% if b.surface %} · {{ b.surface|floatformat:0 }} m²{% endif %}{% if b.chambres %} · {{ b.chambres }} ch.{% endif %}{% if b.neuf %} <span class="badge bg-info text-dark">neuf</span>{% endif %}</td>
        <td class="text-end font-monospace">{% if b.prix %}{{ b.prix|floatformat:0|intcomma }} €{% else %}<span class="text-muted">prix non affiché</span>{% endif %}</td>
        <td class="text-end font-monospace">{% if b.mensualite is not None %}{{ b.mensualite|floatformat:0|intcomma }} €/mois{% else %}—{% endif %}</td>
        <td class="text-end font-monospace">{% if b.endettement is not None %}{{ b.endettement|floatformat:1 }} %{% else %}—{% endif %}</td>
        <td class="text-end">{% include 'analyseur/_ecart.html' %}</td>
        <td>{% include 'analyseur/_dpe.html' %}</td>
        <td class="small">{{ b.agences|join:" + " }}</td>
        <td>{% for a in b.annonces %}<a href="{{ a.url }}" target="_blank" rel="noopener" class="d-block small">Voir{% if b.annonces|length > 1 %} ({{ a.agence }}){% endif %}</a>{% endfor %}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  <div class="d-md-none">
    {% for b in analyse.biens %}
    <div class="card mb-2 bien" data-verdict="{{ b.verdict|default:'' }}" data-type="{{ b.type }}" data-surface="{{ b.surface|default:0 }}" data-pieces="{{ b.pieces|default:0 }}" data-chambres="{{ b.chambres|default:0 }}">
      <div class="card-body py-2">
        <div class="d-flex justify-content-between">{% include 'analyseur/_verdict.html' %}{% include 'analyseur/_dpe.html' %}</div>
        <div class="fw-bold mt-1">{{ b.type }}{% if b.pieces %} {{ b.pieces }} p.{% endif %} · {{ b.lieu }}{% if b.surface %} · {{ b.surface|floatformat:0 }} m²{% endif %}</div>
        <div>{% if b.prix %}{{ b.prix|floatformat:0|intcomma }} €{% else %}prix non affiché{% endif %}{% if b.mensualite is not None %} · {{ b.mensualite|floatformat:0|intcomma }} €/mois · {{ b.endettement|floatformat:1 }} %{% endif %}</div>
        <div class="small">{% include 'analyseur/_ecart.html' %} · {{ b.agences|join:" + " }}
          {% for a in b.annonces %} · <a href="{{ a.url }}" target="_blank" rel="noopener">Voir</a>{% endfor %}</div>
      </div>
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>

<script>
(function () {
  const f = document.getElementById('filtres');
  if (!f) return;
  const biens = [...document.querySelectorAll('.bien')];
  const num = (el, k) => parseFloat(el.dataset[k] || '0');
  function filtrer() {
    const verdicts = [...f.querySelectorAll('[name=verdict]:checked')].map(c => c.value);
    const type = document.getElementById('f-type').value;
    const smin = +document.getElementById('f-surface').value || 0;
    const pmin = +document.getElementById('f-pieces').value || 0;
    const cmin = +document.getElementById('f-chambres').value || 0;
    let vus = 0;
    biens.forEach(el => {
      const ok = (!verdicts.length || verdicts.includes(el.dataset.verdict))
        && (!type || el.dataset.type === type)
        && num(el, 'surface') >= smin && num(el, 'pieces') >= pmin && num(el, 'chambres') >= cmin;
      el.classList.toggle('d-none', !ok);
      if (ok && el.tagName === 'TR') vus++;
    });
    document.getElementById('aucun').classList.toggle('d-none', vus > 0);
  }
  f.addEventListener('input', filtrer);
  document.getElementById('f-reset').addEventListener('click', () => setTimeout(filtrer));
  const corps = document.querySelector('#table-biens tbody');
  document.querySelectorAll('#table-biens th[data-tri]').forEach(th => {
    th.addEventListener('click', () => {
      const cle = th.dataset.tri === 'verdict' ? 'ordre' : th.dataset.tri;
      const asc = th.getAttribute('aria-sort') !== 'ascending';
      document.querySelectorAll('#table-biens th').forEach(h => h.removeAttribute('aria-sort'));
      th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
      [...corps.rows].sort((a, b) => (num(a, cle) - num(b, cle)) * (asc ? 1 : -1))
        .forEach(r => corps.appendChild(r));
    });
  });
})();
</script>
{% endblock %}
```

Créer aussi les trois petits gabarits inclus :

`templates/analyseur/_verdict.html`
```html
{% if b.verdict == 'financable' %}<span class="badge bg-success"><i class="bi bi-check-circle"></i> Finançable</span>
{% elif b.verdict == 'limite' %}<span class="badge bg-warning text-dark"><i class="bi bi-exclamation-triangle"></i> Limite</span>
{% elif b.verdict == 'hors_budget' %}<span class="badge bg-danger"><i class="bi bi-x-circle"></i> Hors budget</span>
{% else %}<span class="badge bg-light text-muted border"><i class="bi bi-dash-circle"></i> Non calculé</span>{% endif %}
```

`templates/analyseur/_dpe.html`
```html
{% if b.dpe %}<span class="badge dpe dpe-{{ b.dpe }}" title="DPE {{ b.dpe }}">{{ b.dpe }}{% if b.alerte_dpe %} <i class="bi bi-exclamation-triangle-fill" aria-label="passoire énergétique"></i>{% endif %}</span>
{% else %}<span class="badge bg-light text-muted border">DPE n.c.</span>{% endif %}
```

`templates/analyseur/_ecart.html`
```html
{% if b.ecart_m2 is not None %}{% if b.ecart_m2 < 0 %}<span class="text-success"><i class="bi bi-arrow-down"></i> {% widthratio b.ecart_m2 1 -100 %} % sous la ville</span>{% else %}<span class="text-muted"><i class="bi bi-arrow-up"></i> {% widthratio b.ecart_m2 1 100 %} %</span>{% endif %}{% else %}<span class="text-muted">—</span>{% endif %}
```

et, dans `biens_financables.html`, juste après `{% block content %}`, les couleurs officielles du DPE (contraste AA : texte sombre sur les teintes claires) :

```html
<style>
  .dpe { color: #fff; min-width: 2rem; }
  .dpe-A { background: #009c6d; } .dpe-B { background: #52b153; } .dpe-C { background: #78bd76; color: #1b1b1b; }
  .dpe-D { background: #f4e70f; color: #1b1b1b; } .dpe-E { background: #f0b40f; color: #1b1b1b; }
  .dpe-F { background: #eb8235; color: #1b1b1b; } .dpe-G { background: #d7221f; }
</style>
```

Dans `tools_immo/settings.py`, ajouter `'django.contrib.humanize',` à `INSTALLED_APPS` (vérifié : absent le 28/09) — il fournit `intcomma` (« 254 000 ») et n'a ni modèle ni migration : le choix « sans base » est préservé.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test analyseur_bancaire -v 2`
Expected: PASS (tous les tests des tâches 1 à 5 ; `test_fresnes_reel` passe ou est « skipped » si les données sont absentes).

- [ ] **Step 8: Vérifier dans le navigateur**

Run: `venv/Scripts/python.exe manage.py runserver` puis ouvrir `http://127.0.0.1:8000/biens-financables/?ville=fresnes` (adapter le préfixe à celui de `tools_immo/urls.py`).
Expected : sans profil, liste et invitation « Complète ton profil » ; après saisie (4 000 € de revenus), des pastilles vert/orange/rouge avec icône et mot ; filtres et tri instantanés ; en fenêtre étroite (375 px), des cartes au lieu du tableau ; les doublons Primo + L'Adresse sur une seule ligne.

- [ ] **Step 9: Commit**

```bash
git add tools_immo/settings.py analyseur_bancaire/views.py analyseur_bancaire/urls.py analyseur_bancaire/test_vue_biens.py templates/analyseur/biens_financables.html templates/analyseur/_verdict.html templates/analyseur/_dpe.html templates/analyseur/_ecart.html templates/analyseur/base.html
git commit -m "Page « Biens finançables » : biens de Gino, coût mensuel et verdict de financement"
```

---

### Task 6: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Documenter** — ajouter à `CLAUDE.md` une section :

```markdown
### Biens finançables (lecture des résultats de Gino)

- Page `biens-financables/` : les biens relevés par Gino (projet **séparé** agence-immo,
  futur SaaS) pour une ville, avec frais de notaire, mensualité, endettement et verdict
  (≤ 35 % finançable, ≤ 40 % limite, au-delà hors budget).
- Tout ce qui dépend du format de Gino vit dans `analyseur_bancaire/biens_gino.py` (sans
  Django). tools_immo **lit seulement** `<ville>/_gino_*.json` — tous les biens, pas les
  onglets Excel déjà filtrés. `criteres.json` n'est pas utilisé.
- Dossier lu : setting `AGENCE_IMMO_DIR` (variable d'environnement du même nom).
- Barèmes (taux, assurance, frais de notaire dont primo-accédant 7,5 %) : septembre 2026,
  sources en commentaire en tête de `views.py`. À mettre à jour quand les taux bougent.
- Tests : `venv/Scripts/python.exe manage.py test analyseur_bancaire`. Valeur de contrôle
  officielle : 200 000 € · 20 ans · 3,53 % tout compris → ≈ 1 163 €/mois.
```

et corriger la phrase « aucun test réel pour l'instant » de la section Commandes.

- [ ] **Step 2: Vérification finale**

Run: `venv/Scripts/python.exe manage.py test analyseur_bancaire -v 2` puis `venv/Scripts/python.exe manage.py check`
Expected: tous les tests PASS ; « System check identified no issues ».

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "CLAUDE.md : page Biens finançables, barèmes 2026, tests"
```
