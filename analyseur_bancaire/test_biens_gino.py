import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from . import biens_gino as bg
from .views import SimulateurPretImmobilier

SIM = SimulateurPretImmobilier()


def ville(dossier, fichiers, stan=None):
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, contenu in fichiers.items():
        (dossier / nom).write_text(contenu if isinstance(contenu, str) else json.dumps(contenu),
                                   encoding="utf-8")
    if stan is not None:
        (dossier / "_stan.json").write_text(json.dumps(stan), encoding="utf-8")
    return dossier


def bien(**k):
    base = {"type": "Appartement", "type_source": "Appartement", "lieu": "Fresnes",
            "pieces": 4, "chambres": 3, "annee": None, "dpe": "", "surface": 80.0,
            "prix": 250000.0, "url": "u", "agence": "A", "statut": ""}
    base.update(k)
    return base


def profil(**k):
    p = dict(revenus=4000.0, charges=300.0, apport=0.0, duree=20, taux_nominal=3.33,
             taux_assurance=0.20, primo=False, nb_adultes=2, nb_enfants=0)
    p.update(k)
    return bg.Profil(**p)


class LectureNombresTests(SimpleTestCase):
    def test_formats_reels_de_gino(self):
        self.assertEqual(bg.nombre("254 000 €"), 254000.0)
        self.assertEqual(bg.nombre("254\N{NARROW NO-BREAK SPACE}000\N{NO-BREAK SPACE}€"), 254000.0)
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

    def test_robustesse_type_non_string(self):
        """Type non-string (ex: entier) ne doit pas planter ; le bien est ignoré."""
        d = ville(self.tmp / "robustesse", {
            "_gino_test.json": [
                {"type": "Maison", "prix": "100 000", "url": "https://ex/valid"},
                {"type": 123, "prix": "200 000", "url": "https://ex/invalid"},
            ]
        })
        r = bg.charger_ville(d)
        self.assertEqual(len(r["biens"]), 1)
        self.assertEqual(r["biens"][0]["url"], "https://ex/valid")

    def test_robustesse_stan_nom_non_string(self):
        """Nom non-string dans _stan.json ne doit pas planter ; fallback au nom de fichier."""
        d = ville(self.tmp / "robustesse-stan", {
            "_gino_lesprix.json": [{"type": "Maison", "prix": "150 000", "url": "https://ex/1"}]
        }, stan=[{"nom": 12345}])
        r = bg.charger_ville(d)
        self.assertEqual(len(r["biens"]), 1)
        # Sans nom valide dans Stan, on doit utiliser le nom du fichier
        self.assertEqual(r["biens"][0]["agence"], "Lesprix")


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

    def test_completion_preserve_zero(self):
        # Legitimate 0 (studio) should not be overwritten by duplicate's 1
        g = bg.regrouper_doublons([
            bien(chambres=0, agence="A", url="1"),
            bien(chambres=1, agence="B", url="2"),
        ])
        self.assertEqual(g[0]["chambres"], 0)
        # Missing (None) should be filled from duplicate
        g = bg.regrouper_doublons([
            bien(chambres=None, agence="A", url="1"),
            bien(chambres=1, agence="B", url="2"),
        ])
        self.assertEqual(g[0]["chambres"], 1)


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
