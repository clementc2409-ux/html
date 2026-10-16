# Compagnon IA vocal pour Minecraft

Un compagnon qui t'accompagne pendant que tu joues à Minecraft en solo. Il **voit ton écran**,
**t'écoute** et **te répond à voix haute**, en français, dans la peau d'un vieux routier loyal et moqueur.

Deux moteurs au choix (réglage `[moteur]` de `config.toml`), tous les deux gratuits :

- **Gemini Live** (par défaut, conseillé) : il regarde la fenêtre de Minecraft **en continu**
  (vidéo, une image par seconde), t'entend et te répond **en direct** avec une voix naturelle.
  Il voit l'action se dérouler au lieu de photos isolées.
- **Groq** (ancien moteur) : une capture de temps en temps, transcription Whisper et voix edge-tts.

Le programme tourne sur Windows (il marche aussi sur Mac et Linux). Il **n'interagit jamais avec
le jeu** : pas de clic, pas de touche simulée. Il regarde et il parle, c'est tout.

---

## 0. Moteur Gemini Live (par défaut)

### Créer ta clé Gemini (gratuite)

1. Va sur <https://aistudio.google.com/apikey> et connecte-toi avec un compte Google.
2. **Create API key** → copie la clé (elle commence souvent par `AIza…`).
3. Dans PowerShell : `setx GEMINI_API_KEY "ta_clé"`, puis **ferme et rouvre** le terminal.

### Ce qui se passe pendant que tu joues

- **Il regarde** : la fenêtre de Minecraft est envoyée en continu, une image par seconde au plus,
  et seulement quand l'écran change (rien n'est envoyé quand le jeu est en pause).
- **Tu lui parles** : maintiens **V**, parle, relâche. Il répond en une à deux secondes et se tait dès
  que tu reprends la parole. Avec `micro_continu = true`, plus besoin de touche : parle quand tu veux.
- **Il réagit au jeu** : morts, progrès et messages `@compagnon` du chat, comme avec l'autre moteur.
- **Il commente de lui-même** : au plus toutes les 45 s (`cooldown_spontane`), et seulement si l'écran a
  changé. Il parle quand il voit quelque chose de **nouveau**, ou pour relancer la conversation si vous ne
  vous êtes pas parlé depuis plusieurs minutes (une question, une idée pour le royaume, un souvenir).
  Sinon il se tait. S'il commence quand même par « rien à signaler », sa voix est coupée avant que tu l'entendes.
- **Il voit l'écran actuel** : une capture fraîche part au moment où tu appuies sur V, et une seconde avant
  chaque événement ou coup d'œil (le temps qu'il la « voie »). La console affiche « écran capturé et envoyé ».
- **Il se souvient d'une partie à l'autre** : tes morts, tes progrès, vos échanges et ses remarques sont gardés
  dans `souvenirs.json`. Au lancement suivant, il peut y faire allusion (« encore noyé, comme hier ! ») et te
  rappeler tes projets (« tu m'avais parlé du port, on s'y met ? »). Pour lui faire tout oublier, supprime ce fichier.
- **La conversation continue** : Google coupe la connexion toutes les ~10 minutes, le compagnon se
  reconnecte tout seul et reprend la conversation là où elle en était.
- **Il tient le carnet du royaume** (projets, quêtes, lieux, rappels) et vérifie les recettes dans le wiki :
  voir plus bas.
- **Avec le mod « compagnon »**, il connaît ta vie, ta faim, le biome, l'heure, ce que tu vises et les monstres
  autour de toi, même dans ton dos, et il te prévient tout de suite d'un danger : voir plus bas.
- Dans la console : `[Moi]` (ce qu'il a compris de ta voix), `[Lui]` (ce qu'il a dit), `[Regard]`, `[Jeu]`,
  `[Vidéo]`, `[Capteur]`, `[Alerte]`, `[Carnet]`, `[Rappel]`, `[Wiki]`. Le numéro de version s'affiche au
  démarrage : vérifie-le après une mise à jour.

### Le mod « compagnon » : il sait exactement ce qui se passe (conseillé)

Sur une image, le modèle devine. Avec ce petit mod Fabric, il **sait**. Deux fois par seconde, le mod écrit
dans `<dossier du jeu>\compagnon\etat.json` ta vie, ta faim, ton armure, ton niveau, l'air, le feu, ta
position, la dimension, le biome, l'heure, la météo, les objets en main, les effets, le bloc ou la créature
visés, le menu ouvert, et les **monstres dans un rayon de 24 blocs** avec leur distance et leur direction
(devant, derrière, à gauche, à droite). Le mod **ne modifie rien** dans la partie : il lit et il écrit ce fichier, c'est tout.

