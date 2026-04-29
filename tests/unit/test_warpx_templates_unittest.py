import unittest


class WarpXTemplatesSmokeTest(unittest.TestCase):
    def test_smoke(self) -> None:
        # Minimal smoke test to ensure unittest discovery finds at least one test.
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
