"""Compagnon IA vocal pour Minecraft — point d'entrée.

    python compagnon.py                 lance le compagnon
    python compagnon.py --test          mode test (images d'exemple au lieu de vraies captures)
    python compagnon.py --modeles       liste les modèles Groq disponibles avec ta clé
    python compagnon.py --peripheriques liste les micros et sorties audio
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

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
    logging.basicConfig(level=logging.DEBUG if verbeux else logging.INFO,
                        format="%(asctime)s  %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Compagnon IA vocal pour Minecraft (Groq).")
    parser.add_argument("--test", action="store_true",
                        help="images d'exemple au lieu de vraies captures, faux journal du jeu")
    parser.add_argument("--config", type=Path, help="autre fichier de configuration que config.toml")
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
