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
            "A bat and a ball cost RM1.10 in total. The bat costs RM1.00 more than the ball. "
            "How much does the ball cost?": "no",  # gives its own amounts: a calculation
            "A train travels 42 km in 3 hours. What is its average speed?": "no",
            "How much is the iPhone 17 Pro vs iPhone 16 in Malaysia?": "yes",  # numbers in names
            "What was the population of Malaysia in 2020 and 2024?": "maybe",  # years
            "How much does an RTX 5090 cost in Malaysia?": "yes",
            # talking about the chat or the model in use is not a lookup
            "No right now you're Granite4 which I'm using, but the last time I used Qwen "
            "it always output </turn>": "no",
            "Granite 4 is annoying": "no",
            "I want the latest NVIDIA drivers": "yes",
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

    def test_tables_menus_and_notices(self):
        html = """<body><article>
        <p>This article is about the in-game system. For the quest, see Wishes (Quest).</p>
        <table><tr><th>Wish</th><th>5-star rate</th></tr><tr><td>1 to 73</td><td>0.6%</td></tr>
        <tr><td>X = 90</td><td>100%<math><annotation>{\\displaystyle 100\\%}</annotation></math></td></tr></table>
        <ul><li><a href="/a">Version 6.7 Luna VIII</a></li><li><a href="/b">Version 7.2 Codes and more links here</a></li></ul>
        <p>Soft pity starts at wish 74, after which the 5-star rate climbs by 6% with every wish.</p>
        </article></body>"""
        text = "\n".join(research.page_paragraphs(html)[1])
        self.assertIn("1 to 73 | 0.6%", text)  # a table row stays together
        self.assertIn("X = 90 | 100%", text)
        self.assertNotIn("displaystyle", text)
        self.assertNotIn("Luna", text)  # menu links
        self.assertNotIn("This article is about", text)
        self.assertIn("Soft pity starts at wish 74", text)

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


class WikiApiTests(unittest.TestCase):
    def setUp(self):
        research.clear_cache()

    def test_fandom_pages_are_read_through_the_api(self):
        class Reply:
            status_code = 200
            def json(self):
                return {"parse": {"displaytitle": "<span>Wish</span>", "text": PAGE}}
        with patch.object(research.requests, "get", return_value=Reply()) as get:
            title, paragraphs = research.fetch_page("https://genshin-impact.fandom.com/wiki/Wish")
        self.assertEqual(get.call_args.args[0], "https://genshin-impact.fandom.com/api.php")
        self.assertEqual(get.call_args.kwargs["params"]["page"], "Wish")
        self.assertEqual(title, "Wish | Genshin Impact Wiki")
        self.assertIn("90 wishes", " ".join(paragraphs))
        with patch.object(research.requests, "get", return_value=Reply()) as get:
            title, _ = research.fetch_page("https://en.wikipedia.org/wiki/Gacha_game")
        self.assertEqual(get.call_args.args[0], "https://en.wikipedia.org/w/api.php")
        self.assertEqual(get.call_args.kwargs["params"]["page"], "Gacha game")
        self.assertEqual(title, "Wish | Wikipedia")

    def test_page_title_replaces_the_search_engines_title(self):
        fetch = lambda q, n: [{"title": "Wish | Genshin ImpactGenshin Impact Wish", "url": "https://w.example/wish",
                               "body": "Wishes."}]
        read = lambda url: ("Wish | Genshin Impact Wiki", research.page_paragraphs(PAGE)[1])
        found = research.gather_sources("How does Genshin pity work?", ["Genshin pity"], fetch=fetch, read=read)
        self.assertEqual(found["sources"][0]["title"], "Wish | Genshin Impact Wiki")

    def test_game_references_rank_high(self):
        self.assertGreater(research.source_quality("https://game8.co/games/Genshin-Impact/archives/305937"), 0)


