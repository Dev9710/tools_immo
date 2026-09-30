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


def _poste(exemple, moyen, nb_mois=3, sens='debit', frequence=100):
    return {'poste': exemple.upper()[:20], 'exemple': exemple, 'sens': sens,
            'nb_mois': nb_mois, 'frequence': frequence,
            'montant_moyen': moyen, 'montant_total': moyen * nb_mois}


class ChargesBancairesTests(SimpleTestCase):
    """Seuls les crédits en cours comptent dans l'endettement ; le loyer est à part."""

    def test_credits_seuls_dans_les_charges(self):
        from .views import charges_bancaires
        postes = [
            _poste('PRLV SEPA COFIDIS', 120.0),
            _poste('ECHEANCE PRET 0123456', 250.0),
            _poste('PRLV LOYER FONCIA', 950.0),
            _poste('ACHAT CB CARREFOUR', 400.0),
            _poste('PRLV FREE MOBILE', 20.0),
            _poste('VIR COFIDIS REMBOURSEMENT', 50.0, sens='credit'),   # une entrée
            _poste('PRLV SEPA CETELEM', 90.0, nb_mois=1, frequence=33),  # ponctuel
        ]
        c = charges_bancaires(postes, nb_mois=3)
        self.assertEqual(c['credits_mensuels'], 370.0)
        self.assertEqual([p['exemple'] for p in c['credits']],
                         ['ECHEANCE PRET 0123456', 'PRLV SEPA COFIDIS'])
        self.assertEqual(c['loyer_mensuel'], 950.0)

    def test_moyenne_sur_tous_les_mois_complets(self):
        from .views import charges_bancaires
        # vu 2 mois sur 3 (≥ 50 %) : la moyenne mensuelle se fait sur les 3 mois
        c = charges_bancaires([_poste('PRLV SOFINCO', 150.0, nb_mois=2, frequence=67)], nb_mois=3)
        self.assertEqual(c['credits_mensuels'], 100.0)

    def test_rien_trouve(self):
        from .views import charges_bancaires
        c = charges_bancaires([_poste('ACHAT CB LECLERC', 300.0)], nb_mois=2)
        self.assertEqual((c['credits_mensuels'], c['loyer_mensuel'], c['credits']), (0.0, 0.0, []))


class SimulateurPreremplissageTests(SimpleTestCase):
    def test_charges_preremplies_avec_les_credits_pas_les_depenses(self):
        s = self.client.session
        s['depenses_mensuelles'] = 2800.0      # toutes les sorties : ne doit PAS aller dans les charges
        s['charges_credits'] = 370.0
        s['loyer_actuel'] = 950.0
        s.save()
        # sessions en cookie signé : la clé EST le contenu, à remettre dans le cookie
        from django.conf import settings
        self.client.cookies[settings.SESSION_COOKIE_NAME] = s.session_key
        r = self.client.get(reverse('simulateur_pret'))
        self.assertContains(r, 'name="charges_mensuelles" min="0" step="50" value="370"')
        self.assertContains(r, 'loyer')
