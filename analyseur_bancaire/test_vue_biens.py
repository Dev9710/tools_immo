import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from .views import TAUX_ACTUELS

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
        self.assertContains(r, "Complétez votre profil")
        self.assertContains(r, "valeurs par défaut")

    def test_profil_saisi_donne_les_verdicts(self):
        r = self.client.post(reverse("biens_financables"), PROFIL, follow=True)
        self.assertContains(r, "Finançable")
        self.assertContains(r, "Hors budget")
        self.assertContains(r, "votre saisie")
        self.assertEqual(self.client.session["profil_biens"]["taux_nominal"], 3.33)

    def test_ville_inconnue_retombe_sur_la_premiere_ville(self):
        """Une ville absente de la liste (faute de frappe ou tentative de path traversal) ne
        sert jamais à construire un chemin : on retombe sur la première ville connue, pour que
        le sélecteur affiché et la liste chargée restent cohérents."""
        r = self.client.get(reverse("biens_financables"), {"ville": "../../etc"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["ville"]["slug"], "fresnes")
        self.assertNotContains(r, "../../etc")

    @override_settings(AGENCE_IMMO_DIR=TMP / "absent")
    def test_dossier_gino_introuvable(self):
        r = self.client.get(reverse("biens_financables"))
        self.assertContains(r, "AGENCE_IMMO_DIR")

    def test_duree_hors_bornes_repli_sur_defaut(self):
        for duree in ("0", "-5", "40"):
            r = self.client.post(reverse("biens_financables"), {**PROFIL, "duree": duree},
                                  follow=True)
            self.assertEqual(r.status_code, 200, duree)
            self.assertEqual(self.client.session["profil_biens"]["duree"], 20, duree)

    def test_montants_negatifs_ramenes_a_zero(self):
        r = self.client.post(reverse("biens_financables"),
                              {**PROFIL, "revenus": "-100", "charges": "-50", "apport": "-1000",
                               "nb_adultes": "-2", "nb_enfants": "-1"}, follow=True)
        self.assertEqual(r.status_code, 200)
        p = self.client.session["profil_biens"]
        self.assertEqual(p["revenus"], 0.0)
        self.assertEqual(p["charges"], 0.0)
        self.assertEqual(p["apport"], 0.0)
        self.assertEqual(p["nb_adultes"], 2)
        self.assertEqual(p["nb_enfants"], 0)

    def test_valeurs_non_finies_repli_sur_defaut(self):
        """nan/inf saisis (via une saisie manuelle de l'URL ou du formulaire) ne doivent
        jamais atteindre le calcul de mensualité ni s'afficher tels quels."""
        r = self.client.post(reverse("biens_financables"),
                              {**PROFIL, "nb_adultes": "inf", "taux_nominal": "nan"}, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'value="nan"')
        self.assertNotContains(r, 'value="inf"')
        p = self.client.session["profil_biens"]
        self.assertEqual(p["nb_adultes"], 2)
        self.assertEqual(p["taux_nominal"], TAUX_ACTUELS['regions']['ile_de_france']['20'])  # défaut = barème du jour

    def test_taux_negatif_repli_sur_defaut(self):
        r = self.client.post(reverse("biens_financables"),
                              {**PROFIL, "taux_nominal": "-1", "taux_assurance": "-0.5"},
                              follow=True)
        self.assertEqual(r.status_code, 200)
        p = self.client.session["profil_biens"]
        self.assertEqual(p["taux_nominal"], TAUX_ACTUELS['regions']['ile_de_france']['20'])  # défaut = barème du jour
        self.assertEqual(p["taux_assurance"], 0.2)

    def test_donnees_numeriques_non_localisees_dans_les_data_attributes(self):
        """Les data-* numériques doivent rester en point décimal (format JS), jamais en
        virgule française, sous peine de fausser le tri et les filtres côté client."""
        r = self.client.get(reverse("biens_financables"), {"ville": "fresnes"})
        self.assertContains(r, 'data-ecart="-0.')
        self.assertNotContains(r, 'data-surface="82,0"')
        self.assertNotContains(r, 'data-prix="209000,0"')

    def test_duree_max_30_ans(self):
        r = self.client.get(reverse("biens_financables"), {"ville": "fresnes"})
        self.assertContains(r, 'max="30"')
        self.assertNotContains(r, 'max="27"')

    def test_note_prix_max_hors_reste_a_vivre(self):
        r = self.client.post(reverse("biens_financables"), PROFIL, follow=True)
        self.assertContains(r, "hors reste à vivre")

    def test_ville_sans_bien_affiche_un_etat_vide(self):
        vide = TMP / "vide"
        vide.mkdir(exist_ok=True)
        (vide / "_gino_agence.json").write_text(json.dumps([
            {"type": "Parking", "lieu": "Vide", "prix": "10 000 €", "url": "https://ex/parking"},
        ]), encoding="utf-8")
        r = self.client.get(reverse("biens_financables"), {"ville": "vide"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Aucun bien")
        self.assertNotContains(r, "<table")


class NavigationTests(SimpleTestCase):
    """Le lien « Biens finançables » doit être visible depuis toutes les pages, y compris
    celles qui redéfinissent le bloc nav_buttons."""

    def test_lien_biens_financables_visible_partout(self):
        for nom_url in ("simulateur_pret", "dashboard", "charges_fixes", "upload_releve"):
            r = self.client.get(reverse(nom_url))
            self.assertContains(r, "Biens finançables", msg_prefix=nom_url)

    def test_lien_biens_financables_apres_simulation(self):
        r = self.client.get(reverse("simulateur_pret"))
        self.assertContains(r, "Voir les biens à ce prix")


class VraiesDonneesTests(SimpleTestCase):
    """Bout en bout sur les vrais fichiers de Gino, s'ils sont présents sur ce poste."""

    def test_fresnes_reel(self):
        if not (Path(settings.AGENCE_IMMO_DIR) / "fresnes").is_dir():
            self.skipTest("données de Gino absentes")
        r = self.client.get(reverse("biens_financables"), {"ville": "fresnes"})
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.context["analyse"]["resume"]["total"], 50)


class TauxPerimeEnSessionTests(SimpleTestCase):
    """Un taux gardé en session depuis un ancien barème est remis au barème du jour."""

    def _session(self, **valeurs):
        s = self.client.session
        s.update(valeurs)
        s.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = s.session_key

    def test_simulation_d_un_ancien_bareme_actualisee(self):
        self._session(revenus_nets=4200.0, taux_nominal=3.12, taux_assurance=0.20, duree=25)
        r = self.client.get(reverse('biens_financables'))
        from .views import taux_pour_duree
        self.assertEqual(r.context['profil'].taux_nominal, taux_pour_duree(25))
        self.assertContains(r, 'remis au barème du')

    def test_simulation_du_bareme_courant_gardee(self):
        from .views import TAUX_DATE
        self._session(revenus_nets=4200.0, taux_nominal=3.40, taux_assurance=0.20, duree=20,
                      bareme_date=TAUX_DATE.isoformat())
        r = self.client.get(reverse('biens_financables'))
        self.assertEqual(r.context['profil'].taux_nominal, 3.40)
        self.assertNotContains(r, 'remis au barème du')

    def test_saisie_d_un_ancien_bareme_actualisee(self):
        self._session(profil_biens={'revenus': 4200.0, 'charges': 0.0, 'apport': 50000.0, 'duree': 25,
                                    'taux_nominal': 3.12, 'taux_assurance': 0.2, 'primo': True,
                                    'nb_adultes': 2, 'nb_enfants': 0})
        r = self.client.get(reverse('biens_financables'))
        from .views import taux_pour_duree
        self.assertEqual(r.context['profil'].taux_nominal, taux_pour_duree(25))

    def test_saisie_recente_gardee(self):
        self.client.post(reverse('biens_financables'), {'revenus': '4200', 'charges': '0', 'apport': '0',
                         'duree': '20', 'taux_nominal': '3,30', 'taux_assurance': '0.20'})
        r = self.client.get(reverse('biens_financables'))
        self.assertEqual(r.context['profil'].taux_nominal, 3.30)
