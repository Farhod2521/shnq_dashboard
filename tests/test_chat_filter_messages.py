import unittest

from app.services.chat_service import _no_answer_with_filter_hint


class ChatFilterMessageTests(unittest.TestCase):
    def test_filter_active_message(self) -> None:
        message = _no_answer_with_filter_hint(True)
        self.assertIn("Tanlangan filter", message)
        self.assertIn("kengaytirib", message)

    def test_filter_inactive_with_fallback_message(self) -> None:
        message = _no_answer_with_filter_hint(False, fallback="Mos band topilmadi")
        self.assertIn("Mos band topilmadi.", message)
        self.assertIn("chat filterlaridan foydalaning", message)

    def test_filter_inactive_default_message(self) -> None:
        message = _no_answer_with_filter_hint(False)
        self.assertIn("ma'lumot topolmadim", message)
        self.assertIn("chat filterlaridan foydalaning", message)


if __name__ == "__main__":
    unittest.main()
