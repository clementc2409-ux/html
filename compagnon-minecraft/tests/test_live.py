"""Moteur Gemini Live testé avec les vrais types du SDK google-genai et une fausse session (sans réseau)."""

import asyncio
import unittest

import numpy as np
from google.genai import types

from compagnon_ia.live import (COUP_D_OEIL, CompagnonLive, PorteSilenceLive, construire_config,
                               construire_consignes)
from tests.faux import FausseCapture, FauxLecteur, FauxMicro, config_test


class FausseSession:
    def __init__(self):
        self.envois = []

    async def send_realtime_input(self, **contenu):
        (cle, valeur), = contenu.items()
        self.envois.append((cle, valeur))


def creer(**reglages):
    c = CompagnonLive(config_test(**reglages), micro=FauxMicro(), lecteur=FauxLecteur(), capture=FausseCapture(),
                      client=object())
    c.micro_actif = True
    c.fichier_capture = None
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
    tache = asyncio.create_task(c._boucle_envoi())
    while not c._file_envoi.empty():
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.01)
    tache.cancel()


class TestConfiguration(unittest.TestCase):
    def test_config_push_to_talk(self):
        cfg = config_test()
        config = construire_config(types, cfg, "consignes")
        self.assertEqual(config.response_modalities, [types.Modality.AUDIO])
        self.assertEqual(config.speech_config.voice_config.prebuilt_voice_config.voice_name, "Algenib")
        self.assertTrue(config.realtime_input_config.automatic_activity_detection.disabled)
        self.assertIsNotNone(config.context_window_compression.sliding_window)
        self.assertTrue(config.proactivity.proactive_audio)
        self.assertEqual(config.media_resolution, types.MediaResolution.MEDIA_RESOLUTION_MEDIUM)

    def test_config_micro_continu_et_minimale(self):
        config = construire_config(types, config_test(micro_continu=True), "c", handle="abc", minimale=True)
        self.assertIsNone(config.realtime_input_config)
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

        self.assertEqual(asyncio.run(scenario()),
                         ["activity_start", ("audio", b"avant"), ("audio", b"pendant"), "activity_end"])

    def test_evenement_envoye_comme_texte_entoure(self):
        from compagnon_ia.journal_jeu import EvenementJeu

        async def scenario():
            c = creer()
            c._sur_evenement(EvenementJeu("mort", "Arthur a été tué par Zombie"))
            await vider_file(c)
            return c._session.envois

        envois = asyncio.run(scenario())
        self.assertEqual([cle for cle, _ in envois], ["activity_start", "text", "activity_end"])
        self.assertIn("vient de mourir", envois[1][1])

    def test_micro_continu_sans_signaux(self):
        async def scenario():
            c = creer(micro_continu=True)
            c._file_envoi.put_nowait(("audio", b"x"))
            c._file_envoi.put_nowait(("texte", "[Écrit] salut", False))
            await vider_file(c)
            return [cle for cle, _ in c._session.envois]

        self.assertEqual(asyncio.run(scenario()), ["audio", "text"])


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


class TestPorte(unittest.TestCase):
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
        self.assertEqual(textes, [("texte", COUP_D_OEIL, True)])


if __name__ == "__main__":
    unittest.main()
