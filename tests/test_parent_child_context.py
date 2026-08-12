# tests/test_parent_child_context.py
import os
import tempfile
import unittest

from src.indexing.chunker import chunk_file, format_chunk_with_context
from src.indexing.indexer import index_repository
from src.retrieval.rag import retrieve_context


class TestParentChildContextWindowing(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_temp_file(self, filename: str, content: str) -> str:
        filepath = os.path.join(self.temp_dir.name, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

    def test_python_imports_and_parent_scope(self):
        py_code = """import os
from datetime import datetime

class OrderProcessor:
    def process_order(self, order_id):
        return True

def standalone_helper():
    return "ok"
"""
        filepath = self._create_temp_file("order.py", py_code)
        chunks = chunk_file(filepath)

        chunk_dict = {c.name: c for c in chunks}

        self.assertIn("process_order", chunk_dict)
        self.assertEqual(chunk_dict["process_order"].parent_name, "OrderProcessor")
        self.assertTrue(any("from datetime import datetime" in imp for imp in chunk_dict["process_order"].imports))
        self.assertIsNone(chunk_dict["standalone_helper"].parent_name)

    def test_javascript_imports_and_parent_scope(self):
        js_code = """import axios from 'axios';
const fs = require('fs');

class AuthService {
    login(username, password) {
        return true;
    }
}
"""
        filepath = self._create_temp_file("auth.js", js_code)
        chunks = chunk_file(filepath)

        chunk_dict = {c.name: c for c in chunks}
        self.assertIn("login", chunk_dict)
        self.assertEqual(chunk_dict["login"].parent_name, "AuthService")
        self.assertTrue(any("import axios" in imp for imp in chunk_dict["login"].imports))

    def test_java_package_imports_and_parent_scope(self):
        java_code = """package com.example.service;

import java.util.List;
import java.util.Map;

public class PaymentGateway {
    public boolean processPayment(double amount) {
        return true;
    }
}
"""
        filepath = self._create_temp_file("PaymentGateway.java", java_code)
        chunks = chunk_file(filepath)

        chunk_dict = {c.name: c for c in chunks}
        self.assertIn("processPayment", chunk_dict)
        self.assertEqual(chunk_dict["processPayment"].parent_name, "PaymentGateway")
        self.assertTrue(any("package com.example.service;" in imp for imp in chunk_dict["processPayment"].imports))

    def test_go_package_imports_and_receiver_parent_scope(self):
        go_code = """package main

import (
    "fmt"
    "net/http"
)

type Server struct {
    Port int
}

func (s *Server) ListenAndServe() error {
    return nil
}
"""
        filepath = self._create_temp_file("main.go", go_code)
        chunks = chunk_file(filepath)

        chunk_dict = {c.name: c for c in chunks}
        self.assertIn("ListenAndServe", chunk_dict)
        self.assertEqual(chunk_dict["ListenAndServe"].parent_name, "Server")
        self.assertTrue(any("package main" in imp for imp in chunk_dict["ListenAndServe"].imports))

    def test_format_chunk_with_context(self):
        py_code = """from models import User

class UserMapper:
    def to_dict(self, user):
        return {}
"""
        filepath = self._create_temp_file("mapper.py", py_code)
        chunks = chunk_file(filepath)
        method_chunk = [c for c in chunks if c.name == "to_dict"][0]

        formatted = format_chunk_with_context(method_chunk)

        self.assertIn("File: ", formatted)
        self.assertIn("Imports / Package Statements:", formatted)
        self.assertIn("from models import User", formatted)
        self.assertIn("Enclosing Scope: method 'to_dict' in 'UserMapper'", formatted)

    def test_chromadb_metadata_persistence(self):
        py_code = """import sys

class Evaluator:
    def evaluate(self):
        pass
"""
        self._create_temp_file("eval.py", py_code)
        collection = index_repository(self.temp_dir.name, reset=True)
        results = retrieve_context(collection, "evaluate", n_results=1)

        self.assertTrue(len(results) > 0)
        retrieved_chunk = results[0].chunk

        self.assertEqual(retrieved_chunk.name, "evaluate")
        self.assertEqual(retrieved_chunk.parent_name, "Evaluator")
        self.assertTrue(any("import sys" in imp for imp in retrieved_chunk.imports))


if __name__ == "__main__":
    unittest.main()
