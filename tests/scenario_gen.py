# -*- coding: utf-8 -*-

from .context import helpers
from .context import sheet_categorizer
from .context import database
from .context import sheets
from .context import tagtrail_gen
from .test_helpers import TagtrailTestCase

import logging
import argparse
import unittest
import shutil
import os
from decimal import Decimal

class GenTest(TagtrailTestCase):
    """ Tests of tagtrail_gen """
    testDate = helpers.DateUtility.strptime('2021-04-01')
    testProductIds = ['spaghetti']

    def setUp(self):
        if __name__ != '__main__':
            self.skipTest(reason = 'only run when invoked directly')
        self.baseSetUp('medium')

    def baseSetUp(self, templateName):
        self.templateName = templateName
        self.templateRootDir = f'tests/data/template_{self.templateName}/'
        self.templateGenDir = f'tests/data/gen_{self.templateName}/'
        self.templateNextDir = f'tests/data/gen_next_{self.templateName}/'

        self.tmpDir = 'tests/tmp/'
        self.testRootDir = f'{self.tmpDir}{self.templateName}/'
        self.testGenDir = f'{self.tmpDir}gen_{self.templateName}/'
        self.testNextDir = f'{self.tmpDir}next_{self.templateName}/'

        self.logger = logging.getLogger('tagtrail.tests.scenario_gen.GenTest')
        self.logger.info(f'\nStarting test {self.id()}\n')
        helpers.recreateDir(self.tmpDir)
        shutil.copytree(self.templateRootDir, self.testRootDir)
        self.config = database.Database(f'{self.testRootDir}0_input/').config

    def check_sheet_in_category(self, productId, sheetNumber, sheetsInCategory):
        sheetNumberStr = self.config.get('tagtrail_gen',
                'sheet_number_string').format(sheetNumber=str(sheetNumber))
        filename = f'{productId}_{sheetNumberStr}.csv'
        self.assertIn(filename, [s.filename for s in sheetsInCategory])

    def product_sheet_filenames_in_dir(self, productId, inputDir):
        """
        Retrieve filenames of all sheets of a given product in a directory

        :param productId: id of the product to look for
        :type productId: str
        :param inputDir: directory to check
        :type inputDir: str
        :return: list of filenames
        :rtype: list of str
        """
        return [filename for filename in os.listdir(inputDir) if
                sheets.ProductSheet.productId_from_filename(filename) == productId]

    def check_files(self, model, excludedProductIds = []):
        """
        Check if all files are written as claimed to the user, and if they
        match the expected template output.

        :param model: model after initializing sheets and saving them
        :type model: :class: `tagtrail_gen.Model`
        :param excludedProductIds: ids of products that were modified before
        running tagtrail_gen on the template and should therefore not be
        compared to template output
        :type  excludedProductIds: list of str
        """
        testOutputActiveDir = f'{self.testGenDir}5_output/sheets/active/'
        testOutputInactiveDir = f'{self.testGenDir}5_output/sheets/inactive/'
        nextInputActiveDir = f'{self.testNextDir}0_input/sheets/active/'
        nextInputInactiveDir = f'{self.testNextDir}0_input/sheets/inactive/'
        self.assertTrue(os.path.exists(self.testGenDir))
        self.assertTrue(os.path.exists(self.testNextDir))

        # check if categories shown to the user claim the correct origin
        for filename in [s.filename for s in model.sheetCategorizer.activeSheetsFromActive
                .union(model.sheetCategorizer.inactiveSheetsFromActive)
                .union(model.sheetCategorizer.missingSheets)
                .union(model.sheetCategorizer.obsoleteSheetsFromActive)]:
            p = f'{self.testGenDir}0_input/sheets/active/{filename}'
            self.assertTrue(os.path.exists(p), p)

        for filename in [s.filename for s in model.sheetCategorizer.activeSheetsFromInactive
                .union(model.sheetCategorizer.inactiveSheetsFromInactive)
                .union(model.sheetCategorizer.obsoleteSheetsFromInactive)]:
            p = f'{self.testGenDir}0_input/sheets/inactive/{filename}'
            self.assertTrue(os.path.exists(p), p)

        # check if files were written according to the categories which are
        # shown to the user
        activeFilenames = [sheet.filename
                for sheet in model.sheetCategorizer.activeSheetsToBePrinted
                    .union(model.sheetCategorizer.activeSheetsFromInactive)
                    .union(model.sheetCategorizer.activeSheetsFromActive)]
        for filename in activeFilenames:
            p = f'{testOutputActiveDir}{filename}'
            self.assertTrue(os.path.exists(p), p)
            p = f'{nextInputActiveDir}{filename}'
            self.assertTrue(os.path.exists(p), p)

        for sheet in model.sheetCategorizer.activeSheetsToBePrinted:
            p = (f'{self.testGenDir}1_generatedSheets/{sheet.productId()}'
                    f'_{sheet.sheetNumber}.jpg')
            self.assertTrue(os.path.exists(p), p)

        for sheet in (model.sheetCategorizer.inactiveSheetsFromInactive
                .union(model.sheetCategorizer.inactiveSheetsFromActive)):
            p = f'{testOutputInactiveDir}{sheet.filename}'
            self.assertTrue(os.path.exists(p), p)
            p = f'{nextInputInactiveDir}{sheet.filename}'
            self.assertTrue(os.path.exists(p), p)


        for sheet in (model.sheetCategorizer.obsoleteSheetsFromInactive
                .union(model.sheetCategorizer.obsoleteSheetsFromActive)):
            if os.path.exists(
                    f'{self.testGenDir}5_output/sheets/obsolete/removed/{sheet.filename}'):
                p = f'{nextInputActiveDir}{sheet.filename}'
                self.assertFalse(os.path.exists(p), p)
                p = f'{nextInputInactiveDir}{sheet.filename}'
                self.assertFalse(os.path.exists(p), p)
            elif os.path.exists(
                    f'{self.testGenDir}5_output/sheets/obsolete/replaced/{sheet.filename}'):
                p = f'{nextInputActiveDir}{sheet.filename}'
                self.assertTrue(os.path.exists(p), p)
            else:
                self.assertTrue(False, '''Obsolete sheet neither stored in
                5_output/obsolete nor 5_output/replaced''')

        # check if generated sheets (including content) match the template
        templateOutputSheetsDir = f'{self.templateGenDir}5_output/sheets/'
        self.check_sheets_in_dir(f'{templateOutputSheetsDir}active/',
                testOutputActiveDir, excludedProductIds)
        self.check_sheets_in_dir(f'{templateOutputSheetsDir}inactive/',
                testOutputInactiveDir, excludedProductIds)

        templateNextSheetsDir = f'{self.templateNextDir}0_input/sheets/'
        self.check_sheets_in_dir(f'{templateNextSheetsDir}active/',
                nextInputActiveDir, excludedProductIds)
        self.check_sheets_in_dir(f'{templateNextSheetsDir}inactive/',
                nextInputInactiveDir, excludedProductIds)

        # general safety checks
        ## all files in testGenDir/0_input should exist and be equivalent in
        ## next/0_input, apart from products.csv and sheets/
        for root, dirs, filenames in os.walk(f'{self.testGenDir}0_input/'):
            if root.startswith(f'{self.testGenDir}0_input/sheets'):
                continue
            path = root.split('/')
            for filename in filenames:
                if filename == 'products.csv':
                    continue
                self.assert_file_equality(
                    f'{root}/{filename}',
                    f'{self.testNextDir}{"/".join(path[3:])}/{filename}')

        ## check consistency of next/0_input/products.csv
        nextDb = database.Database(f'{self.testNextDir}0_input/')
        for productId, product in nextDb.products.items():
            self.assertEqual(product.addedQuantity, 0)
            self.assertEqual(product.soldQuantity,
                    model.db.products[productId].soldQuantity)
            self.assertEqual(product.expectedQuantity,
                    model.db.products[productId].expectedQuantity)

    def test_unmodified(self):
        """
        tagtrail_gen should create the expected output on unmodified template
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        model.initializeSheets()
        model.save()
        self.check_files(model)

    def test_product_removed(self):
        """
        A product removed from the database must not exist in next/0_input
        """
        testedAtLeastOneProduct = False
        for testProductId in self.testProductIds:
            with self.subTest(testProductId = testProductId):
                model = tagtrail_gen.Model(self.testRootDir, True,
                        self.testDate, self.testGenDir, self.testNextDir)
                model.db.products.pop(testProductId)
                model.initializeSheets()
                model.save()
                self.check_files(model, [testProductId])

                for filename in self.product_sheet_filenames_in_dir(
                        testProductId,
                        f'{self.templateRootDir}0_input/sheets/active'):
                    self.assertIn(filename, [s.filename for s in
                        model.sheetCategorizer.obsoleteSheetsFromActive])
                    testedAtLeastOneProduct = True

                for filename in self.product_sheet_filenames_in_dir(
                        testProductId,
                        f'{self.templateRootDir}0_input/sheets/inactive'):
                    self.assertIn(filename, [s.filename for s in
                        model.sheetCategorizer.obsoleteSheetsFromInactive])
                    testedAtLeastOneProduct = True

        self.assertTrue(testedAtLeastOneProduct,
                'No product with existing sheets to deactivate found.')

    def test_product_out_of_stock(self):
        """
        If a product is sold out, its existing sheets should be deactivated
        """
        for testProductId in self.testProductIds:
            with self.subTest(testProductId = testProductId):
                model = tagtrail_gen.Model(self.testRootDir, True,
                        self.testDate, self.testGenDir, self.testNextDir)

                testProduct = model.db.products[testProductId]
                testProduct.soldQuantity = (testProduct.previousQuantity +
                        testProduct.addedQuantity)
                assert(testProduct.expectedQuantity <= 0)

                # add one active and one inactive sheet
                activeSheet = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 5)
                activeSheet.store(f'{self.testRootDir}/0_input/sheets/active/')
                inactiveSheet = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 6)
                inactiveSheet.store(f'{self.testRootDir}/0_input/sheets/inactive/')

                model.initializeSheets()
                model.save()
                self.check_files(model, [testProductId])

                for filename in self.product_sheet_filenames_in_dir(
                        testProductId,
                        f'{self.templateRootDir}0_input/sheets/active'):
                    self.assertIn(filename, [s.filename for s in
                        model.sheetCategorizer.inactiveSheetsFromActive])

                for filename in self.product_sheet_filenames_in_dir(
                        testProductId,
                        f'{self.templateRootDir}0_input/sheets/inactive'):
                    self.assertIn(filename,  [s.filename for s in
                        model.sheetCategorizer.inactiveSheetsFromInactive])

    def test_add_product_out_of_stock(self):
        """
        No sheets should be generated for a new product with amount 0 in DB
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)

        testProduct = database.Product('test product', 100, 'g',
                Decimal(12.3), Decimal(.05), 0,
                addedQuantity = 0, soldQuantity = 0)
        model.db.products[testProduct.id] = testProduct
        assert(testProduct.expectedQuantity == 0)

        model.initializeSheets()
        model.save()
        self.check_files(model, [testProduct.id])

        self.assertEqual(len(self.product_sheet_filenames_in_dir(
            testProduct.id, f'{self.testNextDir}/0_input/sheets/active')), 0)
        self.assertEqual(len(self.product_sheet_filenames_in_dir(
            testProduct.id, f'{self.testNextDir}/0_input/sheets/inactive')), 0)

    def test_product_remaining_active(self):
        """
        Sheets of an active product with no changes remain active
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)
        model.initializeSheets()
        model.save()
        self.check_files(model, [testProduct.id])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.activeSheetsFromActive)

    def test_product_remaining_inactive(self):
        """
        Sheets of an inactive product with no changes remain inactive
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_inactive_test_product(model.db)
        model.initializeSheets()
        model.save()
        self.check_files(model, [testProduct.id])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.inactiveSheetsFromInactive)

    def test_high_price_change_on_inactive_product(self):
        """
        Sheets of an inactive product with high price change remain inactive
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_inactive_test_product(model.db)
        priceChangeThreshold = (self.config.getint('tagtrail_gen',
            'max_neglectable_price_change_percentage') / Decimal(100))
        testProduct.purchasePrice *= (Decimal(1) + priceChangeThreshold
                * Decimal(1.5))
        model.initializeSheets()
        model.save()
        self.check_files(model, [testProduct.id])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.inactiveSheetsFromInactive)

    def test_high_price_change_on_active_product(self):
        """
        Sheets of an active product with high price change are replaced
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)
        sheet = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 4)
        sheet.store(f'{self.testRootDir}/0_input/sheets/active/')
        priceChangeThreshold = (self.config.getint('tagtrail_gen',
            'max_neglectable_price_change_percentage') / Decimal(100))
        testProduct.purchasePrice *= (Decimal(1) - priceChangeThreshold
                * Decimal(3))
        model.initializeSheets()
        model.save()
        self.check_files(model, [testProduct.id])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.activeSheetsToBePrinted)
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.obsoleteSheetsFromActive)
        self.check_sheet_in_category(testProduct.id, 4,
                model.sheetCategorizer.obsoleteSheetsFromActive)

    def test_low_price_change_on_inactive_product(self):
        """
        Sheets of an inactive product with low price change remain unchanged
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_inactive_test_product(model.db)
        priceChangeThreshold = (self.config.getint('tagtrail_gen',
            'max_neglectable_price_change_percentage') / Decimal(100))
        testProduct.purchasePrice *= (Decimal(1) - priceChangeThreshold
                / Decimal(2))
        model.initializeSheets()
        model.save()

        self.check_files(model, [testProduct.id])
        self.assertEqual([s for s in model.sheetCategorizer.activeSheetsToBePrinted
            if s.filename.find(testProduct.id) != -1], [])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.inactiveSheetsFromInactive)

    def test_low_price_change_on_active_product(self):
        """
        Sheets of an active product with low price change remain unchanged
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)
        priceChangeThreshold = (self.config.getint('tagtrail_gen',
            'max_neglectable_price_change_percentage') / Decimal(100))
        testProduct.purchasePrice *= (Decimal(1) + priceChangeThreshold
                / Decimal(3))
        model.initializeSheets()
        model.save()

        self.check_files(model, [testProduct.id])
        self.assertEqual([s for s in model.sheetCategorizer.activeSheetsToBePrinted
            if s.filename.find(testProduct.id) != -1], [])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.activeSheetsFromActive)

    def test_high_price_difference_active_sheet_to_db_fails(self):
        """
        No active sheet in next should have a high price difference to DB
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)
        model.initializeSheets()
        # smuggle in price change after initialization
        priceChangeThreshold = (self.config.getint('tagtrail_gen',
            'max_neglectable_price_change_percentage') / Decimal(100))
        testProduct.purchasePrice *= (Decimal(1) + priceChangeThreshold
                * Decimal(3))
        self.assertRaises(AssertionError, model.save)

    def test_amount_change_with_low_price(self):
        """
        Sheets of an active product with changed amount respect price change
        (even if price change is low)
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)
        testProduct.amount -= 5
        priceChangeThreshold = (self.config.getint('tagtrail_gen',
            'max_neglectable_price_change_percentage') / Decimal(100))
        testProduct.purchasePrice *= (Decimal(1) + priceChangeThreshold
                / Decimal(3))
        model.initializeSheets()
        model.save()

        self.check_files(model, [testProduct.id])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.obsoleteSheetsFromActive)
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.activeSheetsToBePrinted)
        for s in model.sheetCategorizer.activeSheetsToBePrinted:
            if s.productId() == testProduct.id:
                self.assertEqual(s.grossSalesPrice,
                        testProduct.grossSalesPrice())

    def test_unit_change_with_low_price(self):
        """
        Sheets of an active product with changed unit respect price change
        (even if price change is low)
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)
        testProduct.unit = 'l'
        priceChangeThreshold = (self.config.getint('tagtrail_gen',
            'max_neglectable_price_change_percentage') / Decimal(100))
        testProduct.purchasePrice *= (Decimal(1) - priceChangeThreshold
                / Decimal(2))
        model.initializeSheets()
        model.save()

        self.check_files(model, [testProduct.id])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.obsoleteSheetsFromActive)
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.activeSheetsToBePrinted)
        for s in model.sheetCategorizer.activeSheetsToBePrinted:
            if s.productId() == testProduct.id:
                self.assertEqual(s.grossSalesPrice,
                        testProduct.grossSalesPrice())

    def test_not_enough_space_and_price_change(self):
        """
        All sheets must be replaced if capacity is not enough and price changed
        (even if price change is low)
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)
        testProduct.addedQuantity = 100
        priceChangeThreshold = (self.config.getint('tagtrail_gen',
            'max_neglectable_price_change_percentage') / Decimal(100))
        testProduct.purchasePrice *= (Decimal(1) - priceChangeThreshold
                / Decimal(2))
        model.initializeSheets()
        model.save()

        self.check_files(model, [testProduct.id])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.obsoleteSheetsFromActive)
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.activeSheetsToBePrinted)
        self.check_sheet_in_category(testProduct.id, 2,
                model.sheetCategorizer.activeSheetsToBePrinted)
        for s in model.sheetCategorizer.activeSheetsToBePrinted:
            if s.productId() == testProduct.id:
                self.assertEqual(s.grossSalesPrice,
                        testProduct.grossSalesPrice())

    def test_no_replacement_if_not_allowed(self):
        """
        If model.allowRemoval == False, replacing sheets must fail
        """
        model = tagtrail_gen.Model(self.testRootDir, False, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)
        testProduct.unit = 'l'
        self.assertRaises(ValueError, model.initializeSheets)

    def test_added_quantity_enough_space(self):
        """
        Inactive sheets must be activated to provide enough space
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)

        inactiveSheet1 = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 2)
        inactiveSheet1.boxByName('dataBox0(0,0)').text = 'TEST'
        inactiveSheet1.boxByName('dataBox0(0,0)').confidence = 1
        inactiveSheet1.store(f'{self.testRootDir}/0_input/sheets/inactive/')
        inactiveSheet2 = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 4)
        inactiveSheet2.store(f'{self.testRootDir}/0_input/sheets/inactive/')

        # make sure we need two full sheets for next accounting
        # -> empty inactiveSheet2 has to be activated
        testProduct.addedQuantity = (sheets.ProductSheet.maxQuantity() * 2 -
                testProduct.expectedQuantity)
        model.initializeSheets()
        model.save()

        self.check_files(model, [testProduct.id])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.activeSheetsFromActive)
        self.check_sheet_in_category(testProduct.id, 4,
                model.sheetCategorizer.activeSheetsFromInactive)
        try:
            # inactiveSheet1 could be active or inactive, as other two sheets
            # already provide enough space
            self.check_sheet_in_category(testProduct.id, 2,
                    model.sheetCategorizer.activeSheetsFromInactive)
        except AssertionError:
            self.check_sheet_in_category(testProduct.id, 2,
                    model.sheetCategorizer.inactiveSheetsFromInactive)

    def test_added_quantity_not_enough_space(self):
        """
        Inactive sheets must be activated and a new sheet added
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)

        inactiveSheet = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 2)
        inactiveSheet.store(f'{self.testRootDir}/0_input/sheets/inactive/')

        # make sure we need more than two full sheets for next accounting
        # -> need to generate one new sheet
        testProduct.addedQuantity = (sheets.ProductSheet.maxQuantity() * 2 + 1
                - testProduct.expectedQuantity)
        model.initializeSheets()
        model.save()

        self.check_files(model, [testProduct.id])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.activeSheetsFromActive)
        self.check_sheet_in_category(testProduct.id, 2,
                model.sheetCategorizer.activeSheetsFromInactive)
        self.check_sheet_in_category(testProduct.id, 3,
                model.sheetCategorizer.activeSheetsToBePrinted)

    def test_fill_all_sheets(self):
        """
        If existing sheets provide enough capacity don't create any new sheets
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)

        inactiveSheet = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 3)
        inactiveSheet.store(f'{self.testRootDir}/0_input/sheets/inactive/')

        # make sure we need exactly two full sheets for next accounting
        testProduct.addedQuantity = (sheets.ProductSheet.maxQuantity() * 2
                - testProduct.expectedQuantity)
        assert(testProduct.expectedQuantity == sheets.ProductSheet.maxQuantity() * 2)
        model.initializeSheets()
        model.save()

        self.check_files(model, [testProduct.id])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.activeSheetsFromActive)
        self.assertEqual(len([s for s in model.sheetCategorizer.activeSheetsFromActive
            if s.productId() == testProduct.id]),
            1)
        self.check_sheet_in_category(testProduct.id, 3,
                model.sheetCategorizer.activeSheetsFromInactive)
        self.assertEqual(len([s for s in model.sheetCategorizer.activeSheetsFromInactive
            if s.productId() == testProduct.id]),
            1)
        self.assertEqual([s for s in model.sheetCategorizer.activeSheetsToBePrinted
            if s.productId() == testProduct.id],
            [])

    def test_not_enough_space_no_replacement(self):
        """
        Unable to add enough new sheets, replacement forbidden -> expected fail
        """
        model = tagtrail_gen.Model(self.testRootDir, False, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_inactive_test_product(model.db)

        # add another sheet that would need to be replaced to make enough space
        sheet = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 2)
        sheet.boxByName('dataBox0(0,0)').text = 'TEST'
        sheet.boxByName('dataBox0(0,0)').confidence = 1
        sheet.store(f'{self.testRootDir}/0_input/sheets/active/')

        maxNumSheets = self.config.getint('tagtrail_gen',
                'max_num_sheets_per_product')

        # make sure we need all sheets empty for next accounting
        testProduct.addedQuantity = (sheets.ProductSheet.maxQuantity() * maxNumSheets
                - testProduct.expectedQuantity)

        self.assertRaises(ValueError, model.initializeSheets)

    def test_not_enough_space_replacement_allowed(self):
        """
        Not enough space in new sheets, need to replace fullest existing
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_inactive_test_product(model.db)

        # add another sheet that has to be replaced to make enough space
        sheet = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 2)
        sheet.boxByName('dataBox0(0,0)').text = 'TEST'
        sheet.boxByName('dataBox0(0,0)').confidence = 1
        sheet.store(f'{self.testRootDir}/0_input/sheets/active/')

        maxNumSheets = self.config.getint('tagtrail_gen',
                'max_num_sheets_per_product')

        # make sure we need all sheets empty for next accounting
        testProduct.addedQuantity = (sheets.ProductSheet.maxQuantity() * maxNumSheets
                - testProduct.expectedQuantity)
        assert(testProduct.expectedQuantity ==
                sheets.ProductSheet.maxQuantity() * maxNumSheets)

        model.initializeSheets()
        model.save()

        self.check_files(model, [testProduct.id])
        self.check_sheet_in_category(testProduct.id, 1,
                model.sheetCategorizer.activeSheetsFromInactive)
        self.check_sheet_in_category(testProduct.id, 2,
                model.sheetCategorizer.obsoleteSheetsFromActive)
        for n in range(2, maxNumSheets):
            self.check_sheet_in_category(testProduct.id, n,
                    model.sheetCategorizer.activeSheetsToBePrinted)

    def test_not_enough_space_in_max_num_sheets(self):
        """
        Hitting max_num_sheets_per_product limitation -> expected fail
        """
        model = tagtrail_gen.Model(self.testRootDir, False, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)
        maxNumSheets = self.config.getint('tagtrail_gen',
                'max_num_sheets_per_product')
        testProduct.addedQuantity = (sheets.ProductSheet.maxQuantity() * maxNumSheets
                - testProduct.expectedQuantity) + 1

        self.assertRaises(ValueError, model.initializeSheets)

    def test_fail_if_generated_sheets_name_inconsistent(self):
        """
        All sheets of a product must have the exact same name
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_active_test_product(model.db)
        sheet = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 2)
        # smuggle in name inconsistency
        sheet.name = self.testProductIds[0]
        sheet.store(f'{self.testRootDir}/0_input/sheets/active/')

        self.assertRaises(ValueError, model.initializeSheets)

    def test_fail_if_generated_sheets_amount_and_unit_inconsistent(self):
        """
        All sheets of a product must have the same amount and unit
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_inactive_test_product(model.db)
        sheet = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 2)
        # smuggle in amountAndUnit inconsistency
        sheet.amountAndUnit = 'Test Amount'
        sheet.store(f'{self.testRootDir}/0_input/sheets/active/')

        self.assertRaises(ValueError, model.initializeSheets)

    def test_fail_if_generated_sheets_price_inconsistent(self):
        """
        All sheets of a product must have the exact same name
        """
        model = tagtrail_gen.Model(self.testRootDir, True, self.testDate,
                self.testGenDir, self.testNextDir)
        (testProduct, _) = self.create_inactive_test_product(model.db)
        sheet = sheet_categorizer.SheetCategorizer.generateProductSheet(model.db, testProduct, 2)
        # smuggle in price change
        sheet.grossSalesPrice = helpers.formatPrice(
                testProduct.grossSalesPrice()+Decimal(0.1),
                self.config.get('general', 'currency'))
        sheet.store(f'{self.testRootDir}/0_input/sheets/inactive/')

        self.assertRaises(ValueError, model.initializeSheets)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Test tagtrail_gen')
    parser.add_argument('--pattern',
            default=None,
            help='Only run tests containing `pattern` in there id.')
    parser.add_argument('--logLevel', dest='logLevel',
            help='Log level to write to console', default='INFO')
    args = parser.parse_args()
    helpers.configureLogger(logging.getLogger('tagtrail'), consoleLevel =
            logging.getLevelName(args.logLevel))

    loader = unittest.TestLoader()
    completeSuite = loader.loadTestsFromTestCase(GenTest)
    filteredSuite = unittest.TestSuite()
    for test in completeSuite:
        if args.pattern is not None and test.id().find(args.pattern) == -1:
            print(f'skip {test.id()} - {args.pattern} not contained')
        else:
            filteredSuite.addTest(test)

    runner = unittest.TextTestRunner()
    runner.run(filteredSuite)
