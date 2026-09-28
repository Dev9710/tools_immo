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
