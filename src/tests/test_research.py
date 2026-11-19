"""The web research pipeline: decide, query, search, read, trim, answer, retry (all offline)."""

import json
import threading
import unittest
from unittest.mock import patch

import requests

from hyperflux.search import research

PAGE = """<html><head><title>Wish | Genshin Impact Wiki</title><script>var tracking = 1;</script></head><body>
<nav><a>Home</a> <a>Characters</a> <a>Weapons and more navigation links here</a></nav>
<div class="cookie-banner">We use cookies to improve your experience on this website, accept them please.</div>
<article><h1>Wish</h1>
<p>Wishes are Genshin Impact's gacha system. The pity system guarantees a 5-star item within 90 wishes
on the character event banner, and soft pity starts around wish 74.</p>
<p>Capturing Radiance gives a 55% chance to win the 50/50 on the featured 5-star character after losing it.</p>
<p>Players can buy Intertwined Fate with Primogems in the shop, which has nothing to do with pity rules.</p>
</article><footer>Copyright notice and many footer links that should never be read by the model.</footer>
</body></html>"""


class DecideTests(unittest.TestCase):
    def test_rules(self):
        cases = {
            "/search genshin banner": "yes",
            "What is the latest Minecraft version?": "yes",
            "hi": "no",
            "thanks a lot": "no",
            "How do I write a for loop in Python?": "no",
            "What is 15% of 240?": "no",
            "Why is the sky blue?": "no",
            "How does Genshin gacha system works?": "yes",
            "Compare the pity in Genshin and Honkai Star Rail": "yes",
            "Who designed the Eiffel Tower?": "maybe",
            "How much does an RTX 5090 cost in Malaysia?": "yes",
        }
        for question, expected in cases.items():
            self.assertEqual(research.search_need(question), expected, question)

    def test_question_text_drops_prefix(self):
        self.assertEqual(research.question_text("/search genshin pity"), "genshin pity")
        self.assertEqual(research.question_text("web: rtx 5090 price"), "rtx 5090 price")


class QueryTests(unittest.TestCase):
    def test_parse_queries(self):
        self.assertEqual(research.parse_queries("NO"), [])
        self.assertEqual(research.parse_queries("1. Genshin Impact pity system\n- \"Genshin Capturing Radiance\"\n"),
                         ["Genshin Impact pity system", "Genshin Capturing Radiance"])
        self.assertEqual(len(research.parse_queries("a b\nc d\ne f\ng h")), 3)
        self.assertEqual(research.parse_queries("this line is far too long to be a sensible search engine query at all"), [])

    def test_year_only_for_current_topics(self):
        self.assertEqual(research.with_year("latest Minecraft version", 2026), "latest Minecraft version 2026")
        self.assertEqual(research.with_year("Genshin pity system", 2026), "Genshin pity system")
        self.assertEqual(research.with_year("RTX 5090 price 2025", 2026), "RTX 5090 price 2025")

    def test_plan_uses_the_model_only_when_unsure(self):
        calls = []
        def ask(system, user):
            calls.append((system, user))
            return "Genshin Impact pity system\nGenshin Capturing Radiance"
        self.assertEqual(research.plan("hello there friend", ask=ask)["search"], False)
        self.assertEqual(calls, [])  # clear "no": no model call
        result = research.plan("Who designed the Eiffel Tower?", ask=ask)
        self.assertEqual(result["queries"], ["Genshin Impact pity system", "Genshin Capturing Radiance"])
        self.assertIn("If no search is needed, write only: NO", calls[-1][0])
        self.assertIn("Question: What is the capital of France?\nNO", calls[-1][0])
        research.plan("How does Genshin gacha system works?", ask=ask)
        self.assertNotIn("write only: NO", calls[-1][0])  # rules said yes: the model may not refuse
        self.assertFalse(research.plan("Who designed the Eiffel Tower?", ask=lambda s, u: "NO")["search"])

    def test_plan_retry_needs_new_queries_and_survives_a_busy_model(self):
        seen = {}
        def ask(system, user):
            seen["user"] = user
            return "Genshin pity system\nGenshin wish rules official"
        result = research.plan("genshin pity?", force=True, previous=["Genshin pity system"], ask=ask)
        self.assertEqual(result["queries"], ["Genshin wish rules official"])  # the failed one is dropped
        self.assertIn("did not find the answer: Genshin pity system", seen["user"])
        def broken(system, user):
            raise requests.ConnectionError("model busy")
        fallback = research.plan("/search latest minecraft version", ask=broken)
        self.assertTrue(fallback["search"])
        self.assertIn("minecraft", fallback["queries"][0].lower())


