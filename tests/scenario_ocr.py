# -*- coding: utf-8 -*-

from .context import helpers
from .context import database
from .context import sheets
from .context import tagtrail_ocr

import logging
import argparse
import unittest
import configparser
import shutil
import os
import re

class OcrTest(unittest.TestCase):
    """ Tests of tagtrail_ocr """
    minSheetPrecision = 0.95
    minSheetRecall = 0.81
    minAveragePrecision = 0.99
    minAverageRecall = 0.94

    writeDebugImages = False

    tmpDir = 'tests/tmp/'
    debugOutputDir  = 'tests/tmp/ocrDebugOutput/'
    # directory to copy all wrongly labeled images to
    debugOutputNotRecalledDir  = 'tests/tmp/ocrDebugOutput/notRecalled/'
    debugOutputWrongDir  = 'tests/tmp/ocrDebugOutput/wrong/'

    @classmethod
    def setUpClass(cls):
        helpers.recreateDir(cls.tmpDir)
        helpers.recreateDir(cls.debugOutputDir)
        helpers.recreateDir(cls.debugOutputNotRecalledDir)
        helpers.recreateDir(cls.debugOutputWrongDir)

    def setUp(self):
        if __name__ != '__main__':
            self.skipTest(reason = 'only run when invoked directly')
        self.baseSetUp('template_medium')
