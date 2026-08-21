#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================
 Gestion des Calendriers de Surveillance Scolaire
====================================================================

Application de bureau (Tkinter) permettant de generer automatiquement
des calendriers de surveillance scolaire au format PDF (mise en page
paysagere, ReportLab), pour le 1er Cycle/College et le 2e Cycle/Lycee.

Fichier unique, organise en sections clairement delimitees pour rester
lisible et facile a maintenir :

    1. MODELES DE DONNEES        (AdminConfig, ScheduleRow, CycleData, ProjectData)
    2. GENERATION PDF             (generate_pdf, avec ReportLab)
    3. BOITES DE DIALOGUE          (CreneauDialog)
    4. FENETRE DE DEMARRAGE        (AdminConfigWindow)
    5. PANNEAU D'UN CYCLE          (ScrollableGrid, CycleFrame)
    6. FENETRE PRINCIPALE          (MainApplication)
    7. POINT D'ENTREE              (main)

Dependances :
    pip install reportlab

Lancement :
    python3 gestion_surveillance.py
====================================================================
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import tkinter as tk
from datetime import date, datetime
from dataclasses import asdict, dataclass, field
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A2, A3, A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


# ====================================================================
# 1. MODELES DE DONNEES
# ====================================================================
#
# Ces classes ne dependent d'aucune bibliotheque graphique : elles ne
# contiennent que des structures de donnees simples (dataclasses) et
# leur (de)serialisation JSON.
#
# Hierarchie des donnees :
#
#     ProjectData
#     |-- AdminConfig            (informations administratives)
#     |-- CycleData (1er Cycle)  (classes + creneaux de surveillance)
#     `-- CycleData (2e Cycle)   (classes + creneaux de surveillance)
#             `-- ScheduleRow    (un creneau : jour, date, horaire, affectations)
# ====================================================================


@dataclass
class AdminConfig:
    """Informations administratives affichees en entete de chaque calendrier."""

    nom_etablissement: str = ""
    bp: str = ""
    annee_scolaire: str = ""
    iesg: str = ""

    def is_complete(self) -> bool:
        """Renvoie True si les champs essentiels sont renseignes."""
        return bool(self.nom_etablissement.strip())


@dataclass
class ScheduleRow:
    """
    Represente un creneau de surveillance, c'est-a-dire une ligne du
    tableau final : un jour, une date, un horaire, et pour chaque classe
    le nom du surveillant affecte (chaine vide si aucun surveillant
    n'est affecte).
    """

    jour: str = ""
    date: str = ""
    horaire: str = ""
    cellules_sans_surveillant: List[str] = field(default_factory=list)
    assignments: Dict[str, str] = field(default_factory=dict)

    def surveillant(self, classe: str) -> str:
        return self.assignments.get(classe, "")

    def set_surveillant(self, classe: str, nom: str) -> None:
        self.assignments[classe] = nom

    def cellule_sans_surveillant(self, classe: str) -> bool:
        return classe in self.cellules_sans_surveillant

    # -- (de)serialisation ---------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "jour": self.jour,
            "date": self.date,
            "horaire": self.horaire,
            "cellules_sans_surveillant": list(self.cellules_sans_surveillant),
            "assignments": dict(self.assignments),
        }

    @staticmethod
    def from_dict(data: dict) -> "ScheduleRow":
        if not isinstance(data, dict):
            raise ValueError("Un créneau doit être représenté par un objet JSON.")
        assignments = data.get("assignments", {})
        if not isinstance(assignments, dict):
            raise ValueError("Les affectations d'un créneau doivent être un objet JSON.")
        cellules = data.get("cellules_sans_surveillant", [])
        if not isinstance(cellules, list):
            raise ValueError("Les cellules sans surveillant doivent être une liste JSON.")
        row = ScheduleRow(
            jour=data.get("jour", ""),
            date=data.get("date", ""),
            horaire=data.get("horaire", ""),
            cellules_sans_surveillant=[str(classe) for classe in cellules],
            assignments={str(classe): str(nom) for classe, nom in assignments.items()},
        )
        for classe in row.cellules_sans_surveillant:
            row.assignments.pop(classe, None)
        return row


@dataclass
class Surveillant:
    """
    Represente un surveillant pouvant etre affecte a des creneaux de
    surveillance.

    `jours_libres` contient les jours de la semaine ou ce surveillant
    N'EST PAS disponible (il ne doit donc jamais lui etre affecte de
    creneau tombant l'un de ces jours).

    `horaires_libres` contient les horaires auxquels ce surveillant
    N'EST PAS disponible.

    `quota` est le nombre cible de surveillances a lui affecter au total
    (0 = illimite, aucune limite appliquee).
    """

    nom: str = ""
    jours_libres: List[str] = field(default_factory=list)
    horaires_libres: List[str] = field(default_factory=list)
    quota: int = 0

    # -- (de)serialisation ---------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "nom": self.nom,
            "jours_libres": list(self.jours_libres),
            "horaires_libres": list(self.horaires_libres),
            "quota": self.quota,
        }

    @staticmethod
    def from_dict(data: dict) -> "Surveillant":
        return Surveillant(
            nom=data.get("nom", ""),
            jours_libres=list(data.get("jours_libres", [])),
            horaires_libres=list(data.get("horaires_libres", [])),
            quota=int(data.get("quota", 0) or 0),
        )


@dataclass
class CycleData:
    """
    Regroupe les donnees d'un cycle d'enseignement : la liste des classes
    concernees (colonnes du tableau), la liste des creneaux de
    surveillance (lignes du tableau), chaque creneau portant les
    affectations de surveillants pour chaque classe, ainsi que la base de
    donnees des surveillants disponibles pour ce cycle (utilisee pour la
    generation automatique du planning).
    """

    nom_cycle: str = ""
    titre_calendrier: str = "CALENDRIER DE SURVEILLANCE"
    classes: List[str] = field(default_factory=list)
    rows: List[ScheduleRow] = field(default_factory=list)
    surveillants: List[Surveillant] = field(default_factory=list)

    # -- gestion des classes --------------------------------------------------

    def add_classe(self, nom: str) -> bool:
        """Ajoute une classe (colonne). Renvoie False si elle existe deja."""
        nom = nom.strip()
        if not nom or nom in self.classes:
            return False
        self.classes.append(nom)
        for row in self.rows:
            row.assignments.setdefault(nom, "")
        return True

    def rename_classe(self, ancien_nom: str, nouveau_nom: str) -> bool:
        nouveau_nom = nouveau_nom.strip()
        if not nouveau_nom or ancien_nom not in self.classes or nouveau_nom in self.classes:
            return False
        idx = self.classes.index(ancien_nom)
        self.classes[idx] = nouveau_nom
        for row in self.rows:
            row.assignments[nouveau_nom] = row.assignments.pop(ancien_nom, "")
            if ancien_nom in row.cellules_sans_surveillant:
                row.cellules_sans_surveillant.remove(ancien_nom)
                row.cellules_sans_surveillant.append(nouveau_nom)
        return True

    def remove_classe(self, nom: str) -> None:
        if nom in self.classes:
            self.classes.remove(nom)
            for row in self.rows:
                row.assignments.pop(nom, None)
                if nom in row.cellules_sans_surveillant:
                    row.cellules_sans_surveillant.remove(nom)

    # -- gestion des creneaux --------------------------------------------------

    def add_row(self, jour: str, date: str, horaire: str) -> ScheduleRow:
        row = ScheduleRow(
            jour=jour,
            date=date,
            horaire=horaire,
            assignments={c: "" for c in self.classes},
        )
        self.rows.append(row)
        return row

    def update_row(self, index: int, jour: str, date: str, horaire: str) -> None:
        if 0 <= index < len(self.rows):
            row = self.rows[index]
            row.jour, row.date, row.horaire = jour, date, horaire

    def remove_row(self, index: int) -> None:
        if 0 <= index < len(self.rows):
            del self.rows[index]

    def validation_errors(self) -> List[str]:
        """Retourne les incoherences qui empecheraient un export fiable."""
        erreurs: List[str] = []
        noms_surveillants = {s.nom for s in self.surveillants}
        if len(self.classes) != len(set(self.classes)):
            erreurs.append("Le cycle contient des classes en double.")
        cles_creneaux = [(row.jour, row.date, row.horaire) for row in self.rows]
        if len(cles_creneaux) != len(set(cles_creneaux)):
            erreurs.append("Le cycle contient des créneaux en double.")
        for index, row in enumerate(self.rows, start=1):
            for classe, nom in row.assignments.items():
                if classe not in self.classes:
                    erreurs.append(f"L'affectation de la ligne {index} vise une classe inconnue : {classe}.")
                if nom and nom not in noms_surveillants:
                    erreurs.append(f"Ligne {index}, classe {classe} : surveillant inconnu ({nom}).")
            noms_du_creneau = [
                row.surveillant(classe)
                for classe in self.classes
                if not row.cellule_sans_surveillant(classe) and row.surveillant(classe)
            ]
            if len(noms_du_creneau) != len(set(noms_du_creneau)):
                erreurs.append(
                    f"Ligne {index} ({row.date} {row.horaire}) : un surveillant est affecté à plusieurs classes."
                )
        return erreurs

    def move_row(self, index: int, delta: int) -> None:
        """Deplace une ligne vers le haut (delta=-1) ou le bas (delta=+1)."""
        new_index = index + delta
        if 0 <= index < len(self.rows) and 0 <= new_index < len(self.rows):
            self.rows[index], self.rows[new_index] = self.rows[new_index], self.rows[index]

    # -- gestion des surveillants ----------------------------------------------

    def add_surveillant(
        self,
        nom: str,
        jours_libres: Optional[List[str]] = None,
        quota: int = 0,
        horaires_libres: Optional[List[str]] = None,
    ) -> bool:
        """Ajoute un surveillant a la base. Renvoie False si le nom existe deja."""
        nom = nom.strip()
        if not nom or any(s.nom == nom for s in self.surveillants):
            return False
        self.surveillants.append(
            Surveillant(
                nom=nom,
                jours_libres=list(jours_libres or []),
                horaires_libres=list(horaires_libres or []),
                quota=max(0, quota),
            )
        )
        return True

    def update_surveillant(
        self,
        index: int,
        nom: str,
        jours_libres: Optional[List[str]] = None,
        quota: int = 0,
        horaires_libres: Optional[List[str]] = None,
    ) -> bool:
        """Modifie un surveillant existant. Renvoie False si le nouveau nom entre en conflit."""
        nom = nom.strip()
        if not nom or not (0 <= index < len(self.surveillants)):
            return False
        if any(i != index and s.nom == nom for i, s in enumerate(self.surveillants)):
            return False
        ancien_nom = self.surveillants[index].nom
        self.surveillants[index] = Surveillant(
            nom=nom,
            jours_libres=list(jours_libres or []),
            horaires_libres=list(horaires_libres or []),
            quota=max(0, quota),
        )
        if ancien_nom != nom:
            # repercute le changement de nom sur les affectations deja saisies
            for row in self.rows:
                for classe, affecte in list(row.assignments.items()):
                    if affecte == ancien_nom:
                        row.assignments[classe] = nom
        return True

    def remove_surveillant(self, index: int) -> None:
        if 0 <= index < len(self.surveillants):
            del self.surveillants[index]

    # -- (de)serialisation ---------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "nom_cycle": self.nom_cycle,
            "titre_calendrier": self.titre_calendrier,
            "classes": list(self.classes),
            "rows": [r.to_dict() for r in self.rows],
            "surveillants": [s.to_dict() for s in self.surveillants],
        }

    @staticmethod
    def from_dict(data: dict) -> "CycleData":
        if not isinstance(data, dict):
            raise ValueError("Un cycle doit être représenté par un objet JSON.")
        classes = data.get("classes", [])
        rows = data.get("rows", [])
        if not rows and isinstance(data.get("creneaux"), list):
            rows = data["creneaux"]
        surveillants = data.get("surveillants", [])
        if not all(isinstance(valeur, list) for valeur in (classes, rows, surveillants)):
            raise ValueError("Les classes, créneaux et surveillants doivent être des listes JSON.")
        cycle = CycleData(
            nom_cycle=data.get("nom_cycle", ""),
            titre_calendrier=data.get("titre_calendrier", "CALENDRIER DE SURVEILLANCE"),
        )
        cycle.classes = [str(classe) for classe in classes]
        cycle.rows = [ScheduleRow.from_dict(row) for row in rows]
        cycle.surveillants = [Surveillant.from_dict(surveillant) for surveillant in surveillants]
        return cycle