class ReadAndTrimTests(unittest.TestCase):
    def setUp(self):
        research.clear_cache()

    def test_page_text_skips_menus_scripts_cookies_and_footers(self):
        title, paragraphs = research.page_paragraphs(PAGE)
        self.assertEqual(title, "Wish | Genshin Impact Wiki")
        text = "\n".join(paragraphs)
        self.assertIn("guarantees a 5-star item within 90 wishes", text)
        for junk in ("tracking", "navigation links", "cookies", "footer links"):
            self.assertNotIn(junk, text)

    def test_short_neighbouring_paragraphs_are_kept_together(self):
        self.assertEqual(research.chunks(["Hard pity: 90 wishes.", "Soft pity: from wish 74."]),
                         ["Hard pity: 90 wishes.\nSoft pity: from wish 74."])
        self.assertEqual(len(research.chunks(["x" * 600, "y" * 600])), 2)

    def test_best_passages_prefer_specific_facts(self):
        facts = ("The Genshin pity system guarantees a 5-star item within 90 wishes on the character event "
                 "banner, and soft pity starts around wish 74, when the 0.6% base rate climbs sharply.")
        vague = ("Genshin Impact is a popular game, and many players talk about the Genshin pity system "
                 "and the Genshin community, which is large and friendly.")
        shop = "Players can buy Intertwined Fate with Primogems in the shop on any day of the week at all."
        best = research.best_passages("How does Genshin pity work, how many wishes?", ["Genshin pity system"],
                                      [[vague], [facts], [shop]])
        self.assertEqual(best[0][1], 1)  # the page with the numbers wins over the one repeating the name
        self.assertNotIn(2, [index for _, index, _ in best])  # shares no words with the question

    def test_good_sources_rank_first(self):
        self.assertGreater(research.source_quality("https://en.wikipedia.org/wiki/X"), 0)
        self.assertGreater(research.source_quality("https://www.mof.gov.my/x"), 0)
        self.assertLess(research.source_quality("https://www.pinterest.com/pin/1"), 0)

    def test_gather_sources_searches_in_parallel_reads_pages_and_numbers_sources(self):
        searched = []
        def fetch(query, count):
            searched.append(query)
            return [{"title": "Spam list", "url": "https://www.pinterest.com/genshin", "body": "Genshin pins"},
                    {"title": "Wish | Genshin Impact Wiki", "url": "https://genshin-impact.fandom.com/wiki/Wish",
                     "body": "Wishes are the gacha system."}]
        read = lambda url: research.page_paragraphs(PAGE)[1] if "fandom" in url else []
        found = research.gather_sources("How does Genshin pity work?", ["Genshin pity system", "Genshin Capturing Radiance"],
                                        fetch=fetch, read=read)
        self.assertEqual(sorted(searched), ["Genshin Capturing Radiance", "Genshin pity system"])
        self.assertEqual(found["sources"][0]["url"], "https://genshin-impact.fandom.com/wiki/Wish")  # good source first
        self.assertIn("[1] Wish | Genshin Impact Wiki", found["context"])
        self.assertIn("90 wishes", found["context"])
        self.assertEqual(found["pages_read"], 1)
        self.assertLessEqual(len(found["context"]), research.CONTEXT_CHARS)
        # Cached: asking again within 10 minutes doesn't search again.
        research.gather_sources("How does Genshin pity work?", ["Genshin pity system"], fetch=fetch, read=read)
        self.assertEqual(len(searched), 2)