class AnswerTests(unittest.TestCase):
    def test_answer_prompt_and_no_answer_detection(self):
        prompt = research.build_answer_prompt("/search genshin pity", "[1] Wiki\nhttps://x\n90 wishes")
        self.assertIn("Cite sources like [1]", prompt)
        self.assertIn(research.NO_ANSWER_OPENING, prompt)
        self.assertTrue(prompt.endswith("Question: genshin pity"))
        self.assertTrue(research.is_no_answer("The sources I found don't say what the pity is."))
        self.assertTrue(research.is_no_answer("The sources I found do not say."))
        self.assertFalse(research.is_no_answer("Pity is 90 wishes [1]."))

    def test_footer_lists_cited_sources(self):
        sources = [{"n": 1, "title": "Wiki [Genshin]", "url": "https://a"}, {"n": 2, "title": "News", "url": "https://b"}]
        self.assertEqual(research.sources_footer("Pity is 90 [1].", sources), "\n\n**Sources**\n1. [Wiki (Genshin)](https://a)")
        self.assertEqual(research.sources_footer("No citations.", sources), "")  # unused sources: no list
        both = research.sources_footer("Fates cost 160 Primogems [1, 2].", sources)
        self.assertIn("1. [Wiki (Genshin)]", both)
        self.assertIn("2. [News]", both)

    def test_answer_prompt_asks_for_explanations_in_natural_style(self):
        prompt = research.build_answer_prompt("genshin pity", "[1] Wiki")
        self.assertIn("Explain how each part works, with the key numbers; don't just name features.", prompt)
        self.assertIn("Cite sources like [1] or [2] once per paragraph, not after every sentence.", prompt)
        self.assertIn("Write naturally, as you normally would", prompt)

    def test_repeated_titles_are_cut_at_the_repeat(self):
        self.assertEqual(research.tidy_title("Wish system explained - Genshin ImpactGenshin Impact Wish system guide"),
                         "Wish system explained - Genshin Impact")
        self.assertEqual(research.tidy_title("The Genshin Impact gacha guide for new playersGenshin Impact gacha"),
                         "The Genshin Impact gacha guide for new players")

    def test_echoed_queries_are_spotted(self):
        queries = ["Genshin Impact gacha system explained", "Genshin Impact banner mechanics 2026"]
        self.assertTrue(research.is_echoed_queries(
            "Genshin Impact gacha system explained\nGenshin Impact banner mechanics", queries))
        self.assertFalse(research.is_echoed_queries("The gacha system, called Wish, uses Fates [1].", queries))
        self.assertFalse(research.is_echoed_queries("", queries))

    def test_glued_titles_are_tidied(self):
        self.assertEqual(research.tidy_title("Here's How The Gacha System Works In Genshin ImpactWish | Genshin Impact Wiki | Fandom"),
                         "Here's How The Gacha System Works In Genshin Impact")
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


class ResearchPromptThinkingTests(unittest.TestCase):
    def test_research_prompt_does_not_switch_on_thinking(self):
        from hyperflux.core.engine import HyperFluxEngine
        from tests.test_core import FakeStreamResponse
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        prompt = research.build_answer_prompt("How does Genshin gacha system works?", "[1] Wiki")
        self.assertIn("Explain how", prompt)  # would look like a riddle ("explain how") on its own
        with patch("hyperflux.core.kobold.requests.post", return_value=FakeStreamResponse()) as post:
            engine.query_local_llm(prompt, quiet=True, remember_as="How does Genshin gacha system works?")
        sent = post.call_args.kwargs["json"]["prompt"]
        self.assertNotIn("<|think|>", sent)
        self.assertNotIn("may be a riddle", sent)


