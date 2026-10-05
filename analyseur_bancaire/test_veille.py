# analyseur_bancaire/test_veille.py
import json
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from . import biens_gino

TMP = Path(tempfile.mkdtemp())
VILLE = TMP / "creteil"
VILLE.mkdir()
(VILLE / "_gino_laforet-creteil.json").write_text(json.dumps([
    {"type": "Appartement", "lieu": "Créteil", "pieces": 4, "chambres": 4, "surface": 82, "prix": 254000,
     "url": "https://ex/1", "statut": "disponible", "verifie_le": "2026-10-05T21:12",
     "a_verifier": ["4 chambres pour 4 pièces"]},
    {"type": "Appartement", "lieu": "Créteil", "pieces": 3, "surface": 60, "prix": 199000,
     "url": "https://ex/2", "statut": "retire"},
    {"type": "Maison", "lieu": "Créteil", "pieces": 5, "chambres": 3, "surface": 100, "prix": 290000,
     "url": "https://ex/3", "statut": "disponible", "verifie_le": "2026-01-01T10:00"},
]), encoding="utf-8")
(VILLE / "_stan.json").write_text(json.dumps([{"nom": "Laforêt Créteil"}]), encoding="utf-8")
ETAT = {"en_cours": False, "debut": "2026-10-05T21:00", "fin": "2026-10-05T21:12",
        "avancement": {"fait": 1, "total": 1, "agence": "laforet-creteil"},
        "agences": {"laforet-creteil": {"etat": "ok", "verifie_le": "2026-10-05T21:12",
                                        "evenements": {"nouveau": 2}},
                    "orpi-crossard": {"etat": "recette_cassee", "raison": "0 bien lu, 24 au contrôle précédent"},
                    "nina": {"etat": "sans_recette"}}}


ETAT_AVEC_SOUCIS = {**ETAT, "agences": {
    "laforet-creteil": {"etat": "ok", "verifie_le": "2026-10-05T21:12", "evenements": {},
                        "avertissement": "Excel non mis à jour : classeur ouvert"},
    "foncia-creteil": {"etat": "injoignable", "raison": "liste des biens illisible"},
    "nina": {"etat": "sans_recette"}}}


def ecrire_etat(etat=ETAT):
    (VILLE / "_veille_etat.json").write_text(json.dumps(etat), encoding="utf-8")


def verrouiller(debut=None):
    (VILLE / "_veille.lock").write_text(json.dumps({"pid": 1, "debut": debut or time.time()}), encoding="utf-8")


def deverrouiller():
    (VILLE / "_veille.lock").unlink(missing_ok=True)


class LectureEtatTests(SimpleTestCase):
    def setUp(self):
        ecrire_etat()
        deverrouiller()

    def test_retire_masque_et_champs_transmis(self):
        lu = biens_gino.charger_ville(VILLE)
        self.assertEqual([b["url"] for b in lu["biens"]], ["https://ex/1", "https://ex/3"])
        self.assertEqual(lu["masques"], 1)
        self.assertEqual(lu["biens"][0]["a_verifier"], ["4 chambres pour 4 pièces"])
        self.assertEqual(lu["biens"][0]["verifie_le"], "2026-10-05T21:12")

    def test_etat_veille(self):
        self.assertEqual(biens_gino.etat_veille(VILLE)["fin"], "2026-10-05T21:12")
        self.assertIsNone(biens_gino.etat_veille(TMP / "absente"))

    def test_veille_en_cours(self):
        self.assertFalse(biens_gino.veille_en_cours(VILLE))
        verrouiller()
        self.assertTrue(biens_gino.veille_en_cours(VILLE))
        verrouiller(debut=time.time() - 3 * 3600)        # abandonné
        self.assertFalse(biens_gino.veille_en_cours(VILLE))

    def test_agences_veille_noms_et_ordre(self):
        a = biens_gino.agences_veille(VILLE)
        self.assertEqual([x["etat"] for x in a], ["recette_cassee", "sans_recette", "ok"])
        self.assertEqual(a[2]["nom"], "Laforêt Créteil")
        self.assertEqual(a[2]["resume"], "2 nouveau")
        self.assertEqual(a[0]["raison"], "0 bien lu, 24 au contrôle précédent")
        self.assertEqual(a[2]["avertissement"], "")

    def test_agences_veille_remonte_l_avertissement(self):
        ecrire_etat(ETAT_AVEC_SOUCIS)
        a = {x["etat"]: x for x in biens_gino.agences_veille(VILLE)}
        self.assertEqual(a["ok"]["avertissement"], "Excel non mis à jour : classeur ouvert")
        self.assertEqual(a["injoignable"]["avertissement"], "")


