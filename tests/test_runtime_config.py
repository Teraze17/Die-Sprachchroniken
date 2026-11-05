import unittest

from runtime_config import session_duration_seconds


class SessionConfigTests(unittest.TestCase):
    def test_disabled_by_default(self):
        self.assertEqual(session_duration_seconds("0"), 0)

    def test_four_hours(self):
        self.assertEqual(session_duration_seconds("4"), 14400)

    def test_fractional_hour(self):
        self.assertEqual(session_duration_seconds("0.5"), 1800)

    def test_invalid_values(self):
        for value in ("-1", "25", "nan", "inf", "abc"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                session_duration_seconds(value)


if __name__ == "__main__":
    unittest.main()