@dataclass
class ProjectData:
    """Represente l'integralite d'un projet : un fichier .json de travail."""

    FORMAT_VERSION = 1

    admin: AdminConfig = field(default_factory=AdminConfig)
    cycle1: CycleData = field(
        default_factory=lambda: CycleData(nom_cycle="1er Cycle / College")
    )
    cycle2: CycleData = field(
        default_factory=lambda: CycleData(nom_cycle="2e Cycle / Lycee")
    )

    # -- (de)serialisation ---------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": self.FORMAT_VERSION,
            "admin": asdict(self.admin),
            "cycle1": self.cycle1.to_dict(),
            "cycle2": self.cycle2.to_dict(),
        }

    @staticmethod
    def from_dict(data: dict) -> "ProjectData":
        if not isinstance(data, dict):
            raise ValueError("Le fichier de projet doit contenir un objet JSON.")
        version = data.get("version", 1)
        if version != ProjectData.FORMAT_VERSION:
            raise ValueError(f"Version de projet non prise en charge : {version}.")
        admin_data = data.get("admin", {})
        cycles_data = data.get("cycles")
        if isinstance(cycles_data, list):
            cycle1_data = cycles_data[0] if len(cycles_data) > 0 else {}
            cycle2_data = cycles_data[1] if len(cycles_data) > 1 else {}
        else:
            cycle1_data = data.get("cycle1", data.get("cycle_1", {}))
            cycle2_data = data.get("cycle2", data.get("cycle_2", {}))
        if not all(isinstance(valeur, dict) for valeur in (admin_data, cycle1_data, cycle2_data)):
            raise ValueError("Les sections admin, cycle1 et cycle2 doivent être des objets JSON.")
        project = ProjectData()
        project.admin = AdminConfig(
            nom_etablissement=str(admin_data.get("nom_etablissement", "")),
            bp=str(admin_data.get("bp", "")),
            annee_scolaire=str(admin_data.get("annee_scolaire", "")),
            iesg=str(admin_data.get("iesg", "")),
        )
        project.cycle1 = CycleData.from_dict(cycle1_data)
        project.cycle2 = CycleData.from_dict(cycle2_data)
        return project

    def save(self, path: str) -> None:
        directory = os.path.dirname(os.path.abspath(path))
        temporary_path = None
        try:
            if os.path.exists(path):
                with open(path, "rb") as source, open(f"{path}.bak", "wb") as backup:
                    backup.write(source.read())
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory, prefix=".calendrier-", suffix=".tmp", delete=False
            ) as fh:
                temporary_path = fh.name
                json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary_path, path)
        except (OSError, TypeError, ValueError):
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
            raise

    @staticmethod
    def load(path: str) -> "ProjectData":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return ProjectData.from_dict(data)


# ====================================================================
# 2. GENERATION PDF
# ====================================================================
#
# Le document reproduit la structure d'un calendrier de surveillance
# "officiel" :
#   - un entete administratif (etablissement, BP, IESG, annee scolaire) ;
#   - un titre centre, en gras et souligne ;
#   - un tableau ou chaque ligne est un creneau (jour / date / horaire)
#     et chaque colonne (au-dela des trois premieres) une classe, la
#     cellule contenant le nom du surveillant affecte ;
#   - les cellules "jour/date" de creneaux consecutifs du meme jour sont
#     fusionnees verticalement, et les jours alternent une couleur de
#     fond pour faciliter la lecture ;
#   - une zone de signature en bas de page.
# ====================================================================

# Couleur de fond utilisee en alternance pour distinguer les jours
# (rappel du jaune utilise dans le modele original de calendrier).
_COULEUR_ALTERNEE = colors.HexColor("#FFF2AE")
_COULEUR_ENTETE = colors.HexColor("#D9D9D9")


def _choisir_format_page(nb_classes: int):
    """Choisit un format de page paysager adapte au nombre de colonnes."""
    if nb_classes > 16:
        return landscape(A2)
    if nb_classes > 8:
        return landscape(A3)
    return landscape(A4)


def _style(nom: str, **kwargs) -> ParagraphStyle:
    base = dict(fontName="Helvetica", fontSize=9, leading=11)
    base.update(kwargs)
    return ParagraphStyle(nom, **base)


def _construire_entete(project: ProjectData, largeur_page: float) -> Table:
    """Construit le bloc d'entete administratif (etablissement / annee)."""
    admin = project.admin
    style_gauche = _style("entete_gauche", fontName="Helvetica-Bold", fontSize=12, leading=15)
    style_droite = _style(
        "entete_droite", fontName="Helvetica-Bold", fontSize=12, leading=15, alignment=2
    )

    texte_gauche = f"IESG - {admin.iesg}<br/>{admin.nom_etablissement}<br/>BP : {admin.bp}"
    texte_droite = f"ANNEE SCOLAIRE : {admin.annee_scolaire}"

    tbl = Table(
        [[Paragraph(texte_gauche, style_gauche), Paragraph(texte_droite, style_droite)]],
        colWidths=[largeur_page * 0.6, largeur_page * 0.4],
    )
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return tbl


def _construire_titre(cycle: CycleData) -> Paragraph:
    style = _style(
        "titre",
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=19,
        alignment=1,  # centre
    )
    texte = f"<u>{cycle.titre_calendrier}</u><br/><u>{cycle.nom_cycle.upper()}</u>"
    return Paragraph(texte, style)


def _construire_tableau(cycle: CycleData, largeur_page: float) -> Table:
    """
    Construit le tableau principal du calendrier :
        colonne 0 : Jour / Date
        colonne 1 : Horaire
        colonnes suivantes : une par classe
    Les lignes portant le meme (jour, date) sont fusionnees sur la
    premiere colonne, et les groupes de jours alternent une couleur de
    fond.
    """
    style_entete_cell = _style(
        "entete_cell", fontName="Helvetica-Bold", fontSize=10, alignment=1, leading=12
    )
    style_cell = _style("cell", fontName="Helvetica", fontSize=9, alignment=1, leading=11)
    style_cell_bold = _style(
        "cell_bold", fontName="Helvetica-Bold", fontSize=9, alignment=1, leading=11
    )

    # -- construction des lignes -------------------------------------------------
    entetes = [Paragraph("Jour / Date", style_entete_cell), Paragraph("Horaire", style_entete_cell)]
    entetes += [Paragraph(c, style_entete_cell) for c in cycle.classes]
    data = [entetes]

    # SPAN et couleurs a appliquer, calcules pendant la construction des lignes
    spans = []
    background_commands = []

    ligne_courante = 1  # la ligne 0 est l'entete
    idx = 0
    alterner = False
    n = len(cycle.rows)
    while idx < n:
        row = cycle.rows[idx]
        # regroupe les creneaux consecutifs partageant le meme (jour, date)
        debut_groupe = idx
        while (
            idx + 1 < n
            and cycle.rows[idx + 1].jour == row.jour
            and cycle.rows[idx + 1].date == row.date
        ):
            idx += 1
        fin_groupe = idx
        taille_groupe = fin_groupe - debut_groupe + 1

        for i in range(debut_groupe, fin_groupe + 1):
            r = cycle.rows[i]
            ligne = []
            if i == debut_groupe:
                ligne.append(Paragraph(f"{r.jour}<br/>{r.date}", style_cell_bold))
            else:
                ligne.append(Paragraph("", style_cell))  # cellule fusionnee -> vide
            ligne.append(Paragraph(r.horaire, style_cell))
            for c in cycle.classes:
                texte = "/////" if r.cellule_sans_surveillant(c) else (r.surveillant(c) or "")
                ligne.append(Paragraph(texte, style_cell))
            for c_idx, classe in enumerate(cycle.classes):
                if r.cellule_sans_surveillant(classe):
                    background_commands.append(
                        (
                            "BACKGROUND",
                            (2 + c_idx, ligne_courante + i - debut_groupe),
                            (2 + c_idx, ligne_courante + i - debut_groupe),
                            colors.HexColor("#D0D0D0"),
                        )
                    )
            data.append(ligne)

        if taille_groupe > 1:
            ligne_debut = ligne_courante
            ligne_fin = ligne_courante + taille_groupe - 1
            spans.append(("SPAN", (0, ligne_debut), (0, ligne_fin)))

        if alterner:
            background_commands.append(
                (
                    "BACKGROUND",
                    (0, ligne_courante),
                    (-1, ligne_courante + taille_groupe - 1),
                    _COULEUR_ALTERNEE,
                )
            )
        alterner = not alterner

        ligne_courante += taille_groupe
        idx += 1

    # -- largeurs de colonnes -------------------------------------------------
    largeur_jour = largeur_page * 0.10
    largeur_horaire = largeur_page * 0.09
    largeur_restante = largeur_page - largeur_jour - largeur_horaire
    n_classes = max(len(cycle.classes), 1)
    largeur_classe = largeur_restante / n_classes
    col_widths = [largeur_jour, largeur_horaire] + [largeur_classe] * len(cycle.classes)

    tbl = Table(data, colWidths=col_widths, repeatRows=1)

    style_commands = [
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), _COULEUR_ENTETE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    style_commands += spans
    style_commands += background_commands
    tbl.setStyle(TableStyle(style_commands))
    return tbl


