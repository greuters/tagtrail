# -*- coding: utf-8 -*-

from .scenario_ocr import OcrTest
from .scenario_gen import GenTest
from .scenario_account import AccountTest

import unittest
import sys

class BasicOcrTest(OcrTest):
    def setUp(self):
        self.baseSetUp('template_basic')

class BasicGenTest(GenTest):
    def setUp(self):
        self.baseSetUp('basic')

class BasicAccountTest(AccountTest):
    def setUp(self):
        self.baseSetUp('basic')

if __name__ == '__main__':
    loader = unittest.TestLoader()
    completeSuite = unittest.TestSuite()
    for suite in [BasicOcrTest, BasicGenTest, BasicAccountTest]:
        for test in loader.loadTestsFromTestCase(suite):
            completeSuite.addTest(test)
    runner = unittest.TextTestRunner()
    result = runner.run(completeSuite)
    if not result.wasSuccessful():
        print('scenario_basic: tests failed')
        sys.exit(1)
