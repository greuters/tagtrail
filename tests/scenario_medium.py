# -*- coding: utf-8 -*-

from .scenario_ocr import OcrTest

import unittest

class BasicOcrTest(OcrTest):
    def setUp(self):
        self.baseSetUp('medium_template')

if __name__ == '__main__':
    unittest.main()