class AnswerTests(unittest.TestCase):
    def test_answer_prompt_and_no_answer_detection(self):
        prompt = research.build_answer_prompt("/search genshin pity", "[1] Wiki\nhttps://x\n90 wishes")
        self.assertIn("cite them like [1]", prompt)
        self.assertIn(research.NO_ANSWER_OPENING, prompt)
        self.assertTrue(prompt.endswith("Question: genshin pity"))
        self.assertTrue(research.is_no_answer("The sources I found don't say what the pity is."))
        self.assertTrue(research.is_no_answer("The sources I found do not say."))
        self.assertFalse(research.is_no_answer("Pity is 90 wishes [1]."))

    def test_footer_lists_cited_sources(self):
        sources = [{"n": 1, "title": "Wiki [Genshin]", "url": "https://a"}, {"n": 2, "title": "News", "url": "https://b"}]
        self.assertEqual(research.sources_footer("Pity is 90 [1].", sources), "\n\n**Sources**\n1. [Wiki (Genshin)](https://a)")
        self.assertIn("2. [News](https://b)", research.sources_footer("No citations.", sources))
        both = research.sources_footer("Fates cost 160 Primogems [1, 2].", sources)
        self.assertIn("1. [Wiki (Genshin)]", both)
        self.assertIn("2. [News]", both)

    def test_glued_titles_are_tidied(self):
        self.assertEqual(research.tidy_title("Banner Schedule (November 2026) | Genshin ...Genshin Impact 2026 Banner"),
                         "Banner Schedule (November 2026) | Genshin")
        self.assertEqual(research.tidy_title("How to watch on YouTube Premium for free"), "How to watch on YouTube Premium for free")
        self.assertEqual(research.tidy_title("", "https://www.example.com/a"), "www.example.com")


class EngineResearchTests(unittest.TestCase):
    def test_terminal_retries_once_when_sources_do_not_answer(self):
        from hyperflux.core.engine import HyperFluxEngine
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        plans = iter([{"search": True, "need": "maybe", "queries": ["genshin pity"]},
                      {"search": True, "need": "yes", "queries": ["genshin wish rules"]}])
        found = {"sources": [{"n": 1, "title": "Wiki", "url": "https://a"}], "context": "[1] Wiki", "pages_read": 1}
        answers = iter(["The sources I found don't say.", "Pity is 90 wishes [1]."])

        def fake_llm(prompt, **kwargs):
            reply = next(answers)
            engine._remember_exchange(kwargs.get("remember_as") or prompt, reply)
            return reply

        with patch.object(research, "plan", side_effect=lambda *a, **k: next(plans)) as plan, \
                patch.object(research, "gather_sources", return_value=found), \
                patch.object(engine, "query_local_llm", side_effect=fake_llm):
            reply = engine.process_chat("How does Genshin gacha system works?", quiet=True)
        self.assertEqual(reply, "Pity is 90 wishes [1].\n\n**Sources**\n1. [Wiki](https://a)")
        self.assertEqual(plan.call_args_list[1].kwargs["previous"], ["genshin pity"])
        self.assertEqual(len(engine.chat_history), 1)  # only the final answer is remembered
        self.assertEqual(engine.chat_history[0]["user"], "How does Genshin gacha system works?")


class BridgeResearchTests(unittest.TestCase):
    def test_bridge_plan_and_sources(self):
        from hyperflux.search.bridge import create_search_bridge
        server = create_search_bridge(None, port=0, log_token="tok")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        found = {"sources": [{"n": 1, "title": "Wiki", "url": "https://a"}], "context": "[1] Wiki\n90 wishes", "pages_read": 1}
        try:
            with patch.object(research, "plan", return_value={"search": True, "need": "maybe", "queries": ["q"]}) as plan:
                reply = requests.post(base + "/research/plan", json={"question": "genshin pity?"}, timeout=5).json()
            self.assertEqual(reply["queries"], ["q"])
            self.assertEqual(plan.call_args.kwargs, {"force": False, "previous": []})
            with patch.object(research, "gather_sources", return_value=found):
                reply = requests.post(base + "/research/sources", json={"question": "genshin pity?", "queries": ["q"]}, timeout=5).json()
            self.assertIn("WEB SOURCES\n[1] Wiki", reply["prompt"])
            with patch.object(research, "gather_sources", return_value={"sources": [], "context": "", "pages_read": 0}):
                self.assertEqual(requests.post(base + "/research/sources", json={"question": "x y z", "queries": ["q"]},
                                               timeout=5).status_code, 502)
            self.assertEqual(requests.post(base + "/research/sources", json={"question": "x", "queries": []},
                                           timeout=5).status_code, 400)
            self.assertEqual(requests.post(base + "/research/plan", data=json.dumps({"question": ""}),
                                           headers={"Content-Type": "application/json"}, timeout=5).status_code, 400)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
