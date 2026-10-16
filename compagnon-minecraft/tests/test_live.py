"""Moteur Gemini Live testé avec les vrais types du SDK google-genai et une fausse session (sans réseau)."""

import asyncio
import unittest

import numpy as np
from google.genai import types

from compagnon_ia.carnet import Carnet
from compagnon_ia.live import (COUP_D_OEIL, CompagnonLive, PorteSilenceLive, construire_config,
                               construire_consignes, est_silence_parle)
from compagnon_ia.souvenirs import Souvenirs
from tests.faux import FausseCapture, FauxLecteur, FauxMicro, config_test


class FausseSession:
    def __init__(self):
        self.envois = []
        self.reponses_outils = []

    async def send_realtime_input(self, **contenu):
        (cle, valeur), = contenu.items()
        self.envois.append((cle, valeur))

    async def send_tool_response(self, function_responses):
        self.reponses_outils.extend(function_responses)


def creer(**reglages):
    c = CompagnonLive(config_test(**reglages), micro=FauxMicro(), lecteur=FauxLecteur(), capture=FausseCapture(),
                      client=object(), souvenirs=Souvenirs(None), carnet=Carnet(None))
    c.micro_actif = True
    c.fichier_capture = None
    c.delai_image = 0
    c.delai_double_image = 0
    c._session = FausseSession()
    return c


def message(audio=b"", texte_lui=None, texte_moi=None, fini=False, interrompu=False, poignee=None):
    contenu = types.LiveServerContent(
        model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(data=audio, mime_type="audio/pcm"))])
        if audio else None,
        output_transcription=types.Transcription(text=texte_lui) if texte_lui else None,
        input_transcription=types.Transcription(text=texte_moi) if texte_moi else None,
        turn_complete=fini or None, interrupted=interrompu or None)
    reprise = types.LiveServerSessionResumptionUpdate(new_handle=poignee, resumable=True) if poignee else None
    return types.LiveServerMessage(server_content=contenu, session_resumption_update=reprise)


SON = (np.ones(2400) * 1000).astype(np.int16).tobytes()  # 0,1 s de son à 24 kHz


async def vider_file(c):
    """Laisse la tâche d'envoi tout traiter (captures fraîches comprises), puis l'arrête."""
    tache = asyncio.create_task(c._boucle_envoi())
    calme, dernier = 0, -1
    while calme < 15:  # 15 × 20 ms sans nouvel envoi, file vide
        await asyncio.sleep(0.02)
        n = len(c._session.envois)
        calme, dernier = (calme + 1, n) if c._file_envoi.empty() and n == dernier else (0, n)
    for travail in c._taches:
        await travail
    tache.cancel()


class TestConfiguration(unittest.TestCase):
    def test_config_push_to_talk(self):
        cfg = config_test()
        config = construire_config(types, cfg, "consignes")
        self.assertEqual(config.response_modalities, [types.Modality.AUDIO])
        self.assertEqual(config.speech_config.voice_config.prebuilt_voice_config.voice_name, "Algenib")
        self.assertTrue(config.realtime_input_config.automatic_activity_detection.disabled)
        self.assertEqual(config.realtime_input_config.turn_coverage, types.TurnCoverage.TURN_INCLUDES_ALL_INPUT)
        self.assertIsNotNone(config.context_window_compression.sliding_window)
        self.assertTrue(config.proactivity.proactive_audio)
        self.assertIsNone(config.media_resolution)  # "auto" : réglage laissé à Google
        haute = construire_config(types, config_test(resolution_video="haute"), "c")
        self.assertEqual(haute.media_resolution, types.MediaResolution.MEDIA_RESOLUTION_HIGH)

    def test_config_micro_continu_et_minimale(self):
        config = construire_config(types, config_test(micro_continu=True), "c", handle="abc", minimale=True)
        self.assertIsNone(config.realtime_input_config.automatic_activity_detection)
        self.assertEqual(config.realtime_input_config.turn_coverage, types.TurnCoverage.TURN_INCLUDES_ALL_INPUT)
        self.assertIsNone(config.proactivity)
        self.assertIsNone(config.media_resolution)
        self.assertEqual(config.session_resumption.handle, "abc")

    def test_consignes(self):
        texte = construire_consignes(config_test(), "Tu es un vieux routier.", "Le royaume de Valombre.")
        self.assertIn("vieux routier", texte)
        self.assertIn("Arthur", texte)
        self.assertIn("Valombre", texte)
        self.assertIn("rien à signaler", texte)


