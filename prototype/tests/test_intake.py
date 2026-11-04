import unittest

from companion.intake import (understand, next_question, extract_hours, extract_known, infer_domain,
                              QUESTIONS, normalize_digits)
from companion.lang import LANG_NAMES, script_ok


class Domain(unittest.TestCase):
    def test_languages(self):
        cases = {"I want to become a machine learning engineer": "ml_engineer",
                 "मुझे 1 महीने का डेटा साइंस प्लान चाहिए": "data_analysis",
                 "I want to build websites with React": "web_dev",
                 "எனக்கு தரவு பகுப்பாய்வு கற்க வேண்டும்": "data_analysis",
                 "আমি মেশিন লার্নিং শিখতে চাই": "ml_engineer",
                 "నాకు వెబ్ డెవలప్‌మెంట్ నేర్చుకోవాలి": "web_dev"}
        for text, want in cases.items():
            self.assertEqual(infer_domain(text)[0], want, text)

    def test_ambiguous_and_unknown_ask_instead_of_guessing(self):
        d, cands = infer_domain("machine learning and data analysis")
        self.assertIsNone(d)
        self.assertEqual(set(cands), {"ml_engineer", "data_analysis"})
        self.assertEqual(infer_domain("I want to learn cooking"), (None, []))

    def test_short_keywords_need_word_boundaries(self):
        self.assertIsNone(infer_domain("I want to maintain my email")[0])  # 'ai' inside 'maintain'


class Hours(unittest.TestCase):
    def test_extract(self):
        self.assertEqual(extract_hours("5 hours a week"), 5)
        self.assertEqual(extract_hours("about 7.5 hrs per week"), 7.5)
        self.assertEqual(extract_hours("2 hours a day"), 14)
        self.assertEqual(extract_hours("मैं हफ़्ते में 5 घंटे दे सकता हूँ"), 5)
        self.assertEqual(extract_hours("সপ্তাহে ৫ ঘণ্টা"), 5)
        self.assertEqual(extract_hours("வாரத்திற்கு 6 மணி நேரம்"), 6)
        self.assertIsNone(extract_hours("1 महीने का प्लान"))
        self.assertIsNone(extract_hours("no number here"))

    def test_digits(self):
        self.assertEqual(normalize_digits("৫ ५ ௫ ౫"), "5 5 5 5")


class Known(unittest.TestCase):
    def test_knowing_vs_wanting(self):
        self.assertEqual(extract_known("I know Python but want to learn PyTorch", "ml_engineer"), ["python_basics"])
        self.assertEqual(extract_known("I want to learn Python", "ml_engineer"), [])
        self.assertEqual(extract_known("I already know Python and want to be an ML engineer", "ml_engineer"), ["python_basics"])
        self.assertEqual(extract_known("I don't know SQL", "data_analysis"), [])
        self.assertEqual(extract_known("I learned linear algebra in college", "ml_engineer"), ["linear_algebra"])

    def test_answering_mode_accepts_bare_lists(self):
        self.assertEqual(extract_known("Python, SQL", "data_analysis", answering=True), ["python_basics", "sql_basics"])
        self.assertEqual(extract_known("none", "data_analysis", answering=True), [])


class Flow(unittest.TestCase):
    def test_multi_turn_intake(self):
        p = understand("I want to become a machine learning engineer")
        self.assertEqual(p["missing"], ["hours", "known"])
        self.assertEqual(next_question(p), QUESTIONS["en"]["hours"])
        p = understand("5", prior=p, answering="hours")
        self.assertEqual(p["weekly_hours"], 5)
        self.assertTrue(next_question(p).startswith(QUESTIONS["en"]["known"]))
        p = understand("python and numpy", prior=p, answering="known")
        self.assertEqual((p["known"], p["missing"]), (["numpy_pandas", "python_basics"], []))
        self.assertIsNone(next_question(p))

    def test_language_is_sticky_and_questions_localised(self):
        p = understand("मुझे डेटा साइंस सीखना है")
        self.assertEqual(p["language"], "hi")
        self.assertEqual(next_question(p), QUESTIONS["hi"]["hours"])
        p = understand("5", prior=p, answering="hours")
        self.assertEqual(p["language"], "hi")  # a bare '5' must not flip the language to English

    def test_hours_out_of_range_ignored(self):
        self.assertIsNone(understand("0 hours a week")["weekly_hours"])
        self.assertIsNone(understand("500 hours a week")["weekly_hours"])

    def test_all_question_strings_exist_and_are_in_their_script(self):
        for lang in LANG_NAMES:
            for key in ("goal", "hours", "known"):
                q = QUESTIONS[lang][key]
                self.assertTrue(script_ok(q, lang), f"{lang}/{key}")


if __name__ == "__main__":
    unittest.main()