Ce que ça change :
- une bande noire « CAPTEUR (infos exactes) » est collée sous chaque image envoyée : il ne se trompe plus sur ta
  vie, ton biome ou l'objet en main ;
- **alertes immédiates** : creeper à moins de 8 blocs, monstre dans ton dos, gros dégâts d'un coup (avec la
  cause), plus que 3 cœurs, faim, noyade, feu, arrivée dans le Nether, coucher du soleil… Il te prévient en
  une phrase, comme un ami qui crie « attention, derrière toi ! » ;
- il sait exactement quand un menu est ouvert ou que le jeu est en pause (la vidéo s'arrête alors) ;
- `noter_lieu` (voir le carnet) enregistre tes vraies coordonnées.

Installation (Minecraft Java **26.3**) :
1. Installe **Fabric** : télécharge l'installateur sur <https://fabricmc.net/use/installer/>, lance-le,
   choisis la version **26.3**, clique sur **Install**. Le launcher Minecraft a maintenant un profil
   « fabric-loader-…-26.3 ».
2. Télécharge **Fabric API** pour 26.3 sur <https://modrinth.com/mod/fabric-api> (version `0.162.0+26.3` ou
   plus récente pour 26.3) et mets le fichier `.jar` dans `%APPDATA%\.minecraft\mods\` (crée le dossier
   `mods` s'il n'existe pas).
3. Copie `compagnon-minecraft\mod-pret\compagnon-capteur-26.3-1.0.0.jar` dans ce même dossier `mods`.
4. Lance Minecraft avec le profil **fabric-loader** et entre dans ton monde. Dans la console du compagnon :
   `[Capteur] mod détecté : il connaît maintenant ta vie, les monstres autour, le biome…`

Le mod est compilé automatiquement par GitHub (code source dans `mod/`). Il ne marche qu'avec Minecraft 26.3 :
pour une autre version, il faut l'adapter. Sans le mod, tout le reste fonctionne comme avant.

Pour essayer sans Minecraft : lance `python compagnon.py --test`, puis dans une 2e console
`python compagnon.py --simuler creeper` (un creeper arrive dans ton dos), `--simuler blesse` (des flèches de
squelette) ou `--simuler capteur` (état normal, pour voir la bande).

### Le carnet du royaume, les quêtes et les rappels

Le compagnon tient lui-même un **carnet du royaume** grâce à des outils que Gemini peut utiliser pendant la
conversation (la console affiche une ligne `[Carnet]` à chaque fois) :
- **projets** : « on va construire un port au sud » → il le note, et il te le rappellera plus tard ;
- **quêtes** : il te propose de temps en temps une quête concrète adaptée à ton avancement (« rapporte 20
  blocs de quartz pour la salle du trône »). Si tu acceptes, il la note ; quand il voit qu'elle est
  accomplie, il la coche et te félicite. Pendant les coups d'œil, il garde la quête en tête ;
- **lieux** : « note ma base ici » → il enregistre le lieu avec tes coordonnées (prises par le mod).
  Plus tard : « c'était où le village ? » → il te les redonne ;
- **rappels** : « rappelle-moi dans 10 minutes d'aller replanter les arbres » → 10 minutes plus tard, il te
  le dit (même si tu as quitté le jeu entre-temps : il te le dira au prochain lancement) ;
- **wiki** : quand il n'est pas sûr d'une recette ou d'un chiffre, il cherche dans le wiki Minecraft
  (<https://fr.minecraft.wiki>), gratuitement. La recherche Google, elle, n'est pas incluse dans l'offre
  gratuite de Gemini.

Tout est gardé dans `carnet.json`, avec une version lisible dans **`carnet.md`** (ouvre-la avec le Bloc-notes).
Toutes les 15 minutes et quand tu quittes, un petit modèle rapide (`gemini-3.5-flash`) réécrit l'**histoire du
royaume** à partir de vos souvenirs. Au lancement suivant, le compagnon connaît cette histoire, tes projets,
tes quêtes et tes lieux. Pour repartir de zéro, supprime `carnet.json`, `carnet.md` et `souvenirs.json`.
Réglages : section `[carnet]` de `config.toml`.

### Réglages (section `[gemini]` de `config.toml`)

| Réglage | Par défaut | Effet |
|---|---|---|
| `modele` | `"gemini-3.8-live"` | Modèle temps réel (vérifié le 16/10/2026). Liste à jour : `python compagnon.py --modeles`. |
| `voix` | `"Algenib"` | Voix grave et rocailleuse. Autres voix masculines : `Charon` (posée), `Orus` (ferme), `Fenrir` (énergique), `Puck` (enjouée). |
| `micro_continu` | `false` | `true` = micro toujours ouvert, sans touche. Casque obligatoire. |
| `images_par_seconde` | `1.0` | Images envoyées par seconde (1 au maximum). |
| `largeur_video`, `resolution_video` | `1280`, `"auto"` | Précision de l'image. `"auto"` est conseillé : en forçant `"moyenne"`, il disait parfois ne pas voir l'écran. |
| `bande_capteur` | `true` | Colle la bande « CAPTEUR » sous chaque image (avec le mod). |
| `proactivite` | `true` | Il peut décider de se taire quand il n'a rien d'intéressant à dire. |

Section `[carnet]` : `outils` (carnet, rappels et wiki, `true`), `quetes` (il propose des quêtes, `true`),
`wiki` (`true`), `resume_auto` (histoire du royaume résumée automatiquement, `true`), `modele_resume`
(`"gemini-3.5-flash"`).

### Limites à connaître

- L'offre gratuite de Google a ses propres quotas (visibles dans AI Studio). Si un quota est atteint,
  le compagnon le dit dans la console et réessaie un peu plus tard.
- Avec l'offre **gratuite**, Google peut utiliser les données envoyées (images, voix) pour améliorer ses
  produits. Ne montre rien de personnel à l'écran pendant que le compagnon tourne.
- La proactivité utilise la version « v1alpha » de l'API Google. Si elle est refusée, le compagnon se
  reconnecte automatiquement sans elle.
- Testé en conditions réelles le 16/10/2026 (images d'exemple, questions écrites et parlées, événements,
  coups d'œil) : voix lancée 2 à 3 s après la fin de ta phrase.

Pour revenir à l'ancien moteur : `choix = "groq"` dans `[moteur]`, ou `python compagnon.py --moteur groq`.

---

## 1. Modèles Groq utilisés (vérifiés le 16/10/2026)

| Rôle | Modèle | Remarques |
|---|---|---|
| Transcription de ta voix | `whisper-large-v3-turbo` | Rapide et multilingue. Variante `whisper-large-v3`, un peu plus précise mais plus lente. |
| Chat avec image (vision) | `qwen/qwen3.8-27b` | Modèle multimodal (texte + image) en *preview*. Il a remplacé `qwen/qwen3.6-27b` (retiré le 14/09/2026). Llama 4 Scout a été retiré le 17/07/2026. |

Les noms de modèles **changent souvent**. Si un modèle disparaît, lance :

```
python compagnon.py --modeles
```

Cette commande affiche les modèles disponibles avec ta clé. Corrige ensuite `config.toml`.

### Limites de l'offre gratuite (à vérifier sur ton compte)

Les vrais chiffres de ton compte sont sur <https://console.groq.com/settings/limits>. Les limites
s'appliquent à toute ton organisation, pas à chaque clé. Ordres de grandeur publiés en octobre 2026 :

- **Whisper** : 20 requêtes/minute, 2 000/jour, 7 200 secondes d'audio/heure, 28 800 s/jour. Largement suffisant.
- **Modèle vision** : environ 30 requêtes/minute, 1 000 requêtes/jour, 8 000 jetons/minute et 200 000 jetons/jour.
  **C'est le jeton par jour qui limite** : chaque réponse avec image coûte environ 1 500 à 3 000 jetons.
- **Images** : 20 Mo maximum par image envoyée par URL. En base64, ce que fait le compagnon, la doc
  historique de Groq indique 4 Mo par requête. Selon le modèle, une requête accepte 3 à 5 images au plus.
  Le compagnon envoie **une seule** image de 1280 px de large en JPEG qualité 85, soit environ
  150 à 350 Ko : on est très loin de la limite.

Le compagnon tient compte de ces limites (voir [Budget](#budget-et-limites-groq)).

---

## 2. Créer ta clé API Groq

1. Va sur <https://console.groq.com> et crée un compte (gratuit, sans carte bancaire).
2. Menu **API Keys** → **Create API Key** → donne-lui un nom (ex. « compagnon ») → copie la clé (`gsk_…`).
   Elle ne sera plus affichée ensuite.
3. **Ne la publie jamais** (GitHub, Discord…). Si elle a fuité, supprime-la dans la console et crées-en une autre.

---

## 3. Installation sur Windows, pas à pas

### a) Installer Python

1. Télécharge **Python 3.12 ou 3.13** sur <https://www.python.org/downloads/windows/> (3.11 minimum).
2. Lance l'installateur et **coche « Add python.exe to PATH »** en bas de la première fenêtre, puis *Install Now*.
3. Vérifie dans PowerShell (touche Windows, tape « PowerShell ») :
   ```powershell
   py --version
   ```

### b) Récupérer le projet

Télécharge le dépôt (bouton **Code → Download ZIP** sur GitHub, puis extrais-le) ou clone-le avec git.
Ouvre ensuite PowerShell **dans le dossier `compagnon-minecraft`**. Dans l'explorateur : clic droit
dans le dossier → *Ouvrir dans le terminal*.

### c) Créer un environnement et installer les dépendances

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Si PowerShell refuse d'exécuter `Activate.ps1`, lance une fois
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, puis réessaie.
> À chaque nouvelle session, refais seulement `.venv\Scripts\Activate.ps1`.

### d) Enregistrer tes clés

Le plus sûr est de passer par des variables d'environnement, pour que les clés ne soient écrites dans aucun
fichier du projet. Gemini (moteur par défaut, voir section 0) :

```powershell
setx GEMINI_API_KEY "ta_cle_gemini"
```

Groq (seulement si tu utilises l'ancien moteur) :

```powershell
setx GROQ_API_KEY "gsk_ta_cle_ici"
```

**Ferme puis rouvre PowerShell** : `setx` ne s'applique qu'aux nouvelles fenêtres. Refais ensuite
l'activation de `.venv`. Tu peux aussi mettre la clé dans `cle_api` de `config.toml`, mais alors
ne partage pas ce fichier.

### e) Autorisations Windows

- **Micro** : *Paramètres → Confidentialité et sécurité → Microphone*. Active **« Accès au microphone »**
  et **« Autoriser les applications de bureau à accéder à votre microphone »**. Python est une
  application de bureau : sans ce réglage, l'enregistrement est muet.
- **Clavier/souris** : aucune autorisation à donner. Exception : si tu lances Minecraft **en
  administrateur**, lance aussi le compagnon en administrateur, sinon Windows l'empêche de voir
  la touche push-to-talk quand le jeu a le focus.
- **Capture d'écran** : aucune autorisation sous Windows.
- Si ton antivirus signale `pynput` (il écoute le clavier/la souris pour la touche push-to-talk),
  autorise-le. Le programme ne fait qu'écouter cette touche.

---

## 4. Configuration (`config.toml`)

Ouvre `config.toml` avec le Bloc-notes. Chaque réglage est expliqué en commentaire. Les principaux :

| Réglage | Par défaut | À quoi ça sert |
|---|---|---|
| `touche` | `"clavier:v"` | Touche à maintenir pour parler (V par défaut ; elle marche aussi quand tu es dans Minecraft). Autres exemples : `clavier:b`, `clavier:alt_r`, `souris:x1` (bouton latéral arrière), `souris:x2` (avant). |
| `micro` / `sortie_audio` | `""` | Périphériques audio (vide = ceux par défaut de Windows). Liste : `python compagnon.py --peripheriques`. |
| `voix` | `"fr-FR-HenriNeural"` | Voix du compagnon. Pour d'autres voix : `edge-tts --list-voices`. |
| `modele_vision` | `"qwen/qwen3.8-27b"` | Modèle Groq qui voit l'écran. |
| `ecran` | `1` | Écran à capturer, si tu en as plusieurs. |
| `pseudo` | `""` | **Ton pseudo Minecraft exact.** Sans lui, tes morts et tes succès ne sont pas détectés. |
| `chemin_log` | `%APPDATA%\.minecraft\logs\latest.log` | Journal du jeu. Avec CurseForge, Prism ou Modrinth, mets le `logs\latest.log` de ton instance. |
| `mot_cle_chat` | `"@compagnon"` | Écris ce mot au début d'un message du chat pour lui parler par écrit. |
| `commentaires_spontanes` | `true` | Commentaires spontanés activés ou non. |
| `intervalle_capture` | `20` | Une capture toutes les 20 s pour un éventuel commentaire spontané. |
| `cooldown_spontane` | `45` | Au moins 45 s entre deux commentaires spontanés prononcés. |
| `seuil_changement` | `0.04` | Écart minimal (4 %) avec la dernière image envoyée pour en envoyer une nouvelle. |
| `fenetre_minecraft` | `"Minecraft"` | Pas de commentaire spontané si la fenêtre active n'a pas ce mot dans son titre. Mets `""` si ton modpack change le titre. |
| `jetons_par_jour`, `jetons_spontanes_par_heure` | `200000`, `40000` | Budget Groq (voir plus bas). |

Personnalité : modifie librement **`personnalite.md`**. Elle est relue à chaque lancement.

Chronique (facultatif) : crée un fichier **`chronique.md`** à côté de `compagnon.py` et raconte-y
l'histoire de ta partie (nom du royaume, lieux, événements marquants, projets en cours). Son contenu
est ajouté au prompt système au démarrage : le compagnon s'en souviendra. Pense à rester concis, car
chaque ligne est renvoyée à chaque requête et consomme des jetons. Exemple :

```markdown
# Le royaume de Valombre
- J'ai fondé Valombre au bord d'un grand lac, au sud d'une forêt de bouleaux.
- Le donjon est fini, les remparts sont à moitié construits.
- Projet en cours : un barrage sur la rivière de l'est et un port pour la capitale.
- Mon chien s'appelle Brigand. Je suis mort deux fois dans la lave, il ne faut pas m'en parler.
```

---

## 5. Lancement

**Le plus simple : double-clique sur `lancer.bat`.** La première fois, il crée l'environnement Python et
installe les bibliothèques tout seul (une ou deux minutes), puis il lance le compagnon. Les fois suivantes,
il démarre directement. Pas besoin d'activer `.venv` ni de taper de commande.

Ou, depuis PowerShell :

```powershell
.venv\Scripts\Activate.ps1
python compagnon.py
```

Commandes utiles :

| Commande | Effet |
|---|---|
| `python compagnon.py --test` | Mode test : images d'exemple au lieu de vraies captures, faux journal du jeu (pas besoin de Minecraft). |
| `python compagnon.py --simuler mort` | Ajoute une fausse mort au faux journal du mode test. Aussi : `--simuler progres`, `--simuler chat "ton message"`. |
| `python compagnon.py --simuler creeper` | Imite le mod pendant 20 s pendant le mode test : un creeper arrive dans ton dos. Aussi : `--simuler blesse`, `--simuler capteur`. |
| `python compagnon.py --diagnostic` | **Teste chaque maillon** (clé Groq, modèle, voix, micro, touche) et dit quoi corriger. À lancer en premier si quelque chose ne marche pas. |
| `python compagnon.py --modeles` | Liste les modèles Groq disponibles avec ta clé. |
| `python compagnon.py --peripheriques` | Liste les micros et sorties audio. |
| `python compagnon.py --verbeux` | Plus de détails dans la console. |

**Ctrl+C** pour quitter. Tu peux aussi taper une phrase dans la console puis Entrée pour lui
parler par écrit : pratique pour tester sans micro.

### Ce que tu vois dans la console

```
14:02:11  [Micro]  j'écoute…
14:02:13  [Moi]    Tu as vu ce creeper ?   (transcription 0.45 s)
14:02:14  [Lui]    Vu, et il te colle aux talons. Recule avant qu'il siffle !   (premier mot 1.10 s, 1834 jetons)
14:02:14           -> voix lancée 1.72 s après ta phrase
```

---

## 6. Tester, étape 1 : push-to-talk, capture et réponse vocale

1. **Casque sur les oreilles** (voir conseils plus bas), puis lance `python compagnon.py --test`.
2. Vérifie la console : aucun message « indisponible », et « Compagnon prêt (MODE TEST) ».
3. **Maintiens la touche V**, dis « Salut, tu vois quoi là ? », relâche.
   - Tu dois voir `[Moi]` avec ta phrase, puis `[Lui]` avec sa réponse, et l'entendre.
   - Il doit parler de l'image d'exemple (prairie, creeper, grotte, château : une nouvelle image à chaque question).
   - Regarde la ligne « voix lancée X s après ta phrase ». L'objectif est 2 à 3 s.
4. **Interruption** : pose une question qui appelle une longue réponse, puis réappuie sur la touche
   pendant qu'il parle. Il doit se taire immédiatement.
5. **Mémoire** : demande « Qu'est-ce que je viens de te demander ? ». Il doit s'en souvenir.
6. Ensuite, en vrai : lance Minecraft, puis `python compagnon.py` (sans `--test`), et pose-lui une question sur ce que tu vois.

Si quelque chose ne marche pas, va voir la section [Dépannage](#dépannage).

## 7. Tester, étape 2 : réactions aux événements du jeu

Le compagnon lit `latest.log` en temps réel et réagit aussitôt, avec une capture d'écran en contexte, à :

- **ta mort** : tous les messages de mort qui commencent par ton pseudo, en français ou en anglais ;
- **tes progrès / défis / objectifs** (« a obtenu le progrès [L'âge de pierre] ») ;
- **tes messages du chat qui commencent par `@compagnon`** : il répond à voix haute.

Test sans Minecraft :

1. Console 1 : `python compagnon.py --test`. Vérifie la ligne « Journal jeu : …\exemples\faux_latest.log ».
2. Console 2 (même dossier, `.venv` activé) :
   ```powershell
   python compagnon.py --simuler mort
   python compagnon.py --simuler progres
   python compagnon.py --simuler chat "tu trouves ma tour réussie ?"
   ```
   Dans la console 1, tu dois voir `[Jeu] mort : …`, `[Jeu] progrès : …` puis `[Chat] …`, et l'entendre
   réagir à chaque fois (il te charrie pour la mort, te félicite pour le progrès, répond au message).
3. Tu peux aussi ouvrir `exemples\faux_latest.log` dans le Bloc-notes, **ajouter une ligne à la fin** et
   enregistrer, par exemple : `[21:04:11] [Server thread/INFO]: Steve a été tué par Zombie`.
   En mode test, le pseudo est `Steve` si tu n'en as pas configuré.

Test en vrai : mets ton `pseudo` dans `config.toml`, lance Minecraft puis `python compagnon.py`.
Écris `@compagnon salut !` dans le chat du jeu, puis meurs bêtement (une chute fera l'affaire).

> Le journal est écrit dans la langue du jeu : le compagnon reconnaît les messages en français et en
> anglais. Les messages d'autres joueurs ou de tes animaux nommés sont ignorés.

---

## 8. Tester, étape 3 : commentaires spontanés

Toutes les `intervalle_capture` secondes (20 s par défaut), le compagnon prend une capture et décide
s'il l'envoie au modèle. **Il ne l'envoie pas** si :

- il est déjà en train de parler ou de répondre, ou si tu es en train de parler ;
- un commentaire spontané a déjà été prononcé il y a moins de `cooldown_spontane` secondes (45 s) ;
- la fenêtre au premier plan n'est pas Minecraft (tu es sur le bureau, dans Discord…). Minecraft se
  met d'ailleurs en pause tout seul dans ce cas ;
- l'écran a à peine changé depuis la dernière image envoyée. C'est le cas quand le jeu est en pause,
  car l'image est figée, ou quand tu restes immobile ;
- le budget de jetons ne le permet pas (voir plus bas).

Sinon, il envoie l'image avec la consigne « réagis seulement si ça vaut le coup ». Le modèle répond
exactement `SILENCE` s'il n'y a rien à dire (y compris devant un menu ou un inventaire), et dans ce cas
**rien n'est prononcé**. Les réponses à tes questions ne sont jamais soumises au cooldown.

Test sans Minecraft :

1. `python compagnon.py --test`, puis attends sans rien faire.
2. Toutes les 20 s, une image d'exemple différente est utilisée. Tu dois voir alternativement
   `[Regard] coup d'œil envoyé`, puis soit `[Regard] SILENCE (rien d'intéressant à dire)`, soit
   `[Lui] (spontané) …` avec sa voix. Après un commentaire prononcé, la ligne
   `pas de commentaire : cooldown…` apparaît avec `--verbeux`.
3. **Écran inchangé** : laisse une seule image dans `exemples\images` (déplace les autres ailleurs). Après
   le premier envoi, tu dois voir `[Regard] pas de commentaire : écran quasi identique`.
4. **Priorités** : pendant un commentaire spontané, appuie sur la touche push-to-talk. Il se tait et t'écoute.

Test en vrai : joue normalement 10 minutes. Mets le jeu en pause : plus rien n'est envoyé. Passe sur le
bureau : plus rien non plus. Si tu le trouves trop bavard, augmente `cooldown_spontane` ou baisse
`jetons_spontanes_par_heure`. Pour le couper complètement : `commentaires_spontanes = false`.

> Astuce : remplace les images de `exemples\images` par tes propres captures Minecraft (touche F2 dans
> le jeu, elles sont dans `%APPDATA%\.minecraft\screenshots`) pour des tests plus parlants.

## 9. Conseils

- **Casque obligatoire.** Avec des haut-parleurs, le micro capte la voix du compagnon. Le push-to-talk
  limite les dégâts, mais un casque est bien plus confortable.
- **Minecraft en mode fenêtré ou plein écran « sans bordure »** si la capture est noire. Le plein
  écran exclusif peut empêcher la capture.
- Choisis une touche push-to-talk **qui ne sert pas dans le jeu** (V par défaut). Les boutons latéraux de souris
  ne sont pas utilisés par défaut dans Minecraft.
- La première réponse après le lancement peut être un peu plus lente (connexions à établir).

## Qualité de l'analyse des images

Pour qu'il comprenne mieux ce qu'il voit, le compagnon :

- envoie des captures nettes (1280 px de large, JPEG qualité 85) ;
- donne au modèle un mode d'emploi de l'écran de Minecraft (vie, faim, objet en main, chat, écran de mort, menus…) ;
- lui fait d'abord **noter ce qu'il voit**, avant de répondre. Cette observation n'est pas prononcée, mais elle
  s'affiche dans la console sur une ligne `[Vu]`. Tu sais ainsi ce qu'il a compris de l'image :
  ```
  14:02:14  [Vu]     Grotte sombre, pioche en fer en main, vie à 6 cœurs, un squelette au fond à gauche, lave en bas.
  14:02:14  [Lui]    Squelette au fond, et de la lave juste sous tes pieds : doucement, Seigneur.
  ```

Pour aller encore plus loin (dans `config.toml`) :

| Réglage | Effet |
|---|---|
| `effort_raisonnement = "low"` | Le modèle réfléchit avant de répondre : analyse plus fine, mais 1 à 3 s d'attente en plus et bien plus de jetons. |
| `largeur_image = 1600` | Encore plus de détails (plus lent, plus de jetons). À l'inverse, `768` est plus économique. |
| `temperature = 0.4` | Colle encore plus à ce qu'il voit, invente moins (mais réponses moins variées). |

Si un autre modèle vision apparaît dans `python compagnon.py --modeles` (voir aussi
<https://console.groq.com/docs/vision>), tu peux l'essayer en changeant `modele_vision`.

## Budget et limites Groq

Avec l'offre gratuite, la vraie limite est le **nombre de jetons par jour** du modèle vision (environ
200 000). Une requête avec image coûte environ 1 500 à 3 000 jetons, soit une centaine de réponses par
jour. Envoyer une capture toutes les 20 s viderait ce quota en moins d'une heure : le compagnon se régule donc tout seul.

- **Tes questions, tes messages `@compagnon` et les événements du jeu passent toujours** (dans la limite
  de ce que Groq accepte).
- Les **commentaires spontanés** ont leur propre budget, `jetons_spontanes_par_heure` (40 000 par défaut,
  soit environ un envoi toutes les 3 à 4 minutes en moyenne quand l'écran bouge). Un petit crédit
  s'accumule quand tu ne joues pas, ce qui permet quelques commentaires rapprochés de temps en temps.
- Au-delà de **80 % de `jetons_par_jour`**, ou s'il reste moins de 30 requêtes Groq pour la journée,
  plus de commentaire spontané : le reste est gardé pour tes questions.
- Si Groq répond « trop de requêtes » (429) : un commentaire spontané est **abandonné immédiatement**
  et les suivants sont mis en pause le temps demandé par Groq. Une question est **réessayée**
  (jusqu'à 3 fois, si l'attente demandée est courte). Sinon le compagnon te dit à voix haute de
  patienter. En cas de coupure réseau, même principe, et le programme ne plante jamais.
- La consommation du jour s'affiche au démarrage et après chaque réponse (en jetons). Elle est
  enregistrée dans `.consommation_groq.json` (remise à zéro chaque jour).

Si ton compte a un quota plus large (voir <https://console.groq.com/settings/limits>), augmente
`jetons_par_jour` et `jetons_spontanes_par_heure` dans `config.toml`.

## Dépannage

**Premier réflexe : `python compagnon.py --diagnostic`.** En une minute, il teste la clé Groq, une
réponse du modèle, la voix (tu dois entendre une phrase), le micro (parle quand il te le demande) et
la touche push-to-talk (il affiche le nom de chaque touche ou bouton que tu presses). Il termine par
la liste de ce qu'il faut corriger.

| Problème | Solution |
|---|---|
| Rien ne s'affiche quand j'appuie sur la touche | La touche n'est pas détectée : `--diagnostic` t'affiche le nom à mettre dans `touche`. Le logiciel de certaines souris réaffecte les boutons latéraux : prends alors une touche clavier (`clavier:v`). |
| « Clé API Groq manquante » | Refais l'étape 3 d) et **rouvre** PowerShell. |
| « clé API refusée » | Clé mal copiée ou supprimée : crées-en une nouvelle. |
| « le modèle … n'apparaît pas » | `python compagnon.py --modeles`, puis corrige `config.toml`. |
| « je n'ai rien entendu » | Autorisation micro (étape 3 e), ou mauvais micro : `--peripheriques`, puis réglage `micro`. |
| Un bouton de souris ne fait rien | Ta souris envoie peut-être x2 au lieu de x1. Essaie `souris:x2`, ou garde la touche V. |
| « Memory allocation still failed after 10 retries » | Mémoire saturée (souvent Minecraft qui a trop de RAM allouée). Corrigé dans le code depuis le 16/10 ; sinon tape une fois `setx OPENBLAS_NUM_THREADS 1` puis rouvre le terminal. Évite d'allouer à Minecraft plus de la moitié de ta RAM. |
| « IMPOSSIBLE D'OUVRIR LE MICRO » | Paramètres Windows > Système > Son > Entrée : un micro doit être choisi et sa barre doit bouger quand tu parles. Puis `--peripheriques` et réglage `micro` (numéro du micro). |
| Pas de son | Vérifie la sortie par défaut de Windows ou le réglage `sortie_audio`. edge-tts a besoin d'Internet. |
| « synthèse impossible » | Pas d'accès Internet à Microsoft (pare-feu, VPN) ou nom de voix erroné. |
| Capture noire | Mode fenêtré / sans bordure, et vérifie le réglage `ecran`. |
| Il ne réagit pas à mes morts | Vérifie `pseudo` (exactement comme dans le jeu) et la ligne « Journal jeu » au démarrage. |
| « journal introuvable » | Chemin du launcher différent : ouvre le dossier de ton instance, puis `logs\latest.log`. |
| Il ne fait jamais de commentaire spontané | Regarde les lignes `[Regard] pas de commentaire : …` (avec `--verbeux` pour toutes). Souvent : titre de fenêtre (mets `fenetre_minecraft = ""`) ou budget. |
| Il parle trop | Augmente `cooldown_spontane`, baisse `jetons_spontanes_par_heure`, ou durcis la règle « SILENCE » dans `personnalite.md`. |

## Structure du code

```
compagnon.py              point d'entrée (options en ligne de commande)
config.toml               réglages commentés
personnalite.md           prompt système (personnalité), modifiable
chronique.md              (facultatif, à créer) l'histoire de ta partie, ajoutée au prompt
compagnon_ia/
  config.py               lecture de config.toml
  capture.py              captures d'écran (mss), images de test, JPEG, écran changé ?, fenêtre active
  audio.py                micro push-to-talk (sounddevice), encodage FLAC
  touches.py              touche push-to-talk clavier/souris (pynput)
  voix.py                 synthèse edge-tts, lecteur audio interruptible, parole phrase par phrase
  phrases.py              découpage en phrases, filtres (SILENCE, nettoyage)
  cerveau.py              Groq : Whisper, modèle vision en streaming, mémoire courte, erreurs/429
  budget.py               suivi des jetons, budget des commentaires spontanés
  live.py                 moteur Gemini Live : vidéo en continu, voix en direct, reconnexion, outils
  etat_jeu.py             lecture de l'état exact du jeu (mod), bande « CAPTEUR », alertes, simulation
  carnet.py               carnet du royaume : projets, quêtes, lieux, rappels, histoire résumée
  outils.py               outils proposés à Gemini (function calling) et leur exécution
  wiki.py                 recherche dans fr.minecraft.wiki
  souvenirs.py            mémoire d'une partie à l'autre (souvenirs.json)
  journal_jeu.py          lecture en direct de latest.log (morts, progrès, @compagnon)
  boucle.py               chef d'orchestre : tours de parole, priorités, interruptions, regard
exemples/images/          images d'exemple pour --test (remplace-les par tes captures F2 !)
mod/                      code source du mod Fabric « compagnon » (capteur), compilé par GitHub Actions
mod-pret/                 le mod compilé (.jar) à copier dans le dossier mods de Minecraft
tests/                    tests automatiques : python -m unittest
```
