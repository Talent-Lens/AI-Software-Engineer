import ast
import unittest
from src.agents.bug_detection import (
    check_mutable_default_args,
    check_assert_validation,
    check_tempfile_mktemp,
    check_open_without_encoding,
    check_yaml_load_unsafe,
    check_redos_patterns,
    check_comparison_to_none,
    check_is_with_literal,
    check_open_without_context_manager,
    check_unreachable_code,
    check_unused_variables,
    check_silent_except_pass,
    check_duplicate_dict_keys,
    check_finally_return_raise,
    check_shelve_open,
    check_path_traversal_open,
    find_ast_bugs,
    run_bug_scan,
)


class TestASTBugPatterns(unittest.TestCase):
    def test_mutable_default_args(self):
        code = "def fn(items=[]): pass"
        issues = check_mutable_default_args(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "mutable_default_args")

    def test_assert_validation(self):
        code = "def validate(x): assert x > 0"
        issues = check_assert_validation(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "assert_validation")

    def test_tempfile_mktemp(self):
        code = "import tempfile\nf = tempfile.mktemp()"
        issues = check_tempfile_mktemp(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "tempfile_mktemp")

    def test_open_without_encoding(self):
        code = "with open('file.txt', 'r') as f: pass"
        issues = check_open_without_encoding(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "open_without_encoding")

    def test_yaml_load_unsafe(self):
        code = "import yaml\nyaml.load(stream)"
        issues = check_yaml_load_unsafe(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "yaml_load_unsafe")

    def test_redos_pattern(self):
        code = "import re\nre.compile(r'(a+)+$')"
        issues = check_redos_patterns(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "redos_pattern")

    def test_comparison_to_none(self):
        code = "if val == None: pass"
        issues = check_comparison_to_none(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "comparison_to_none")

    def test_is_with_literal(self):
        code = "if count is 42: pass"
        issues = check_is_with_literal(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "is_with_literal")

    def test_open_without_context_manager(self):
        code = "f = open('test.txt', 'r', encoding='utf-8')\nf.read()"
        issues = check_open_without_context_manager(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "open_without_context_manager")

    def test_unreachable_code(self):
        code = "def fn():\n    return 1\n    print('dead')"
        issues = check_unreachable_code(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "unreachable_code")

    def test_unused_variables(self):
        code = "def fn():\n    unused = 123\n    return 456"
        issues = check_unused_variables(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "unused_variable")

    def test_silent_except_pass(self):
        code = "try:\n    x = 1\nexcept Exception:\n    pass"
        issues = check_silent_except_pass(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "silent_except_pass")

    def test_duplicate_dict_key(self):
        code = "d = {'key': 1, 'key': 2}"
        issues = check_duplicate_dict_keys(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "duplicate_dict_key")

    def test_finally_return_raise(self):
        code = "try:\n    pass\nfinally:\n    return False"
        issues = check_finally_return_raise(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "finally_return_raise")

    def test_shelve_open(self):
        code = "import shelve\nshelve.open('data.db')"
        issues = check_shelve_open(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "shelve_open")

    def test_path_traversal_open(self):
        code = "open(f'/var/data/{user_path}', 'r', encoding='utf-8')"
        issues = check_path_traversal_open(ast.parse(code))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "path_traversal_open")

    def test_find_ast_bugs_integrated(self):
        code = """
import tempfile, yaml, re, shelve

def bad_function(val=[]):
    unused_var = 123
    assert val != None
    x = 10
    if x is 10:
        pass
    f = open("test.txt", "r")
    tempfile.mktemp()
    yaml.load(data)
    re.compile(r"(a+)+$")
    shelve.open("mydb")
    d = {"a": 1, "a": 2}
    try:
        pass
    except Exception:
        pass
    finally:
        return 1
    return 2
    print("unreachable")
"""
        issues = find_ast_bugs("test.py", code=code)
        found_types = {issue["type"] for issue in issues}
        self.assertIn("mutable_default_args", found_types)
        self.assertIn("unused_variable", found_types)
        self.assertIn("assert_validation", found_types)
        self.assertIn("comparison_to_none", found_types)
        self.assertIn("is_with_literal", found_types)
        self.assertIn("open_without_encoding", found_types)
        self.assertIn("open_without_context_manager", found_types)
        self.assertIn("tempfile_mktemp", found_types)
        self.assertIn("yaml_load_unsafe", found_types)
        self.assertIn("redos_pattern", found_types)
        self.assertIn("shelve_open", found_types)
        self.assertIn("duplicate_dict_key", found_types)
        self.assertIn("silent_except_pass", found_types)
        self.assertIn("finally_return_raise", found_types)
        self.assertIn("unreachable_code", found_types)


if __name__ == "__main__":
    unittest.main()