def _construire_signature(nom_signataire: str, lieu_signature: str, date_signature: str) -> Table:
    """Bloc de signature renseigne, aligne a droite en bas de page."""
    style = _style("signature", fontName="Helvetica-Bold", fontSize=12, alignment=2)
    tbl = Table(
        [
            [Paragraph(f"Fait à {lieu_signature}, le {date_signature}", style)],
            [Paragraph(nom_signataire, style)],
        ],
        colWidths=[6 * cm],
    )
    tbl.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 30),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return tbl


def _construire_flowables_cycle(
    project: ProjectData,
    cycle: CycleData,
    largeur_page: float,
    nom_signataire: str,
    lieu_signature: str,
    date_signature: str,
) -> list:
    elements = []
    elements.append(_construire_entete(project, largeur_page))
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(_construire_titre(cycle))
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(_construire_tableau(cycle, largeur_page))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(_construire_signature(nom_signataire, lieu_signature, date_signature))
    return elements


def generate_pdf(
    project: ProjectData,
    cycles: Sequence[CycleData],
    output_path: str,
    nom_signataire: str,
    lieu_signature: str,
    date_signature: str,
) -> None:
    """
    Genere le PDF du calendrier de surveillance pour un ou plusieurs cycles.

    Parametres
    ----------
    project : ProjectData
        Le projet complet (utilise pour les informations d'entete).
    cycles : sequence de CycleData
        Le(s) cycle(s) a exporter. Si plusieurs cycles sont fournis, chacun
        est place sur une page distincte du meme document.
    output_path : str
        Chemin du fichier PDF a produire.

    Leve
    ----
    ValueError si un cycle ne comporte aucune classe ou aucun creneau.
    """
    cycles = list(cycles)
    if not cycles:
        raise ValueError("Aucun cycle n'a été sélectionné pour l'export.")
    for cycle in cycles:
        if not cycle.classes:
            raise ValueError(f"Le cycle « {cycle.nom_cycle} » ne comporte aucune classe.")
        if not cycle.rows:
            raise ValueError(f"Le cycle « {cycle.nom_cycle} » ne comporte aucun creneau.")

    page_size = _choisir_format_page(max(len(c.classes) for c in cycles))
    marge = 0.7 * cm
    largeur_page = page_size[0] - 2 * marge

    directory = os.path.dirname(os.path.abspath(output_path))
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=directory, prefix=".calendrier-pdf-", suffix=".tmp", delete=False
        ) as temporary_file:
            temporary_path = temporary_file.name
        doc = BaseDocTemplate(
            temporary_path,
            pagesize=page_size,
            leftMargin=marge,
            rightMargin=marge,
            topMargin=marge,
            bottomMargin=marge,
            title="Calendrier de surveillance",
        )
        frame = Frame(marge, marge, largeur_page, page_size[1] - 2 * marge, id="main")
        doc.addPageTemplates([PageTemplate(id="page", frames=[frame])])

        story = []
        for i, cycle in enumerate(cycles):
            if i > 0:
                story.append(PageBreak())
            story.extend(
                _construire_flowables_cycle(
                    project, cycle, largeur_page, nom_signataire, lieu_signature, date_signature
                )
            )
        doc.build(story)
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


# ====================================================================
# 2 bis. ALGORITHME D'AFFECTATION AUTOMATIQUE DES SURVEILLANTS
# ====================================================================


def generer_planning_automatique(cycle: CycleData, remplacer_existant: bool = False) -> Dict[str, int]:
    """
    Genere automatiquement les affectations de surveillants pour toutes les
    cellules (creneau x classe) d'un cycle, en respectant :
        - les jours libres de chaque surveillant (il n'est jamais affecte
          un jour ou il n'est pas disponible) ;
        - le quota de chaque surveillant (nombre cible de surveillances,
          0 = illimite) ;
        - l'impossibilite pour un meme surveillant de surveiller deux
          classes sur le meme creneau (meme jour + meme horaire).

    La charge est repartie de maniere equilibree : a chaque cellule, le
    surveillant disponible ayant le moins d'affectations en cours est
    choisi en priorite.

    Parametres
    ----------
    cycle : CycleData
        Le cycle pour lequel generer le planning.
    remplacer_existant : bool
        Si True, toutes les affectations deja saisies sont effacees avant
        la generation. Si False, seules les cellules vides sont
        if not rows and isinstance(data.get("creneaux"), list):
            rows = data["creneaux"]
        cycle.rows = [
            ScheduleRow.from_dict(row) if isinstance(row, dict) else ScheduleRow(
                jour=str(row[0]), date=str(row[1]), horaire=str(row[2]),
                assignments={classe: "" for classe in cycle.classes},
            )
            for row in rows
        ]

    Renvoie
    -------
    Un dictionnaire de statistiques :
        {"affectees": nb de cellules affectees par l'algorithme,
         "total": nb total de cellules du tableau,
         "non_affectees": nb de cellules restees vides faute de
                           surveillant disponible}

    Leve
    ----
    ValueError si aucun surveillant, aucune classe ou aucun creneau n'est
    defini.
    """
    if not cycle.surveillants:
        raise ValueError(
            "Aucun surveillant enregistre. Ajoutez des surveillants dans "
            "l'onglet « Saisie des Surveillants »."
        )
    if not cycle.classes or not cycle.rows:
        raise ValueError("Ajoutez au moins une classe et un creneau avant de generer le planning.")

    if remplacer_existant:
        for row in cycle.rows:
            for classe in cycle.classes:
                row.assignments[classe] = ""

    for row in cycle.rows:
        for classe in row.cellules_sans_surveillant:
            row.assignments.pop(classe, None)

    # compte les affectations deja presentes (mode "completer") pour que
    # l'equilibrage de charge en tienne compte des le depart
    compte: Dict[str, int] = {s.nom: 0 for s in cycle.surveillants}
    for row in cycle.rows:
        for classe in cycle.classes:
            if row.cellule_sans_surveillant(classe):
                continue
            nom = row.surveillant(classe)
            if nom in compte:
                compte[nom] += 1

    total = 0
    affectees = 0
    non_affectees = 0

    affectations_par_creneau: Dict[Tuple[str, str, str], set[str]] = {}
    for row in cycle.rows:
        cle_creneau = (row.jour, row.date, row.horaire)
        affectations_par_creneau.setdefault(cle_creneau, set()).update(
            row.surveillant(c) for c in cycle.classes if row.surveillant(c)
        )

    for row in cycle.rows:
        cle_creneau = (row.jour, row.date, row.horaire)
        deja_utilises_ce_creneau = affectations_par_creneau[cle_creneau]

        for classe in cycle.classes:
            total += 1
            if row.cellule_sans_surveillant(classe):
                continue
            if row.surveillant(classe):
                continue  # cellule deja remplie : on ne la touche pas

            # 1) candidats respectant strictement le quota
            candidats = [
                s
                for s in cycle.surveillants
                if row.jour not in s.jours_libres
                and row.horaire not in s.horaires_libres
                and s.nom not in deja_utilises_ce_creneau
                and (s.quota <= 0 or compte[s.nom] < s.quota)
            ]
            # 2) si personne ne respecte le quota, on le relache (mieux vaut
            #    depasser un quota que laisser une case vide)
            if not candidats:
                candidats = [
                    s
                    for s in cycle.surveillants
                    if (
                        row.jour not in s.jours_libres
                        and row.horaire not in s.horaires_libres
                        and s.nom not in deja_utilises_ce_creneau
                    )
                ]
            if not candidats:
                non_affectees += 1
                continue

            candidats.sort(key=lambda s: compte[s.nom])
            choisi = candidats[0]
            row.set_surveillant(classe, choisi.nom)
            compte[choisi.nom] += 1
            deja_utilises_ce_creneau.add(choisi.nom)
            affectees += 1

    quotas_depasse = sum(
        1 for surveillant in cycle.surveillants if surveillant.quota > 0 and compte[surveillant.nom] > surveillant.quota
    )
    return {
        "affectees": affectees,
        "total": total,
        "non_affectees": non_affectees,
        "quotas_depasse": quotas_depasse,
    }


# ====================================================================
# 3. BOITES DE DIALOGUE
# ====================================================================

JOURS_SEMAINE = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def _valider_date_creneau(date_text: str, jour: str) -> Optional[str]:
    """Valide une date et vérifie qu'elle correspond au jour sélectionné."""
    try:
        date_obj = datetime.strptime(date_text, "%d/%m/%Y")
    except ValueError:
        return "La date doit respecter le format jj/mm/aaaa."
    if JOURS_SEMAINE[date_obj.weekday()] != jour:
        return f"La date indiquée ne correspond pas au jour {jour}."
    return None


def _valider_horaire(horaire: str) -> bool:
    """Vérifie un horaire simple de type 07h30-09h30."""
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3])h[0-5]\d-(?:[01]\d|2[0-3])h[0-5]\d", horaire))