class TestEnvoi(unittest.TestCase):
    def test_push_to_talk_dans_le_bon_ordre(self):
        async def scenario():
            c = creer()
            c._file_envoi.put_nowait(("audio", b"avant"))  # pré-enregistrement
            c._appui()
            c._file_envoi.put_nowait(("audio", b"pendant"))
            c._relache()
            c._file_envoi.put_nowait(("audio", b"apres"))
            await vider_file(c)
            return [cle if cle != "audio" else ("audio", v.data) for cle, v in c._session.envois]

        envois = asyncio.run(scenario())
        self.assertIn("video", envois)  # capture fraîche au moment où tu parles
        self.assertEqual([e for e in envois if e != "video"],
                         ["activity_start", ("audio", b"avant"), ("audio", b"pendant"), "activity_end"])
        self.assertLess(envois.index("activity_start"), envois.index("video"))

    def test_evenement_envoye_comme_texte_seul(self):
        # Pas de activity_start/end autour d'un texte : Google répond 1007 (vérifié le 16/10/2026).
        from compagnon_ia.journal_jeu import EvenementJeu

        async def scenario():
            c = creer()
            c._sur_evenement(EvenementJeu("mort", "Arthur a été tué par Zombie"))
            await vider_file(c)
            return c._session.envois

        envois = asyncio.run(scenario())
        self.assertEqual([cle for cle, _ in envois], ["video", "video", "text"])  # capture envoyée deux fois
        self.assertEqual(envois[0][1].mime_type, "image/jpeg")
        self.assertIn("vient de mourir", envois[2][1])

    def test_texte_pendant_que_tu_parles_attend_la_fin(self):
        async def scenario():
            c = creer()
            c._appui()
            c._file_envoi.put_nowait(("texte", "[Chat] coucou", False))
            c._file_envoi.put_nowait(("texte", COUP_D_OEIL, True))  # un coup d'œil, lui, est abandonné
            c._relache()
            await vider_file(c)
            return [cle for cle, _ in c._session.envois]

        envois = [e for e in asyncio.run(scenario()) if e != "video"]
        self.assertEqual(envois, ["activity_start", "activity_end", "text"])

    def test_micro_continu_sans_signaux(self):
        async def scenario():
            c = creer(micro_continu=True)
            c._file_envoi.put_nowait(("audio", b"x"))
            c._file_envoi.put_nowait(("texte", "[Écrit] salut", False))
            await vider_file(c)
            return [cle for cle, _ in c._session.envois]

        self.assertEqual(asyncio.run(scenario()), ["audio", "video", "video", "text"])

    def test_alerte_envoyee_sans_attendre(self):
        async def scenario():
            c = creer()
            c._file_envoi.put_nowait(("texte", "[Alerte] Creeper à 3 blocs derrière lui !", False, True))
            await vider_file(c)
            return [cle for cle, _ in c._session.envois]

        self.assertEqual(asyncio.run(scenario()), ["text"])


class TestReception(unittest.TestCase):
    def test_voix_jouee_et_transcriptions(self):
        async def scenario():
            c = creer()
            with self.assertLogs("compagnon", level="INFO") as journaux:
                c._traiter(message(texte_moi="Tu vois le creeper ?"))
                c._traiter(message(audio=SON, texte_lui="Oui, recule !"))
                c._traiter(message(fini=True, poignee="ticket-1"))
            return c, journaux.output

        c, journaux = asyncio.run(scenario())
        self.assertEqual(len(c.lecteur.joue), 1)
        self.assertEqual(c._handle, "ticket-1")
        self.assertTrue(any("[Moi]    Tu vois le creeper ?" in l for l in journaux))
        self.assertTrue(any("[Lui]    Oui, recule !" in l for l in journaux))

    def test_interruption_coupe_le_son(self):
        async def scenario():
            c = creer()
            c._traiter(message(audio=SON, texte_lui="Bon, alors"))
            c._traiter(message(interrompu=True))
            return c

        c = asyncio.run(scenario())
        self.assertEqual(c.lecteur.interruptions, 1)
        self.assertFalse(c._modele_actif)

    def test_son_ignore_pendant_que_tu_parles(self):
        async def scenario():
            c = creer()
            c._appui()
            c._traiter(message(audio=SON))
            return c

        self.assertEqual(asyncio.run(scenario()).lecteur.joue, [])

    def test_coup_d_oeil_silencieux_jamais_entendu(self):
        async def scenario():
            c = creer()
            c._porte = PorteSilenceLive()
            c._traiter(message(audio=SON))                     # son en attente…
            c._traiter(message(audio=SON, texte_lui="Rien à signaler."))
            c._traiter(message(fini=True))
            return c

        self.assertEqual(asyncio.run(scenario()).lecteur.joue, [])

    def test_coup_d_oeil_interessant_joue_en_entier(self):
        async def scenario():
            c = creer()
            c._porte = PorteSilenceLive()
            c._traiter(message(audio=SON))
            c._traiter(message(audio=SON, texte_lui="Joli pont, Seigneur !"))
            c._traiter(message(audio=SON, fini=True))
            return c

        self.assertEqual(len(asyncio.run(scenario()).lecteur.joue), 3)


