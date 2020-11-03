# -*- coding: utf-8 -*-

from .context import helpers
from .context import database
from .context import sheets
from .context import tagtrail_ocr

import unittest
import configparser
import shutil
import os

class OcrTest(unittest.TestCase):
    """ Tests of tagtrail_ocr """
    minSheetPrecision = 0.9
    minSheetRecall = 0.6
    minAveragePrecision = 0.95
    minAverageRecall = 0.8


    def setUp(self):
        if __name__ != '__main__':
            self.skipTest(reason = 'only run when invoked directly')
        self.baseSetUp('medium_template')

    def baseSetUp(self, templateName):
        self.templateName = templateName
        self.templateDir = 'tests/data/'
        self.templateAccountingDir = f'{self.templateDir}{self.templateName}/'
        self.templateOutputDir = f'{self.templateAccountingDir}2_taggedProductSheets/'

        self.tmpDir = 'tests/tmp/'
        self.testAccountingDir = f'{self.tmpDir}{self.templateName}/'
        self.testOutputDir = f'{self.testAccountingDir}2_taggedProductSheets/'
        self.testScanDir = f'{self.testAccountingDir}0_input/scans/'

        self.log = helpers.Log(helpers.Log.LEVEL_INFO)
        helpers.recreateDir(self.tmpDir)
        shutil.copytree(self.templateAccountingDir, self.testAccountingDir)
        helpers.recreateDir(self.testOutputDir)
        self.db = database.Database(f'{self.testAccountingDir}0_input/')
        self.scanConfigFilePath = f'{self.testAccountingDir}scan_config.cfg'
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
            with self.subTest(scanFilename = section):
                self.processScan(section, precisions, recalls)
        averagePrecision = sum(precisions) / len(precisions)
        averageRecall = sum(recalls) / len(recalls)
        self.log.info(f'averagePrecision = {averagePrecision}')
        self.log.info(f'averageRecall = {averageRecall}')
        self.assertGreaterEqual(averagePrecision, self.minAveragePrecision,
                'averagePrecision not high enough')
        self.assertGreaterEqual(averageRecall, self.minAverageRecall,
                'averageRecall not high enough')

    def processScan(self, scanFilename, precisions, recalls):
        model = tagtrail_ocr.Model(self.tmpDir, self.testScanDir,
                self.testOutputDir, [scanFilename], self.db,
                helpers.Log(helpers.Log.LEVEL_ERROR))
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

        model.prepareTagRecognition()
        for idx, sheet in enumerate(model.sheets):
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
                    precision, recall = self.computePerformanceMetrics(
                            expectedSheetName, sheet.name)
                    precisions.append(precision)
                    recalls.append(recall)
                    self.assertGreaterEqual(precision, self.minSheetPrecision,
                            'sheet precision not high enough')
                    self.assertGreaterEqual(recall, self.minSheetRecall,
                            'sheet recall not high enough')

    def computePerformanceMetrics(self, templateSheetName, testedSheetName):
        templateSheet = sheets.ProductSheet(log = self.log)
        templateSheet.load(f'{self.templateOutputDir}{templateSheetName}')
        testedSheet = sheets.ProductSheet(log = self.log)
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
            self.log.debug('')
            self.log.debug(f'falsePositives = {falsePositives}')
            self.log.debug(f'testedBox: ({testedBox.text}, {testedBox.confidence})')
            self.log.debug(f'templateBox: ({templateBox.text}, {templateBox.confidence})')
            self.log.debug(f'truePositives = {truePositives}')

        precision = truePositives / (truePositives + falsePositives)
        recall = truePositives / len(templateSheet.boxes())
        self.log.info(f'{testedSheetName}: ' +
                f'precision = {precision}, recall = {recall}')
        return (precision, recall)


if __name__ == '__main__':
    unittest.main()
