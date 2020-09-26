# -*- coding: utf-8 -*-

from .scenario_ocr import OcrTest

import unittest

class BasicOcrTest(OcrTest):
    minAverageRecall = 0.88

    def setUp(self):
        self.baseSetUp('basic_template')

if __name__ == '__main__':
    unittest.main()
