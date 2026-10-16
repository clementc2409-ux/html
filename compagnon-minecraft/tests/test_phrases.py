import unittest

from compagnon_ia.phrases import (DecoupeurPhrases, FiltreReflexion, PorteSilence, est_hallucination,
                                  est_silence, nettoyer_pour_voix)


def decouper(morceaux, **options):
    d = DecoupeurPhrases(**options)
    sortie = []
    for m in morceaux:
        sortie += d.ajouter(m)
    return sortie + d.terminer()


class TestDecoupeur(unittest.TestCase):
    def test_phrases_rendues_des_qu_elles_sont_finies(self):
        d = DecoupeurPhrases()
        self.assertEqual(d.ajouter("Ah, te voilà"), [])
        self.assertEqual(d.ajouter(" enfin ! Tu as vu"), ["Ah, te voilà enfin !"])
        self.assertEqual(d.ajouter(" ce creeper ?"), [])  # pas encore d'espace après le « ? »
        self.assertEqual(d.terminer(), ["Tu as vu ce creeper ?"])

    def test_nombres_et_points_de_suspension(self):
        self.assertEqual(decouper(["Il te reste 2.5 cœurs... Fais gaffe."]),
                         ["Il te reste 2.5 cœurs...", "Fais gaffe."])

    def test_morceaux_caractere_par_caractere(self):
        texte = "Bien joué. On rentre au château ? Moi je dis oui !"
        self.assertEqual(decouper(list(texte)), ["Bien joué.", "On rentre au château ?", "Moi je dis oui !"])

    def test_phrase_trop_longue_coupee_sur_une_virgule(self):
        longue = "on pose une pierre, puis une autre, " * 6 + "et voilà"
        phrases = decouper([longue], longueur_max=80)
        self.assertGreater(len(phrases), 1)
        self.assertEqual(" ".join(phrases).replace("  ", " "), longue)


class TestFiltres(unittest.TestCase):
    def test_reflexion_retiree_meme_coupee_en_morceaux(self):
        f = FiltreReflexion()
        morceaux = ["<thi", "nk>je réfléchis", " encore</th", "ink>Salut", " toi"]
        self.assertEqual("".join(f.filtrer(m) for m in morceaux) + f.terminer(), "Salut toi")

    def test_texte_normal_intact(self):
        f = FiltreReflexion()
        self.assertEqual(f.filtrer("3 < 4, bien sûr") + f.terminer(), "3 < 4, bien sûr")

    def test_silence(self):
        self.assertTrue(est_silence("SILENCE"))
        self.assertTrue(est_silence(" silence. "))
        self.assertFalse(est_silence("Silence, on tourne !"))

    def test_porte_silence(self):
        p = PorteSilence()
        self.assertEqual(p.ajouter("SIL"), "")
        self.assertIsNone(p.etat)
        self.assertEqual(p.ajouter("ENCE"), "")
        self.assertTrue(p.etat)

        p = PorteSilence()
        self.assertEqual(p.ajouter("Si"), "")
        self.assertEqual(p.ajouter(" tu"), "Si tu")
        self.assertFalse(p.etat)
        self.assertEqual(p.ajouter(" veux"), " veux")

        p = PorteSilence()
        p.ajouter("")
        p.terminer()
        self.assertTrue(p.etat)

    def test_nettoyage_voix(self):
        self.assertEqual(nettoyer_pour_voix("*il rit* Bien joué 😄 **mon seigneur**"), "Bien joué mon seigneur")
        self.assertEqual(nettoyer_pour_voix("..."), "")

    def test_hallucinations_whisper(self):
        self.assertTrue(est_hallucination("Sous-titres réalisés par la communauté d'Amara.org"))
        self.assertTrue(est_hallucination(" . "))
        self.assertFalse(est_hallucination("Tu vois le village là-bas ?"))


if __name__ == "__main__":
    unittest.main()