@override_settings(AGENCE_IMMO_DIR=TMP)
class LancementTests(SimpleTestCase):
    def setUp(self):
        ecrire_etat()
        deverrouiller()

    def test_bouton_lance_la_verification(self):
        with mock.patch("analyseur_bancaire.views._demarrer_veille", return_value=True) as dem:
            r = self.client.post(reverse("lancer_veille"), {"ville": "creteil"})
        dem.assert_called_once_with(TMP, "creteil")
        self.assertRedirects(r, f"{reverse('biens_financables')}?ville=creteil", fetch_redirect_response=False)

    def test_second_clic_ne_relance_pas(self):
        verrouiller()
        with mock.patch("analyseur_bancaire.views._demarrer_veille") as dem:
            self.client.post(reverse("lancer_veille"), {"ville": "creteil"})
        dem.assert_not_called()

    def test_ville_inconnue_jamais_lancee(self):
        with mock.patch("analyseur_bancaire.views._demarrer_veille") as dem:
            self.client.post(reverse("lancer_veille"), {"ville": "../../etc"})
        dem.assert_not_called()

    def test_get_ne_lance_rien(self):
        with mock.patch("analyseur_bancaire.views._demarrer_veille") as dem:
            r = self.client.get(reverse("lancer_veille"))
        dem.assert_not_called()
        self.assertEqual(r.status_code, 302)

    def test_python_introuvable_signale(self):
        with mock.patch("analyseur_bancaire.views._demarrer_veille", return_value=False):
            r = self.client.post(reverse("lancer_veille"), {"ville": "creteil"})
        self.assertIn("veille=impossible", r["Location"])

    def test_etat_json(self):
        r = self.client.get(reverse("etat_veille"), {"ville": "creteil"})
        self.assertEqual(r.json()["avancement"]["fait"], 1)
        self.assertFalse(r.json()["en_cours"])
        self.assertEqual(self.client.get(reverse("etat_veille"), {"ville": "../x"}).status_code, 404)

    def test_contexte_de_la_page(self):
        r = self.client.get(reverse("biens_financables"), {"ville": "creteil"})
        self.assertEqual(r.context["veille_fin"].strftime("%d/%m %H:%M"), "05/10 21:12")
        self.assertFalse(r.context["veille_en_cours"])
        self.assertEqual(len(r.context["agences_veille"]), 3)
        anciens = {b["url"]: b["jours_sans_verif"] for b in r.context["analyse"]["biens"]}
        self.assertGreater(anciens["https://ex/3"], 7)      # vérifié le 01/01/2026

    def test_demarrer_veille_python_absent(self):
        from .views import _demarrer_veille
        with override_settings(AGENCE_IMMO_PYTHON=TMP / "pas-de-python.exe"):
            self.assertFalse(_demarrer_veille(TMP, "creteil"))

    def test_page_affiche_bouton_et_etat(self):
        r = self.client.get(reverse("biens_financables"), {"ville": "creteil"})
        self.assertContains(r, "Mettre à jour cette ville")
        self.assertContains(r, "Vérifié le 05/10 à 21:12")
        self.assertContains(r, "Recette à réparer")
        self.assertContains(r, "relance Gino sur Orpi Crossard")
        self.assertContains(r, "pas encore de recette")
        self.assertContains(r, "à vérifier")
        self.assertContains(r, "4 chambres pour 4 pièces")
        self.assertContains(r, "non vérifié depuis")
        self.assertContains(r, "Laforêt Créteil</span> — vérifiée (2 nouveau)")

    def test_page_site_injoignable_et_avertissement(self):
        ecrire_etat(ETAT_AVEC_SOUCIS)
        r = self.client.get(reverse("biens_financables"), {"ville": "creteil"})
        self.assertContains(r, "site injoignable au dernier contrôle (données conservées)")
        self.assertNotContains(r, "Recette à réparer")
        self.assertContains(r, "Excel non mis à jour : classeur ouvert")

    def test_page_pendant_un_controle(self):
        verrouiller()
        r = self.client.get(reverse("biens_financables"), {"ville": "creteil"})
        self.assertContains(r, "Vérification en cours")
        self.assertContains(r, 'data-etat-url="')
        deverrouiller()

    def test_page_python_introuvable(self):
        r = self.client.get(reverse("biens_financables"), {"ville": "creteil", "veille": "impossible"})
        self.assertContains(r, "Impossible de lancer la vérification")


class DemarrageTests(SimpleTestCase):
    def setUp(self):
        from . import views
        self.views = views
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        (self.racine / 'veille.py').write_text('', encoding='utf-8')
        (self.racine / 'ville').mkdir()
        self.python = self.racine / 'python.exe'
        self.python.write_text('', encoding='utf-8')

    def _lancer(self, popen, **kw):
        with override_settings(AGENCE_IMMO_PYTHON=str(self.python)), \
                mock.patch('analyseur_bancaire.views.subprocess.Popen', popen):
            return self.views._demarrer_veille(self.racine, 'ville')

    def test_attend_le_verrou(self):
        popen = mock.MagicMock()
        with mock.patch('analyseur_bancaire.views.biens_gino.veille_en_cours',
                        side_effect=[False, False, True]), \
                mock.patch.object(self.views, '_pause_lancement') as pause:
            self.assertTrue(self._lancer(popen))
        popen.assert_called_once()
        # « -u » : journal _veille.log écrit au fil de l'eau, pas à la fin du contrôle.
        self.assertEqual(popen.call_args[0][0], [str(self.python), '-u', 'veille.py', '--ville', 'ville'])
        self.assertEqual(pause.call_count, 2)

    def test_verrou_jamais_vu_rend_la_main(self):
        popen = mock.MagicMock()
        with mock.patch('analyseur_bancaire.views.biens_gino.veille_en_cours',
                        return_value=False), \
                mock.patch.object(self.views, '_pause_lancement') as pause:
            self.assertTrue(self._lancer(popen))
        self.assertEqual(pause.call_count, 50)

    def test_popen_echoue(self):
        popen = mock.MagicMock(side_effect=OSError('boom'))
        self.assertFalse(self._lancer(popen))
