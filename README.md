# Celia — votre assistante vocale de bureau

Celia est une assistante vocale qui fonctionne comme Siri ou Google Assistant, mais
c'est **Claude** qui répond. Vous la lancez une fois le matin, elle reste active en
arrière-plan, et vous l'appelez par son prénom :

> « **Celia**, quel temps fera-t-il demain à Lyon ? »
> « **Celia**… » *(bip, « Oui ? »)* « …explique-moi la différence entre un ETF et une SICAV. »

## Ce qu'elle sait faire

- **Écoute permanente** de son prénom. La détection se fait **sur votre ordinateur** (Vosk,
  hors-ligne). Rien ne part sur Internet tant que vous ne l'avez pas appelée.
- **Répond à toutes vos questions** avec Claude, et cherche sur le web pour l'actualité,
  la météo, les horaires, etc.
- **Se souvient de la conversation** : vous pouvez enchaîner « et demain ? ». Elle repart de
  zéro après 20 minutes sans échange, ou si vous dites « Celia, nouvelle conversation ».
- **Prénom modifiable** dans les Réglages : si vous l'appelez « Jade », c'est « Jade » qui la réveille.
- **Bouton ON/OFF** :
  - le gros bouton rond dans la fenêtre ;
  - le raccourci **« Celia ON-OFF »** sur le bureau (un double-clic coupe ou rallume le micro) ;
  - l'icône près de l'horloge (clic droit → *Écoute active*).
- Commandes vocales : « Celia stop » (elle se tait), « Celia, mets-toi en veille »,
  « Celia, nouvelle conversation ».
- Vous pouvez aussi **écrire** vos questions dans la fenêtre.
- Démarrage automatique à l'ouverture de session (option dans les Réglages).

## Mémoire permanente, planning et projets

Celia garde en mémoire, **sur votre ordinateur**, tout ce que vous organisez avec elle,
même après un redémarrage :

- **Planning et tâches** : « Celia, rappelle-moi d'appeler le comptable demain à 9 h 30 »,
  « qu'est-ce qu'il me reste à faire aujourd'hui ? », « et demain ? »,
  « c'est fait pour le devis », « décale la réunion à vendredi ».
- **Rappels vocaux** : à l'heure prévue, Celia vous prévient à voix haute (même micro coupé).
- **Point du matin** : au premier lancement de la journée, elle annonce ce qui est prévu
  aujourd'hui, ce qui est en retard et ce qui arrive demain.
- **Décisions et actions mises en place** : « Celia, retiens qu'on passe par Stripe pour les
  paiements ». Elle note aussi d'elle-même les décisions prises pendant vos échanges.
- **Retour en arrière à tout moment** : « qu'avait-on décidé pour le logo ? »,
  « on en était où sur l'appli resto ? ». Chaque conversation est archivée dans un journal.
- **Projets** : « Celia, crée un nouveau projet pour une application de réservation ».
  Elle crée un dossier dans `Documents\Projets` avec une fiche `PROJET.md` (objectif, premières
  étapes), et ajoute ces étapes à votre planning.

Le bouton **📋 Planning & mémoire** affiche tout cela : tâches (cocher, supprimer, ajouter),
souvenirs (les effacer), projets (ouvrir leur dossier).

Les données sont dans `%APPDATA%\Celia\` : `memoire.json` (planning, notes, projets) et
`journal.jsonl` (historique des conversations). Rien n'est stocké en ligne.

## Installation (Windows)

1. Installez **Python 3.10 ou plus récent** depuis <https://www.python.org/downloads/>
   en cochant **« Add python.exe to PATH »**.
2. Téléchargez ce dossier (bouton *Code → Download ZIP* sur GitHub) et décompressez-le
   dans un endroit stable, par exemple `Documents\Celia`.
3. Double-cliquez sur **`INSTALLER_WINDOWS.bat`**.
   Deux raccourcis apparaissent sur le bureau : **Celia** et **Celia ON-OFF**.
4. Au premier lancement, Celia :
   - vous demande votre **clé API Anthropic** (à créer sur <https://console.anthropic.com>,
     rubrique *API Keys*) ;
   - télécharge son modèle de reconnaissance vocale français (environ 40 Mo, une seule fois).

> Pour une voix française sous Windows : *Paramètres → Heure et langue → Voix* et ajoutez
> une voix française (par exemple « Microsoft Hortense » ou « Julie »). Choisissez-la ensuite
> dans les Réglages de Celia.

### macOS / Linux

Lancez `./install.sh`. Sous Linux, installez d'abord `espeak-ng` et `libportaudio2`.

## Utilisation au quotidien

| Action | Comment |
|---|---|
| Démarrer le matin | Double-clic sur **Celia** (ou démarrage automatique) |
| Poser une question | « Celia, … » |
| Couper / rallumer le micro | **Celia ON-OFF** sur le bureau, ou le bouton rond |
| La faire taire | « Celia stop » ou le bouton *Interrompre* |
| Fermer la fenêtre | La croix la cache : Celia reste active près de l'horloge |
| Quitter complètement | Clic droit sur l'icône près de l'horloge → *Quitter* |

## Réglages

- **Prénom de l'assistante** : le mot pour l'appeler. Un prénom de 2 ou 3 syllabes,
  peu courant dans les conversations, marche mieux.
- **Modèle Claude** : Opus 5.5 (le plus intelligent, par défaut), Sonnet 5.5 ou Haiku 5.5
  (le plus rapide et le moins cher).
- **Profondeur de réflexion** : `low` est conseillé à l'oral, pour des réponses rapides.
- **Exigence de reconnaissance du prénom** : baissez-la si Celia ne vous entend pas,
  montez-la si elle se déclenche toute seule.

Les réglages sont dans `%APPDATA%\Celia\config.json`. La clé API reste uniquement sur votre PC.

## Coût

Celia utilise l'API Anthropic, facturée à l'usage. Une question courte coûte en général
une fraction de centime, un peu plus avec une recherche web. Pour réduire la facture,
choisissez Haiku 5.5 dans les Réglages.

## Structure du code

```
Celia.pyw            lanceur (sans fenêtre de console)
celia/app.py         interface, bouton ON/OFF, icône de notification, logique du mot de réveil
celia/brain.py       appels à Claude (API Anthropic), boucle d'outils, recherche web
celia/memory.py      mémoire permanente : tâches, rappels, notes, projets, journal
celia/tools.py       outils que Claude utilise pour gérer la mémoire et les projets
celia/voice.py       micro + reconnaissance Vosk hors-ligne, synthèse vocale, détection du prénom
celia/system.py      raccourcis du bureau, démarrage automatique, instance unique
celia/config.py      réglages
```
