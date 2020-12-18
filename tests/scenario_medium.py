# -*- coding: utf-8 -*-

from .scenario_ocr import OcrTest
from .scenario_gen import GenTest
from .scenario_account import AccountTest

import unittest

class MediumOcrTest(OcrTest):
    def setUp(self):
        self.baseSetUp('template_medium')

class MediumGenTest(GenTest):
    def setUp(self):
        self.baseSetUp('medium')

class MediumAccountTest(AccountTest):
    def setUp(self):
        self.baseSetUp('medium')

if __name__ == '__main__':
    loader = unittest.TestLoader()
    completeSuite = unittest.TestSuite()
    for suite in [MediumOcrTest, MediumGenTest, MediumAccountTest]:
        for test in loader.loadTestsFromTestCase(suite):
            completeSuite.addTest(test)
    runner = unittest.TextTestRunner()
    runner.run(completeSuite)
