import asyncio
import unittest

import numpy as np

from compagnon_ia.boucle import Compagnon, Demande
from compagnon_ia.voix import Lecteur
from tests.faux import FausseCapture, FausseSynthese, FauxCerveau, FauxLecteur, FauxMicro, config_test


def creer(cerveau=None, lecteur=None, **reglages):
    return Compagnon(config_test(**reglages), cerveau=cerveau or FauxCerveau(), synthese=FausseSynthese(),
                     lecteur=lecteur or FauxLecteur(), micro=FauxMicro(), capture=FausseCapture())


async def attendre_tour(c):
    while c._tour is None or not c._tour.done():
        await asyncio.sleep(0.005)


class TestPushToTalk(unittest.TestCase):
    def test_voix_transcrite_capture_et_reponse_phrase_par_phrase(self):
        async def scenario():
            c = creer(FauxCerveau(["Oui, je le vois. Recule doucement !"]))
            c._appui()
            self.assertTrue(c.micro.enregistre)
            c._relache()
            await c._tache_voix
            await attendre_tour(c)
            return c

        c = asyncio.run(scenario())
        self.assertEqual(c.cerveau.entrees, ["[Voix] Tu vois ce creeper ?"])
        self.assertTrue(c.cerveau.images[0].startswith("data:image/jpeg;base64,"))
        self.assertEqual(c.synthese.textes, ["Oui, je le vois.", "Recule doucement !"])
        self.assertEqual(c.cerveau.historique,
                         [("[Voix] Tu vois ce creeper ?", "Oui, je le vois. Recule doucement !")])

    def test_appui_interrompt_la_parole(self):
        async def scenario():
            c = creer(FauxCerveau(["Une très longue histoire qui ne finit jamais vraiment, " * 3], delai=0.02),
                      FauxLecteur(duree=1.0))
            await c.soumettre(Demande("voix", "Raconte"))
            await asyncio.sleep(0.15)  # il a commencé à répondre
            c._appui()                 # on appuie : il doit se taire tout de suite
            await asyncio.sleep(0.02)
            return c

        c = asyncio.run(scenario())
        self.assertGreaterEqual(c.lecteur.interruptions, 1)
        self.assertTrue(c._tour.cancelled())
        self.assertTrue(c.cerveau.historique[0][1].endswith("[…interrompu]"))

    def test_appui_trop_court_ignore(self):
        async def scenario():
            c = creer()
            c.micro.arreter = lambda: np.zeros(1000, dtype=np.int16)
            c._appui()
            c._relache()
            await c._tache_voix
            return c

        c = asyncio.run(scenario())
        self.assertEqual(c.cerveau.entrees, [])


class TestLecteur(unittest.TestCase):
    def test_lecture_puis_interruption(self):
        lecteur = Lecteur()
        lecteur._flux = object()  # comme si la sortie audio était ouverte
        lecteur.jouer(np.full(100, 0.5, dtype=np.float32))
        lecteur.jouer(np.full(100, 0.25, dtype=np.float32))
        sortie = np.zeros((150, 1), dtype=np.float32)
        lecteur._rappel(sortie, 150, None, None)
        self.assertTrue(np.all(sortie[:100, 0] == 0.5) and np.all(sortie[100:, 0] == 0.25))
        self.assertTrue(lecteur.parle)
        lecteur.interrompre()
        self.assertFalse(lecteur.parle)
        lecteur._rappel(sortie, 150, None, None)
        self.assertTrue(np.all(sortie == 0))


if __name__ == "__main__":
    unittest.main()
