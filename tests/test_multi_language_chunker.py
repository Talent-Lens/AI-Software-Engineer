# tests/test_multi_language_chunker.py
import os
import tempfile
import unittest

from src.indexing.chunker import chunk_file


class TestMultiLanguageChunker(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_temp_file(self, filename: str, content: str) -> str:
        filepath = os.path.join(self.temp_dir.name, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

    def test_python_chunking(self):
        py_code = """
class Calculator:
    def add(self, a, b):
        return a + b

def multiply(x, y):
    return x * y
"""
        filepath = self._create_temp_file("test.py", py_code)
        chunks = chunk_file(filepath)

        names = [c.name for c in chunks]
        types = [c.type for c in chunks]

        self.assertIn("Calculator", names)
        self.assertIn("add", names)
        self.assertIn("multiply", names)
        self.assertIn("class", types)

    def test_javascript_chunking(self):
        js_code = """
class UserService {
    getUser(id) {
        return { id: id, name: "Alice" };
    }
}

function formatName(user) {
    return user.name.toUpperCase();
}
"""
        filepath = self._create_temp_file("test.js", js_code)
        chunks = chunk_file(filepath)

        names = [c.name for c in chunks]
        self.assertIn("UserService", names)
        self.assertIn("getUser", names)
        self.assertIn("formatName", names)

    def test_typescript_chunking(self):
        ts_code = """
interface User {
    id: string;
    name: string;
}

class UserMapper {
    mapUser(data: any): User {
        return { id: data.id, name: data.name };
    }
}
"""
        filepath = self._create_temp_file("test.ts", ts_code)
        chunks = chunk_file(filepath)

        names = [c.name for c in chunks]
        self.assertIn("User", names)
        self.assertIn("UserMapper", names)
        self.assertIn("mapUser", names)

    def test_java_chunking(self):
        java_code = """
public class OrderProcessor {
    public void processOrder(String orderId) {
        System.out.println("Processing " + orderId);
    }
}
"""
        filepath = self._create_temp_file("OrderProcessor.java", java_code)
        chunks = chunk_file(filepath)

        names = [c.name for c in chunks]
        self.assertIn("OrderProcessor", names)
        self.assertIn("processOrder", names)

    def test_go_chunking(self):
        go_code = """
package main

import "fmt"

type Server struct {
    Port int
}

func (s *Server) Start() {
    fmt.Println("Server starting...")
}

func NewServer(port int) *Server {
    return &Server{Port: port}
}
"""
        filepath = self._create_temp_file("main.go", go_code)
        chunks = chunk_file(filepath)

        names = [c.name for c in chunks]
        self.assertIn("Server", names)
        self.assertIn("Start", names)
        self.assertIn("NewServer", names)

    def test_fallback_line_chunking(self):
        text_code = "\n".join([f"line_{i} = {i}" for i in range(1, 50)])
        filepath = self._create_temp_file("config.txt", text_code)
        chunks = chunk_file(filepath)

        self.assertTrue(len(chunks) > 0)
        self.assertEqual(chunks[0].type, "code_block")


if __name__ == "__main__":
    unittest.main()