class CreneauDialog(tk.Toplevel):
    """
    Boite de dialogue modale pour saisir (ou modifier) un creneau de
    surveillance : jour, date et plusieurs horaires.

    Utilisation :
        dlg = CreneauDialog(parent, jour="Mardi", date="21/05/2026", horaires=["07h30-09h30"])
        parent.wait_window(dlg)
        if dlg.resultat is not None:
            jour, date, horaires = dlg.resultat
    """

    def __init__(
        self,
        parent: tk.Widget,
        titre: str = "Nouveau creneau",
        jour: str = "",
        date: str = "",
        horaire: str = "",
        horaires: Optional[List[str]] = None,
    ):
        super().__init__(parent)
        self.title(titre)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.resultat: Optional[Tuple[str, str, List[str]]] = None

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        self._var_jour = tk.StringVar(value=jour or JOURS_SEMAINE[0])
        self._var_date = tk.StringVar(value=date)
        self._var_horaire = tk.StringVar()
        self._horaires = list(horaires or ([horaire] if horaire else []))

        ttk.Label(frame, text="Jour :").grid(row=0, column=0, sticky="w", pady=4)
        combo_jour = ttk.Combobox(
            frame, textvariable=self._var_jour, values=JOURS_SEMAINE, state="readonly", width=20
        )
        combo_jour.grid(row=0, column=1, pady=4, padx=(8, 0))

        ttk.Label(frame, text="Date (jj/mm/aaaa) :").grid(row=1, column=0, sticky="w", pady=4)
        entry_date = ttk.Entry(frame, textvariable=self._var_date, width=22)
        entry_date.grid(row=1, column=1, pady=4, padx=(8, 0))

        ttk.Label(frame, text="Horaires (ex: 07h30-09h30) :").grid(row=2, column=0, sticky="nw", pady=4)
        entry_horaire = ttk.Entry(frame, textvariable=self._var_horaire, width=22)
        entry_horaire.grid(row=2, column=1, pady=4, padx=(8, 0))
        zone_horaires = ttk.Frame(frame)
        zone_horaires.grid(row=3, column=1, sticky="ew", padx=(8, 0))
        self._liste_horaires = tk.Listbox(zone_horaires, height=5, width=24, exportselection=False)
        self._liste_horaires.pack(side="left", fill="both", expand=True)
        actions_horaires = ttk.Frame(zone_horaires)
        actions_horaires.pack(side="left", fill="y", padx=(6, 0))
        ttk.Button(actions_horaires, text="Ajouter", command=self._ajouter_horaire).pack(anchor="w")
        ttk.Button(actions_horaires, text="Retirer", command=self._retirer_horaire).pack(
            anchor="w", pady=(6, 0)
        )
        for valeur in self._horaires:
            self._liste_horaires.insert("end", valeur)

        boutons = ttk.Frame(frame)
        boutons.grid(row=4, column=0, columnspan=2, pady=(16, 0), sticky="e")
        ttk.Button(boutons, text="Annuler", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(boutons, text="Valider", command=self._valider).pack(side="right")

        self.bind("<Return>", lambda _evt: self._valider())
        self.bind("<Escape>", lambda _evt: self.destroy())
        entry_date.focus_set()

    def _ajouter_horaire(self) -> bool:
        horaire = self._var_horaire.get().strip()
        if not _valider_horaire(horaire):
            messagebox.showwarning(
                "Horaire invalide",
                "L'horaire doit respecter le format HHhMM-HHhMM, par exemple 07h30-09h30.",
                parent=self,
            )
            return False
        if horaire in self._horaires:
            messagebox.showinfo("Horaire deja ajoute", "Cet horaire figure deja dans la liste.", parent=self)
            return False
        self._horaires.append(horaire)
        self._liste_horaires.insert("end", horaire)
        self._var_horaire.set("")
        return True

    def _retirer_horaire(self) -> None:
        selection = self._liste_horaires.curselection()
        if not selection:
            return
        index = selection[0]
        self._liste_horaires.delete(index)
        del self._horaires[index]

    def _valider(self) -> None:
        date = self._var_date.get().strip()
        horaire_saisi = self._var_horaire.get().strip()
        if horaire_saisi:
            if not self._ajouter_horaire():
                return
        if not date or not self._horaires:
            messagebox.showwarning("Champs manquants", "La date et au moins un horaire sont obligatoires.", parent=self)
            return
        erreur_date = _valider_date_creneau(date, self._var_jour.get())
        if erreur_date:
            messagebox.showwarning("Date invalide", erreur_date, parent=self)
            return
        self.resultat = (self._var_jour.get(), date, list(self._horaires))
        self.destroy()


class CellulesSansSurveillantDialog(tk.Toplevel):
    """Permet de sélectionner les cellules qui doivent rester vides."""

    def __init__(self, parent: tk.Widget, cycle: CycleData):
        super().__init__(parent)
        self.title("Cellules sans surveillant")
        self.geometry("760x600")
        self.minsize(520, 320)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        self.resultat: Optional[List[Tuple[int, str]]] = None
        self._vars: Dict[Tuple[int, str], tk.BooleanVar] = {}

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(
            frame,
            text="Cochez les cellules dans lesquelles aucun surveillant ne sera affecté :",
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        zone_defilement = ttk.Frame(frame)
        zone_defilement.grid(row=1, column=0, sticky="nsew")
        zone_defilement.rowconfigure(0, weight=1)
        zone_defilement.columnconfigure(0, weight=1)

        canvas = tk.Canvas(zone_defilement, highlightthickness=0)
        curseur = ttk.Scrollbar(zone_defilement, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=curseur.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        curseur.grid(row=0, column=1, sticky="ns")

        liste = ttk.Frame(canvas)
        fenetre_liste = canvas.create_window((0, 0), window=liste, anchor="nw")

        def actualiser_zone(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def ajuster_largeur(_event) -> None:
            canvas.itemconfigure(fenetre_liste, width=canvas.winfo_width())

        liste.bind("<Configure>", actualiser_zone)
        canvas.bind("<Configure>", ajuster_largeur)

        for row_idx, row in enumerate(cycle.rows):
            groupe = ttk.LabelFrame(
                liste, text=f"{row.jour} {row.date} - {row.horaire}", padding=6
            )
            groupe.pack(fill="x", pady=3)
            for col_idx, classe in enumerate(cycle.classes):
                key = (row_idx, classe)
                var = tk.BooleanVar(value=row.cellule_sans_surveillant(classe))
                self._vars[key] = var
                ttk.Checkbutton(groupe, text=classe, variable=var).grid(
                    row=col_idx // 3, column=col_idx % 3, sticky="w", padx=(0, 18), pady=1
                )

        canvas.bind(
            "<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units")
        )

        boutons = ttk.Frame(frame)
        boutons.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(boutons, text="Annuler", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(boutons, text="Valider", command=self._valider).pack(side="right")
        self.bind("<Return>", lambda _evt: self._valider())
        self.bind("<Escape>", lambda _evt: self.destroy())

    def _valider(self) -> None:
        self.resultat = [key for key, var in self._vars.items() if var.get()]
        self.destroy()


class SignatureDialog(tk.Toplevel):
    """Boite de dialogue pour renseigner la date et le nom du signataire."""

    def __init__(self, parent: tk.Widget):
        super().__init__(parent)
        self.title("Informations de signature")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.resultat: Optional[Tuple[str, str, str]] = None
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        self._var_date = tk.StringVar(value=date.today().strftime("%d/%m/%Y"))
        self._var_lieu = tk.StringVar()
        self._var_nom = tk.StringVar()

        ttk.Label(frame, text="Date du jour (jj/mm/aaaa) :").grid(
            row=0, column=0, sticky="w", pady=4
        )
        entry_date = ttk.Entry(frame, textvariable=self._var_date, width=22)
        entry_date.grid(row=0, column=1, pady=4, padx=(8, 0))

        ttk.Label(frame, text="Le lieu :").grid(row=1, column=0, sticky="w", pady=4)
        entry_lieu = ttk.Entry(frame, textvariable=self._var_lieu, width=22)
        entry_lieu.grid(row=1, column=1, pady=4, padx=(8, 0))

        ttk.Label(frame, text="Nom du signataire :").grid(row=2, column=0, sticky="w", pady=4)
        entry_nom = ttk.Entry(frame, textvariable=self._var_nom, width=22)
        entry_nom.grid(row=2, column=1, pady=4, padx=(8, 0))

        boutons = ttk.Frame(frame)
        boutons.grid(row=3, column=0, columnspan=2, pady=(16, 0), sticky="e")
        ttk.Button(boutons, text="Annuler", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(boutons, text="Valider", command=self._valider).pack(side="right")

        self.bind("<Return>", lambda _evt: self._valider())
        self.bind("<Escape>", lambda _evt: self.destroy())
        entry_nom.focus_set()

    def _valider(self) -> None:
        date_signature = self._var_date.get().strip()
        lieu_signature = self._var_lieu.get().strip()
        nom_signataire = self._var_nom.get().strip()
        if not date_signature or not lieu_signature or not nom_signataire:
            messagebox.showwarning(
                "Champs manquants",
                "La date, le lieu et le nom du signataire sont obligatoires.",
                parent=self,
            )
            return
        self.resultat = (nom_signataire, lieu_signature, date_signature)
        self.destroy()


class SurveillantDialog(tk.Toplevel):
    """
    Boite de dialogue modale pour ajouter/modifier un surveillant :
    nom, jours et horaires libres (indisponibilite), et quota de surveillance.

    Utilisation :
        dlg = SurveillantDialog(parent, nom="SANNI", jours_libres=["Samedi"], quota=6)
        parent.wait_window(dlg)
        if dlg.resultat is not None:
            nom, jours_libres, horaires_libres, quota = dlg.resultat
    """

    def __init__(
        self,
        parent: tk.Widget,
        titre: str = "Nouveau surveillant",
        nom: str = "",
        jours_libres: Optional[List[str]] = None,
        horaires_disponibles: Optional[List[str]] = None,
        horaires_libres: Optional[List[str]] = None,
        quota: int = 0,
    ):
        super().__init__(parent)
        self.title(titre)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.resultat: Optional[Tuple[str, List[str], List[str], int]] = None
        jours_libres = jours_libres or []
        horaires_disponibles = horaires_disponibles or []
        horaires_libres = horaires_libres or []

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Nom du surveillant :").grid(row=0, column=0, sticky="w", pady=4)
        self._var_nom = tk.StringVar(value=nom)
        entry_nom = ttk.Entry(frame, textvariable=self._var_nom, width=28)
        entry_nom.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4, padx=(8, 0))

        ttk.Label(frame, text="Jours libres\n(indisponible) :", justify="left").grid(
            row=1, column=0, sticky="nw", pady=(10, 4)
        )
        self._vars_jours: Dict[str, tk.BooleanVar] = {}
        jours_frame = ttk.Frame(frame)
        jours_frame.grid(row=1, column=1, columnspan=2, sticky="w", pady=(10, 4), padx=(8, 0))
        for i, jour in enumerate(JOURS_SEMAINE):
            var = tk.BooleanVar(value=jour in jours_libres)
            self._vars_jours[jour] = var
            ttk.Checkbutton(jours_frame, text=jour, variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 12), pady=1
            )

        ttk.Label(frame, text="Horaires libres\n(indisponible) :", justify="left").grid(
            row=2, column=0, sticky="nw", pady=(10, 4)
        )
        self._vars_horaires: Dict[str, tk.BooleanVar] = {}
        horaires_frame = ttk.Frame(frame)
        horaires_frame.grid(row=2, column=1, columnspan=2, sticky="w", pady=(10, 4), padx=(8, 0))
        for i, horaire in enumerate(horaires_disponibles):
            var = tk.BooleanVar(value=horaire in horaires_libres)
            self._vars_horaires[horaire] = var
            ttk.Checkbutton(horaires_frame, text=horaire, variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 12), pady=1
            )
        if not horaires_disponibles:
            ttk.Label(horaires_frame, text="Aucun horaire defini", foreground="#666666").grid(
                row=0, column=0, sticky="w"
            )

        ttk.Label(frame, text="Nombre de surveillance\n(quota) :", justify="left").grid(
            row=3, column=0, sticky="w", pady=(10, 4)
        )
        self._var_quota = tk.IntVar(value=quota)
        spin = ttk.Spinbox(frame, from_=0, to=999, textvariable=self._var_quota, width=8)
        spin.grid(row=3, column=1, sticky="w", pady=(10, 4), padx=(8, 0))
        ttk.Label(frame, text="(0 = illimite)", foreground="#666666").grid(row=3, column=2, sticky="w")

        boutons = ttk.Frame(frame)
        boutons.grid(row=4, column=0, columnspan=3, pady=(16, 0), sticky="e")
        ttk.Button(boutons, text="Annuler", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(boutons, text="Valider", command=self._valider).pack(side="right")

        self.bind("<Return>", lambda _evt: self._valider())
        self.bind("<Escape>", lambda _evt: self.destroy())
        entry_nom.focus_set()

    def _valider(self) -> None:
        nom = self._var_nom.get().strip()
        if not nom:
            messagebox.showwarning("Champ manquant", "Le nom du surveillant est obligatoire.", parent=self)
            return
        jours_libres = [jour for jour, var in self._vars_jours.items() if var.get()]
        horaires_libres = [horaire for horaire, var in self._vars_horaires.items() if var.get()]
        try:
            quota = int(self._var_quota.get())
        except (tk.TclError, ValueError):
            quota = 0
        self.resultat = (nom, jours_libres, horaires_libres, max(0, quota))
        self.destroy()


# ====================================================================
# 4. FENETRE DE DEMARRAGE (informations administratives)
# ====================================================================


class AdminConfigWindow(tk.Tk):
    """
    Fenetre de demarrage demandant les informations administratives.

    Le parametre `on_valid` est une fonction appelee avec l'objet
    AdminConfig rempli lorsque l'utilisateur valide le formulaire ; cette
    fenetre se detruit alors elle-meme et laisse la main a la fenetre
    principale.
    """

    def __init__(self, on_valid: Callable[[AdminConfig], None], initial: Optional[AdminConfig] = None):
        super().__init__()
        self._on_valid = on_valid
        self.title("Informations administratives - Nouveau calendrier")
        self.resizable(False, False)
        self.geometry("480x320")

        initial = initial or AdminConfig()

        conteneur = ttk.Frame(self, padding=24)
        conteneur.pack(fill="both", expand=True)

        ttk.Label(
            conteneur,
            text="Calendrier de Surveillance Scolaire",
            font=("Helvetica", 14, "bold"),
        ).grid(row=0, column=0, columnspan=2, pady=(0, 16))

        self._var_nom = tk.StringVar(value=initial.nom_etablissement)
        self._var_bp = tk.StringVar(value=initial.bp)
        self._var_annee = tk.StringVar(value=initial.annee_scolaire)
        self._var_iesg = tk.StringVar(value=initial.iesg)

        champs = [
            ("Nom de l'établissement :", self._var_nom),
            ("BP :", self._var_bp),
            ("Année scolaire (ex: 2026-2027) :", self._var_annee),
            ("IESG :", self._var_iesg),
        ]
        entry = None
        for i, (libelle, var) in enumerate(champs, start=1):
            ttk.Label(conteneur, text=libelle).grid(row=i, column=0, sticky="w", pady=6)
            entry = ttk.Entry(conteneur, textvariable=var, width=32)
            entry.grid(row=i, column=1, sticky="ew", pady=6, padx=(8, 0))

        conteneur.columnconfigure(1, weight=1)

        boutons = ttk.Frame(conteneur)
        boutons.grid(row=len(champs) + 1, column=0, columnspan=2, pady=(24, 0), sticky="e")
        ttk.Button(boutons, text="Quitter", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(boutons, text="Continuer", command=self._valider).pack(side="right")

        self.bind("<Return>", lambda _evt: self._valider())
        if entry is not None:
            entry.focus_set()

    def _valider(self) -> None:
        config = AdminConfig(
            nom_etablissement=self._var_nom.get().strip(),
            bp=self._var_bp.get().strip(),
            annee_scolaire=self._var_annee.get().strip(),
            iesg=self._var_iesg.get().strip(),
        )
        if not config.is_complete():
            messagebox.showwarning(
                "Champ manquant", "Veuillez au moins renseigner le nom de l'établissement.", parent=self
            )
            return
        self.destroy()
        self._on_valid(config)


# ====================================================================
# 5. PANNEAU D'UN CYCLE (classes, creneaux, grille editable)
# ====================================================================


class ScrollableGrid(ttk.Frame):
    """
    Zone defilante (horizontale + verticale) contenant la grille de saisie.
    Le contenu (widgets) est fourni de l'exterieur via `inner`, cette classe
    ne fait que gerer le defilement.
    """

    def __init__(self, parent):
        super().__init__(parent)

        self.canvas = tk.Canvas(self, highlightthickness=0, background="#ffffff")
        v_scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        h_scroll = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.inner = ttk.Frame(self.canvas)
        self._window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", lambda _e: self._bind_mousewheel())
        self.canvas.bind("<Leave>", lambda _e: self._unbind_mousewheel())

    def _on_inner_configure(self, _event=None) -> None:
        self.after_idle(self._update_scrollregion)

    def _on_canvas_configure(self, event) -> None:
        largeur_interne = self.inner.winfo_reqwidth()
        self.canvas.itemconfigure(self._window_id, width=max(event.width, largeur_interne))
        self.after_idle(self._update_scrollregion)

    def _update_scrollregion(self) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _bind_mousewheel(self) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel)
        # Linux
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self) -> None:
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Shift-MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event) -> None:
        delta = -1 if getattr(event, "num", None) == 4 else 1 if getattr(event, "num", None) == 5 else None
        if delta is None:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")

    def _on_shift_mousewheel(self, event) -> None:
        delta = -1 if event.delta > 0 else 1
        self.canvas.xview_scroll(delta, "units")


class CycleFrame(ttk.Frame):
    """
    Onglet complet pour un cycle : gestion des classes, des creneaux, et
    grille d'affectation des surveillants.
    """

    LARGEUR_COL_CLASSE = 14

    def __init__(self, parent, cycle: CycleData, on_change: Optional[Callable[[], None]] = None):
        super().__init__(parent, padding=10)
        self.cycle = cycle
        self._on_change = on_change or (lambda: None)
        self._entry_vars: Dict[Tuple[int, str], tk.StringVar] = {}
        self._on_generate_pdf: Optional[Callable[[CycleData], None]] = None

        self._build_layout()
        self.refresh()

    # ------------------------------------------------------------------
    # Construction de la disposition generale (appelee une seule fois)
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # -- Titre du calendrier ------------------------------------------------
        titre_frame = ttk.Frame(self)
        titre_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        titre_frame.columnconfigure(1, weight=1)
        ttk.Label(titre_frame, text="Titre du calendrier :").grid(row=0, column=0, sticky="w")
        self._var_titre = tk.StringVar(value=self.cycle.titre_calendrier)
        self._var_titre.trace_add("write", self._on_titre_change)
        ttk.Entry(titre_frame, textvariable=self._var_titre).grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )

        # -- Panneaux "Classes", "Creneaux" et "Surveillants" ---------------------
        panneaux = ttk.Frame(self)
        panneaux.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        panneaux.columnconfigure(0, weight=1)
        panneaux.columnconfigure(1, weight=1)
        panneaux.columnconfigure(2, weight=2)

        self._build_panneau_classes(panneaux).grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._build_panneau_creneaux(panneaux).grid(row=0, column=1, sticky="nsew", padx=(6, 6))

        # Panneau place « a cote » du panneau Creneaux : base des
        # surveillants (jours libres, quotas) + generation automatique du
        # planning, visualisation/modification et statistiques.
        self.panneau_surveillants = SurveillantsPanel(
            panneaux, self.cycle, on_planning_change=self._on_planning_change
        )
        self.panneau_surveillants.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        # -- Grille de saisie -----------------------------------------------------
        self._grid_container = ScrollableGrid(self)
        self._grid_container.grid(row=2, column=0, sticky="nsew")

        # -- Barre du bas : generation PDF ----------------------------------------
        bas = ttk.Frame(self)
        bas.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(bas, text="Générer le PDF de ce cycle", command=self._demander_generation_pdf).pack(
            side="right"
        )

    def _build_panneau_classes(self, parent) -> ttk.LabelFrame:
        cadre = ttk.LabelFrame(parent, text="Classes", padding=8)

        liste_frame = ttk.Frame(cadre)
        liste_frame.pack(fill="both", expand=True)
        self._liste_classes = tk.Listbox(liste_frame, height=6, exportselection=False)
        scroll = ttk.Scrollbar(liste_frame, orient="vertical", command=self._liste_classes.yview)
        self._liste_classes.configure(yscrollcommand=scroll.set)
        self._liste_classes.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        saisie = ttk.Frame(cadre)
        saisie.pack(fill="x", pady=(8, 0))
        self._var_nouvelle_classe = tk.StringVar()
        entry = ttk.Entry(saisie, textvariable=self._var_nouvelle_classe)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self._ajouter_classe())
        ttk.Button(saisie, text="Ajouter", command=self._ajouter_classe).pack(side="left", padx=(6, 0))

        boutons = ttk.Frame(cadre)
        boutons.pack(fill="x", pady=(6, 0))
        ttk.Button(boutons, text="Renommer", command=self._renommer_classe).pack(side="left")
        ttk.Button(boutons, text="Supprimer", command=self._supprimer_classe).pack(side="left", padx=(6, 0))

        return cadre

    def _build_panneau_creneaux(self, parent) -> ttk.LabelFrame:
        cadre = ttk.LabelFrame(parent, text="Créneaux de surveillance", padding=8)
        ttk.Label(
            cadre,
            text=(
                "Un créneau = un jour + une date + un horaire.\n"
                "Utilisez la grille ci-dessous pour affecter les\n"
                "surveillants à chaque classe pour chaque créneau."
            ),
            justify="left",
        ).pack(anchor="w")

        boutons = ttk.Frame(cadre)
        boutons.pack(fill="x", pady=(10, 0))
        ttk.Button(boutons, text="+ Ajouter un créneau", command=self._ajouter_creneau).pack(
            side="left"
        )
        return cadre

    # ------------------------------------------------------------------
    # Rafraichissement complet de la grille (appele a chaque changement
    # de structure : classes ou creneaux ajoutes/supprimes/modifies)
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_liste_classes()
        self._refresh_grille()
        if hasattr(self, "panneau_surveillants"):
            self.panneau_surveillants.refresh()
        self._on_change()

    def _on_planning_change(self) -> None:
        """Appele par SurveillantsPanel apres une generation automatique ou
        le retrait d'une affectation, pour repercuter le changement dans la
        grille de saisie principale."""
        self._refresh_grille()
        self._on_change()

    def _refresh_liste_classes(self) -> None:
        self._liste_classes.delete(0, tk.END)
        for classe in self.cycle.classes:
            self._liste_classes.insert(tk.END, classe)

    def _refresh_grille(self) -> None:
        for widget in self._grid_container.inner.winfo_children():
            widget.destroy()
        self._entry_vars.clear()

        inner = self._grid_container.inner

        # -- ligne d'entete -------------------------------------------------------
        entetes = ["Jour", "Date", "Horaire"] + list(self.cycle.classes) + ["Actions"]
        for col, texte in enumerate(entetes):
            lbl = tk.Label(
                inner,
                text=texte,
                font=("Helvetica", 9, "bold"),
                relief="ridge",
                background="#d9d9d9",
                padx=4,
                pady=4,
            )
            lbl.grid(row=0, column=col, sticky="nsew", ipadx=2)

        if not self.cycle.classes:
            tk.Label(
                inner,
                text="Ajoutez au moins une classe pour commencer la saisie.",
                fg="#666666",
                padx=8,
                pady=8,
            ).grid(row=1, column=0, columnspan=len(entetes), sticky="w")
            return

        if not self.cycle.rows:
            tk.Label(
                inner,
                text="Ajoutez un creneau (bouton ci-dessus) pour commencer la saisie.",
                fg="#666666",
                padx=8,
                pady=8,
            ).grid(row=1, column=0, columnspan=len(entetes), sticky="w")
            return

        # -- lignes de donnees ------------------------------------------------------
        for idx, row in enumerate(self.cycle.rows):
            tk_row = idx + 1
            style_hachure = {"background": "#d0d0d0", "stipple": "gray50"}
            tk.Label(inner, text=row.jour, relief="groove", padx=4, pady=2).grid(
                row=tk_row, column=0, sticky="nsew"
            )
            tk.Label(inner, text=row.date, relief="groove", padx=4, pady=2).grid(
                row=tk_row, column=1, sticky="nsew"
            )
            tk.Label(inner, text=row.horaire, relief="groove", padx=4, pady=2).grid(
                row=tk_row, column=2, sticky="nsew"
            )

            for c_idx, classe in enumerate(self.cycle.classes):
                if row.cellule_sans_surveillant(classe):
                    tk.Label(
                        inner, text="/////", relief="groove", padx=4, pady=2, **style_hachure
                    ).grid(row=tk_row, column=3 + c_idx, sticky="nsew")
                    continue
                var = tk.StringVar(value=row.surveillant(classe))
                var.trace_add(
                    "write",
                    lambda *_args, r=row, cl=classe, v=var: r.set_surveillant(cl, v.get()),
                )
                self._entry_vars[(idx, classe)] = var
                valeurs = [""] + [surveillant.nom for surveillant in self.cycle.surveillants]
                entry = ttk.Combobox(
                    inner,
                    textvariable=var,
                    values=valeurs,
                    state="readonly",
                    width=self.LARGEUR_COL_CLASSE,
                )
                entry.grid(row=tk_row, column=3 + c_idx, sticky="nsew")

            actions = ttk.Frame(inner)
            actions.grid(row=tk_row, column=3 + len(self.cycle.classes), sticky="nsew")
            ttk.Button(
                actions, text="Modifier", width=8, command=lambda i=idx: self._modifier_creneau(i)
            ).pack(side="left", padx=1)
            ttk.Button(
                actions, text="Suppr.", width=6, command=lambda i=idx: self._supprimer_creneau(i)
            ).pack(side="left", padx=1)
            ttk.Button(actions, text="^", width=2, command=lambda i=idx: self._deplacer_creneau(i, -1)).pack(
                side="left", padx=1
            )
            ttk.Button(actions, text="v", width=2, command=lambda i=idx: self._deplacer_creneau(i, 1)).pack(
                side="left", padx=1
            )

        inner.update_idletasks()
        self._grid_container._on_inner_configure()

    # ------------------------------------------------------------------
    # Callbacks : classes
    # ------------------------------------------------------------------

    def _on_titre_change(self, *_args) -> None:
        self.cycle.titre_calendrier = self._var_titre.get()
        self._on_change()

    def _ajouter_classe(self) -> None:
        nom = self._var_nouvelle_classe.get().strip()
        if not nom:
            return
        if not self.cycle.add_classe(nom):
            messagebox.showinfo("Classe existante", f"La classe « {nom} » existe deja.", parent=self)
            return
        self._var_nouvelle_classe.set("")
        self.refresh()

    def _classe_selectionnee(self) -> Optional[str]:
        selection = self._liste_classes.curselection()
        if not selection:
            messagebox.showinfo("Aucune selection", "Veuillez selectionner une classe.", parent=self)
            return None
        return self._liste_classes.get(selection[0])

    def _renommer_classe(self) -> None:
        classe = self._classe_selectionnee()
        if classe is None:
            return
        nouveau_nom = simpledialog.askstring(
            "Renommer la classe", "Nouveau nom :", initialvalue=classe, parent=self
        )
        if nouveau_nom and self.cycle.rename_classe(classe, nouveau_nom.strip()):
            self.refresh()

    def _supprimer_classe(self) -> None:
        classe = self._classe_selectionnee()
        if classe is None:
            return
        if messagebox.askyesno(
            "Confirmer la suppression",
            f"Supprimer la classe « {classe} » ?\nToutes les affectations associees seront perdues.",
            parent=self,
        ):
            self.cycle.remove_classe(classe)
            self.refresh()

    # ------------------------------------------------------------------
    # Callbacks : creneaux
    # ------------------------------------------------------------------

    def _ajouter_creneau(self) -> None:
        dlg = CreneauDialog(self, titre="Ajouter un creneau")
        self.wait_window(dlg)
        if dlg.resultat:
            jour, date, horaires = dlg.resultat
            for horaire in horaires:
                self.cycle.add_row(jour, date, horaire)
            self.refresh()

    def _modifier_creneau(self, index: int) -> None:
        row = self.cycle.rows[index]
        dlg = CreneauDialog(
            self,
            titre="Modifier le creneau",
            jour=row.jour,
            date=row.date,
            horaires=[row.horaire],
        )
        self.wait_window(dlg)
        if dlg.resultat:
            jour, date, horaires = dlg.resultat
            self.cycle.update_row(index, jour, date, horaires[0])
            for horaire in horaires[1:]:
                self.cycle.add_row(jour, date, horaire)
            self.refresh()

    def _supprimer_creneau(self, index: int) -> None:
        row = self.cycle.rows[index]
        if messagebox.askyesno(
            "Confirmer la suppression",
            f"Supprimer le creneau du {row.jour} {row.date} ({row.horaire}) ?",
            parent=self,
        ):
            self.cycle.remove_row(index)
            self.refresh()

    def _deplacer_creneau(self, index: int, delta: int) -> None:
        self.cycle.move_row(index, delta)
        self.refresh()

    # ------------------------------------------------------------------
    # Generation PDF (delegue au conteneur parent qui connait le projet)
    # ------------------------------------------------------------------

    def _demander_generation_pdf(self) -> None:
        if self._on_generate_pdf:
            self._on_generate_pdf(self.cycle)

    def set_generate_pdf_handler(self, handler: Callable[[CycleData], None]) -> None:
        # Cette reference est branchee depuis l'exterieur (MainApplication)
        # car CycleFrame n'a pas acces aux informations administratives
        # du projet (necessaires pour l'entete du PDF).
        self._on_generate_pdf = handler


