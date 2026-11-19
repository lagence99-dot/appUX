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
  - sur Windows, l'icône près de l'horloge (clic droit → *Écoute active*).
- Commandes vocales : « Celia stop » (elle se tait), « Celia, mets-toi en veille »,
  « Celia, nouvelle conversation ».
- Vous pouvez aussi **écrire** vos questions dans la fenêtre.
- Démarrage automatique à l'ouverture de session (option dans les Réglages).

## Tester gratuitement, sans crédit

Celia fonctionne **sans clé API et sans payer**, pour les tests. Le moteur se choisit dans les
Réglages (*Moteur d'intelligence*) ; en mode **Automatique**, elle utilise Claude si une clé est
saisie, sinon un mode gratuit :

- **Démo** (rien à installer) : elle donne l'heure, la date et votre planning. Parfait pour vérifier
  le micro, la reconnaissance du prénom, la voix, le planning et les rappels.
- **Ollama** (IA gratuite sur votre ordinateur) : de vraies conversations, et la gestion du planning,
  de la mémoire et des projets. Moins forte que Claude, sans recherche web, mais gratuite et privée.
  1. Téléchargez Ollama sur <https://ollama.com/download> et ouvrez l'application.
  2. Relancez Celia : elle télécharge toute seule son IA (`qwen2.5:7b`, environ 4,7 Go, une seule fois).
     Sur un Mac avec 8 Go de mémoire, choisissez plutôt `qwen2.5:3b` dans les Réglages.
  Conseillé : un Mac avec puce Apple (M1 ou plus récent).

Le jour où vous ajoutez une clé Claude, Celia passe automatiquement sur Claude.

## Version web (sans rien installer)

`web/celia.html` est une version de Celia qui s'ouvre dans le navigateur, publiée comme page
Claude (artefact). Elle répond avec Claude **via votre compte Claude, sans clé ni crédit API**,
écoute votre voix (Chrome ou application Claude), parle avec une voix de Claude ou celle de
l'ordinateur, et garde planning, mémoire et projets de façon privée. Elle n'écoute que tant que
la page est ouverte et visible.

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
  Elle crée un dossier dans `Documents/Projets` avec une fiche `PROJET.md` (objectif, premières
  étapes), et ajoute ces étapes à votre planning.

Le bouton **📋 Planning & mémoire** affiche tout cela : tâches (cocher, supprimer, ajouter),
souvenirs (les effacer), projets (ouvrir leur dossier).

Les données sont dans `~/Library/Application Support/Celia/` sur Mac (`%APPDATA%\Celia\` sur Windows) : `memoire.json` (planning, notes, projets) et
`journal.jsonl` (historique des conversations). Rien n'est stocké en ligne.

## Installation sur Mac

1. Installez **Python 3.10 ou plus récent** depuis <https://www.python.org/downloads/macos/>
   (« macOS 64-bit universal2 installer »). Si vous l'oubliez, l'installateur ouvre la page pour vous.
2. Téléchargez ce dossier (bouton *Code → Download ZIP* sur GitHub) et décompressez-le dans un
   endroit stable, par exemple `Documents/Celia`.
3. Double-cliquez sur **`INSTALLER_MAC.command`**. Si macOS le bloque : clic droit → *Ouvrir* →
   *Ouvrir*.
4. Deux applications sont créées, sur le **Bureau** et dans le dossier **Applications** de votre
   compte (donc trouvables avec Spotlight) : **Celia** et **Celia ON-OFF**.
5. Au premier lancement :
   - macOS demande l'**accès au micro** : cliquez sur *Autoriser* (modifiable ensuite dans
     *Réglages Système → Confidentialité et sécurité → Micro*) ;
   - Celia vous demande votre **clé API Anthropic** (à créer sur <https://console.anthropic.com>,
     rubrique *API Keys*) ;
   - elle télécharge son modèle de reconnaissance vocale français (environ 40 Mo, une seule fois).

### Une belle voix sur Mac

Celia utilise les voix du Mac. Les voix **Premium** et **Améliorée** sont bien plus naturelles que
les voix de base, mais il faut les télécharger une fois :

*Réglages Système → Accessibilité → Contenu énoncé → Voix du système → Gérer les voix… →
Français (France)*, puis téléchargez par exemple **Audrey (Premium)**, **Aurélie (Améliorée)**
ou **Thomas (Améliorée)**.

Pas besoin de retenir ce chemin : au premier lancement, si aucune voix Premium n'est installée,
Celia affiche un **guide pas à pas** avec un bouton qui ouvre directement le bon réglage, puis un
bouton « C'est fait, essayer ma nouvelle voix » qui l'adopte aussitôt.

Celia choisit automatiquement la meilleure voix française installée (Premium d'abord, puis
Améliorée). Dans ses Réglages, les voix Premium sont marquées d'une ⭐ et le bouton **▶ Écouter**
permet de les comparer. Les voix « Siri » ne sont pas accessibles aux applications.

## Installation sur Windows

1. Installez **Python 3.10 ou plus récent** depuis <https://www.python.org/downloads/>
   en cochant **« Add python.exe to PATH »**.
2. Décompressez ce dossier dans un endroit stable, puis double-cliquez sur
   **`INSTALLER_WINDOWS.bat`**. Deux raccourcis apparaissent sur le bureau : **Celia** et
   **Celia ON-OFF**.
3. Pour une voix française : *Paramètres → Heure et langue → Voix*, ajoutez une voix française,
   puis choisissez-la dans les Réglages de Celia.

### Linux

Lancez `./install.sh` après avoir installé `python3-tk`, `espeak-ng` et `libportaudio2`.

## Utilisation au quotidien

| Action | Sur Mac | Sur Windows |
|---|---|---|
| Démarrer le matin | **Celia** (Bureau, Spotlight) ou démarrage automatique | Raccourci **Celia** ou démarrage automatique |
| Poser une question | « Celia, … » | « Celia, … » |
| Couper / rallumer le micro | **Celia ON-OFF**, ou le bouton rond | **Celia ON-OFF**, le bouton rond, ou l'icône près de l'horloge |
| La faire taire | « Celia stop » ou *Interrompre* | « Celia stop » ou *Interrompre* |
| Fermer la fenêtre | Le bouton rouge la ferme, Celia reste dans le Dock (clic sur l'icône pour la rouvrir) | La croix la cache, Celia reste près de l'horloge |
| Quitter complètement | **Cmd + Q** | Clic droit sur l'icône près de l'horloge → *Quitter* |

## Réglages

- **Prénom de l'assistante** : le mot pour l'appeler. Un prénom de 2 ou 3 syllabes,
  peu courant dans les conversations, marche mieux.
- **Modèle Claude** : Opus 5.5 (le plus intelligent, par défaut), Sonnet 5.5 ou Haiku 5.5
  (le plus rapide et le moins cher).
- **Profondeur de réflexion** : `low` est conseillé à l'oral, pour des réponses rapides.
- **Exigence de reconnaissance du prénom** : baissez-la si Celia ne vous entend pas,
  montez-la si elle se déclenche toute seule.

Les réglages sont dans `config.json`, dans ce même dossier. La clé API reste uniquement sur votre ordinateur.

## Coût

Celia utilise l'API Anthropic, facturée à l'usage. Une question courte coûte en général
une fraction de centime, un peu plus avec une recherche web. Pour réduire la facture,
choisissez Haiku 5.5 dans les Réglages.

## Structure du code

```
Celia.pyw            lanceur (sans fenêtre de console)
celia/app.py         interface, bouton ON/OFF, icône de notification, logique du mot de réveil
celia/brain.py       choix du moteur, appels à Claude (API Anthropic), boucle d'outils, mode démo
celia/local_ai.py    IA gratuite locale via Ollama
celia/memory.py      mémoire permanente : tâches, rappels, notes, projets, journal
celia/tools.py       outils que Claude utilise pour gérer la mémoire et les projets
celia/voice.py       micro + reconnaissance Vosk hors-ligne, synthèse vocale, détection du prénom
celia/system.py      raccourcis du bureau, démarrage automatique, instance unique
celia/config.py      réglages
```
