# Gestion des calendriers de surveillance

Application de bureau Python/Tkinter pour créer, organiser et exporter des calendriers de surveillance scolaire.

L'application prend en charge deux cycles d'enseignement :

- 1er Cycle / Collège

- 2e Cycle / Lycée

## Fonctionnalités

- Saisie des informations administratives de l'établissement

- Gestion des classes et des créneaux de surveillance

- Gestion des surveillants, de leurs jours et horaires d'indisponibilité

- Définition d'un quota de surveillances par surveillant

- Affectation manuelle avec liste contrôlée des surveillants

- Génération automatique d'un planning équilibré

- Détection des conflits, doublons et affectations invalides

- Défilement horizontal et vertical des tableaux

- Annulation et rétablissement des modifications avec `Ctrl+Z` et `Ctrl+Y`

- Sauvegarde des projets au format JSON

- Création automatique d'une copie de secours `.bak`

- Export PDF individuel ou complet

- Formats A4, A3 et A2 selon le nombre de classes

## Prérequis

- Python 3.10 ou supérieur

- Tkinter

- ReportLab

Sur Ubuntu ou Debian, Tkinter peut être installé avec :

```
sudo apt install python3-tk
```

## Installation

Depuis le dossier du projet :

```
python3 -m pip install reportlab
```

Pour installer ReportLab uniquement pour l'utilisateur courant :

```
python3 -m pip install --user reportlab
```

## Lancement

```
python3 gestion\_surveillance.py
```

La fenêtre de configuration administrative s'ouvre au démarrage. Après validation, les deux onglets de cycle sont disponibles.

## Utilisation rapide

1. Renseigner le nom de l'établissement.

2. Ajouter les classes dans l'onglet du cycle concerné.

3. Ajouter les créneaux avec le jour, la date et l'horaire.

4. Ajouter les surveillants et renseigner leurs indisponibilités et quotas.

5. Saisir les affectations manuellement ou lancer la génération automatique.

6. Vérifier les statistiques et les éventuels conflits.

7. Enregistrer le projet JSON.

8. Exporter le calendrier en PDF.

## Format des horaires

Les horaires utilisent le format suivant :

```
07h30-09h30
```

Les heures doivent être comprises entre `00h00` et `23h59`. La date doit correspondre au jour sélectionné.

## Fichiers

```
gestion\_surveillance.py          Application principale  
test\_gestion\_surveillance.py     Tests automatisés  
gestion\_surveillance.json        Projet enregistré par l'utilisateur  
gestion\_surveillance.json.bak    Copie de secours avant remplacement
```

Le fichier JSON contient les informations administratives, les deux cycles, les classes, les créneaux, les surveillants et les affectations.

## Tests

Exécuter les tests depuis le dossier du projet :

```
python3 -m unittest -v test\_gestion\_surveillance.py
```

Les tests couvrent notamment :

- la détection des conflits d'affectation ;

- le respect des indisponibilités ;

- la gestion des quotas ;

- la sauvegarde de secours `.bak` ;

- la génération atomique des PDF.

## Sécurité des données

- Les sauvegardes JSON sont écrites dans un fichier temporaire puis remplacées atomiquement.

- Une copie `.bak` du fichier précédent est conservée avant chaque remplacement.

- Les exports PDF utilisent également un fichier temporaire afin d'éviter un PDF partiellement écrit.

- Les projets restent stockés localement sur l'ordinateur.

## Limites connues

- La génération automatique utilise une stratégie d'équilibrage gloutonne ; elle privilégie les surveillants les moins chargés, mais ne garantit pas toujours la solution mathématique optimale.

- Les quotas peuvent être dépassés lorsqu'il n'existe aucune autre affectation possible. L'application le signale après la génération.

- L'export PDF nécessite au moins une classe et un créneau par cycle exporté.

## Dépannage

### ReportLab introuvable

```
python3 -m pip install reportlab
```

### Tkinter introuvable

```
sudo apt install python3-tk
```

### Les changements d'interface ne sont pas visibles

Fermer complètement l'application puis la relancer : les classes Tkinter sont chargées en mémoire au démarrage.

## Licence

Ce projet est fourni tel quel pour usage éducatif et administratif.


**Auteurs**  
KOUGBENA Yao Novignon & OLAJIDE Gbenga.

