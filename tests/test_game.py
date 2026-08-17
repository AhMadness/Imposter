import unittest
from unittest.mock import patch

import main


class GameLogicTests(unittest.TestCase):
    def setUp(self):
        self.category = main.Category(
            id="animals",
            name="Animals",
            name_ar="حيوانات",
            img="",
            words=[
                {
                    "word": "Lion",
                    "hint": "Wild",
                    "word_ar": "أسد",
                    "hint_ar": "بري",
                }
            ],
        )

    def test_category_builder_applies_language_fallbacks(self):
        categories = main.build_categories(
            {"categories": [{"id": "places", "words": []}]}
        )

        self.assertEqual("places", categories[0].name)
        self.assertEqual("places", categories[0].name_ar)

    @patch("main.random.sample", return_value=["Mona"])
    def test_assignment_creates_requested_imposter_count(self, _sample):
        state = main.assign_players(["Mona", "Ali", "Sara"], self.category, 1)

        self.assertEqual(1, sum(player.is_imposter for player in state.assignments))
        self.assertEqual(3, len(state.alive))
        self.assertEqual("Lion", state.word_en)
        self.assertEqual("أسد", state.word_ar)

    def test_assignment_rejects_invalid_player_count(self):
        with self.assertRaises(ValueError):
            main.assign_players(["Mona", "Ali"], self.category, 1)

    def test_winner_detection(self):
        state = main.assign_players(["Mona", "Ali", "Sara"], self.category, 1)
        imposter = next(player.name for player in state.assignments if player.is_imposter)
        state.alive[imposter] = False

        self.assertEqual("CREW", main.check_winner(state))

    def test_qr_payload_keeps_role_private(self):
        state = main.assign_players(["Mona", "Ali", "Sara"], self.category, 1)

        crew_payload = main.build_qr_payload(state, "Ali", False, False, main.Lang.EN)
        imposter_payload = main.build_qr_payload(state, "Mona", True, True, main.Lang.EN)

        self.assertIn("WORD: Lion", crew_payload)
        self.assertIn("IMPOSTER", imposter_payload)
        self.assertIn("HINT: Wild", imposter_payload)


if __name__ == "__main__":
    unittest.main()
