# analyseur_bancaire/test_pastilles.py
import json
import tempfile
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import reverse

from . import biens_gino

TMP = Path(tempfile.mkdtemp())
VILLE = TMP / "thiais"
VILLE.mkdir()
AUJOURDHUI = date(2026, 10, 6)


def bien(n, **k):
    return {"type": "Appartement", "lieu": "Thiais", "pieces": 3, "surface": 60, "prix": 200000,
            "url": f"https://ex/{n}", "statut": "disponible", **k}


(VILLE / "_gino_agence.json").write_text(json.dumps([
    bien(1, vu_depuis="2026-09-26"),                                   # premier relevé
    bien(2, vu_depuis="2026-10-03"),                                   # apparu il y a 3 jours
    bien(3, vu_depuis="2026-09-28"),                                   # apparu il y a 8 jours
    bien(4, vu_depuis="2026-09-26", prix=240000, historique_prix=[
        {"date": "2026-09-26", "prix": 250000}, {"date": "2026-10-05", "prix": 240000}]),
    bien(5, vu_depuis="2026-09-26", prix=260000, historique_prix=[
        {"date": "2026-09-26", "prix": 250000}, {"date": "2026-10-05", "prix": 260000}]),
    bien(6, vu_depuis="2026-09-26", annee=2025),
]), encoding="utf-8")
# Agence ajoutée récemment : tous ses biens ont la même date de premier relevé.
(VILLE / "_gino_nouvelle-agence.json").write_text(json.dumps([
    bien(7, vu_depuis="2026-10-05", surface=70), bien(8, vu_depuis="2026-10-05", surface=80),
]), encoding="utf-8")


def par_url(lu):
    return {b["url"]: b for b in lu["biens"]}


class PastillesTests(SimpleTestCase):
    def setUp(self):
        self.b = par_url(biens_gino.charger_ville(VILLE, aujourdhui=AUJOURDHUI))

    def test_nouveau_seulement_apres_le_premier_releve_et_sous_7_jours(self):
        self.assertTrue(self.b["https://ex/2"]["nouveau"])
        self.assertFalse(self.b["https://ex/1"]["nouveau"])     # présent dès le premier relevé
        self.assertFalse(self.b["https://ex/3"]["nouveau"])     # apparu il y a plus de 7 jours

    def test_agence_ajoutee_recemment_pas_tout_en_nouveau(self):
        self.assertFalse(self.b["https://ex/7"]["nouveau"])
        self.assertFalse(self.b["https://ex/8"]["nouveau"])

    def test_baisse_de_prix_par_rapport_au_plus_haut_vu(self):
        self.assertEqual(self.b["https://ex/4"]["baisse"],
                         {"avant": 250000.0, "apres": 240000.0, "pct": -4.0, "depuis": "2026-10-05"})
        self.assertIsNone(self.b["https://ex/5"]["baisse"])     # hausse : pas de pastille
        self.assertIsNone(self.b["https://ex/1"]["baisse"])     # pas d'historique

    def test_dates_ou_historique_illisibles_sans_erreur(self):
        dossier = TMP / "orly"
        dossier.mkdir(exist_ok=True)
        (dossier / "_gino_x.json").write_text(json.dumps([
            bien(1, vu_depuis="n'importe quoi", historique_prix="pas une liste"),
            bien(2, historique_prix=[{"date": "2026-10-01"}, "x", {"prix": "abc"}]),
        ]), encoding="utf-8")
        b = par_url(biens_gino.charger_ville(dossier, aujourdhui=AUJOURDHUI))
        self.assertFalse(b["https://ex/1"]["nouveau"])
        self.assertIsNone(b["https://ex/1"]["baisse"])
        self.assertIsNone(b["https://ex/2"]["baisse"])

    def test_pastilles_et_filtre_dans_la_page(self):
        with self.settings(AGENCE_IMMO_DIR=TMP):
            r = self.client.get(reverse("biens_financables"), {"ville": "thiais", "revenus": 5000})
        html = r.content.decode()
        self.assertIn('id="f-pastille"', html)
        for p in ("neuf", "ancien", "baisse", "nouveau"):
            self.assertIn(f'value="{p}"', html)
        self.assertIn('class="pastille-bien p-nouveau"', html)
        self.assertIn('class="pastille-bien p-baisse"', html)
        self.assertIn("250 000 → 240 000 € (−4 %) depuis le 05/10", html)
        self.assertIn('data-pastilles="neuf"', html)


class JamaisReverifieTests(SimpleTestCase):
    """Biens d'une agence sans recette : relevés une fois par Gino, jamais revérifiés depuis
    (ex. maison KSI vendue mais toujours affichée). Signalés et masquables."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import os, time
        cls.ville = TMP / "lhay"
        cls.ville.mkdir(exist_ok=True)
        f = cls.ville / "_gino_ksi.json"
        f.write_text(json.dumps([bien(20), bien(21, verifie_le="2026-10-05T10:00")]), encoding="utf-8")
        releve = time.mktime((2026, 9, 28, 12, 0, 0, 0, 0, -1))
        os.utime(f, (releve, releve))

    def test_jamais_revérifie_et_date_du_releve(self):
        b = par_url(biens_gino.charger_ville(self.ville, aujourdhui=AUJOURDHUI))
        self.assertTrue(b["https://ex/20"]["jamais_verifie"])
        self.assertEqual(b["https://ex/20"]["releve_le"], "2026-09-28")
        self.assertFalse(b["https://ex/21"]["jamais_verifie"])

    def test_etiquette_et_filtre_dans_la_page(self):
        with self.settings(AGENCE_IMMO_DIR=TMP):
            html = self.client.get(reverse("biens_financables"), {"ville": "lhay"}).content.decode()
        self.assertIn("jamais revérifié · relevé le 28/09", html)
        self.assertIn('value="verifies"', html)
        self.assertEqual(html.count('data-jamais="1"'), 2)      # ligne du tableau + carte mobile
