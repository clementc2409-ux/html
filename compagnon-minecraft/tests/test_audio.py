import types
import unittest

from compagnon_ia.audio import Micro


class FauxSoundDevice(types.SimpleNamespace):
    """Imite sounddevice : le micro par défaut refuse de s'ouvrir, le n°3 accepte seulement 48 kHz."""

    def __init__(self):
        super().__init__(ouverts=[])
        self.peripheriques = [
            {"name": "Haut-parleurs", "max_input_channels": 0, "hostapi": 0, "default_samplerate": 48000},
            {"name": "Mixage stéréo (Realtek)", "max_input_channels": 2, "hostapi": 0, "default_samplerate": 48000},
            {"name": "Micro WDM", "max_input_channels": 1, "hostapi": 1, "default_samplerate": 48000},
            {"name": "Micro du casque", "max_input_channels": 1, "hostapi": 0, "default_samplerate": 48000},
        ]

    def query_devices(self, device=None, kind=None):
        if device is None and kind is None:
            return self.peripheriques
        if device is None:
            raise RuntimeError("Error querying device -1")
        return self.peripheriques[device]

    def query_hostapis(self):
        return [{"name": "MME"}, {"name": "Windows WDM-KS"}]

    def InputStream(self, samplerate, device, **_):
        if device is None:
            raise RuntimeError("Error querying device -1")
        if samplerate != 48000:
            raise RuntimeError("Invalid sample rate")
        self.ouverts.append((device, samplerate))
        return types.SimpleNamespace(start=lambda: None, stop=lambda: None, close=lambda: None)


class TestMicro(unittest.TestCase):
    def test_essaie_les_autres_micros_si_le_defaut_refuse(self):
        sd = FauxSoundDevice()
        micro = Micro()
        self.assertEqual(micro._autres_micros(sd), [3])  # ni le mixage stéréo, ni WDM-KS, ni une sortie
        import sys
        sys.modules["sounddevice"], ancien = sd, sys.modules.get("sounddevice")
        try:
            with self.assertLogs("compagnon", level="WARNING"):
                micro.demarrer()
        finally:
            if ancien is None:
                del sys.modules["sounddevice"]
            else:
                sys.modules["sounddevice"] = ancien
        self.assertEqual((micro.peripherique, micro.frequence), (3, 48000))

    def test_aucun_micro(self):
        sd = FauxSoundDevice()
        sd.peripheriques = sd.peripheriques[:1]
        import sys
        sys.modules["sounddevice"], ancien = sd, sys.modules.get("sounddevice")
        try:
            with self.assertRaises(RuntimeError):
                Micro().demarrer()
        finally:
            if ancien is None:
                del sys.modules["sounddevice"]
            else:
                sys.modules["sounddevice"] = ancien


if __name__ == "__main__":
    unittest.main()
