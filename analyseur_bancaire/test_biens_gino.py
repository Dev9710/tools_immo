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
        self.assertEqual(bg.nombre("254 000\xa0€"), 254000.0)
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
