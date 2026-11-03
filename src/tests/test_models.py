import unittest
from unittest.mock import patch

from hyperflux.core.engine import HyperFluxEngine
from hyperflux.core.models import MODELS, reply_budget, uses_thinking


class _Stream:
    status_code = 200
    encoding = "utf-8"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self, chunk_size, decode_unicode):
        yield 'data: {"token": "Done.", "finish_reason": "stop"}'


class ModelTierTests(unittest.TestCase):
    def _payload(self, model_id, question="Prove that the square root of 2 is irrational.", think=True):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        engine.model_id = model_id
        engine.thinking_enabled = think
        with patch("hyperflux.core.kobold.requests.post", return_value=_Stream()) as post:
            engine.query_local_llm(question, quiet=True)
        return post.call_args.kwargs["json"]

    def test_each_model_has_its_own_instructions(self):
        prompts = {key: self._payload(key)["prompt"] for key in MODELS}
        self.assertIn("You are Flash 1", prompts["flash"])
        self.assertIn("You are Apex 1", prompts["apex"])
        self.assertIn("You are Horizon 1", prompts["horizon"])
        self.assertNotIn("You are Apex 1", prompts["flash"])
        self.assertIn("The active model is HyperFlux Horizon 1", prompts["horizon"])
        for prompt in prompts.values():
            self.assertNotIn("Gen 1", prompt)
            self.assertIn("not in underlying intelligence", prompt)

    def test_flash_never_thinks_and_stays_short(self):
        payload = self._payload("flash", think=True)
        self.assertNotIn("<|think|>", payload["prompt"])
        self.assertLessEqual(payload["max_length"], MODELS["flash"]["max_length"])

    def test_horizon_always_thinks_deeply_with_more_room(self):
        payload = self._payload("horizon", think=False)  # even with Think switched off
        self.assertIn("<|think|>", payload["prompt"])
        self.assertIn("Think deeply and systematically", payload["prompt"])
        self.assertGreaterEqual(payload["max_length"], MODELS["horizon"]["max_length"])

    def test_apex_follows_the_think_toggle(self):
        self.assertIn("<|think|>", self._payload("apex", think=True)["prompt"])
        self.assertNotIn("<|think|>", self._payload("apex", think=False)["prompt"])

    def test_greetings_skip_thinking_on_every_model(self):
        for key in MODELS:
            self.assertFalse(uses_thinking(key, True, exempt_message=True))

    def test_reply_budget_always_leaves_room_for_the_prompt(self):
        self.assertEqual(reply_budget("flash", 4096, 16384), 1536)
        self.assertEqual(reply_budget("apex", 4096, 16384), 4096)
        self.assertEqual(reply_budget("horizon", 4096, 16384), 6144)
        self.assertEqual(reply_budget("horizon", 4096, 4096), 3072)  # small context: capped

    def test_model_and_think_commands(self):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        self.assertIn("Apex 1", engine.handle_runtime_command("/model"))
        self.assertIn("Horizon 1", engine.handle_runtime_command("/model horizon"))
        self.assertEqual(engine.model_id, "horizon")
        self.assertIn("always thinks", engine.handle_runtime_command("/think off"))
        self.assertIn("Unknown model", engine.handle_runtime_command("/model gen1"))
        engine.handle_runtime_command("/model flash")
        self.assertIn("never thinks", engine.handle_runtime_command("/think on"))
        self.assertIn("HyperFlux Flash 1", engine.handle_runtime_command("/sys"))

    def test_riddles_and_scenarios_get_a_reality_check(self):
        from hyperflux.core.prompts import REALITY_CHECK_HINT, wants_reality_check

        scenario = "I place a brick in a paper bag and lift it by the handles. What happens?"
        riddle = "A man was born in 1990 and is 25 today. How is this possible?"
        for question in (scenario, riddle, "Here's a riddle for you."):
            self.assertTrue(wants_reality_check(question), question)
        for question in ("What is the capital of Japan?", "Write a function that sorts a list."):
            self.assertFalse(wants_reality_check(question), question)
        # Every model gets the hint, including Flash, which never thinks.
        for model_id in MODELS:
            self.assertIn(REALITY_CHECK_HINT, self._payload(model_id, scenario)["prompt"])
            self.assertNotIn(REALITY_CHECK_HINT, self._payload(model_id)["prompt"])
        # Day and month words in a riddle get a note that they may be names.
        from hyperflux.core.prompts import name_word_notes

        cowboy = "A cowboy rides in on Friday, stays three days and leaves on Friday. How is this possible?"
        self.assertEqual(len(name_word_notes(cowboy)), 1)
        self.assertIn('"on Friday" can mean riding', name_word_notes(cowboy)[0])
        self.assertEqual(name_word_notes("May I ask a riddle?"), [])
        self.assertEqual(name_word_notes("What day comes after Friday?"), [])  # not a riddle
        # Apex thinks about these even with Think off; Flash stays fast.
        self.assertIn("<|think|>", self._payload("apex", scenario, think=False)["prompt"])
        self.assertNotIn("<|think|>", self._payload("apex", think=False)["prompt"])
        self.assertNotIn("<|think|>", self._payload("flash", scenario)["prompt"])


if __name__ == "__main__":
    unittest.main()