# ====================================================================
# 5 bis. GESTION DES SURVEILLANTS ET DU PLANNING (panneau a cote des
#         creneaux de surveillance)
# ====================================================================


class SurveillantsPanel(ttk.Frame):
    """
    Panneau place a cote de « Creneaux de surveillance », regroupant deux
    onglets :

        Onglet 1 - Saisie des Surveillants :
            base de donnees des surveillants, jours libres, nombre de
            surveillance (quota).

        Onglet 2 - Calendrier & Services :
            generation automatique du planning, visualisation/modification
            des affectations, statistiques.
    """

    def __init__(self, parent, cycle: CycleData, on_planning_change: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.cycle = cycle
        self._on_planning_change = on_planning_change or (lambda: None)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self._onglet_saisie = ttk.Frame(notebook, padding=8)
        self._onglet_calendrier = ttk.Frame(notebook, padding=8)
        notebook.add(self._onglet_saisie, text="Saisie des Surveillants")
        notebook.add(self._onglet_calendrier, text="Calendrier & Services")

        self._build_onglet_saisie()
        self._build_onglet_calendrier()

        self.refresh()

    # ------------------------------------------------------------------
    # Onglet 1 - Saisie des Surveillants
    # ------------------------------------------------------------------

    def _build_onglet_saisie(self) -> None:
        frame = self._onglet_saisie

        ttk.Label(
            frame, text="Base de données des surveillants", font=("Helvetica", 10, "bold")
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="Définissez pour chaque surveillant ses jours libres et son nombre de surveillance (quota).",
            foreground="#666666",
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        arbre_frame = ttk.Frame(frame)
        arbre_frame.pack(fill="both", expand=True, pady=(0, 6))
        colonnes = ("nom", "jours_libres", "quota")
        self._arbre_surveillants = ttk.Treeview(
            arbre_frame, columns=colonnes, show="headings", height=8, selectmode="browse"
        )
        self._arbre_surveillants.heading("nom", text="Nom")
        self._arbre_surveillants.heading("jours_libres", text="Jours libres")
        self._arbre_surveillants.heading("quota", text="Quota")
        self._arbre_surveillants.column("nom", width=130, anchor="w")
        self._arbre_surveillants.column("jours_libres", width=170, anchor="w")
        self._arbre_surveillants.column("quota", width=60, anchor="center")
        scroll = ttk.Scrollbar(arbre_frame, orient="vertical", command=self._arbre_surveillants.yview)
        scroll_x = ttk.Scrollbar(arbre_frame, orient="horizontal", command=self._arbre_surveillants.xview)
        self._arbre_surveillants.configure(yscrollcommand=scroll.set, xscrollcommand=scroll_x.set)
        self._arbre_surveillants.pack(side="top", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x")
        self._arbre_surveillants.bind("<Double-1>", lambda _e: self._modifier_surveillant())

        boutons = ttk.Frame(frame)
        boutons.pack(fill="x")
        ttk.Button(boutons, text="Ajouter", command=self._ajouter_surveillant).pack(side="left")
        ttk.Button(boutons, text="Modifier", command=self._modifier_surveillant).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(boutons, text="Supprimer", command=self._supprimer_surveillant).pack(
            side="left", padx=(6, 0)
        )

    def _index_selectionne(self) -> Optional[int]:
        selection = self._arbre_surveillants.selection()
        if not selection:
            messagebox.showinfo("Aucune sélection", "Veuillez sélectionner un surveillant.", parent=self)
            return None
        return int(selection[0])

    def _ajouter_surveillant(self) -> None:
        horaires = list(dict.fromkeys(row.horaire for row in self.cycle.rows if row.horaire))
        dlg = SurveillantDialog(
            self, titre="Ajouter un surveillant", horaires_disponibles=horaires
        )
        self.wait_window(dlg)
        if dlg.resultat:
            nom, jours_libres, horaires_libres, quota = dlg.resultat
            if not self.cycle.add_surveillant(
                nom, jours_libres, quota, horaires_libres=horaires_libres
            ):
                messagebox.showinfo("Nom existant", f"Le surveillant « {nom} » existe déja.", parent=self)
                return
            self.refresh()

    def _modifier_surveillant(self) -> None:
        index = self._index_selectionne()
        if index is None:
            return
        s = self.cycle.surveillants[index]
        horaires = list(dict.fromkeys(row.horaire for row in self.cycle.rows if row.horaire))
        dlg = SurveillantDialog(
            self,
            titre="Modifier le surveillant",
            nom=s.nom,
            jours_libres=s.jours_libres,
            horaires_disponibles=horaires,
            horaires_libres=s.horaires_libres,
            quota=s.quota,
        )
        self.wait_window(dlg)
        if dlg.resultat:
            nom, jours_libres, horaires_libres, quota = dlg.resultat
            if not self.cycle.update_surveillant(
                index, nom, jours_libres, quota, horaires_libres=horaires_libres
            ):
                messagebox.showinfo("Nom existant", f"Le surveillant « {nom} » existe déja.", parent=self)
                return
            self.refresh()
            self._on_planning_change()

    def _supprimer_surveillant(self) -> None:
        index = self._index_selectionne()
        if index is None:
            return
        s = self.cycle.surveillants[index]
        if messagebox.askyesno(
            "Confirmer la suppression",
            f"Supprimer le surveillant « {s.nom} » ?\n"
            "(Les affectations deja saisies portant ce nom resteront\n"
            "inchangees dans le planning.)",
            parent=self,
        ):
            self.cycle.remove_surveillant(index)
            self.refresh()

    # ------------------------------------------------------------------
    # Onglet 2 - Calendrier & Services
    # ------------------------------------------------------------------

    def _build_onglet_calendrier(self) -> None:
        frame = self._onglet_calendrier

        # -- generation automatique -----------------------------------------------
        gen_frame = ttk.LabelFrame(frame, text="Génération automatique", padding=8)
        gen_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(
            gen_frame,
            text=(
                "Affecte automatiquement les surveillants aux créneaux en\n"
                "respectant leurs jours libres et leur quota."
            ),
            justify="left",
        ).pack(anchor="w")
        ttk.Button(
            gen_frame,
            text="Générer le calendrier automatiquement",
            command=self._generer_automatiquement,
        ).pack(anchor="w", pady=(8, 0))

        # -- planning : visualiser / modifier ----------------------------------------
        planning_frame = ttk.LabelFrame(frame, text="Planning par surveillant", padding=8)
        planning_frame.pack(fill="both", expand=True, pady=(0, 8))

        arbre_frame = ttk.Frame(planning_frame)
        arbre_frame.pack(fill="both", expand=True)
        colonnes = ("surveillant", "jour", "date", "horaire", "classe")
        self._arbre_planning = ttk.Treeview(
            arbre_frame, columns=colonnes, show="headings", height=7, selectmode="browse"
        )
        for col, texte, largeur in [
            ("surveillant", "Surveillant", 110),
            ("jour", "Jour", 75),
            ("date", "Date", 85),
            ("horaire", "Horaire", 95),
            ("classe", "Classe", 85),
        ]:
            self._arbre_planning.heading(col, text=texte)
            self._arbre_planning.column(col, width=largeur, anchor="w")
        scroll_p = ttk.Scrollbar(arbre_frame, orient="vertical", command=self._arbre_planning.yview)
        scroll_p_x = ttk.Scrollbar(arbre_frame, orient="horizontal", command=self._arbre_planning.xview)
        self._arbre_planning.configure(yscrollcommand=scroll_p.set, xscrollcommand=scroll_p_x.set)
        self._arbre_planning.pack(side="top", fill="both", expand=True)
        scroll_p.pack(side="right", fill="y")
        scroll_p_x.pack(side="bottom", fill="x")

        boutons_p = ttk.Frame(planning_frame)
        boutons_p.pack(fill="x", pady=(6, 0))
        ttk.Button(boutons_p, text="Actualiser", command=self._actualiser_avec_confirmation).pack(side="left")
        ttk.Button(boutons_p, text="Retirer l'affectation", command=self._retirer_affectation).pack(
            side="left", padx=(6, 0)
        )

        # -- statistiques -------------------------------------------------------------
        stats_frame = ttk.LabelFrame(frame, text="Statistiques", padding=8)
        stats_frame.pack(fill="both", expand=True)

        self._label_stats_globales = ttk.Label(stats_frame, text="", justify="left")
        self._label_stats_globales.pack(anchor="w", pady=(0, 6))

        arbre_frame2 = ttk.Frame(stats_frame)
        arbre_frame2.pack(fill="both", expand=True)
        colonnes2 = ("surveillant", "affectees", "quota")
        self._arbre_stats = ttk.Treeview(
            arbre_frame2, columns=colonnes2, show="headings", height=6, selectmode="none"
        )
        self._arbre_stats.heading("surveillant", text="Surveillant")
        self._arbre_stats.heading("affectees", text="Surveillances affectees")
        self._arbre_stats.heading("quota", text="Quota")
        self._arbre_stats.column("surveillant", width=130, anchor="w")
        self._arbre_stats.column("affectees", width=150, anchor="center")
        self._arbre_stats.column("quota", width=70, anchor="center")
        scroll_s = ttk.Scrollbar(arbre_frame2, orient="vertical", command=self._arbre_stats.yview)
        scroll_s_x = ttk.Scrollbar(arbre_frame2, orient="horizontal", command=self._arbre_stats.xview)
        self._arbre_stats.configure(yscrollcommand=scroll_s.set, xscrollcommand=scroll_s_x.set)
        self._arbre_stats.pack(side="top", fill="both", expand=True)
        scroll_s.pack(side="right", fill="y")
        scroll_s_x.pack(side="bottom", fill="x")

    def _generer_automatiquement(self) -> None:
        dlg_cellules = CellulesSansSurveillantDialog(self, self.cycle)
        self.wait_window(dlg_cellules)
        if dlg_cellules.resultat is None:
            return
        cellules_par_ligne: Dict[int, List[str]] = {}
        for row_idx, classe in dlg_cellules.resultat:
            cellules_par_ligne.setdefault(row_idx, []).append(classe)
        for row_idx, row in enumerate(self.cycle.rows):
            row.cellules_sans_surveillant = cellules_par_ligne.get(row_idx, [])

        reponse = messagebox.askyesnocancel(
            "Génération automatique",
            "Remplacer TOUTES les affectations existantes ?\n\n"
            "Oui = effacer puis regenerer entierement le planning.\n"
            "Non = completer uniquement les cellules encore vides.\n"
            "Annuler = ne rien faire.",
            parent=self,
        )
        if reponse is None:
            return
        try:
            stats = generer_planning_automatique(self.cycle, remplacer_existant=reponse)
        except ValueError as exc:
            messagebox.showwarning("Impossible de générer", str(exc), parent=self)
            return
        self.refresh()
        self._on_planning_change()
        message = f"{stats['affectees']} cellule(s) affectée(s) sur {stats['total']}."
        if stats["non_affectees"]:
            message += (
                f"\n{stats['non_affectees']} cellule(s) n'ont pas pu etre affectees "
                "(aucun surveillant disponible ce jour-la)."
            )
        if stats["quotas_depasse"]:
            message += f"\nAttention : {stats['quotas_depasse']} quota(s) ont été dépassé(s)."
        messagebox.showinfo("Génération terminée", message, parent=self)

    def _retirer_affectation(self) -> None:
        selection = self._arbre_planning.selection()
        if not selection:
            messagebox.showinfo(
                "Aucune sélection", "Veuillez sélectionner une ligne du planning.", parent=self
            )
            return
        row_idx_str, classe = selection[0].split("::", 1)
        row_idx = int(row_idx_str)
        if 0 <= row_idx < len(self.cycle.rows):
            self.cycle.rows[row_idx].set_surveillant(classe, "")
        self.refresh()
        self._on_planning_change()

    # ------------------------------------------------------------------
    # Rafraichissement
    # ------------------------------------------------------------------

    def _actualiser_avec_confirmation(self) -> None:
        self.refresh()
        messagebox.showinfo("Actualisation", "La liste a été actualisée.", parent=self)

    def refresh(self) -> None:
        self._refresh_arbre_surveillants()
        self._refresh_planning()
        self._refresh_statistiques()

    def _refresh_arbre_surveillants(self) -> None:
        elements = self._arbre_surveillants.get_children()
        if elements:
            self._arbre_surveillants.delete(*elements)
        for idx, s in enumerate(self.cycle.surveillants):
            self._arbre_surveillants.insert(
                "",
                "end",
                iid=str(idx),
                values=(s.nom, ", ".join(s.jours_libres) or "-", s.quota if s.quota > 0 else "illimite"),
            )

    def _refresh_planning(self) -> None:
        elements = self._arbre_planning.get_children()
        if elements:
            self._arbre_planning.delete(*elements)
        for idx, row in enumerate(self.cycle.rows):
            for classe in self.cycle.classes:
                if row.cellule_sans_surveillant(classe):
                    continue
                nom = row.surveillant(classe)
                if nom:
                    iid = f"{idx}::{classe}"
                    self._arbre_planning.insert(
                        "", "end", iid=iid, values=(nom, row.jour, row.date, row.horaire, classe)
                    )

    def _refresh_statistiques(self) -> None:
        total_cellules = len(self.cycle.rows) * len(self.cycle.classes)
        remplies = sum(
            1 for row in self.cycle.rows for classe in self.cycle.classes if row.surveillant(classe)
        )
        taux = (remplies / total_cellules * 100) if total_cellules else 0.0
        self._label_stats_globales.configure(
            text=(
                f"Creneaux : {len(self.cycle.rows)}    Classes : {len(self.cycle.classes)}    "
                f"Cellules remplies : {remplies}/{total_cellules} ({taux:.0f}%)"
            )
        )

        elements = self._arbre_stats.get_children()
        if elements:
            self._arbre_stats.delete(*elements)
        compte: Dict[str, int] = {s.nom: 0 for s in self.cycle.surveillants}
        for row in self.cycle.rows:
            for classe in self.cycle.classes:
                if row.cellule_sans_surveillant(classe):
                    continue
                nom = row.surveillant(classe)
                if nom in compte:
                    compte[nom] += 1
        for s in self.cycle.surveillants:
            self._arbre_stats.insert(
                "", "end", values=(s.nom, compte.get(s.nom, 0), s.quota if s.quota > 0 else "illimite")
            )


# ====================================================================
# 6. FENETRE PRINCIPALE
# ====================================================================


class MainApplication(tk.Tk):
    """Fenetre principale de l'application de gestion des calendriers."""

    def __init__(self, admin_config: AdminConfig):
        super().__init__()
        self.title("Gestion des Calendriers de Surveillance")
        self.geometry("1500x860")
        self.minsize(1100, 650)

        self.project = ProjectData(admin=admin_config)
        self.current_file: Optional[str] = None
        self._modified = False
        self._history: List[dict] = [self.project.to_dict()]
        self._redo_history: List[dict] = []
        self._restoring_history = False

        self._build_menu()
        self._build_notebook()
        self.protocol("WM_DELETE_WINDOW", self._quitter)
        self._modified = False
        self._update_title()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        menu_fichier = tk.Menu(menubar, tearoff=False)
        menu_fichier.add_command(label="Nouveau projet...", command=self._nouveau_projet)
        menu_fichier.add_command(label="Ouvrir...", command=self._ouvrir_projet, accelerator="Ctrl+O")
        menu_fichier.add_separator()
        menu_fichier.add_command(label="Enregistrer", command=self._enregistrer, accelerator="Ctrl+S")
        menu_fichier.add_command(label="Enregistrer sous...", command=self._enregistrer_sous)
        menu_fichier.add_separator()
        menu_fichier.add_command(
            label="Modifier les informations administratives...", command=self._modifier_admin
        )
        menu_fichier.add_separator()
        menu_fichier.add_command(label="Quitter", command=self._quitter)
        menubar.add_cascade(label="Fichier", menu=menu_fichier)

        menu_edition = tk.Menu(menubar, tearoff=False)
        menu_edition.add_command(label="Annuler", command=self._annuler, accelerator="Ctrl+Z")
        menu_edition.add_command(label="Rétablir", command=self._retablir, accelerator="Ctrl+Y")
        menubar.add_cascade(label="Édition", menu=menu_edition)

        menu_pdf = tk.Menu(menubar, tearoff=False)
        menu_pdf.add_command(
            label="Generer le PDF du 1er Cycle", command=lambda: self._generer_pdf(self.project.cycle1)
        )
        menu_pdf.add_command(
            label="Generer le PDF du 2e Cycle", command=lambda: self._generer_pdf(self.project.cycle2)
        )
        menu_pdf.add_command(
            label="Generer un PDF complet (2 cycles)", command=self._generer_pdf_complet
        )
        menubar.add_cascade(label="PDF", menu=menu_pdf)

        self.config(menu=menubar)
        self.bind_all("<Control-s>", lambda _e: self._enregistrer())
        self.bind_all("<Control-o>", lambda _e: self._ouvrir_projet())
        self.bind_all("<Control-z>", lambda _e: self._annuler())
        self.bind_all("<Control-y>", lambda _e: self._retablir())

    def _build_notebook(self) -> None:
        # -- barre d'outils rapide ------------------------------------------------
        barre = ttk.Frame(self, padding=(10, 6))
        barre.pack(fill="x")
        ttk.Button(barre, text="Enregistrer", command=self._enregistrer).pack(side="left")
        ttk.Button(barre, text="Ouvrir", command=self._ouvrir_projet).pack(side="left", padx=(6, 0))
        self._label_fichier = ttk.Label(barre, text="(nouveau projet non enregistre)")
        self._label_fichier.pack(side="left", padx=(16, 0))

        # -- onglets ------------------------------------------------------------------
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._creer_onglets()

    def _creer_onglets(self) -> None:
        """(Re)construit les deux onglets a partir de self.project."""
        for child in list(self.notebook.tabs()):
            self.notebook.forget(child)

        self.frame_cycle1 = CycleFrame(self.notebook, self.project.cycle1, on_change=self._marquer_modifie)
        self.frame_cycle1.set_generate_pdf_handler(self._generer_pdf)
        self.notebook.add(self.frame_cycle1, text="1er Cycle / College")

        self.frame_cycle2 = CycleFrame(self.notebook, self.project.cycle2, on_change=self._marquer_modifie)
        self.frame_cycle2.set_generate_pdf_handler(self._generer_pdf)
        self.notebook.add(self.frame_cycle2, text="2e Cycle / Lycee")

        self._selectionner_cycle_avec_donnees()

    def _selectionner_cycle_avec_donnees(self) -> None:
        """Sélectionne l'onglet du cycle qui contient le plus de données."""
        cycle = self.project.cycle2
        index = 1
        if not (cycle.classes or cycle.rows or cycle.surveillants):
            cycle = self.project.cycle1
            index = 0
        if cycle.classes or cycle.rows or cycle.surveillants:
            onglet = self.notebook.tabs()[index]
            self.notebook.select(onglet)

    # ------------------------------------------------------------------
    # Gestion du fichier projet (JSON)
    # ------------------------------------------------------------------

    def _marquer_modifie(self) -> None:
        if not self._restoring_history:
            etat = self.project.to_dict()
            if etat != self._history[-1]:
                self._history.append(etat)
                self._redo_history.clear()
        self._modified = True
        self._update_title()

    def _restaurer_historique(self, etat: dict) -> None:
        self._restoring_history = True
        try:
            self.project = ProjectData.from_dict(etat)
            self._creer_onglets()
        finally:
            self._restoring_history = False
        self._modified = True
        self._update_title()

    def _annuler(self) -> None:
        if len(self._history) < 2:
            return
        self._redo_history.append(self._history.pop())
        self._restaurer_historique(self._history[-1])

    def _retablir(self) -> None:
        if not self._redo_history:
            return
        etat = self._redo_history.pop()
        self._history.append(etat)
        self._restaurer_historique(etat)

    def _update_title(self) -> None:
        nom = os.path.basename(self.current_file) if self.current_file else "Nouveau projet"
        suffixe = " *" if self._modified else ""
        self.title(f"Gestion des Calendriers de Surveillance - {nom}{suffixe}")
        self._label_fichier.configure(text=self.current_file or "(nouveau projet non enregistré)")

    def _confirmer_abandon(self) -> bool:
        if not self._modified:
            return True
        reponse = messagebox.askyesnocancel(
            "Modifications non enregistrées",
            "Le projet contient des modifications non enregistrées.\n"
            "Voulez-vous les enregistrer avant de continuer ?",
            parent=self,
        )
        if reponse is None:
            return False
        if reponse:
            self._enregistrer()
            return not self._modified
        return True

    def _quitter(self) -> None:
        if self._confirmer_abandon():
            self.destroy()

    def _nouveau_projet(self) -> None:
        if not self._confirmer_abandon():
            return
        if not messagebox.askyesno(
            "Nouveau projet",
            "Créer un nouveau projet ? Les données non enregistrées seront perdues.",
            parent=self,
        ):
            return

        self.withdraw()

        def _on_valid(admin_config: AdminConfig) -> None:
            self.project = ProjectData(admin=admin_config)
            self.current_file = None
            self._history = [self.project.to_dict()]
            self._redo_history.clear()
            self._creer_onglets()
            self._modified = False
            self._update_title()
            self.deiconify()

        AdminConfigWindow(on_valid=_on_valid, initial=self.project.admin)

    def _enregistrer(self) -> None:
        if self.current_file is None:
            self._enregistrer_sous()
            return
        self._sauvegarder_vers(self.current_file)

    def _enregistrer_sous(self) -> None:
        chemin = filedialog.asksaveasfilename(
            title="Enregistrer le projet",
            defaultextension=".json",
            filetypes=[("Fichier de projet JSON", "*.json")],
        )
        if not chemin:
            return
        self._sauvegarder_vers(chemin)

    def _sauvegarder_vers(self, chemin: str) -> None:
        try:
            self.project.save(chemin)
        except OSError as exc:
            messagebox.showerror("Erreur", f"Impossible d'enregistrer le fichier :\n{exc}", parent=self)
            return
        self.current_file = chemin
        self._modified = False
        self._update_title()
        messagebox.showinfo("Enregistré", "Le projet a été enregistré avec succès.", parent=self)

    def _ouvrir_projet(self) -> None:
        if not self._confirmer_abandon():
            return
        chemin = filedialog.askopenfilename(
            title="Ouvrir un projet", filetypes=[("Fichier de projet JSON", "*.json")]
        )
        if not chemin:
            return
        try:
            self.project = ProjectData.load(chemin)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le fichier :\n{exc}", parent=self)
            return

        self.current_file = chemin
        self._history = [self.project.to_dict()]
        self._redo_history.clear()
        self._creer_onglets()
        self.update_idletasks()
        self._selectionner_cycle_avec_donnees()
        self._modified = False
        self._update_title()

    def _modifier_admin(self) -> None:
        self.withdraw()

        def _on_valid(admin_config: AdminConfig) -> None:
            self.project.admin = admin_config
            self._marquer_modifie()
            self.deiconify()

        AdminConfigWindow(on_valid=_on_valid, initial=self.project.admin)

    # ------------------------------------------------------------------
    # Generation PDF
    # ------------------------------------------------------------------

    def _generer_pdf(self, cycle: CycleData) -> None:
        erreurs = cycle.validation_errors()
        if erreurs:
            messagebox.showwarning("Données incohérentes", "\n".join(erreurs[:8]), parent=self)
            return
        signature = self._demander_signature()
        if signature is None:
            return
        nom_signataire, lieu_signature, date_signature = signature
        chemin = filedialog.asksaveasfilename(
            title="Enregistrer le calendrier PDF",
            defaultextension=".pdf",
            filetypes=[("Document PDF", "*.pdf")],
            initialfile=f"calendrier_{cycle.nom_cycle.replace('/', '-').replace(' ', '_')}.pdf",
        )
        if not chemin:
            return
        try:
            generate_pdf(
                self.project,
                [cycle],
                chemin,
                nom_signataire,
                lieu_signature,
                date_signature,
            )
        except ValueError as exc:
            messagebox.showwarning("Données incompletes", str(exc), parent=self)
            return
        except Exception as exc:  # pragma: no cover - securite generale
            messagebox.showerror("Erreur", f"La génération du PDF a échoué :\n{exc}", parent=self)
            return
        messagebox.showinfo("PDF généré", f"Le calendrier a été généré avec succès :\n{chemin}", parent=self)

    def _generer_pdf_complet(self) -> None:
        erreurs = self.project.cycle1.validation_errors() + self.project.cycle2.validation_errors()
        if erreurs:
            messagebox.showwarning("Données incohérentes", "\n".join(erreurs[:8]), parent=self)
            return
        signature = self._demander_signature()
        if signature is None:
            return
        nom_signataire, lieu_signature, date_signature = signature
        chemin = filedialog.asksaveasfilename(
            title="Enrégistrer le calendrier PDF complet",
            defaultextension=".pdf",
            filetypes=[("Document PDF", "*.pdf")],
            initialfile="calendrier_surveillance_complet.pdf",
        )
        if not chemin:
            return
        try:
            generate_pdf(
                self.project,
                [self.project.cycle1, self.project.cycle2],
                chemin,
                nom_signataire,
                lieu_signature,
                date_signature,
            )
        except ValueError as exc:
            messagebox.showwarning("Données incompletes", str(exc), parent=self)
            return
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("Erreur", f"La génération du PDF a échoué :\n{exc}", parent=self)
            return
        messagebox.showinfo("PDF généré", f"Le calendrier a été généré avec succès :\n{chemin}", parent=self)

    def _demander_signature(self) -> Optional[Tuple[str, str, str]]:
        dialog = SignatureDialog(self)
        self.wait_window(dialog)
        return dialog.resultat


# ====================================================================
# 7. POINT D'ENTREE
# ====================================================================


def main() -> None:
    def lancer_application_principale(admin_config: AdminConfig) -> None:
        app = MainApplication(admin_config)
        app.mainloop()

    fenetre_config = AdminConfigWindow(on_valid=lancer_application_principale)
    fenetre_config.mainloop()


if __name__ == "__main__":
    main()
