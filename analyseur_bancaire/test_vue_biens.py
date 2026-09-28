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
