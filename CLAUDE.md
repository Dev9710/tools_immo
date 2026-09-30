# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Contexte

`tools_immo` est une application Django **locale** d'aide au montage d'un dossier de prêt
immobilier : lecture des relevés PDF Banque Postale, tableau de bord des flux du compte, calcul
des charges fixes, simulateur de capacité d'emprunt. Interface et code en français.

Le parcours visé est linéaire : **mesurer ses flux → isoler ses charges fixes → simuler sa
capacité d'emprunt**. `depenses_mensuelles` en est l'écran d'entrée.

## Commandes

Le venv est à la racine du projet (Windows) :

```bash
venv/Scripts/python.exe manage.py runserver      # http://127.0.0.1:8000/
venv/Scripts/python.exe manage.py test           # tests de analyseur_bancaire (simulateur, biens_gino, page biens)
venv/Scripts/pip.exe install -r requirements.txt
```

**Ne jamais lancer `runserver --noreload` pour travailler sur les templates** : Django 4.2 active
`cached.Loader` même avec `DEBUG=True`, et c'est l'autoreloader qui vide ce cache. Sans lui, les
templates restent figés dans l'état où ils étaient au démarrage — on croit alors ses modifications
sans effet.

Pas de `migrate` à lancer, pas de superuser à créer : voir ci-dessous.

### Vérifier une modification du parser

Le projet n'a pas de tests. Le contrôle de référence est la ligne **« Total des opérations »**
imprimée sur chaque relevé : comparer les totaux calculés à ceux du PDF détecte immédiatement un
montant mal lu. `extract_totaux` le fait déjà à chaque analyse, et l'écran affiche le verdict —
c'est le premier endroit à regarder après avoir touché à l'extraction.

## Architecture

### Application sans base de données ni comptes

