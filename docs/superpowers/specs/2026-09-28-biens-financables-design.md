# Biens finançables — conception

Date : 28/09/2026 · Statut : validée en conversation, à relire avant le plan.

## 1. Boussole

**tools_immo aide à comprendre sa situation financière et à bien monter son dossier.**
La page « Biens finançables » répond à une seule question :
**« Sur quel prix puis-je m'engager — et lequel de ces biens réels est à ma portée ? »**

Ton de tous les textes affichés :
- puces et phrases simples ;
- peu de texte ;
- l'utilisateur est **guidé et en confiance** : chaque état dit quoi faire ensuite, jamais d'impasse.

## 2. Périmètre

- **Dans le périmètre** : une page qui lit les biens relevés par Gino pour une ville et
  calcule, bien par bien, le coût du crédit et un verdict de financement ; mise à jour des
  barèmes (taux, assurance, frais de notaire) pour tout tools_immo.
- **Hors périmètre (plus tard)** : tools_immo écrit `criteres.json` pour Gino (« sens 1 ») ;
  envoi manuel d'un fichier ; charges de copropriété et taxe foncière (Gino ne les relève pas).

## 3. Contrat avec Stan & Gino

Stan & Gino restent un **projet séparé** (futur SaaS). Aucun code partagé : tools_immo
**lit seulement** leurs fichiers.

- Dossier racine réglable : setting `AGENCE_IMMO_DIR` (surchargeable par variable
  d'environnement), par défaut `../tools/scraping/agence-immo`.
- Une ville = un sous-dossier contenant des `_gino_<agence>.json` (liste de biens).
- Champs lus (tous optionnels sauf `url`) : `type`, `lieu`, `pieces`, `chambres`, `annee`,
  `dpe`, `surface`, `surface_terrain`, `prix`, `url`, `statut`.
- Nom de l'agence : déduit du nom de fichier, ou de `_stan.json` s'il existe.
- Date du relevé : date de modification la plus récente des fichiers de la ville.
- **Tout ce qui dépend de ce format vit dans un seul module** (`biens_gino.py`).
- Les `_gino_*.json` contiennent **tous** les biens de l'agence (vérifié : Nestenn Champigny
  40 biens, dont 1 seul passe `criteres.json`). C'est eux qu'on lit — pas les onglets Excel,
  déjà filtrés.
- **`criteres.json` n'est pas utilisé par la page** : il reste un réglage de Gino. Principe :
  **tout afficher, le verdict fait la distinction entre le possible et l'impossible**.

## 4. Calcul, bien par bien

Réutilise `SimulateurPretImmobilier` (`calculer_mensualites`, `calculer_frais_notaire`,
`calculer_reste_a_vivre`).

1. **Neuf ou ancien** : neuf si `annee` ≥ 2025 ou titre/type contenant « neuf », « VEFA »,
   « livraison » ; sinon ancien (hypothèse prudente).
2. **Frais de notaire** : ancien 8 % ; **ancien primo-accédant 7,5 %** (exonéré de la hausse
   des droits de mutation 2026) ; neuf 3 %.
3. **Emprunt** = prix + frais de notaire − apport (jamais négatif).
4. **Mensualité** : sur la durée et au taux du profil, **assurance comprise** (méthode « taux
   tout compris », comme le calculateur de La finance pour tous référencé par Service-Public).
5. **Endettement** = (charges actuelles + mensualité) ÷ revenus.
6. **Verdict** :
   - ≤ 35 % → **Finançable** ;
   - 35 à 40 % → **Limite** (dérogation possible, à négocier) ;
   - > 40 % → **Hors budget** ;
   - reste à vivre insuffisant (règle existante : 400 €/adulte, 300 €/enfant) → **Hors budget**.
7. **Alerte énergie** : DPE F ou G.
8. **Prix au m² vs ville** : écart à la médiane des biens de la même ville.

Rendu honnête : « coût mensuel hors charges de copropriété et taxe foncière ».

## 5. Profil financier

- Prérempli depuis la session du simulateur s'il a tourné ; **modifiable sur la page**.
- Le simulateur enregistre en plus en session : `taux_nominal`, `taux_assurance`, `nb_adultes`,
  `nb_enfants`, `primo_accedant`.
- Sans simulation : valeurs par défaut (Île-de-France, 20 ans, profil moyen, 30-45 ans),
  **signalées comme telles**.
- Sans revenus : la liste s'affiche sans verdict, avec l'invitation à compléter le profil.

## 6. Barèmes septembre 2026 (tout tools_immo)

Taux nominaux hors assurance, profil « moyen » (moyenne Meilleurtaux 01/09 et Pretto 20/09) :

