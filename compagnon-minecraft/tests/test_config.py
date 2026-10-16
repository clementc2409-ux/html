import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from compagnon_ia.config import RACINE, ErreurConfig, charger_config, chemin_log, developper_chemin


class TestConfig(unittest.TestCase):
    def test_config_livree_valide(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "cle-env"}):
            cfg = charger_config(RACINE / "config.toml")
        self.assertEqual(cfg.cle_api, "cle-env")
        self.assertEqual(cfg.touche, "clavier:v")
        self.assertEqual(cfg.intervalle_capture, 20.0)
        self.assertTrue(cfg.commentaires_spontanes)

    def test_erreur_de_type_claire(self):
        with tempfile.TemporaryDirectory() as dossier:
            fichier = Path(dossier) / "config.toml"
            fichier.write_text('[regard]\nintervalle_capture = "vingt"\n', encoding="utf-8")
            with self.assertRaises(ErreurConfig) as ctx:
                charger_config(fichier)
            self.assertIn("intervalle_capture", str(ctx.exception))

    def test_ancienne_config_trop_courte_relevee(self):
        with tempfile.TemporaryDirectory() as dossier:
            fichier = Path(dossier) / "config.toml"
            fichier.write_text('[groq]\nmax_jetons_reponse = 160\n', encoding="utf-8")
            self.assertEqual(charger_config(fichier).max_jetons_reponse, 250)

    def test_chemin_windows(self):
        with mock.patch.dict(os.environ, {"APPDATA": "/tmp/roaming"}):
            self.assertEqual(developper_chemin(r"%APPDATA%/.minecraft/logs/latest.log"),
                             Path("/tmp/roaming/.minecraft/logs/latest.log"))

    def test_chemin_log_sans_appdata(self):
        cfg = charger_config(RACINE / "config.toml")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(chemin_log(cfg).name, "latest.log")
            self.assertNotIn("%", str(chemin_log(cfg)))


if __name__ == "__main__":
    unittest.main()
