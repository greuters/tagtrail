# -*- coding: utf-8 -*-

from .scenario_ocr import OcrTest
from .scenario_gen import GenTest
from .scenario_account import AccountTest
from .context import helpers

import unittest
import sys
import logging
import argparse

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
    parser = argparse.ArgumentParser(description='Test tagtrail_gen')
    parser.add_argument('--logLevel', dest='logLevel',
            help='Log level to write to console', default='INFO')
    args = parser.parse_args()
    helpers.configureLogger(logging.getLogger('tagtrail'), consoleLevel =
            logging.getLevelName(args.logLevel))

    loader = unittest.TestLoader()
    completeSuite = unittest.TestSuite()
    for suite in [MediumOcrTest, MediumGenTest, MediumAccountTest]:
        for test in loader.loadTestsFromTestCase(suite):
            completeSuite.addTest(test)
    runner = unittest.TextTestRunner()
    result = runner.run(completeSuite)
    if not result.wasSuccessful():
        print('scenario_basic: tests failed')
        sys.exit(1)