#        self.baseSetUp('template_basic')

    def baseSetUp(self, templateName):
        self.templateName = templateName
        self.templateDir = 'tests/data/'
        self.templateRootDir = f'{self.templateDir}{self.templateName}/'
        self.templateOutputDir = f'{self.templateRootDir}2_taggedProductSheets/'

        self.testRootDir = f'{self.tmpDir}{self.templateName}/'
        self.testOutputDir = f'{self.testRootDir}2_taggedProductSheets/'
        self.testScanDir = f'{self.testRootDir}0_input/scans/'

        self.logger = logging.getLogger('tagtrail.tests.scenario_ocr.OcrTest')
        self.logger.info(f'\nStarting test {self.id()}\n')
        shutil.copytree(self.templateRootDir, self.testRootDir)
        helpers.recreateDir(self.testOutputDir)
        self.db = database.Database(f'{self.testRootDir}0_input/')
        self.scanConfigFilePath = f'{self.testRootDir}scan_config.cfg'
        self.scanConfig = configparser.ConfigParser(
                interpolation=configparser.BasicInterpolation(),
                converters={
                    'csvlist': lambda x: [i.strip() for i in x.split(',') if
                        i.strip() != ''],
                    'newlinelist': lambda x: [i.strip() for i in x.splitlines()
                        if i.strip() != '']})
        self.scanConfig.read(self.scanConfigFilePath)

    def test_ocr(self):
        precisions = []
        recalls = []
        for section in self.scanConfig.sections():
            self.logger.info(f'\nSubtest on scan {section}\n')
            with self.subTest(scanFilename = section):
                self.processScan(section, precisions, recalls)
        averagePrecision = sum(precisions) / len(precisions)
        averageRecall = sum(recalls) / len(recalls)
        self.logger.info(f'averagePrecision = {averagePrecision}')
        self.logger.info(f'averageRecall = {averageRecall}')
        self.assertGreaterEqual(averagePrecision, self.minAveragePrecision,
                'averagePrecision not high enough')
        self.assertGreaterEqual(averageRecall, self.minAverageRecall,
                'averageRecall not high enough')

    def processScan(self, scanFilename, precisions, recalls):
        model = tagtrail_ocr.Model(self.testRootDir, self.tmpDir,
                [scanFilename], True, self.writeDebugImages)
        model.prepareScanSplitting()

        self.assertTrue(os.path.exists(f'{self.testScanDir}{scanFilename}'))

        rotationAngle = self.scanConfig.getint(scanFilename, 'rotationAngle')
        sheetCoordinates = []
        sheetCoordinates.append(list(map(float,
            self.scanConfig.getcsvlist(scanFilename, 'sheet0_coordinates'))))
        sheetCoordinates.append(list(map(float,
            self.scanConfig.getcsvlist(scanFilename, 'sheet1_coordinates'))))
        sheetCoordinates.append(list(map(float,
            self.scanConfig.getcsvlist(scanFilename, 'sheet2_coordinates'))))
        sheetCoordinates.append(list(map(float,
            self.scanConfig.getcsvlist(scanFilename, 'sheet3_coordinates'))))

        model.splitScan(scanFilename, sheetCoordinates, rotationAngle)

        with model:
            model.prepareTagRecognition()
            for idx, sheet in enumerate(model.sheetRegions):
                expectedSheetName = self.scanConfig.get(scanFilename,
                        f'sheet{idx}_name')
                with self.subTest(expectedSheetName = expectedSheetName,
                        sheetIdx = idx):
                    model.recognizeTags(sheet)
                    if expectedSheetName == '':
                        self.assertTrue(sheet.isEmpty,
                            f'{scanFilename}, sheet{idx} ' +
                            'wrongly classified as not being empty')
                    else:
                        self.assertFalse(sheet.isEmpty,
                            f'{scanFilename}, sheet{idx} ' +
                            'wrongly classified as being empty')
                        self.checkIdPrecision(expectedSheetName,
                                sheet.recognizedName)
                        precision, recall = self.computePerformanceMetrics(
                                expectedSheetName, sheet.recognizedName,
                                f'{scanFilename}_sheet{idx}')
                        precisions.append(precision)
                        recalls.append(recall)
                        self.assertGreaterEqual(precision, self.minSheetPrecision,
                                'sheet precision not high enough')
                        self.assertGreaterEqual(recall, self.minSheetRecall,
                                'sheet recall not high enough')

    def computePerformanceMetrics(self, templateSheetName, testedSheetName,
            testedSheetDebugDir):
        templateSheet = sheets.ProductSheet()
        templateSheet.load(f'{self.templateOutputDir}{templateSheetName}')
        testedSheet = sheets.ProductSheet()
        testedSheet.load(f'{self.testOutputDir}{testedSheetName}')

        truePositives = 0
        falsePositives = 0
        for templateBox in templateSheet.boxes():
            testedBox = testedSheet.boxByName(templateBox.name)
            if testedBox.confidence == 1:
                if testedBox.text == templateBox.text:
                    truePositives += 1
                else:
                    falsePositives += 1
                    if self.writeDebugImages:
                        self.copyDebugImage(testedSheetDebugDir, testedBox.name,
                                self.debugOutputWrongDir)
            elif self.writeDebugImages:
                self.copyDebugImage(testedSheetDebugDir, testedBox.name,
                        self.debugOutputNotRecalledDir)
            self.logger.debug('')
            self.logger.debug(f'falsePositives = {falsePositives}')
            self.logger.debug(f'testedBox: ({testedBox.text}, {testedBox.confidence})')
            self.logger.debug(f'templateBox: ({templateBox.text}, {templateBox.confidence})')
            self.logger.debug(f'truePositives = {truePositives}')

        precision = truePositives / (truePositives + falsePositives)
        recall = truePositives / len(templateSheet.boxes())
        self.logger.info(f'{testedSheetName}: '
                f'precision = {precision}, recall = {recall}')
        return (precision, recall)

    def copyDebugImage(self, testedSheetDebugDir, testedBoxName, outputDir):
        ocrImagePath = (f'{self.tmpDir}{testedSheetDebugDir}/'
                f'4_recognizeText_{testedBoxName}_10_ocrImage.jpg')
        cornerImagePath = (f'{self.tmpDir}{testedSheetDebugDir}/'
                f'4_recognizeText_{testedBoxName}_00_cornerImg.jpg')
        if os.path.exists(ocrImagePath):
            shutil.copy(ocrImagePath,
                    f'{outputDir}{testedSheetDebugDir}'
                    f'_{testedBoxName}_10_ocrImage.jpg')
        elif os.path.exists(cornerImagePath):
            shutil.copy(cornerImagePath,
                    f'{outputDir}{testedSheetDebugDir}'
                    f'_{testedBoxName}_00_cornerImage.jpg')

    def checkIdPrecision(self, templateSheetName, testedSheetName):
        """
        Wrongly classifiyng name or sheet number must never happen,
        as it is probably not detected by the user when sanitizing.
        """
        templateSheet = sheets.ProductSheet()
        templateSheet.load(f'{self.templateOutputDir}{templateSheetName}')
        testedSheet = sheets.ProductSheet()
        testedSheet.load(f'{self.testOutputDir}{testedSheetName}')

        if testedSheet.boxByName('nameBox').confidence == 1:
            self.assertEqual(testedSheet.boxByName('nameBox').text,
                    templateSheet.boxByName('nameBox').text,
                    'sheet name is wrong and confidence == 1')

        if testedSheet.boxByName('sheetNumberBox').confidence == 1:
            self.assertEqual(testedSheet.boxByName('sheetNumberBox').text,
                    templateSheet.boxByName('sheetNumberBox').text,
                    'sheet number is wrong and confidence == 1')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Test tagtrail_gen')
    parser.add_argument('--writeDebugImages', dest='writeDebugImages', action='store_true')
    parser.add_argument('--logLevel', dest='logLevel',
            help='Log level to write to console', default='INFO')
    args = parser.parse_args()
    helpers.configureLogger(logging.getLogger('tagtrail'), consoleLevel =
            logging.getLevelName(args.logLevel))

    loader = unittest.TestLoader()
    OcrTest.writeDebugImages = args.writeDebugImages
    suite = loader.loadTestsFromTestCase(OcrTest)
    runner = unittest.TextTestRunner()
    runner.run(suite)
