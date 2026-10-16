"""Autodiagnostic (python compagnon.py --diagnostic) : teste chaque maillon et dit quoi corriger."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import sys
import threading
import time

from PIL import Image

from .audio import Micro, encoder_flac, niveau_crete
from .budget import Budget
from .capture import EXTENSIONS_IMAGES, CaptureEcran, encoder_jpeg, preparer_image
from .cerveau import Cerveau
from .config import RACINE, Config
from .touches import analyser_touche
from .voix import Lecteur, Synthese

PROBLEMES: list[str] = []
_ETAPE = [0]


def titre(texte: str) -> None:
    _ETAPE[0] += 1
    print(f"\n=== {_ETAPE[0]}. {texte} ===")


def ok(texte: str) -> None:
    print(f"  [OK] {texte}")


def probleme(texte: str, conseil: str = "") -> None:
    print(f"  [PROBLÈME] {texte}")
    if conseil:
        print(f"     -> {conseil}")
    PROBLEMES.append(texte)


def nom_peripherique(peripherique, genre: str) -> str:
    import sounddevice as sd

    try:
        infos = sd.query_devices(peripherique, genre) if peripherique is not None else sd.query_devices(kind=genre)
        return infos["name"]
    except Exception:
        return "?"


async def tester_groq(cfg: Config) -> Cerveau | None:
    titre("Clé API et modèles Groq")
    if not cfg.cle_api:
        probleme("aucune clé API trouvée",
                 "tape setx GROQ_API_KEY \"gsk_...\" puis FERME et rouvre le terminal (ou remplis cle_api).")
        return None
    cerveau = Cerveau(cfg, "Tu es un test technique. Réponds en français, en 5 mots maximum.", Budget(0, 0))
    try:
        modeles = await cerveau.lister_modeles()
    except Exception as e:
        probleme(f"Groq refuse ou est injoignable : {e}",
                 "clé mal copiée ? pas d'Internet ? pare-feu/antivirus qui bloque Python ?")
        return None
    ok(f"clé acceptée ({len(modeles)} modèles disponibles)")
    for modele in (cfg.modele_transcription, cfg.modele_vision):
        if modele in modeles:
            ok(f"modèle « {modele} » disponible")
        else:
            probleme(f"modèle « {modele} » introuvable",
                     "lance python compagnon.py --modeles et corrige config.toml.")
    return cerveau


async def tester_gemini(cfg: Config, image: Image.Image | None) -> None:
    titre("Gemini Live : connexion, compréhension de la capture et voix")
    if not cfg.gemini_cle_api:
        probleme("aucune clé API Gemini trouvée",
                 "crée-la sur https://aistudio.google.com/apikey, tape setx GEMINI_API_KEY \"ta_clé\" "
                 "puis FERME et rouvre le terminal.")
        return
    try:
        from google.genai import types
    except Exception as e:
        probleme(f"bibliothèque google-genai absente : {e}", "pip install -r requirements.txt")
        return
    from .live import construire_config, construire_consignes, creer_client

    # Détection automatique de la parole pour ce test : un simple message texte suffit à déclencher sa réponse.
    reglages = dataclasses.replace(cfg, micro_continu=True)
    consignes = construire_consignes(cfg, "Tu es un compagnon de jeu qui parle français.", "")
    audio, texte, debut = [], [], time.perf_counter()
    premier_son = None
    for minimale in (False, True):
        try:
            config = construire_config(types, reglages, consignes, minimale=minimale)
            client = creer_client(cfg.gemini_cle_api, avancee=cfg.proactivite and not minimale)
            async with client.aio.live.connect(model=cfg.gemini_modele, config=config) as session:
                ok(f"connecté au modèle « {cfg.gemini_modele} »" + (" (options réduites)" if minimale else ""))
                if image is not None:
                    jpeg = encoder_jpeg(image, cfg.largeur_video, 80)
                    await session.send_realtime_input(video=types.Blob(data=jpeg, mime_type="image/jpeg"))
                debut = time.perf_counter()
                await session.send_realtime_input(
                    text="[Écrit] En une phrase : que vois-tu sur mon écran en ce moment ?")
                async with asyncio.timeout(30):
                    async for message in session.receive():
                        contenu = message.server_content
                        if contenu is None:
                            continue
                        if contenu.output_transcription is not None and contenu.output_transcription.text:
                            texte.append(contenu.output_transcription.text)
                        for partie in (contenu.model_turn.parts if contenu.model_turn else None) or []:
                            if partie.inline_data and partie.inline_data.data:
                                premier_son = premier_son or time.perf_counter() - debut
                                audio.append(partie.inline_data.data)
            break
        except Exception as e:
            if not minimale and "api key" not in str(e).lower() and (
                    "invalid" in str(e).lower() or "not found" in str(e).lower()):
                print(f"  ... options refusées ({e}), nouvel essai avec des options réduites")
                continue
            probleme(f"Gemini Live ne répond pas : {e}",
                     "clé mal copiée, nom de modèle dépassé (python compagnon.py --modeles), "
                     "quota gratuit atteint, ou pare-feu qui bloque Python.")
            return
    if not audio:
        probleme("connecté, mais aucune réponse vocale reçue")
        return
    ok(f"réponse vocale après {premier_son:.1f} s : « {''.join(texte).strip()} »")
    lecteur = Lecteur(cfg.sortie_audio)
    try:
        lecteur.demarrer()
        print(f"  ... lecture de sa voix sur « {nom_peripherique(lecteur.peripherique, 'output')} » : écoute bien !")
        import numpy as np

        lecteur.jouer(np.frombuffer(b"".join(audio), dtype=np.int16).astype(np.float32) / 32768.0)
        await lecteur.attendre_fin()
        await asyncio.sleep(0.4)
        lecteur.fermer()
        ok("voix jouée. Si tu n'as rien entendu : mets ton casque en sortie par défaut dans Windows.")
    except Exception as e:
        probleme(f"impossible de jouer le son : {e}", "python compagnon.py --peripheriques, puis sortie_audio.")


def tester_capture(cfg: Config) -> Image.Image | None:
    titre("Capture d'écran")
    capture = CaptureEcran(cfg.ecran, cfg.fenetre_minecraft, cfg.suivre_fenetre)
    try:
        image = capture.capturer()
    except Exception as e:
        probleme(f"capture impossible : {e}")
        return None
    fichier = RACINE / "derniere_capture.jpg"
    fichier.write_bytes(encoder_jpeg(image, cfg.largeur_image, cfg.qualite_jpeg))
    source = capture._derniere_source or "?"
    if source.startswith("fenêtre"):
        ok(f"capture de la {source}")
    else:
        print(f"  ... fenêtre de Minecraft non trouvée : capture de l'{source} entier "
              "(lance Minecraft avant le diagnostic pour tester la vraie capture)")
    ok(f"image enregistrée dans {fichier.name} : ouvre-la pour voir exactement ce que le compagnon voit")
    return image


async def tester_vision(cfg: Config, cerveau: Cerveau, image: Image.Image | None) -> None:
    titre("Ce que le modèle comprend de la capture")
    if image is None:
        images = sorted(p for p in (RACINE / "exemples" / "images").glob("*") if p.suffix.lower() in EXTENSIONS_IMAGES)
        image = Image.open(images[0]).convert("RGB") if images else Image.new("RGB", (768, 432), (90, 160, 60))
    debut = time.perf_counter()
    try:
        flux = cerveau.repondre("[Voix] Dis-moi en quelques mots ce que tu vois.",
                                preparer_image(image, cfg.largeur_image, cfg.qualite_jpeg))
        async with contextlib.aclosing(flux) as flux:
            texte = "".join([m async for m in flux]).strip()
    except Exception as e:
        probleme(f"le modèle n'a pas répondu : {e}")
        return
    if cerveau.derniere_observation:
        ok(f"il a vu : « {cerveau.derniere_observation} »")
    if texte:
        ok(f"réponse en {time.perf_counter() - debut:.1f} s : « {texte} »")
    else:
        probleme("réponse vide du modèle")


async def tester_voix(cfg: Config) -> None:
    titre("Voix (edge-tts) et casque / haut-parleurs")
    synthese = Synthese(cfg.voix, cfg.debit, cfg.volume)
    try:
        pcm = await synthese.synthetiser("Bonjour Seigneur. Si tu m'entends, la voix fonctionne.")
    except Exception as e:
        probleme(f"synthèse vocale impossible : {e}",
                 "edge-tts a besoin d'Internet (serveurs Microsoft). Vérifie aussi le nom de la voix dans config.toml.")
        return
    if pcm.size == 0:
        probleme("synthèse vocale vide", "vérifie le nom de la voix dans config.toml.")
        return
    ok(f"synthèse OK ({pcm.size / 24000:.1f} s d'audio)")
    lecteur = Lecteur(cfg.sortie_audio)
    try:
        lecteur.demarrer()
    except Exception as e:
        probleme(f"impossible d'ouvrir la sortie audio : {e}",
                 "python compagnon.py --peripheriques, puis réglage sortie_audio dans config.toml.")
        return
    sortie = nom_peripherique(lecteur.peripherique, "output")
    print(f"  ... lecture sur « {sortie} » : écoute bien !")
    lecteur.jouer(pcm)
    await lecteur.attendre_fin()
    await asyncio.sleep(0.4)
    lecteur.fermer()
    ok(f"son envoyé sur « {sortie} ». Si tu n'as RIEN entendu : ce n'est pas ton casque -> mets ton casque "
       "en sortie par défaut dans Windows, ou règle sortie_audio (voir --peripheriques).")


async def tester_micro(cfg: Config, cerveau: Cerveau | None) -> None:
    titre("Micro")
    micro = Micro(cfg.micro)
    try:
        micro.demarrer()
    except Exception as e:
        probleme(f"impossible d'ouvrir le micro : {e}",
                 "python compagnon.py --peripheriques, puis réglage micro dans config.toml.")
        return
    entree = nom_peripherique(micro.peripherique, "input")
    print(f"  ... micro utilisé : « {entree} »")
    print("  ... PARLE MAINTENANT pendant 4 secondes (dis par exemple « Salut, tu m'entends ? »)")
    micro.commencer()
    for reste in range(4, 0, -1):
        print(f"      {reste}…", flush=True)
        await asyncio.sleep(1)
    echantillons = micro.arreter()
    micro.fermer()
    niveau = niveau_crete(echantillons)
    if niveau < 0.01:
        probleme(f"le micro « {entree} » n'enregistre que du silence",
                 "Paramètres Windows > Confidentialité et sécurité > Microphone : active « Accès au microphone » "
                 "ET « Autoriser les applications de bureau ». Sinon choisis le bon micro (--peripheriques).")
        return
    ok(f"le micro capte du son (volume max {niveau:.0%})")
    if niveau < 0.05:
        print("     (c'est faible : rapproche le micro ou monte son volume dans Windows)")
    if cerveau is None:
        return
    try:
        texte = await cerveau.transcrire(await asyncio.to_thread(encoder_flac, echantillons, micro.frequence))
    except Exception as e:
        probleme(f"transcription impossible : {e}")
        return
    if texte:
        ok(f"transcription : « {texte} »")
    else:
        probleme("Whisper n'a rien compris", "parle plus fort / plus près du micro.")


def tester_touche(cfg: Config) -> None:
    titre("Touche push-to-talk")
    try:
        genre, nom = analyser_touche(cfg.touche)
    except Exception as e:
        probleme(str(e))
        return
    print(f"  Touche configurée : « {cfg.touche} »")
    print("  ... Pendant 15 secondes, appuie sur ta touche push-to-talk, puis sur d'autres boutons/touches")
    print("      pour voir leur nom. (Ici rien n'est enregistré, on regarde juste ce qui est détecté.)")
    detectee = threading.Event()

    def annoncer(texte: str, reglage: str | None) -> None:
        if reglage and analyser_touche(reglage) == (genre, nom):
            detectee.set()
            print(f"      détecté : {texte}  <- C'EST TA TOUCHE, elle marche !")
        elif reglage:
            print(f"      détecté : {texte}  -> pour l'utiliser : touche = \"{reglage}\"")
        else:
            print(f"      détecté : {texte}")

    try:
        from pynput import keyboard, mouse
    except Exception as e:
        probleme(f"pynput ne fonctionne pas : {e}")
        return

    def clic(_x, _y, bouton, presse):
        if not presse:
            return
        noms = {"x1": "souris:x1", "x2": "souris:x2", "middle": "souris:milieu"}
        reglage = noms.get(bouton.name)
        annoncer(f"bouton de souris « {bouton.name} »", reglage)

    def touche(t):
        if getattr(t, "char", None):
            annoncer(f"touche « {t.char} »", f"clavier:{t.char.lower()}")
        elif getattr(t, "name", None):
            annoncer(f"touche « {t.name} »", f"clavier:{t.name}")
        else:
            annoncer(f"touche inconnue (code {getattr(t, 'vk', '?')})", None)

    souris = mouse.Listener(on_click=clic)
    clavier = keyboard.Listener(on_press=touche)
    souris.start()
    clavier.start()
    try:
        time.sleep(15)
    finally:
        souris.stop()
        clavier.stop()
    if detectee.is_set():
        ok("ta touche push-to-talk est bien détectée")
    else:
        probleme(f"ta touche « {cfg.touche} » n'a pas été détectée",
                 "choisis une des touches affichées ci-dessus et mets-la dans « touche » de config.toml "
                 "(par ex. touche = \"clavier:v\"). Si le logiciel de ta souris réaffecte ses boutons "
                 "latéraux, prends une touche clavier.")


async def diagnostiquer(cfg: Config) -> int:
    from . import VERSION

    print(f"Autodiagnostic du compagnon (moteur {cfg.moteur}, version {VERSION}). Mets ton casque.")
    print(f"Python {sys.version.split()[0]}")
    if cfg.moteur == "gemini":
        image = await asyncio.to_thread(tester_capture, cfg)
        await tester_gemini(cfg, image)
        await tester_micro(cfg, None)
    else:
        cerveau = await tester_groq(cfg)
        image = await asyncio.to_thread(tester_capture, cfg)
        if cerveau is not None:
            await tester_vision(cfg, cerveau, image)
        await tester_voix(cfg)
        await tester_micro(cfg, cerveau)
    await asyncio.to_thread(tester_touche, cfg)
    titre("Résultat")
    if PROBLEMES:
        print(f"  {len(PROBLEMES)} problème(s) à corriger :")
        for p in PROBLEMES:
            print(f"   - {p}")
        print("  Corrige-les (voir les conseils ci-dessus), puis relance python compagnon.py --diagnostic.")
        return 1
    print("  Tout fonctionne ! Lance python compagnon.py --test (ou python compagnon.py avec Minecraft).")
    return 0
