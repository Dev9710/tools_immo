# views.py - Version refactorisée avec templates
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from datetime import datetime
from decimal import Decimal, InvalidOperation
import tempfile
import os
import re
import json

# Configuration des taux de crédit immobilier (2025)
TAUX_ACTUELS = {
    'regions': {
        'ile_de_france': {'7': 3.00, '10': 3.15, '15': 3.30, '20': 3.45, '25': 3.60},
        'provence': {'7': 3.05, '10': 3.20, '15': 3.35, '20': 3.50, '25': 3.65},
        'rhone_alpes': {'7': 3.02, '10': 3.17, '15': 3.32, '20': 3.47, '25': 3.62},
        'autre': {'7': 3.08, '10': 3.23, '15': 3.38, '20': 3.53, '25': 3.68}
    },
    'profils': {
        'excellent': -0.30,    # CDI, >10% apport, épargne
        'bon': -0.15,          # CDI, 10% apport
        'moyen': 0.00,         # CDD, apport minimal
        'risque': 0.25         # Profil difficile
    },
    'assurance': {
        'moins_30': 0.15,
        '30_45': 0.25,
        '45_plus': 0.45
    }
}

FRAIS_NOTAIRE = {
    'ancien': 0.08,    # 8%
    'neuf': 0.03       # 3%
}


class SimulateurPretImmobilier:
    """Simulateur de prêt immobilier professionnel"""

    def __init__(self):
        self.taux_endettement_max = 35.0  # HCSF 2025
        self.duree_max = 27  # années

    def calculer_capacite_emprunt(self, revenus_nets, charges_mensuelles, duree,
                                  region='autre', profil='moyen', age=35):
        """Calcule la capacité d'emprunt selon les critères bancaires"""

        # Mensualité maximum : la règle HCSF plafonne le TOTAL des charges
        # (existantes + futur crédit) à 35 % des revenus nets. La mensualité
        # du crédit ne peut donc pas dépasser 35 % des revenus MOINS les
        # charges déjà supportées.
        mensualite_max = max(
            0.0, revenus_nets * (self.taux_endettement_max / 100) - charges_mensuelles)

        # Taux selon région et profil
        taux_base = TAUX_ACTUELS['regions'][region].get(str(duree), 3.5)
        ajustement_profil = TAUX_ACTUELS['profils'][profil]
        taux_nominal = taux_base + ajustement_profil

        # Taux assurance selon âge
        if age < 30:
            taux_assurance = TAUX_ACTUELS['assurance']['moins_30']
        elif age < 45:
            taux_assurance = TAUX_ACTUELS['assurance']['30_45']
        else:
            taux_assurance = TAUX_ACTUELS['assurance']['45_plus']

        # TAEG = taux nominal + assurance
        taeg = taux_nominal + taux_assurance

        # Calcul capacité d'emprunt (formule actuarielle)
        nb_mensualites = duree * 12
        if taeg == 0:
            capacite = mensualite_max * nb_mensualites
        else:
            taux_mensuel = taeg / 100 / 12
            capacite = mensualite_max * \
                (1 - (1 + taux_mensuel) ** -nb_mensualites) / taux_mensuel

        # Coût total et intérêts
        cout_total = mensualite_max * nb_mensualites
        cout_interets = cout_total - capacite

        # Taux d'endettement projeté = (charges existantes + mensualité du
        # crédit) / revenus. Plafonné à 35 % par le calcul ci-dessus.
        if revenus_nets > 0:
            taux_endettement = round(
                (charges_mensuelles + mensualite_max) / revenus_nets * 100, 2)
        else:
            taux_endettement = 0.0

        return {
            'capacite_emprunt': round(capacite, 2),
            'mensualite_max': round(mensualite_max, 2),
            'taux_nominal': round(taux_nominal, 2),
            'taux_assurance': round(taux_assurance, 2),
            'taeg': round(taeg, 2),
            'cout_total': round(cout_total, 2),
            'cout_interets': round(cout_interets, 2),
            'taux_endettement': taux_endettement
        }

    def calculer_mensualites(self, montant_emprunt, duree, taux_nominal, taux_assurance):
        """Calcule les mensualités pour un montant donné"""

        taeg = taux_nominal + taux_assurance
        taux_mensuel = taeg / 100 / 12
        nb_mensualites = duree * 12

        if taeg == 0:
            mensualite = montant_emprunt / nb_mensualites
        else:
            mensualite = montant_emprunt * taux_mensuel / \
                (1 - (1 + taux_mensuel) ** -nb_mensualites)

        cout_total = mensualite * nb_mensualites
        cout_interets = cout_total - montant_emprunt

        return {
            'mensualite': round(mensualite, 2),
            'cout_total': round(cout_total, 2),
            'cout_interets': round(cout_interets, 2),
            'taeg': round(taeg, 2)
        }

    def calculer_frais_notaire(self, prix_bien, type_bien='ancien'):
        """Calcule les frais de notaire selon le type de bien"""
        taux = FRAIS_NOTAIRE[type_bien]
        frais = prix_bien * taux
        return round(frais, 2)

    def generer_tableau_amortissement(self, montant, duree, taux_nominal, taux_assurance, nb_lignes=12):
        """Génère un tableau d'amortissement simplifié"""

        taeg = taux_nominal + taux_assurance
        taux_mensuel = taeg / 100 / 12
        nb_mensualites = duree * 12

        if taeg == 0:
            mensualite = montant / nb_mensualites
        else:
            mensualite = montant * taux_mensuel / \
                (1 - (1 + taux_mensuel) ** -nb_mensualites)

        tableau = []
        capital_restant = montant

        for i in range(min(nb_lignes, int(nb_mensualites))):
            if taeg == 0:
                interets = 0
                capital = mensualite
            else:
                interets = capital_restant * taux_mensuel
                capital = mensualite - interets

            capital_restant = max(0, capital_restant - capital)

            tableau.append({
                'mois': i + 1,
                'mensualite': round(mensualite, 2),
                'capital': round(capital, 2),
                'interets': round(interets, 2),
                'capital_restant': round(capital_restant, 2)
            })

        return tableau

    def calculer_reste_a_vivre(self, revenus_nets, charges_totales, nb_adultes=2, nb_enfants=0):
        """Calcule et valide le reste à vivre"""

        # Seuils minimums par personne (données 2025)
        seuil_adulte = 400  # €/mois
        seuil_enfant = 300  # €/mois

        minimum_requis = (nb_adultes * seuil_adulte) + \
            (nb_enfants * seuil_enfant)
        reste_a_vivre = revenus_nets - charges_totales

        alerte = None
        if reste_a_vivre < minimum_requis:
            deficit = minimum_requis - reste_a_vivre
            alerte = {
                'type': 'danger',
                'message': f"Reste à vivre insuffisant : {reste_a_vivre}€ < {minimum_requis}€ requis",
                'conseil': f"Réduisez vos charges de {deficit}€ ou augmentez vos revenus"
            }
        elif reste_a_vivre < minimum_requis * 1.2:
            alerte = {
                'type': 'warning',
                'message': f"Reste à vivre limite : {reste_a_vivre}€",
                'conseil': "Prévoyez une marge de sécurité supplémentaire"
            }

        return {
            'reste_a_vivre': reste_a_vivre,
            'minimum_requis': minimum_requis,
            'alerte': alerte,
            'statut': 'OK' if not alerte else alerte['type']
        }


