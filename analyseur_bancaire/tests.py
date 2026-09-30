import json

from django.test import SimpleTestCase
from django.urls import reverse

from .views import FRAIS_NOTAIRE, TAUX_ACTUELS, SimulateurPretImmobilier


class BaremesTests(SimpleTestCase):
    def test_taux_fin_septembre_2026(self):
        # Meilleurtaux 29/09/2026, profil « bon » = notre « moyen » national
        self.assertEqual(TAUX_ACTUELS['regions']['autre']['20'], 3.64)
        self.assertEqual(TAUX_ACTUELS['regions']['autre']['25'], 3.73)
        self.assertEqual(TAUX_ACTUELS['regions']['ile_de_france']['20'], 3.56)
        self.assertEqual(TAUX_ACTUELS['assurance']['30_45'], 0.20)

    def test_date_du_bareme_et_alerte(self):
        from datetime import date
        from .views import TAUX_DATE, bareme_info
        self.assertEqual(TAUX_DATE, date(2026, 9, 29))
        frais = bareme_info(date(2026, 10, 5))
        self.assertEqual((frais['date'], frais['perime']), ('29/09/2026', False))
        self.assertTrue(bareme_info(date(2026, 11, 5))['perime'])   # plus de 30 jours

    def test_date_affichee_sur_les_pages(self):
        for nom in ('simulateur_pret', 'biens_financables'):
            self.assertContains(self.client.get(reverse(nom)), '29/09/2026')

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
        self.assertEqual(s['taux_nominal'], TAUX_ACTUELS['regions']['ile_de_france']['20'])
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


class VirementsInternesTests(SimpleTestCase):
    """Un virement entre ses propres comptes (ou vers l'épargne du foyer) n'est ni une dépense ni un revenu."""

    def test_titulaires_lus_dans_l_entete(self):
        from .views import BanquePostaleParserSimple
        p = BanquePostaleParserSimple()
        lignes = ["Clients 45900 LA SOURCE CEDEX", "MR DUPONT OU MME DUPONT MARTIN",
                  "Mme PRIEUR FLORENCE APPARTEMENT 55"]
        self.assertEqual(p.extract_titulaires(lignes), ['DUPONT', 'MARTIN'])

    def test_reconnaissance(self):
        from .views import est_virement_interne as interne
        t = ['DUPONT', 'MARTIN']
        op = lambda d, c='': {'description': d, 'complement': c}
        self.assertTrue(interne(op('VIREMENT INSTANTANE A', 'DUPONT JEAN Economie'), t))
        self.assertTrue(interne(op('VIREMENT PERMANENT POUR', 'M DUPPONT JEAN COMPTE FR76'), t))  # 1 faute de frappe
        self.assertTrue(interne(op('VIREMENT INSTANTANE A', 'MME DUPONT MARTIN ALICE Livret A'), t))
        self.assertTrue(interne(op('VIREMENT DE MR JEAN DUPONT'), t))                   # entrée interne
        self.assertTrue(interne(op('VIREMENT POUR', 'X COMPTE LDDS'), []))                # mot d'épargne
        self.assertFalse(interne(op('VIREMENT PERMANENT POUR', 'BOX COMPTE FR76 BOX NUMERO 1'), t))
        self.assertFalse(interne(op('VIREMENT DE HIGHTEKERS', 'PAIE AVRIL'), t))           # salaire
        self.assertFalse(interne(op('PRELEVEMENT DE DUPONT ASSURANCES'), t))              # pas un virement
        self.assertFalse(interne(op('VIREMENT POUR', 'ECHEANCE PRET CAISSE D EPARGNE'), t))  # un crédit

    def test_exclus_des_depenses_et_revenus(self):
        from decimal import Decimal
        from datetime import date
        from .views import analyser_flux_mensuels
        def o(j, desc, m, sens, comp=''):
            return {'date': date(2026, 4, j), 'description': desc, 'libelle': desc, 'complement': comp,
                    'montant': Decimal(m), 'sens': sens, 'type': 'autre'}
        releve = {'nom': 'a.pdf', 'periode': (date(2026, 3, 30), date(2026, 5, 2)), 'totaux_releve': None,
                  'titulaires': ['DUPONT'],
                  'operations': [o(2, 'VIREMENT DE ACME', '3000', 'credit', 'PAIE'),
                                 o(3, 'ACHAT CB LECLERC', '400', 'debit'),
                                 o(4, 'VIREMENT INSTANTANE A', '1000', 'debit', 'DUPONT JEAN Livret A'),
                                 o(5, 'VIREMENT DE MR JEAN DUPONT', '200', 'credit')]}
        a = analyser_flux_mensuels([releve])
        self.assertEqual(a['resume']['sorties_moyennes'], 400.0)
        self.assertEqual(a['resume']['entrees_moyennes'], 3000.0)
        self.assertEqual(a['resume']['internes_sortants_moyens'], 1000.0)
        self.assertEqual(a['resume']['internes_entrants_moyens'], 200.0)
        self.assertNotIn('LIVRET', ' '.join(p['exemple'].upper() for p in a['postes_recurrents']))


class TauxSelonDureeTests(SimpleTestCase):
    """Le taux dépend de la durée : 25 ans coûte plus cher que 20 ans."""

    def test_durees_du_bareme_et_interpolation(self):
        from .views import taux_pour_duree
        idf = TAUX_ACTUELS['regions']['ile_de_france']
        self.assertEqual(taux_pour_duree(20), idf['20'])
        self.assertEqual(taux_pour_duree(25), idf['25'])
        self.assertAlmostEqual(taux_pour_duree(22), idf['20'] + (idf['25'] - idf['20']) * 2 / 5, places=2)
        self.assertEqual(taux_pour_duree(30), idf['25'])      # au-delà du barème : dernier palier
        self.assertEqual(taux_pour_duree(5), idf['7'])
        self.assertGreater(taux_pour_duree(25), taux_pour_duree(20))

    def test_page_biens_embarque_le_bareme_par_duree(self):
        r = self.client.get(reverse('biens_financables'))
        self.assertContains(r, 'id="bareme-durees"')