| Durée | 7 | 10 | 15 | 20 | 25 |
|---|---|---|---|---|---|
| autre (national) | 3,25 | 3,30 | 3,32 | 3,41 | 3,50 |
| île-de-France (−0,08) | 3,17 | 3,22 | 3,24 | 3,33 | 3,42 |
| provence (−0,03) | 3,22 | 3,27 | 3,29 | 3,38 | 3,47 |
| rhône-alpes (−0,06) | 3,19 | 3,24 | 3,26 | 3,35 | 3,44 |

Profils inchangés (−0,30 / −0,15 / 0 / +0,25). Assurance (délégation) : 0,10 % (< 30 ans),
0,20 % (30-45), 0,40 % (45 +). Frais de notaire : voir § 4. Règle HCSF 35 % : inchangée.
Chaque barème porte sa date et ses sources en commentaire.

## 7. La page

De haut en bas :
1. **En-tête** : « Biens finançables » · choix de la ville · date du dernier relevé Gino.
2. **Carte « Ton profil »** : champs + étiquette « repris de ta simulation » / « valeurs par
   défaut, à ajuster » + bouton **Recalculer**.
3. **Chiffres clés** : nb finançables · nb limites · nb hors budget · prix maximum finançable.
4. **Filtres** instantanés (sans rechargement) : verdict, type, surface, pièces, chambres min.
   **Vides à l'ouverture** : tous les biens d'habitation s'affichent (voir § 3).
5. **Liste** : tableau triable (desktop, en-tête collant ; tri par défaut : verdict puis prix
   au m² vs ville) ; **cartes sur mobile**.
   - Verdict : pastille **couleur + icône + mot** (jamais la couleur seule).
   - DPE : pastille aux couleurs officielles A→G, lettre visible, icône d'alerte si F/G.
   - Chiffres alignés à droite ; doublons regroupés (« Primo + L'Adresse », un lien par agence).
6. **États vides** : dossier Gino introuvable · aucune ville · aucun résultat (bouton
   « réinitialiser les filtres ») · profil vide.

Style : **Bootstrap 5 et Bootstrap Icons déjà en place** (cohérence avec les autres pages ;
pas d'émojis, pas de nouveau thème). 21st.dev sert d'inspiration, réécrite en Bootstrap.

## 8. Robustesse

- Bien sans prix : affiché en gris, « prix non affiché », sans verdict.
- Bien sans surface : sans prix au m², verdict calculé.
- DPE vide / « en cours » : pastille grise « n.c. ».
- Fichier illisible : ignoré, bandeau « 1 fichier ignoré : … », la page s'affiche.
- `statut` vendu / sous compromis : masqué, compté (« 3 biens sous compromis masqués »).
- Types hors habitation (parking, terrain, local, immeuble, commerce) : exclus.
- **Doublons** : même type, même ville, prix à 1 % près et surface à 1 m² près → une ligne.
- Rien n'est écrit sur disque ; pas de base de données (choix structurant de tools_immo).

## 9. Organisation du code

- `analyseur_bancaire/biens_gino.py` : lecture des villes et fichiers, normalisation,
  exclusions, doublons, médiane, calcul par bien. **Sans Django** → testable seul.
- `views.py` : une vue `biens_financables` (GET : ville + profil ; POST : recalcul).
- `templates/analyseur/biens_financables.html` + filtres/tri en JavaScript léger.
- Route `biens-financables/`, lien dans la navigation.
- Barèmes mis à jour en tête de `views.py`.

## 10. Tests (écrits avant le code)

- Mensualité : **200 000 € · 20 ans · 3,53 % tout compris → 1 163 €/mois** (valeur de contrôle,
  à confirmer sur le calculateur de La finance pour tous).
- Frais de notaire : 8 % ancien, 7,5 % ancien primo, 3 % neuf.
- Verdicts pile aux seuils 35 % et 40 %, et reste à vivre insuffisant.
- Doublons : cas réels Orpi Mairie + Nestenn (254 000 €) et Primo + L'Adresse (273 000 €).
- Fichiers abîmés (JSON invalide, champs manquants, fourchettes « Entre 222 et 245 m² »).
- Bout en bout sur les vrais fichiers de Fresnes : la page s'affiche, ses biens sont listés.
- Les tests tournent avec `manage.py test` (premiers vrais tests du projet).

## 11. Avant de coder

tools_immo contient du travail **non commité** (page « dépenses mensuelles », `CLAUDE.md`).
Il doit être commité ou mis de côté avant de commencer, pour ne pas mélanger les chantiers.