class RepeatTests(unittest.TestCase):
    """A small model repeats what it reads twice; pages repeat each other too."""

    def test_repeated_sentences_are_dropped_from_the_sources(self):
        seen = []
        first = "Hard pity is 90 pulls on the character banner. Soft pity starts at wish 74."
        again = "On the character banner, hard pity is 90 pulls. The base rate is 0.6% for each pull."
        self.assertEqual(research.novel_text(first, seen), first)
        # the repeated fact goes; the new one stays
        self.assertEqual(research.novel_text(again, seen), "The base rate is 0.6% for each pull.")
        # a different number is a different fact, even with nearly the same words
        weapon = "Hard pity is 80 pulls on the weapon banner."
        self.assertEqual(research.novel_text(weapon, seen), weapon)
        # table rows are never touched
        self.assertEqual(research.novel_text("Hard pity | 90 | 80", seen), "Hard pity | 90 | 80")

    def test_best_passages_do_not_waste_slots_on_repeats(self):
        fact = ("The Genshin pity system guarantees a 5-star item within 90 wishes on the character banner, "
                "and soft pity starts around wish 74 when the 0.6% base rate climbs sharply.")
        best = research.best_passages("How does Genshin pity work, how many wishes?", ["Genshin pity system"],
                                      [[fact], [fact], ["Fates cost 160 Primogems each in the shop menu."]])
        texts = [t for _, _, t in best]
        self.assertEqual(sum("guarantees a 5-star" in t for t in texts), 1)  # said once, not twice

    def test_answer_repeats_are_merged_and_citations_kept(self):
        answer = ("Primogems turn into Fates at 160 each [2]. Character wishes have a 90 pull hard pity [1].\n\n"
                  "To summarise, Primogems turn into Fates at 160 each [3]. Weapon wishes have an 80 pull pity [1].")
        tidy = research.dedupe_sentences(answer)
        self.assertEqual(tidy.count("160"), 1)
        self.assertIn("at 160 each [2, 3].", tidy)  # the dropped sentence's source is not lost
        self.assertIn("80 pull pity [1]", tidy)      # a different fact stays
        self.assertIn("90 pull hard pity", tidy)

    def test_a_closing_recap_is_dropped_but_a_real_summary_is_kept(self):
        body = ("Primogems turn into Fates at 160 each [2]. The system tracks pity counters and guarantees "
                "for each banner type you pull on [1].")
        recap = ("To put it simply, you convert Primogems to Fates, then spend those Fates while the system "
                 "tracks pity counters and guarantees for each banner you pull on [2].")
        # it repeats the second sentence closely, so it is merged into it and its source moves across
        self.assertEqual(research.dedupe_sentences(body + "\n\n" + recap), body.replace("on [1].", "on [1, 2]."))
        # the answer HyperFlux really wrote about Genshin (a paraphrased closing recap, no near-copies)
        real = (
            "The Genshin Impact gacha system operates through a mechanic called Wish, which is how players "
            "acquire new characters and weapons using Primogems [2]. Primogems are the game's primary premium "
            "currency, which players earn by completing activities like quests and daily commissions, and these "
            "Primogems are converted into Fates at a rate of 160 Primogems per Fate [2, 3]. These Fates are the "
            "actual tickets used when pulling on the various banners available in the game [3].\n\n"
            "The system uses several layered guarantees based on the type of banner you are pulling on. For "
            "instance, a Character Event Wish has a 90-pull hard pity, meaning you are guaranteed a 5-star item "
            "by the 90th pull [2]. Furthermore, there are specific pity counters for different banner types; for "
            "a Featured Character Banner, the hard pity is 90 Wishes, while a Featured Weapon Banner has a pity "
            "of 80 Wishes [1].\n\n"
            "To put it simply, you convert Primogems to Fates, and then you spend those Fates while the system "
            "tracks various pity counters and guarantees tied to the specific banner you are pulling on [2]. "
            "For example, a general pity system means you are guaranteed a 4-star or 5-star after a certain "
            "number of pulls [1].")
        tidy = research.dedupe_sentences(real)
        self.assertNotIn("To put it simply", tidy)
        self.assertIn("guaranteed a 4-star or 5-star", tidy)  # the new example in that paragraph survives
        self.assertIn("80 Wishes", tidy)
        # "Overall" with something new to say stays: most of its words are not in the answer yet
        fresh = "Overall, Malaysia's rainy season runs from November until March on the east coast."
        self.assertEqual(research.dedupe_sentences(body + " " + fresh), body + " " + fresh)
        # an opening "In short" has nothing before it to repeat, so it stays
        self.assertEqual(research.dedupe_sentences("In short, the answer is yes because the pity system exists."),
                         "In short, the answer is yes because the pity system exists.")

    def test_answer_cleanup_leaves_code_tables_and_normal_text_alone(self):
        text = ("Use a loop to add the numbers to the running total.\n\n```python\n"
                "total = 0\ntotal = 0\n```\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n"
                "Then print the final total after the loop has finished.")
        self.assertEqual(research.dedupe_sentences(text), text)
        self.assertEqual(research.dedupe_sentences("Short one. Another short one."), "Short one. Another short one.")

    def test_answer_prompt_asks_for_each_fact_once(self):
        prompt = research.build_answer_prompt("genshin pity", "[1] Wiki")
        self.assertIn("Say each fact once", prompt)
        self.assertIn("Never restate or summarise", prompt)
        self.assertNotIn("HyperFlux adds", prompt)  # the app no longer adds a sources list


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
            # tidying a long finished answer (more than the 8 KB the other routes allow)
            long_answer = ("Primogems turn into Fates at 160 each [1]. " * 2 + "Hard pity is 90 pulls [2]. ") * 40
            reply = requests.post(base + "/research/tidy", json={"answer": long_answer}, timeout=5)
            self.assertEqual(reply.status_code, 200)
            self.assertEqual(reply.json()["answer"], "Primogems turn into Fates at 160 each [1]. Hard pity is 90 pulls [2].")
            self.assertEqual(requests.post(base + "/research/tidy", json={"answer": 5}, timeout=5).status_code, 400)
            self.assertEqual(requests.post(base + "/research/plan", data=json.dumps({"question": ""}),
                                           headers={"Content-Type": "application/json"}, timeout=5).status_code, 400)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
