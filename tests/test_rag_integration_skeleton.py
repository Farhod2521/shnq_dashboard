import os
import unittest


class RagIntegrationSkeletonTests(unittest.TestCase):
    def test_answer_message_shape(self) -> None:
        if os.getenv("RUN_RAG_INTEGRATION", "0") != "1":
            self.skipTest("Set RUN_RAG_INTEGRATION=1 to run DB-backed integration tests.")

        from app.db.session import SessionLocal
        from app.services.chat_service import answer_message

        db = SessionLocal()
        try:
            result = answer_message(db, "SHNQ 2.01.05-24 bo'yicha 3.4 band nima deydi?")
        finally:
            db.close()

        self.assertIsInstance(result, dict)
        self.assertIn("answer", result)
        self.assertIn("sources", result)
        self.assertIn("meta", result)
        self.assertIsInstance(result.get("sources"), list)
        self.assertIsInstance(result.get("meta"), dict)


if __name__ == "__main__":
    unittest.main()