Choix structurant, à préserver : **rien n'est persisté**. `INSTALLED_APPS` ne contient que
`staticfiles` + `analyseur_bancaire` — `auth`, `contenttypes`, `sessions` et `admin` ont été
retirés volontairement pour supprimer toute exigence de migrations. Les sessions passent par
`signed_cookies` (`SessionMiddleware` sans l'app `sessions`). L'entrée `DATABASES['default']`
n'existe que parce que Django l'exige ; elle n'est jamais sollicitée.

Conséquences :
- `analyseur_bancaire/models.py` est volontairement vide — ne pas y ajouter de modèle sans
  reconsidérer tout ce choix.
- L'état inter-pages tient dans `request.session`, donc dans un cookie de 4 Ko : clés
  `depenses_mensuelles`, `revenus_mensuels` (écrites par le tableau de bord), puis `revenus_nets`,
  `charges_fixes`, `capacite_emprunt`, `mensualite_max`, `apport`, `duree` (écrites par le
  simulateur). **Une analyse complète n'y tient pas** — d'où le choix décrit plus bas de faire
  porter cet état par la page elle-même.
- Les PDF uploadés vont dans un `NamedTemporaryFile` supprimé dans un `finally`, et les Excel
  générés sont lus puis `os.unlink`. Aucun fichier utilisateur ne doit rester sur disque.

### Dépendances optionnelles

`pdfplumber`, `openpyxl` et `reportlab` sont dans `requirements.txt` mais traités comme
**optionnels** dans le code : imports tardifs, à l'intérieur des fonctions, avec un repli explicite
(texte brut sans sens débit/crédit, CSV zippé, message d'erreur). Ne pas les remonter en tête de
module : un import global ferait échouer l'application entière si l'un manque, et rendrait ces
replis inatteignables.

### Tout tient dans `analyseur_bancaire/views.py`

Fichier unique (~2 200 lignes), en quatre blocs.

#### 1. `SimulateurPretImmobilier` — règles métier de crédit

Constantes en tête de fichier : `TAUX_ACTUELS` (taux par région × durée, ajustement par profil,
taux d'assurance par tranche d'âge) et `FRAIS_NOTAIRE` (8 % ancien / 3 % neuf). Deux calculs déjà
corrigés, à ne pas « resimplifier » :

- la règle HCSF (35 %) plafonne le **total** des charges :
  `mensualite_max = 35 % × revenus − charges existantes` ;
- le prix d'achat max s'obtient en inversant les frais de notaire (`prix = budget / (1 + taux)`),
  sinon les frais ne sont couverts par rien.

#### 2. `BanquePostaleParserSimple` — extraction des opérations

Deux chemins, dans cet ordre :

- **chemin nominal** `extract_word_lines` + `parse_operations_lines` : pdfplumber donne les mots
  *positionnés*. Le sens débit/crédit vient de la **géométrie** — l'abscisse `x1` du montant
  comparée à un seuil calculé depuis les en-têtes « Débit »/« Crédit » (repli
  `SEUIL_PAR_DEFAUT = 503.0`).
- **repli texte** `extract_text_from_pdf` + `parse_operations_section`, uniquement si pdfplumber
  est absent : `sens` vaut alors `None`, l'information est perdue.

Trois garde-fous encadrent cette extraction. Chacun corrige un bug qui produisait des chiffres
faux **sans le moindre signe d'erreur** — c'est ce qui les rend indispensables :

1. **`_recoller_milliers`** — pdfplumber découpe « 8 157,80 » en deux mots (« 8 » puis
   « 157,80 ») et seul le second était reconnu comme montant. Tout montant ≥ 1 000 € perdait ses
   milliers : loyers, salaires, gros virements. Les fragments sont refusionnés quand le mot de
   gauche fait 1 à 3 chiffres, celui de droite un groupe de centaines complet, et l'écart
   horizontal reste sous `ECART_MAX_FRAGMENTS`.
2. **`_bornes_entete`** — n'accepte les en-têtes Débit/Crédit que **sur une même ligne** et à
   droite de `X_MIN_COLONNES` (300). Sans ces conditions, le « CREDIT » de « CREDIT CARTE
   BANCAIRE » (x≈117) servait de frontière : le seuil tombait à ~97, tous les montants passaient
   en crédit, et le relevé entier ressortait avec zéro dépense.
3. **`extract_totaux`** — relit la ligne « Total des opérations » du relevé pour la comparer aux
   totaux calculés. Seul contrôle indépendant disponible ; voir « Vérifier une modification du
   parser » plus haut.

**L'année ne se lit pas dans la première date du document** : les mentions légales en contiennent
(« PEL ouvert jusqu'au 31/12/2017 ») et dataient les relevés récents de plusieurs années.
`build_year_resolver` part de « Relevé édité le 12 septembre 2025 » et renvoie une fonction
mois → année qui recule d'un an pour les mois postérieurs à l'édition — un relevé à cheval sur le
31 décembre est ainsi daté correctement. `extract_periode` en déduit la fenêtre du relevé
(`édition − 1 mois` → `édition − 1 jour`), ou lit un « du JJ/MM/AAAA au JJ/MM/AAAA » présent en
en-tête (validé entre 25 et 35 jours, pour écarter les couples de dates des mentions légales).

La catégorisation (`achat`/`virement`/`depot`/`debit`/`cheque`/`autre`) reste par mots-clés et
n'est qu'**indicative** : elle se trompe régulièrement de sens. Toute évolution du parser doit
garder la géométrie comme source de vérité du sens, et les mots-clés pour le seul classement par
type.

#### 3. Analyse des flux

`analyser_flux_mensuels` et ses fonctions d'appui — détaillé dans la section suivante.

#### 4. Vues + exports

`accueil`, `depenses_mensuelles`, `export_depenses_excel`, `upload_releve`, `charges_fixes`,
`simulateur_pret`, `dashboard_dossier`, `export_dossier_pdf` (routes dans
`analyseur_bancaire/urls.py`). Excel via openpyxl avec **repli CSV zippé**
(`create_excel_multi_onglets` → `create_csv_multi_files`) ; PDF de synthèse via reportlab.

### `depenses_mensuelles` : le tableau de bord des flux

L'écran central. Répond à « combien sort et combien rentre chaque mois, et pourquoi ». Un POST,
N relevés PDF, tout le résultat sur une seule page : indicateurs clés, comparatif entrées/sorties,
postes récurrents, lignes ajoutées à la main, détail complet des opérations.

**Mois civils entiers uniquement.** Un relevé court du 12 au 11 : aucun ne contient un mois civil
à lui seul, mais deux relevés consécutifs se complètent. **N relevés qui se suivent = N−1 mois
complets** (4 relevés → 3 mois, 6 → 5). Les bords partiels sont écartés et listés dans
`mois_ecartes`.

Mécanique, dans l'ordre :

1. `parse_pdf(chemin)` **sans** `types_selectionnes` renvoie tous les types, `autre` compris :
   aucune opération ne doit être perdue à cause d'un libellé non reconnu.
2. `_dedupliquer` retire les opérations comptées deux fois — **uniquement dans les zones couvertes
   par plusieurs relevés**. Ailleurs, deux opérations identiques le même jour sont deux vraies
   dépenses et doivent rester.
3. `_fusionner_periodes` recolle les relevés en segments continus, avec une tolérance de
   `ECART_MAX_SANS_OPERATION` (20 jours). Quand la période n'a pas pu être lue dans le PDF, les
   bornes viennent des opérations : quelques jours sans mouvement entre deux relevés créaient
   alors un faux trou qui écartait le mois entier. Un relevé réellement manquant creuse ~30 jours,
   donc au-delà du seuil — il reste signalé dans `trous`.
4. Un mois n'est retenu que si `[1er, dernier jour]` tient dans un segment.

**Rien n'échoue en silence.** Un fichier qui n'apporte aucune opération remonte dans
`releves_muets` (bandeau rouge) et dans `detail_releves` — c'est la cause la plus fréquente d'un
trou apparent alors que les relevés se suivent bien. `detail_releves` alimente le tableau « ce que
chaque relevé a couvert » (fichier, période, nombre d'opérations, période lue ou déduite, verdict
du contrôle des totaux) : c'est l'outil de diagnostic à regarder en premier quand la couverture
surprend. Sans aucun mois complet, la fonction renvoie `None` et la vue explique la règle N+1 avec
la couverture réelle des fichiers fournis.

**Postes récurrents.** `_cle_poste` retire les préfixes de type d'opération, les chiffres et la
ponctuation, puis garde deux mots : « ACHAT CB CARREFOUR 1234 » et « CARREFOUR.FR » convergent
sans fusionner deux commerçants distincts. Un poste porte sa fréquence (part des mois où il
apparaît) et son montant mensuel moyen — c'est la base pour distinguer une charge fixe d'une
dépense ponctuelle. Le serveur rend **toutes** les lignes ; le seuil (`SEUIL_RECURRENCE_PAR_DEFAUT`
= 40 %) n'est qu'un filtre JS sur `data-frequence`.

**Lignes ajoutées à la main** (une assurance souscrite, pas encore prélevée). Elles vivent **dans
la page**, en JavaScript, et recalculent les indicateurs en direct. Ce n'est pas un raccourci :
sans base de données, et avec une session limitée à un cookie de 4 Ko, le serveur ne peut pas
conserver l'analyse entre deux requêtes. Contrepartie assumée : **un rechargement de page les
perd**.

**`export_depenses_excel`** est sans état : la page lui renvoie `analyse_json` (l'analyse
sérialisée, embarquée dans un champ caché) plus les lignes manuelles et le seuil de récurrence,
et produit six onglets — Synthèse, Mois par mois, Postes récurrents, Opérations, Lignes ajoutées,
Relevés. L'export reflète donc exactement ce que l'utilisateur avait sous les yeux. En GET, la vue
redirige vers le tableau de bord.

Enfin, `sorties_moyennes` et `entrees_moyennes` vont en session pour préremplir charges **et**
revenus du simulateur, avec la mention de leur provenance. C'est le seul état partagé entre écrans.

`format_euros` fait le séparateur de milliers français en espace fine insécable U+202F (`intcomma`
de humanize produit une virgule anglo-saxonne, et l'app n'installe pas humanize) : comme tout le
formatage, il vit dans la vue.

**Virements internes (30/09).** Un virement vers/depuis un titulaire du compte (noms lus dans
l'en-tête du relevé par `extract_titulaires`, jamais écrits dans le code ; tolérance d'une faute :
DUPONT/DUPPONT) ou vers l'épargne (Livret, LDDS, PEL…) est marqué `interne` par
`est_virement_interne` : exclu des entrées, des sorties et des postes récurrents, affiché à part
(« Épargne et virements entre tes comptes »). Le bénéficiaire vient de la ligne SOUS l'opération
(`complement` dans le parser). Le contrôle des totaux du relevé, lui, voit toutes les opérations.

**Charges du simulateur (30/09).** `charges_bancaires` ne retient que les crédits récurrents
(prêteurs/échéances) → session `charges_credits` ; le loyer (`loyer_actuel`) est à part pour le
« saut de charge ». Avant, TOUTES les sorties allaient dans les charges : endettement faux.

**Taux (30/09).** RÈGLE utilisateur : toujours les taux les plus récents. `TAUX_ACTUELS` porte sa
date (`TAUX_DATE`, `TAUX_SOURCE`) ; `bareme_info()` l'affiche sur toutes les pages (context
processor) et alerte au-delà de 30 jours. Le taux dépend de la durée : `taux_pour_duree()`
interpole entre les paliers ; sur « Biens finançables », changer la durée ajuste le taux en
gardant l'écart au barème (profil, négociation). Les tests lisent la table, jamais un taux en dur.

### Parcours « charges fixes » en deux POST

`charges_fixes` est une machine à états dans une seule vue :

1. POST avec `fichier_pdf1` / `fichier_pdf2` → parsing, agrégation des mois disponibles, rendu de
   `selection_charges.html` (les opérations sont sérialisées en JSON dans le template) ;
2. POST avec `selected_operations` (JSON) + `mois_filtre` → filtrage, total, Excel en
   téléchargement.

Attention aux formats de date : les opérations arrivent en `jj/mm/AAAA`, le filtre mois en
`mm/AAAA` ; la comparaison se fait sur le couple mois/année, pas sur un préfixe de chaîne.

Cet écran s'appuie encore sur la catégorisation par mots-clés, avec un filtre `sens != 'credit'`
pour écarter les entrées mal classées.

### `simulateur_pret` : deux modes

POST JSON ou form, champ `mode` :

- `capacite` : capacité d'emprunt, prix max, frais de notaire, reste à vivre, **écrit en session** ;
- `mensualite` : mensualité + tableau d'amortissement, **n'écrit rien en session**.

Réponse toujours `JsonResponse({'success': bool, ...})`, jamais un code HTTP d'erreur.

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

### Templates

`templates/analyseur/`, tous héritant de `base.html` (Bootstrap 5 + bootstrap-icons via CDN, thème
jaune/or Banque Postale). Les templates Django n'ayant pas d'arithmétique, **tout calcul est fait
dans la vue** avant le rendu (cf. `taux_endettement` dans `dashboard_dossier`).

`depenses_mensuelles.html` (~900 lignes) porte deux états dans un seul fichier — formulaire
d'upload si `analyse` est absent, tableau de bord sinon — plus son CSS et son JS en blocs
`extra_css` / `extra_js`. Le JS distingue les deux états sur la présence de `#fichiersPdf` puis
sort. La page rendue pèse plusieurs centaines de Ko avec quelques centaines d'opérations : c'est
assumé (aucun aller-retour serveur ensuite), mais à surveiller si le volume grandit.

Deux détails d'accessibilité à ne pas casser : l'input fichier est masqué visuellement mais reste
**focusable** (`d-none` le sortirait de l'ordre de tabulation, la dropzone porte l'indicateur de
focus via `:focus-within`), et les valeurs injectées en JS passent par `textContent`, jamais par
`innerHTML`.

## Données sensibles

`.gitignore` exclut `analyseur_bancaire/data/` (relevés bancaires réels), `*.xlsx`, `db.sqlite3`
et `.env`. L'historique git a été purgé de ces fichiers — ne jamais réintroduire de relevé ou
d'export dans un commit.
