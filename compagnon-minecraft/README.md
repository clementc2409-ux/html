# Compagnon IA vocal pour Minecraft

Un compagnon qui t'accompagne pendant que tu joues à Minecraft en solo. Il **voit ton écran**,
**t'écoute** quand tu maintiens une touche et **te répond à voix haute**, en français, dans la
peau d'un vieux routier loyal et moqueur.

Tout est gratuit :

- **Groq** (offre gratuite) pour la transcription de ta voix (Whisper) et pour le modèle qui « voit » l'écran ;
- **edge-tts** pour la voix (voix neuronales de Microsoft Edge).

Le programme tourne sur Windows (il marche aussi sur Mac et Linux). Il **n'interagit jamais avec
le jeu** : pas de clic, pas de touche simulée. Il regarde et il parle, c'est tout.

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
  Le compagnon envoie **une seule** image d'environ 768 px de large en JPEG qualité 70, soit environ
  50 à 120 Ko : on est très loin de la limite.

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

### d) Enregistrer ta clé Groq

Le plus sûr est de passer par une variable d'environnement, pour que la clé ne soit écrite dans aucun fichier du projet :

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
| `touche` | `"souris:x1"` | Touche à maintenir pour parler. `souris:x1` est le bouton latéral arrière, `souris:x2` l'avant. Exemples clavier : `clavier:v`, `clavier:f8`, `clavier:alt_r`. |
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

```powershell
.venv\Scripts\Activate.ps1
python compagnon.py
```

Commandes utiles :

| Commande | Effet |
|---|---|
| `python compagnon.py --test` | Mode test : images d'exemple au lieu de vraies captures, faux journal du jeu (pas besoin de Minecraft). |
| `python compagnon.py --simuler mort` | Ajoute une fausse mort au faux journal du mode test. Aussi : `--simuler progres`, `--simuler chat "ton message"`. |
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
3. **Maintiens le bouton latéral de la souris**, dis « Salut, tu vois quoi là ? », relâche.
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
- Choisis une touche push-to-talk **qui ne sert pas dans le jeu**. Les boutons latéraux de souris
  ne sont pas utilisés par défaut dans Minecraft.
- La première réponse après le lancement peut être un peu plus lente (connexions à établir).

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

| Problème | Solution |
|---|---|
| « Clé API Groq manquante » | Refais l'étape 3 d) et **rouvre** PowerShell. |
| « clé API refusée » | Clé mal copiée ou supprimée : crées-en une nouvelle. |
| « le modèle … n'apparaît pas » | `python compagnon.py --modeles`, puis corrige `config.toml`. |
| « je n'ai rien entendu » | Autorisation micro (étape 3 e), ou mauvais micro : `--peripheriques`, puis réglage `micro`. |
| La touche souris ne fait rien | Ta souris envoie peut-être x2 au lieu de x1. Essaie `souris:x2` ou une touche clavier. |
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
  journal_jeu.py          lecture en direct de latest.log (morts, progrès, @compagnon)
  boucle.py               chef d'orchestre : tours de parole, priorités, interruptions, regard
exemples/images/          images d'exemple pour --test (remplace-les par tes captures F2 !)
tests/                    tests automatiques : python -m unittest
```
