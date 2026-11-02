import unittest

from hyperflux.core.formatting import repair_collapsed_tables

# A real one-line table the model produced.
COLLAPSED = (
    "| If you need... | Recommended Focus | Why? | | :--- | :--- | :--- | "
    "| Best Multimodality & Reasoning | Gemini or GPT-4 level models | Excellent at synthesizing information. | "
    "| Open Source & Local Control | Llama or Gemma models | Allows for local deployment. | "
    "| Fast, High-Quality Text | The most recent LLM | Best balance of speed and accuracy. |"
)


class TableRepairTests(unittest.TestCase):
    def test_one_line_table_is_split_into_rows(self):
        rows = repair_collapsed_tables("Summary Recommendation\n" + COLLAPSED).split("\n")
        self.assertEqual(rows[0], "Summary Recommendation")
        self.assertEqual(rows[1], "| If you need... | Recommended Focus | Why? |")
        self.assertEqual(rows[2], "| :--- | :--- | :--- |")
        self.assertEqual(len(rows), 6)
        self.assertTrue(rows[5].startswith("| Fast, High-Quality Text |"))

    def test_proper_tables_and_plain_text_are_unchanged(self):
        proper = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        self.assertEqual(repair_collapsed_tables(proper), proper)
        self.assertEqual(repair_collapsed_tables("a | b | | c"), "a | b | | c")

    def test_empty_cells_in_a_normal_row_are_left_alone(self):
        row = "| x |  | y |"
        self.assertEqual(repair_collapsed_tables(row), row)

    def test_odd_shapes_are_left_alone(self):
        broken = "| A | B | | :--- | :--- | | only one cell |"
        self.assertEqual(repair_collapsed_tables(broken), broken)


if __name__ == "__main__":
    unittest.main()