class TestSouvenirs(unittest.TestCase):
    def test_evenements_et_echanges_memorises(self):
        from compagnon_ia.journal_jeu import EvenementJeu

        async def scenario():
            c = creer()
            c._sur_evenement(EvenementJeu("mort", "Arthur s'est noyé"))
            c._traiter(message(texte_moi="Tu te souviens ?"))
            c._traiter(message(audio=SON, texte_lui="Comment oublier, mon grand !", fini=True))
            return c.souvenirs

        souvenirs = asyncio.run(scenario())
        self.assertEqual([e["genre"] for e in souvenirs.elements], ["mort", "echange"])
        resume = souvenirs.resume()
        self.assertIn("mort : Arthur s'est noyé", resume)
        self.assertIn("« Tu te souviens ? »", resume)

    def test_fichier_relu_au_demarrage(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "souvenirs.json"
            Souvenirs(chemin).ajouter("progres", "Diamants !")
            relu = Souvenirs(chemin)
            self.assertEqual(relu.elements[0]["texte"], "Diamants !")
            consignes = construire_consignes(config_test(), "perso", "", relu.resume())
            self.assertIn("progrès : Diamants !", consignes)


class TestCourseCoupDOeil(unittest.TestCase):
    def test_tu_parles_juste_apres_un_coup_d_oeil(self):
        # Vu en vrai : coup d'œil puis question 1 s après -> il a prononcé « SILENCE ».
        async def scenario():
            c = creer()
            c._porte = PorteSilenceLive()          # coup d'œil envoyé, réponse pas encore arrivée
            c._phrase_tapee("Tu te souviens d'hier ?")
            c._traiter(message(audio=SON, texte_lui="SILENCE"))
            c._traiter(message(fini=True))
            return c

        c = asyncio.run(scenario())
        self.assertEqual(c.lecteur.joue, [])
        self.assertEqual(c.souvenirs.elements, [])

    def test_vraie_reponse_apres_coup_d_oeil_jouee_et_pas_spontanee(self):
        async def scenario():
            c = creer()
            c._porte = PorteSilenceLive()
            c._phrase_tapee("On fait quoi ?")
            with self.assertLogs("compagnon", level="INFO") as journaux:
                c._traiter(message(audio=SON, texte_lui="Le port, pardi !", fini=True))
            return c, journaux.output

        c, journaux = asyncio.run(scenario())
        self.assertEqual(len(c.lecteur.joue), 1)
        self.assertFalse(any("spontané" in l for l in journaux))
        self.assertEqual(c.souvenirs.elements[0]["genre"], "echange")

    def test_silence_parle(self):
        for texte in ("SILENCE", "Silence.", "Rien à signaler.", "rien de neuf ici", "<no speech>{pause}"):
            self.assertTrue(est_silence_parle(texte), texte)
        for texte in ("Silence, on tourne ! Le port avance bien, Seigneur.", "Rien ne vaut un bon château", ""):
            self.assertFalse(est_silence_parle(texte), texte)


class TestPorte(unittest.TestCase):
    def test_marqueur_technique_coupe(self):
        # Vu en vrai : la transcription « <no speech>{pause} » ne doit être ni jouée ni affichée.
        async def scenario():
            c = creer()
            c._porte = PorteSilenceLive()
            c._traiter(message(audio=SON, texte_lui="<no speech>"))
            c._traiter(message(texte_lui="{pause}", fini=True))
            return c

        c = asyncio.run(scenario())
        self.assertEqual(c.lecteur.joue, [])
        self.assertEqual(c.souvenirs.elements, [])

    def test_decisions(self):
        for texte, attendu in (("Silence.", True), ("Rien de neuf", True), ("Ah, un village !", False),
                               ("Rien ne vaut un bon château", False)):
            p = PorteSilenceLive()
            p.ajouter(texte)
            p.terminer()
            self.assertEqual(p.etat, attendu, texte)
        p = PorteSilenceLive()
        p.ajouter("Rien")
        self.assertIsNone(p.etat)  # on attend la suite


class TestRegard(unittest.TestCase):
    def test_coup_d_oeil_seulement_si_l_ecran_a_change(self):
        async def scenario():
            c = creer(cooldown_spontane=0)
            c._fin_parole = float("-inf")
            c._derniere_empreinte_video = np.zeros((36, 64, 3), dtype=np.float32)
            tache = asyncio.create_task(c._boucle_regard())
            await asyncio.sleep(3.2)        # 1er passage : coup d'œil envoyé
            c._dernier_spontane = float("-inf")
            await asyncio.sleep(3.1)        # 2e passage : écran identique -> rien
            tache.cancel()
            return [e for e in list(c._file_envoi._queue) if e[0] == "texte"]

        textes = asyncio.run(scenario())
        self.assertEqual(len(textes), 1)
        self.assertTrue(textes[0][1].startswith("[Coup d'œil]") and textes[0][2])
        self.assertIn("aucun échange depuis le lancement", textes[0][1])


if __name__ == "__main__":
    unittest.main()
