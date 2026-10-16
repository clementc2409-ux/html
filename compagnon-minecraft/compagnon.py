"""Compagnon IA vocal pour Minecraft — point d'entrée.

    python compagnon.py                 lance le compagnon
    python compagnon.py --test          mode test (images d'exemple au lieu de vraies captures)
    python compagnon.py --simuler mort  ajoute une fausse mort au faux journal du mode test
                                        (aussi : progres, chat "ton message")
    python compagnon.py --diagnostic    teste chaque maillon (Groq, voix, micro, touche) et dit quoi corriger
    python compagnon.py --modeles       liste les modèles Groq disponibles avec ta clé
    python compagnon.py --peripheriques liste les micros et sorties audio
"""

from __future__ import annotations

import os

# À faire AVANT d'importer numpy : par défaut, sa bibliothèque de calcul (OpenBLAS) réserve un gros bloc de
# mémoire par cœur de processeur. Avec Minecraft ouvert, Windows peut refuser et tout s'arrête avec
# « Memory allocation still failed after 10 retries, giving up ». Un seul cœur suffit largement ici.
for _variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "1")

import argparse  # noqa: E402
import asyncio  # noqa: E402
import atexit  # noqa: E402
import logging  # noqa: E402
import logging.handlers  # noqa: E402
import queue  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

if sys.version_info < (3, 11):
    sys.exit("Python 3.11 ou plus récent est nécessaire (tu as " + sys.version.split()[0] + ").")

from compagnon_ia.config import ErreurConfig, charger_config  # noqa: E402

log = logging.getLogger("compagnon")


def configurer_logs(verbeux: bool) -> None:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    # Les messages passent par un thread dédié : si la console Windows se fige (clic dans la fenêtre =
    # mode « Sélectionner »), le compagnon continue d'écouter et de parler au lieu de se bloquer.
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    file_messages: queue.SimpleQueue = queue.SimpleQueue()
    ecrivain = logging.handlers.QueueListener(file_messages, console)
    ecrivain.start()
    atexit.register(ecrivain.stop)
    vers_la_file = logging.handlers.QueueHandler(file_messages)
    vers_la_file.setFormatter(logging.Formatter("%(message)s"))  # le format final est appliqué par « console »
    logging.basicConfig(level=logging.DEBUG if verbeux else logging.INFO, handlers=[vers_la_file])
    # Les bibliothèques réseau sont bavardes : on ne garde que leurs avertissements.
    for nom in ("httpx", "httpcore", "groq", "asyncio", "PIL"):
        logging.getLogger(nom).setLevel(logging.WARNING)


async def lister_modeles(cfg) -> None:
    from compagnon_ia.budget import Budget
    from compagnon_ia.cerveau import Cerveau

    cerveau = Cerveau(cfg, "", Budget(0, 0))
    modeles = await cerveau.lister_modeles()
    print("Modèles disponibles avec ta clé Groq :")
    for m in modeles:
        marque = []
        if m == cfg.modele_transcription:
            marque.append("<- transcription configurée")
        if m == cfg.modele_vision:
            marque.append("<- vision configurée")
        print(f"  {m}  {' '.join(marque)}")
    print("\nTranscription : prends un modèle « whisper-… ». Vision : vérifie sur "
          "https://console.groq.com/docs/vision quels modèles acceptent les images.")


def lister_peripheriques() -> None:
    import sounddevice as sd

    print(sd.query_devices())
    print("\n> = entrée par défaut, < = sortie par défaut. Mets le numéro (ou une partie du nom) "
          "dans « micro » ou « sortie_audio » de config.toml.")


def simuler(cfg, genre: str, texte: str) -> None:
    from compagnon_ia.journal_jeu import PSEUDO_TEST, fichier_log_test, ligne_simulee

    chemin = fichier_log_test()
    ligne = ligne_simulee(genre, cfg.pseudo or PSEUDO_TEST, texte, cfg.mot_cle_chat)
    with open(chemin, "a", encoding="utf-8") as fichier:
        fichier.write(ligne + "\n")
    print(f"Ajouté à {chemin} :\n  {ligne}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compagnon IA vocal pour Minecraft (Groq).")
    parser.add_argument("--test", action="store_true",
                        help="images d'exemple au lieu de vraies captures, faux journal du jeu")
    parser.add_argument("--config", type=Path, help="autre fichier de configuration que config.toml")
    parser.add_argument("--simuler", choices=("mort", "progres", "chat"),
                        help="ajoute une fausse ligne au faux journal du mode test (à lancer dans une 2e console)")
    parser.add_argument("texte", nargs="*", help="avec --simuler chat : le message à écrire")
    parser.add_argument("--diagnostic", action="store_true",
                        help="teste la clé Groq, le modèle, la voix, le micro et la touche, et dit quoi corriger")
    parser.add_argument("--modeles", action="store_true", help="liste les modèles Groq disponibles")
    parser.add_argument("--peripheriques", action="store_true", help="liste les micros et sorties audio")
    parser.add_argument("--verbeux", action="store_true", help="affiche plus de détails")
    args = parser.parse_args()
    configurer_logs(args.verbeux)

    if args.peripheriques:
        lister_peripheriques()
        return 0

    try:
        cfg = charger_config(args.config)
    except ErreurConfig as e:
        log.error("%s", e)
        return 1
    if args.simuler:
        simuler(cfg, args.simuler, " ".join(args.texte))
        return 0
    if args.diagnostic:
        from compagnon_ia.diagnostic import diagnostiquer

        try:
            return asyncio.run(diagnostiquer(cfg))
        except KeyboardInterrupt:
            return 1
    if not cfg.cle_api:
        log.error("Clé API Groq manquante. Définis la variable d'environnement GROQ_API_KEY "
                  "(voir README) ou remplis cle_api dans config.toml.")
        return 1

    from compagnon_ia.cerveau import ErreurGroq

    try:
        if args.modeles:
            asyncio.run(lister_modeles(cfg))
            return 0
        from compagnon_ia.boucle import Compagnon

        asyncio.run(Compagnon(cfg, mode_test=args.test).tourner())
    except KeyboardInterrupt:
        log.info("À plus tard, Seigneur !")
    except (ErreurConfig, ErreurGroq) as e:
        log.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