class BanquePostaleParserSimple:
    """Parser Banque Postale optimisé et nettoyé"""

    def __init__(self):
        # Classification basée uniquement sur des mots-clés réalistes
        self.keywords = {
            'achat': [
                'ACHAT CB', 'PAIEMENT CB', 'CARTE', 'TPE', 'RETRAIT',
                'PAYPAL', 'UBER', 'INTERSPORT', 'IMMOBILIERE', 'CB '
            ],
            'virement': [
                'VIREMENT', 'VIR ', 'SEPA', 'REMBOURSEMENT',
                'INSTANTANE', 'EMISSION', 'RECEPTION', 'TRANSFERT'
            ],
            'depot': [
                'DEPOT', 'VERSEMENT', 'REMISE', 'CREDIT'
            ],
            'debit': [
                'PRELEVEMENT', 'PRLV', 'ECHEANCE', 'ABONNEMENT',
                'COTISATION', 'FRAIS', 'TRESOR', 'ORANGE', 'EDF'
            ],
            'cheque': [
                'CHEQUE', 'CHQ'
            ]
        }

    def extract_text_from_pdf(self, pdf_path):
        """Extrait le texte de toutes les pages du PDF"""
        try:
            import pdfplumber
            text = ""
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += f"\n--- PAGE {page_num + 1} ---\n{page_text}\n"
            return text
        except ImportError:
            # Fallback PyPDF2
            import PyPDF2
            text = ""
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page_num, page in enumerate(pdf_reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += f"\n--- PAGE {page_num + 1} ---\n{page_text}\n"
            return text

    def parse_montant(self, montant_str):
        """Parse les montants français avec espaces (ex: 10 000,00)"""
        try:
            montant_clean = montant_str.replace(' ', '').replace(',', '.')
            return Decimal(montant_clean)
        except (InvalidOperation, ValueError, AttributeError):
            return Decimal('0')

    def categorize_operation(self, description):
        """Catégorise une opération selon les mots-clés"""
        desc_upper = description.upper()

        for keyword in self.keywords['cheque']:
            if keyword in desc_upper:
                return 'cheque'

        for keyword in self.keywords['debit']:
            if keyword in desc_upper:
                return 'debit'

        for keyword in self.keywords['achat']:
            if keyword in desc_upper:
                return 'achat'

        for keyword in self.keywords['virement']:
            if keyword in desc_upper:
                return 'virement'

        for keyword in self.keywords['depot']:
            if keyword in desc_upper:
                return 'depot'

        return 'autre'

    def extract_libelle(self, description):
        """Extrait le libellé principal optimisé pour Banque Postale"""
        libelle = description.strip()

        # Supprimer références inutiles
        libelle = re.sub(r'REF(?:ERENCE)?\s*:\s*\d+', '', libelle)
        libelle = re.sub(r'\b\d{10,}\b', '', libelle)  # Numéros longs
        libelle = re.sub(r'COMPTE\s+FR\d+', '', libelle)  # IBAN

        # Cas CB avec astérisque (*UBER B)
        match = re.search(
            r'(?:ACHAT|PAIEMENT)\s+CB\s+(.+?\*?.+?)(?:\s+\d{2}\.\d{2}|\s+CARTE|$)',
            libelle.upper()
        )
        if match:
            return match.group(1).replace('*', ' ').strip()

        # Cas CB classique
        match = re.search(
            r'(?:ACHAT|PAIEMENT)\s+CB\s+(.+?)(?:\s+\d{2}\.\d{2}|\s+CARTE|$)',
            libelle.upper()
        )
        if match:
            return match.group(1).strip()

        # Cas virements
        if 'VIREMENT' in libelle.upper():
            patterns = [
                r'VIREMENT\s+(?:INSTANTANE\s+)?(?:A|POUR)\s+(.+?)(?:\s+COMPTE|\s+DEFAULT|$)',
                r'VIREMENT\s+(.+?)(?:\s+COMPTE|\s+REFERENCE|$)',
            ]
            for pattern in patterns:
                match = re.search(pattern, libelle.upper())
                if match:
                    return match.group(1).strip()

        # Cas prélèvements
        if 'PRELEVEMENT DE' in libelle.upper():
            match = re.search(
                r'PRELEVEMENT DE\s+(.+?)(?:\s+\d+|$)', libelle.upper())
            if match:
                return match.group(1).strip()

        # Cas chèques
        if 'CHEQUE N°' in libelle.upper():
            return libelle

        # Nettoyage final
        libelle = re.sub(r'\s+', ' ', libelle).strip()
        return libelle[:60]

    # Montant au format d'un mot isolé (« 17,00 », « 3360,00 », « 1 234,56 »).
    AMOUNT_RE = re.compile(r'^\d{1,3}(?:[ .]?\d{3})*,\d{2}$')
    _OPERATIONS_MARKER = re.compile(
        r'(?:Vos\s+op[eé]rations|OP[EÉ]RATIONS)', re.IGNORECASE)

    def extract_year(self, text):
        """Année du relevé : d'abord une vraie date jj/mm/20aa (fiable), sinon
        « Relevé … 20aa » (tolérant à l'accent), sinon l'année courante. Bornée
        à 20xx pour ne pas capturer un numéro de compte ou d'agence."""
        date_year = re.search(r'\b\d{2}/\d{2}/(20\d{2})\b', text)
        if date_year:
            return int(date_year.group(1))
        releve_year = re.search(r'Relev[eé].*?(20\d{2})', text)
        return int(releve_year.group(1)) if releve_year else datetime.now().year

    def extract_word_lines(self, pdf_path):
        """Reconstruit les lignes du relevé à partir des mots *positionnés* et
        détecte la frontière horizontale entre les colonnes Débit et Crédit.

        Chaque ligne renvoyée est un dict {'text', 'amounts'} où `amounts` liste
        les (valeur, x1) des montants de la ligne. Le sens d'une opération se lit
        ainsi à la position du montant, et non plus par mots-clés — ce qui évite
        de compter un crédit comme une charge. Renvoie (None, None) si pdfplumber
        est absent : on retombe alors sur le texte brut, sans notion de sens."""
        try:
            import pdfplumber
        except ImportError:
            return None, None

        lines = []
        debit_right = credit_right = None
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                words = page.extract_words()
                for w in words:
                    t = w['text'].lower()
                    if debit_right is None and t.startswith(('débit', 'debit')):
                        debit_right = w['x1']
                    if credit_right is None and t.startswith(('crédit', 'credit')):
                        credit_right = w['x1']
                # Regrouper les mots en lignes visuelles (tolérance verticale).
                clusters = []
                for w in sorted(words, key=lambda w: w['top']):
                    if clusters and abs(w['top'] - clusters[-1]['top']) <= 3:
                        clusters[-1]['words'].append(w)
                    else:
                        clusters.append({'top': w['top'], 'words': [w]})
                for cl in clusters:
                    toks = sorted(cl['words'], key=lambda w: w['x0'])
                    lines.append({
                        'text': ' '.join(w['text'] for w in toks),
                        'amounts': [(w['text'], w['x1'])
                                    for w in toks if self.AMOUNT_RE.match(w['text'])],
                    })

        # Frontière Débit/Crédit : milieu des deux bords droits d'en-tête, avec
        # des valeurs de repli observées sur les relevés Banque Postale.
        if debit_right and credit_right:
            seuil = (debit_right + credit_right) / 2
        elif credit_right:
            seuil = credit_right - 20
        else:
            seuil = 503.0
        return lines, seuil

    def _clean_description(self, description):
        """Nettoie une description : retire les dates parasites, recolle les
        libellés agglutinés et normalise les espaces."""
        description = re.sub(
            r'\d{2}[./]\d{2}[./](?:20)?\d{2}', '', description)
        description = description.replace("ACHATCB", "ACHAT CB ")
        description = re.sub(r'IMMOBILIERE(\d+)', r'IMMOBILIERE \1', description)
        return re.sub(r'\s+', ' ', description).strip()

    def parse_operations_lines(self, lines, seuil, year):
        """Parse les lignes positionnées ; le sens (débit/crédit) vient de la
        colonne dans laquelle tombe le montant."""
        operations = []
        i = 0
        while i < len(lines):
            text = lines[i]['text'].strip()

            if not text or any(w in text for w in
                               ['Ancien solde', 'Nouveau solde', 'Solde', 'Débit', 'Crédit']):
                i += 1
                continue

            date_match = re.match(r'^(\d{2}/\d{2})\s+(.+)', text)
            if not date_match:
                i += 1
                continue

            full_date = f"{date_match.group(1)}/{year or datetime.now().year}"
            try:
                date_operation = datetime.strptime(full_date, '%d/%m/%Y').date()
            except ValueError:
                i += 1
                continue

            description = date_match.group(2)
            amounts = lines[i]['amounts']

            # Montant absent de la ligne de date : chercher sur les suivantes,
            # jusqu'à la prochaine opération, en agrégeant la description.
            j = i
            while not amounts and j + 1 < len(lines):
                nxt = lines[j + 1]
                if re.match(r'^\d{2}/\d{2}\s+', nxt['text'].strip()):
                    break
                if nxt['amounts']:
                    amounts = nxt['amounts']
                    break
                if not any(s in nxt['text'] for s in
                           ['CARTE NUMERO', 'REF :', 'IDENT :', 'MANDAT :']):
                    description += ' ' + nxt['text']
                j += 1

            if not amounts:
                i += 1
                continue

            # Une ligne d'opération porte un seul montant ; s'il y en a plusieurs
            # on prend le plus à droite (colonne des montants).
            value_str, x1 = max(amounts, key=lambda a: a[1])
            montant = self.parse_montant(value_str)
            sens = 'credit' if x1 > seuil else 'debit'

            description = self._clean_description(
                description.replace(value_str, ' '))

            if montant > Decimal('0'):
                operations.append({
                    'date': date_operation,
                    'description': description,
                    'montant': montant,
                    'sens': sens,
                    'type': self.categorize_operation(description),
                    'libelle': self.extract_libelle(description),
                })
            i += 1

        return operations

    def parse_operations_section(self, text_section, year=None):
        """Repli texte (sans position) : on ne connaît pas le sens débit/crédit,
        il reste à None. Utilisé seulement si pdfplumber est indisponible."""
        operations = []
        lines = text_section.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line or any(word in line for word in
                               ['Date', 'Operation', 'Debit', 'Credit',
                                'Ancien solde', 'Nouveau solde']):
                i += 1
                continue

            date_match = re.match(r'^(\d{2}/\d{2})\s+(.+)', line)
            if not date_match:
                i += 1
                continue

            full_date = f"{date_match.group(1)}/{year or datetime.now().year}"
            try:
                date_operation = datetime.strptime(full_date, '%d/%m/%Y').date()
            except ValueError:
                i += 1
                continue

            description = self._clean_description(date_match.group(2))
            montant = Decimal('0')
            montant_matches = list(re.finditer(
                r'(\d{1,3}(?:\s\d{3})*,\d{2})', description))
            if montant_matches:
                last_match = montant_matches[-1]
                montant = self.parse_montant(last_match.group(1))
                description = (description[:last_match.start()]
                               + description[last_match.end():]).strip()
            else:
                j = i + 1
                while j < min(i + 4, len(lines)):
                    next_line = lines[j].strip()
                    if re.match(r'^\d{2}/\d{2}\s+', next_line):
                        break
                    if re.match(r'^\d{1,3}(?:\s\d{3})*,\d{2}$', next_line):
                        montant = self.parse_montant(next_line)
                        break
                    if next_line and not any(skip in next_line for skip in
                                             ['CARTE NUMERO', 'REF :', 'IDENT :', 'MANDAT :']):
                        description += ' ' + next_line
                    j += 1

            if montant > Decimal('0'):
                operations.append({
                    'date': date_operation,
                    'description': description,
                    'montant': montant,
                    'sens': None,
                    'type': self.categorize_operation(description),
                    'libelle': self.extract_libelle(description),
                })
            i += 1

        return operations

    def parse_pdf(self, pdf_path, types_selectionnes):
        """Parse complet du PDF Banque Postale (géométrie des colonnes en
        priorité, texte brut en repli)."""
        try:
            lines, seuil = self.extract_word_lines(pdf_path)

            if lines is not None:
                full_text = '\n'.join(l['text'] for l in lines)
                if len(full_text) < 50:
                    return {'success': False, 'error': 'PDF vide ou illisible'}
                start = next((idx for idx, l in enumerate(lines)
                             if self._OPERATIONS_MARKER.search(l['text'])), None)
                if start is None:
                    return {'success': False, 'error': 'Section "Vos opérations" non trouvée'}
                year = self.extract_year(full_text)
                all_operations = self.parse_operations_lines(
                    lines[start + 1:], seuil, year)
            else:
                text = self.extract_text_from_pdf(pdf_path)
                if not text or len(text) < 50:
                    return {'success': False, 'error': 'PDF vide ou illisible'}
                if not self._OPERATIONS_MARKER.search(text):
                    return {'success': False, 'error': 'Section "Vos opérations" non trouvée'}
                year = self.extract_year(text)
                sections = self._OPERATIONS_MARKER.split(text)
                all_operations = []
                for section in sections[1:]:
                    all_operations.extend(
                        self.parse_operations_section(section, year))

            # Grouper par type ; en charges fixes on ne veut que les sorties :
            # un crédit (sens détecté par la colonne) est exclu même si un
            # mot-clé le rangeait par erreur dans « debit »/« achat ».
            operations_par_type = {k: [] for k in self.keywords.keys()}
            for op in all_operations:
                if op['type'] in types_selectionnes:
                    operations_par_type[op['type']].append({
                        'date': op['date'],
                        'libelle': op['libelle'],
                        'description': op['description'],
                        'montant': op['montant'],
                        'sens': op.get('sens'),
                    })

            return {
                'success': True,
                'operations_par_type': operations_par_type,
                'types_traites': [t for t in types_selectionnes if operations_par_type[t]]
            }

        except Exception as e:
            return {'success': False, 'error': f'Erreur parsing: {str(e)}'}


def create_excel_multi_onglets(operations_par_type, types_traites):
    """Crée un Excel avec un onglet par type d'opération"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        return create_csv_multi_files(operations_par_type, types_traites)

    workbook = Workbook()
    workbook.remove(workbook.active)  # Supprimer feuille par défaut

    type_names = {
        'achat': 'Achats CB',
        'virement': 'Virements',
        'depot': 'Depots & Versements',
        'debit': 'Prelevements & Debits',
        'cheque': 'Cheques'
    }

    type_colors = {
        'achat': 'FF6B6B',
        'virement': '4ECDC4',
        'depot': '45B7D1',
        'debit': 'FFA07A',
        'cheque': 'DDA0DD'
    }

    for type_op in types_traites:
        if not operations_par_type[type_op]:
            continue

        # Créer onglet
        ws = workbook.create_sheet(type_names[type_op])
        ws.sheet_properties.tabColor = type_colors.get(type_op, '808080')

        # En-tête principal
        ws['A1'] = f"ANALYSE {type_names[type_op].upper()}"
        ws['A1'].font = Font(bold=True, size=16)
        ws.merge_cells('A1:D1')

        # Informations
        ws['A2'] = f"Nombre d'operations: {len(operations_par_type[type_op])}"
        ws['A2'].font = Font(size=12)

        ws['A3'] = f"Date d'analyse: {datetime.now().strftime('%d/%m/%Y a %H:%M')}"
        ws['A3'].font = Font(size=10, italic=True)

        # Headers tableau avec style
        headers = ['Date', 'Libelle', 'Description complete', 'Montant (€)']
        header_fill = PatternFill(
            start_color=type_colors[type_op], end_color=type_colors[type_op], fill_type="solid")
        border = Border(left=Side(style='thin'), right=Side(style='thin'),
                        top=Side(style='thin'), bottom=Side(style='thin'))

        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=5, column=col, value=header)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
            cell.border = border

        # Données avec alternance de couleurs
        row = 6
        total = Decimal('0')

        # Trier les opérations par date
        operations_triees = sorted(
            operations_par_type[type_op], key=lambda x: x['date'])

        for i, operation in enumerate(operations_triees):
            # Couleur alternée
            if i % 2 == 0:
                fill = PatternFill(start_color='F8F9FA',
                                   end_color='F8F9FA', fill_type="solid")
            else:
                fill = PatternFill(start_color='FFFFFF',
                                   end_color='FFFFFF', fill_type="solid")

            # Date
            cell = ws.cell(row=row, column=1,
                           value=operation['date'].strftime('%d/%m/%Y'))
            cell.fill = fill
            cell.border = border
            cell.alignment = Alignment(horizontal="center")

            # Libellé
            cell = ws.cell(row=row, column=2, value=operation['libelle'])
            cell.fill = fill
            cell.border = border
            cell.font = Font(bold=True)

            # Description
            cell = ws.cell(row=row, column=3, value=operation['description'])
            cell.fill = fill
            cell.border = border

            # Montant (valeur absolue pour l'affichage)
            montant_val = float(abs(operation['montant']))
            cell = ws.cell(row=row, column=4, value=montant_val)
            cell.fill = fill
            cell.border = border
            cell.alignment = Alignment(horizontal="right")
            cell.number_format = '#,##0.00'

            # Couleur selon le sens (colonne Débit/Crédit du relevé)
            if operation.get('sens') == 'credit':
                cell.font = Font(color="28A745")  # Vert pour les crédits
            else:
                cell.font = Font(color="DC3545")  # Rouge pour les débits

            total += abs(operation['montant'])  # Somme en valeur absolue
            row += 1

        # Ligne totale avec style
        row += 1
        ws.merge_cells(f'A{row}:C{row}')
        total_cell = ws.cell(row=row, column=1, value="TOTAL")
        total_cell.font = Font(bold=True, size=14)
        total_cell.alignment = Alignment(horizontal="center")
        total_cell.fill = PatternFill(
            start_color="FFD966", end_color="FFD966", fill_type="solid")
        total_cell.border = border

        # Montant total
        total_montant_cell = ws.cell(row=row, column=4, value=float(total))
        total_montant_cell.font = Font(bold=True, size=14)
        total_montant_cell.fill = PatternFill(
            start_color="FFD966", end_color="FFD966", fill_type="solid")
        total_montant_cell.border = border
        total_montant_cell.alignment = Alignment(horizontal="right")
        total_montant_cell.number_format = '#,##0.00 "€"'

        # Ajuster largeurs colonnes
        ws.column_dimensions['A'].width = 14
        ws.column_dimensions['B'].width = 35
        ws.column_dimensions['C'].width = 55
        ws.column_dimensions['D'].width = 18

    # Sauvegarder
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    workbook.save(temp_file.name)
    return temp_file.name


def create_csv_multi_files(operations_par_type, types_traites):
    """Fallback CSV si pas d'openpyxl"""
    import csv
    import zipfile

    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')

    with zipfile.ZipFile(temp_zip.name, 'w') as zipf:
        for type_op in types_traites:
            if not operations_par_type[type_op]:
                continue

            temp_csv = tempfile.NamedTemporaryFile(
                mode='w', delete=False, suffix='.csv', newline='', encoding='utf-8')
            writer = csv.writer(temp_csv)

            # Headers
            writer.writerow([f'ANALYSE {type_op.upper()} - BANQUE POSTALE'])
            writer.writerow([])
            writer.writerow(['Date', 'Libelle', 'Description', 'Montant'])

            # Données
            total = 0
            operations_triees = sorted(
                operations_par_type[type_op], key=lambda x: x['date'])

            for op in operations_triees:
                writer.writerow([
                    op['date'].strftime('%d/%m/%Y'),
                    op['libelle'],
                    op['description'],
                    f"{float(abs(op['montant'])):.2f}"
                ])
                total += float(abs(op['montant']))

            # Total
            writer.writerow([])
            writer.writerow(['', '', 'TOTAL:', f"{total:.2f} €"])

            temp_csv.close()
            zipf.write(temp_csv.name, f'{type_op}_banque_postale.csv')
            os.unlink(temp_csv.name)

    return temp_zip.name


def create_excel_charges_fixes_with_month(selected_operations, total_charges, mois_selectionne):
    """Crée un Excel spécialisé pour les charges fixes avec indication du mois"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        return create_csv_charges_fixes(selected_operations, total_charges)

    workbook = Workbook()
    ws = workbook.active
    ws.title = "Charges Fixes Mensuelles"

    # Style
    header_fill = PatternFill(start_color="28a745",
                              end_color="28a745", fill_type="solid")
    border = Border(left=Side(style='thin'), right=Side(style='thin'),
                    top=Side(style='thin'), bottom=Side(style='thin'))

    # En-tête principal avec période
    periode_texte = "PÉRIODE COMPLÈTE" if mois_selectionne == 'tous' else f"MOIS DE {mois_selectionne}"
    ws['A1'] = f"CHARGES FIXES MENSUELLES - {periode_texte}"
    ws['A1'].font = Font(bold=True, size=16)
    ws.merge_cells('A1:E1')

    # Informations
    ws['A2'] = f"Nombre de charges: {len(selected_operations)}"
    ws['A3'] = f"Total mensuel: {total_charges:.2f} €"
    ws['A4'] = f"Date d'analyse: {datetime.now().strftime('%d/%m/%Y à %H:%M')}"

    # Headers
    headers = ['Date', 'Type', 'Libellé', 'Description', 'Montant (€)']
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=6, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = border

    # Données triées par date
    row = 7
    operations_triees = sorted(
        selected_operations, key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y'))

    for op in operations_triees:
        ws.cell(row=row, column=1, value=op['date']).border = border
        ws.cell(row=row, column=2,
                value="Prélèvement" if op['type'] == 'prelevement' else "Achat CB").border = border
        ws.cell(row=row, column=3, value=op['libelle']).border = border
        ws.cell(row=row, column=4, value=op['description']).border = border
        ws.cell(row=row, column=5, value=float(op['montant'])).border = border
        ws.cell(row=row, column=5).number_format = '#,##0.00'
        row += 1

    # Total
    row += 1
    ws.merge_cells(f'A{row}:D{row}')
    total_cell = ws.cell(
        row=row, column=1, value=f"TOTAL CHARGES FIXES - {periode_texte}")
    total_cell.font = Font(bold=True, size=14)
    total_cell.fill = PatternFill(
        start_color="FFD966", end_color="FFD966", fill_type="solid")

    total_montant = ws.cell(row=row, column=5, value=total_charges)
    total_montant.font = Font(bold=True, size=14)
    total_montant.fill = PatternFill(
        start_color="FFD966", end_color="FFD966", fill_type="solid")
    total_montant.number_format = '#,##0.00 "€"'

    # Largeurs colonnes
    ws.column_dimensions['A'].width = 12
    ws.column_dimensions['B'].width = 15
    ws.column_dimensions['C'].width = 30
    ws.column_dimensions['D'].width = 40
    ws.column_dimensions['E'].width = 15

    # Sauvegarder
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    workbook.save(temp_file.name)
    return temp_file.name


def create_csv_charges_fixes(selected_operations, total_charges):
    """Fallback CSV pour les charges fixes"""
    import csv

    temp_csv = tempfile.NamedTemporaryFile(
        mode='w', delete=False, suffix='.csv', newline='', encoding='utf-8')
    writer = csv.writer(temp_csv)

    # Headers
    writer.writerow(['CHARGES FIXES MENSUELLES'])
    writer.writerow([])
    writer.writerow(['Date', 'Type', 'Libelle', 'Description', 'Montant'])

    # Données
    operations_triees = sorted(
        selected_operations, key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y'))

    for op in operations_triees:
        writer.writerow([
            op['date'],
            "Prélèvement" if op['type'] == 'prelevement' else "Achat CB",
            op['libelle'],
            op['description'],
            f"{float(op['montant']):.2f}"
        ])

    # Total
    writer.writerow([])
    writer.writerow(['', '', '', 'TOTAL:', f"{total_charges:.2f} €"])

    temp_csv.close()
    return temp_csv.name


def calculer_statut_dossier(session_data):
    """Calcule le statut d'avancement du dossier"""
    score = 0
    if session_data.get('revenus_nets'):
        score += 25
    if session_data.get('charges_fixes'):
        score += 25
    if session_data.get('capacite_emprunt'):
        score += 25
    if session_data.get('apport'):
        score += 25

    if score >= 75:
        return "Prêt pour RDV banque"
    elif score >= 50:
        return "Dossier en cours"
    else:
        return "Données manquantes"


# VUES REFACTORISÉES - Maintenant avec templates
def accueil(request):
    """Page d'accueil - maintenant avec template"""
    return render(request, 'analyseur/accueil.html')


def upload_releve(request):
    """Interface d'upload avec parser optimisé - maintenant avec template"""
    if request.method == 'POST':
        try:
            # Récupérer les types sélectionnés
            types_selectionnes = []
            if request.POST.get('achat'):
                types_selectionnes.append('achat')
            if request.POST.get('virement'):
                types_selectionnes.append('virement')
            if request.POST.get('depot'):
                types_selectionnes.append('depot')
            if request.POST.get('debit'):
                types_selectionnes.append('debit')
            if request.POST.get('cheque'):
                types_selectionnes.append('cheque')

            if not types_selectionnes:
                raise Exception(
                    "Veuillez sélectionner au moins un type d'opération")

            # Parser le vrai PDF uploadé
            fichier_pdf = request.FILES.get('fichier_pdf')
            if not fichier_pdf:
                raise Exception("Veuillez sélectionner un fichier PDF")

            # Sauvegarder temporairement le PDF
            temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
            for chunk in fichier_pdf.chunks():
                temp_pdf.write(chunk)
            temp_pdf.close()

            # Parser avec le nouveau parser simplifié
            parser = BanquePostaleParserSimple()
            try:
                resultats = parser.parse_pdf(temp_pdf.name, types_selectionnes)
            finally:
                if os.path.exists(temp_pdf.name):
                    os.unlink(temp_pdf.name)

            if not resultats['success']:
                raise Exception(f"Erreur de parsing: {resultats['error']}")

            if not any(resultats['operations_par_type'].values()):
                raise Exception(
                    "Aucune opération trouvée dans le PDF. Vérifiez le format du relevé.")

            # Créer Excel optimisé
            excel_path = create_excel_multi_onglets(
                resultats['operations_par_type'],
                resultats['types_traites']
            )

            # Télécharger
            content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if excel_path.endswith(
                '.xlsx') else 'application/zip'
            filename = f"analyse_banque_postale_{datetime.now().strftime('%Y%m%d_%H%M')}"
            filename += '.xlsx' if excel_path.endswith('.xlsx') else '.zip'

            try:
                with open(excel_path, 'rb') as f:
                    data = f.read()
            finally:
                if os.path.exists(excel_path):
                    os.unlink(excel_path)

            response = HttpResponse(data, content_type=content_type)
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        except Exception as e:
            # En cas d'erreur, afficher le template avec l'erreur
            return render(request, 'analyseur/upload_releve.html', {
                'error': str(e)
            })

    # GET - Afficher le formulaire
    return render(request, 'analyseur/upload_releve.html')


def charges_fixes(request):
    """Interface pour calculer les charges fixes mensuelles avec upload multiple et filtrage par mois"""
    if request.method == 'POST':
        # Étape 1: Upload et parsing initial (1 ou 2 fichiers)
        if 'fichier_pdf1' in request.FILES or 'fichier_pdf2' in request.FILES:
            try:
                fichiers_pdf = []

                # Traiter le premier fichier
                if 'fichier_pdf1' in request.FILES:
                    fichiers_pdf.append(request.FILES['fichier_pdf1'])

                # Traiter le second fichier (optionnel)
                if 'fichier_pdf2' in request.FILES:
                    fichiers_pdf.append(request.FILES['fichier_pdf2'])

                if not fichiers_pdf:
                    raise Exception(
                        "Veuillez sélectionner au moins un fichier PDF")

                # Parser tous les fichiers et agréger les données
                all_prelevements = []
                all_achats_cb = []
                mois_disponibles = set()

                parser = BanquePostaleParserSimple()

                for fichier_pdf in fichiers_pdf:
                    # Sauvegarder temporairement le PDF
                    temp_pdf = tempfile.NamedTemporaryFile(
                        delete=False, suffix='.pdf')
                    for chunk in fichier_pdf.chunks():
                        temp_pdf.write(chunk)
                    temp_pdf.close()

                    # Parser le fichier
                    try:
                        resultats = parser.parse_pdf(
                            temp_pdf.name, ['debit', 'achat'])
                    finally:
                        if os.path.exists(temp_pdf.name):
                            os.unlink(temp_pdf.name)

                    if not resultats['success']:
                        raise Exception(
                            f"Erreur de parsing sur {fichier_pdf.name}: {resultats['error']}")

                    # Agréger les opérations (sorties uniquement : on écarte un
                    # crédit qui aurait été rangé par mot-clé dans debit/achat).
                    prelevements = [op for op in resultats['operations_par_type'].get('debit', [])
                                    if op.get('sens') != 'credit']
                    achats_cb = [op for op in resultats['operations_par_type'].get('achat', [])
                                 if op.get('sens') != 'credit']

                    all_prelevements.extend(prelevements)
                    all_achats_cb.extend(achats_cb)

                    # Extraire les mois disponibles
                    for op in prelevements + achats_cb:
                        mois_annee = f"{op['date'].strftime('%m/%Y')}"
                        mois_nom = f"{op['date'].strftime('%B %Y')}"
                        # Conversion des noms de mois en français
                        mois_fr = mois_nom.replace('January', 'Janvier').replace('February', 'Février') \
                            .replace('March', 'Mars').replace('April', 'Avril') \
                            .replace('May', 'Mai').replace('June', 'Juin') \
                            .replace('July', 'Juillet').replace('August', 'Août') \
                            .replace('September', 'Septembre').replace('October', 'Octobre') \
                            .replace('November', 'Novembre').replace('December', 'Décembre')
                        mois_disponibles.add((mois_annee, mois_fr))

                if not all_prelevements and not all_achats_cb:
                    raise Exception(
                        "Aucun prélèvement ni achat CB trouvé dans le(s) PDF.")

                # Trier les mois chronologiquement
                mois_tries = sorted(list(mois_disponibles), key=lambda x: x[0])

                # Afficher l'interface de sélection avec choix du mois
                return render_selection_interface_with_month(all_prelevements, all_achats_cb, mois_tries, len(fichiers_pdf))

            except Exception as e:
                return render(request, 'analyseur/charges_fixes.html', {
                    'error': str(e)
                })

        # Étape 2: Traitement des sélections utilisateur avec filtrage par mois
        elif 'selected_operations' in request.POST:
            try:
                # Récupérer les opérations sélectionnées et le mois choisi
                selected_data = json.loads(request.POST['selected_operations'])
                mois_selectionne = request.POST.get('mois_filtre', 'tous')

                # Filtrer par mois si nécessaire. Les dates arrivent au format
                # jj/mm/AAAA et le mois choisi au format mm/AAAA : on compare
                # le couple mois/année, pas un préfixe (qui ne matchait jamais).
                if mois_selectionne != 'tous':
                    def _mois_annee(date_str):
                        parts = date_str.split('/')
                        return f"{parts[1]}/{parts[2]}" if len(parts) == 3 else ''
                    selected_data = [op for op in selected_data
                                     if _mois_annee(op['date']) == mois_selectionne]

                # Calculer le total
                total_charges = sum(float(op['montant'])
                                    for op in selected_data)

                # Créer l'Excel des charges fixes
                excel_path = create_excel_charges_fixes_with_month(
                    selected_data, total_charges, mois_selectionne)

                # Télécharger
                try:
                    with open(excel_path, 'rb') as f:
                        data = f.read()
                finally:
                    if os.path.exists(excel_path):
                        os.unlink(excel_path)

                filename_suffix = f"_{mois_selectionne.replace('/', '_')}" if mois_selectionne != 'tous' else '_periode_complete'
                filename = f"charges_fixes{filename_suffix}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                response = HttpResponse(
                    data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                return response

            except Exception as e:
                return HttpResponse(f"Erreur lors du traitement: {str(e)}")

    # GET - Formulaire initial avec upload multiple
    return render(request, 'analyseur/charges_fixes.html')


def render_selection_interface_with_month(prelevements, achats_cb, mois_disponibles, nb_fichiers):
    """Maintenant utilise un template au lieu de HTML en dur"""

    # Préparer les données pour le template
    context = {
        'prelevements': prelevements,
        'achats_cb': achats_cb,
        'mois_disponibles': mois_disponibles,
        'nb_fichiers': nb_fichiers,
        'prelevements_json': json.dumps([{
            'date': op['date'].strftime('%d/%m/%Y'),
            'mois': op['date'].strftime('%m/%Y'),
            'libelle': op['libelle'],
            'description': op['description'],
            'montant': str(op['montant']),
            'type': 'prelevement'
        } for op in prelevements]),
        'achats_json': json.dumps([{
            'date': op['date'].strftime('%d/%m/%Y'),
            'mois': op['date'].strftime('%m/%Y'),
            'libelle': op['libelle'],
            'description': op['description'],
            'montant': str(op['montant']),
            'type': 'achat'
        } for op in achats_cb])
    }

    # Utiliser un template Django au lieu de HTML en dur
    html_content = render_to_string(
        'analyseur/selection_charges.html', context)
    return HttpResponse(html_content)


def simulateur_pret(request):
    """Interface principale du simulateur de prêt immobilier avec dashboard intégré"""

    if request.method == 'POST':
        try:
            data = json.loads(
                request.body) if request.content_type == 'application/json' else request.POST

            # Récupération des paramètres
            mode = data.get('mode', 'capacite')  # capacite ou mensualite

            simulateur = SimulateurPretImmobilier()

            if mode == 'capacite':
                # Mode calcul de capacité d'emprunt
                revenus = float(data.get('revenus_nets', 0))
                charges = float(data.get('charges_mensuelles', 0))
                duree = int(data.get('duree', 20))
                region = data.get('region', 'autre')
                profil = data.get('profil', 'moyen')
                age = int(data.get('age', 35))
                nb_adultes = int(data.get('nb_adultes', 2))
                nb_enfants = int(data.get('nb_enfants', 0))

                if revenus <= 0:
                    raise ValueError("Les revenus doivent être supérieurs à 0")

                resultat = simulateur.calculer_capacite_emprunt(
                    revenus, charges, duree, region, profil, age)

                # Prix d'achat maximum : l'argent disponible (capacité + apport)
                # doit couvrir le prix DU BIEN *et* les frais de notaire. Comme
                # frais = prix × taux, on inverse : prix = dispo / (1 + taux),
                # sinon les frais ne seraient réservés par rien.
                apport = float(data.get('apport', 0))
                type_bien = data.get('type_bien', 'ancien')
                taux_notaire = FRAIS_NOTAIRE.get(
                    type_bien, FRAIS_NOTAIRE['ancien'])

                budget_disponible = resultat['capacite_emprunt'] + apport
                prix_max = budget_disponible / (1 + taux_notaire)
                frais_notaire = simulateur.calculer_frais_notaire(
                    prix_max, type_bien)

                # Calcul reste à vivre avec alertes
                reste_vivre_data = simulateur.calculer_reste_a_vivre(
                    revenus, charges + resultat['mensualite_max'], nb_adultes, nb_enfants)

                # Sauvegarde en session pour le dashboard
                request.session['revenus_nets'] = revenus
                request.session['charges_fixes'] = charges
                request.session['capacite_emprunt'] = resultat['capacite_emprunt']
                request.session['mensualite_max'] = resultat['mensualite_max']
                request.session['apport'] = apport
                request.session['duree'] = duree

                resultat.update({
                    'prix_achat_max': round(prix_max, 2),
                    'apport': apport,
                    'frais_notaire': frais_notaire,
                    'budget_total': round(prix_max + frais_notaire, 2),
                    'reste_a_vivre': reste_vivre_data['reste_a_vivre'],
                    'alerte_reste_vivre': reste_vivre_data['alerte'],
                    'statut_dossier': calculer_statut_dossier(request.session)
                })

            else:  # mode == 'mensualite'
                # Mode calcul de mensualités
                montant = float(data.get('montant_emprunt', 0))
                duree = int(data.get('duree', 20))
                taux_nominal = float(data.get('taux_nominal', 3.5))
                taux_assurance = float(data.get('taux_assurance', 0.25))

                if montant <= 0:
                    raise ValueError(
                        "Le montant d'emprunt doit être supérieur à 0")

                resultat = simulateur.calculer_mensualites(
                    montant, duree, taux_nominal, taux_assurance)

                # Ajout du tableau d'amortissement
                resultat['tableau_amortissement'] = simulateur.generer_tableau_amortissement(
                    montant, duree, taux_nominal, taux_assurance
                )

            return JsonResponse({'success': True, 'data': resultat})

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    # GET - Interface utilisateur avec template Django
    return render(request, 'analyseur/simulateur_pret.html')


def dashboard_dossier(request):
    """Dashboard centralisé du dossier immobilier"""

    # Récupérer les données utilisateur (session)
    revenus = float(request.session.get('revenus_nets', 0) or 0)
    charges = float(request.session.get('charges_fixes', 0) or 0)
    mensualite_max = float(request.session.get('mensualite_max', 0) or 0)

    # Le taux d'endettement est calculé ici : les templates Django n'ont pas
    # d'opérateurs arithmétiques (les filtres « div »/« mul » n'existent pas).
    taux_endettement = round(
        (charges + mensualite_max) / revenus * 100, 1) if revenus > 0 else 0

    dossier_data = {
        'revenus_nets': revenus,
        'charges_fixes': charges,
        'capacite_calculee': request.session.get('capacite_emprunt', 0),
        'apport': request.session.get('apport', 0),
        'mensualite_max': mensualite_max,
        'taux_endettement': taux_endettement,
        'statut_dossier': calculer_statut_dossier(request.session),
    }

    return render(request, 'analyseur/dashboard.html', {'dossier': dossier_data})


def export_dossier_pdf(request):
    """Génère un PDF synthétique du dossier"""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
    except ImportError:
        return HttpResponse("Module reportlab non installé", status=500)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="dossier_immobilier_{datetime.now().strftime("%Y%m%d")}.pdf"'

    p = canvas.Canvas(response, pagesize=A4)

    # En-tête
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, 800, "DOSSIER DE FINANCEMENT IMMOBILIER")
    p.setFont("Helvetica", 10)
    p.drawString(50, 780, f"Généré le {datetime.now().strftime('%d/%m/%Y')}")

    # Données financières
    y_pos = 750
    session_data = request.session

    sections = [
        ("SITUATION FINANCIÈRE", [
            f"Revenus nets mensuels: {session_data.get('revenus_nets', 'N/A')} €",
            f"Charges fixes mensuelles: {session_data.get('charges_fixes', 'N/A')} €",
            f"Apport personnel: {session_data.get('apport', 'N/A')} €"
        ]),
        ("CAPACITÉ D'EMPRUNT", [
            f"Montant maximum: {session_data.get('capacite_emprunt', 'N/A')} €",
            f"Mensualité maximum: {session_data.get('mensualite_max', 'N/A')} €",
            f"Durée recommandée: {session_data.get('duree', 'N/A')} ans"
        ])
    ]

    for titre, items in sections:
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y_pos, titre)
        y_pos -= 20

        p.setFont("Helvetica", 10)
        for item in items:
            p.drawString(70, y_pos, f"• {item}")
            y_pos -= 15
        y_pos -= 10

    p.save()
    return response
